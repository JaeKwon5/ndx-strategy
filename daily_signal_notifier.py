"""
NDX 250일선 레짐 전략 일일 신호 알림 봇 (텔레그램 / 카카오톡 '나에게 보내기')
- 미국 정규장 마감 후 실행하면 당일 종가 기준 목표 포지션과 포지션 변경 여부를 계산하여 전송합니다.
- 설정 방법:
  1) .env.example 파일을 복사하여 .env 파일 생성 (또는 환경변수 등록)
  2) TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 입력 (또는 KAKAO_REST_API_KEY, KAKAO_REFRESH_TOKEN 입력)
  3) python daily_signal_notifier.py 실행 (옵션: --dry-run 화면 출력만 수행)
"""
import os
import sys
import json
from pathlib import Path
import requests
import pandas as pd
from ndx_regime_backtest import P, load_real, build_signal


def load_dotenv(env_path=".env"):
    """별도 패키지(python-dotenv) 없이 .env 파일을 읽어 환경변수로 로드"""
    p = Path(env_path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


PORTFOLIO_DESC = {
    "TQQQ": "🔥 TQQQ 100% (3.0배 공격)",
    "QQQ50_QLD50": "🛡️ QQQ 50% + QLD 50% (1.5배 방어)",
    "SOXL": "🔥 SOXL 100% (3.0배 공격)",
    "USD50_QQQM50": "🛡️ USD 50% + QQQM 50% (1.5배 방어)",
    "CASH": "💵 현금/단기채 100% (0.0배 대피)",
}


def build_daily_message():
    df = load_real()
    sig = build_signal(df, **P)

    # 최근 2거래일 비교 (전일 vs 당일)
    valid = sig.dropna(subset=["target"])
    today_dt = valid.index[-1]
    prev_dt = valid.index[-2]

    today_row = valid.loc[today_dt]
    prev_row = valid.loc[prev_dt]

    ndx_close = df.loc[today_dt, "ndx"]
    ndx_prev = df.loc[prev_dt, "ndx"]
    ndx_chg = (ndx_close / ndx_prev - 1) * 100

    vix_close = df.loc[today_dt, "vix"]
    vix10 = today_row["vix10"]
    dd_pct = today_row["dd"] * 100

    ma250 = df["ndx"].rolling(250).mean().loc[today_dt]
    up_band = ma250 * P["up"]
    dn_band = ma250 * P["dn"]
    high_252 = df["ndx"].rolling(252, min_periods=252).max().loc[today_dt]

    curr_tgt = today_row["target"]
    prev_tgt = prev_row["target"]
    changed = curr_tgt != prev_tgt

    # 상태 전환까지 남은 여유폭(%) 계산
    dist_to_up = (ndx_close / up_band - 1) * 100
    dist_to_dn = (ndx_close / dn_band - 1) * 100

    header_icon = "🚨 [포지션 변경 발생!]" if changed else "✅ [포지션 유지]"
    action_line = (
        f"⚡ **오늘 밤 시가 매매 필요**: `{prev_tgt}` ➔ `{curr_tgt}`"
        if changed
        else f"현재 포지션(`{curr_tgt}`)을 그대로 유지합니다."
    )

    # 다음 단계 전환 트리거 안내
    if today_row["state"] == "BULL":
        if curr_tgt == "TQQQ":
            dd_trigger_price = high_252 * (1 - P["dd_lim"])
            trigger_note = (
                f"• 방어(1.5x) 전환 조건: VIX10 ≥ {P['vix_hi']:.0f} 또는 "
                f"NDX ≤ {dd_trigger_price:,.1f} (고점 대비 -{P['dd_lim']*100:.0f}%)\n"
                f"• 하락장(BEAR) 전환선: NDX < {dn_band:,.1f} (현재가 대비 {dist_to_dn:+.1f}%)"
            )
        else:
            dd_recover_price = high_252 * (1 - P["dd_re"])
            trigger_note = (
                f"• TQQQ(3x) 복귀 조건: VIX10 < {P['vix_re']:.0f} 및 "
                f"NDX ≥ {dd_recover_price:,.1f} (고점 대비 -{P['dd_re']*100:.0f}% 이내)\n"
                f"• 하락장(BEAR) 전환선: NDX < {dn_band:,.1f} (현재가 대비 {dist_to_dn:+.1f}%)"
            )
    else:
        trigger_note = (
            f"• 상승장(BULL) 전환선: NDX > {up_band:,.1f} (현재가 대비 {dist_to_up:+.1f}%)\n"
            f"• 하락장 역발상(1.5x) 기준: VIX10 < {P['vix_lo']:.0f}"
        )

    msg = (
        f"{header_icon} NDX 레짐 전략 일일 리포트\n"
        f"📅 기준일(미국장): {today_dt.strftime('%Y-%m-%d')}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 목표 포트폴리오: {PORTFOLIO_DESC.get(curr_tgt, curr_tgt)}\n"
        f"📌 실행 지침: {action_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 [핵심 지표 현황]\n"
        f"• 시장 레짐: {today_row['state']} (전일: {prev_row['state']})\n"
        f"• NDX 종가: {ndx_close:,.2f} ({ndx_chg:+.2f}%)\n"
        f"• 250일선: {ma250:,.2f} (상단 {up_band:,.1f} / 하단 {dn_band:,.1f})\n"
        f"• 52주 고점 대비 낙폭(DD): -{dd_pct:.2f}% (고점 {high_252:,.1f})\n"
        f"• VIX10 (10일 평균): {vix10:.2f} (당일 VIX {vix_close:.2f})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 [향후 전환 기준점]\n"
        f"{trigger_note}"
    )
    sox_csv = Path(__file__).resolve().parent / "backtest_result_soxl.csv"
    if sox_csv.exists():
        try:
            sdf = pd.read_csv(sox_csv, index_col=0, parse_dates=True).dropna(subset=["target"])
            st_today = sdf.iloc[-1]
            st_prev = sdf.iloc[-2]
            s_tgt = str(st_today["target"])
            s_prev_tgt = str(st_prev["target"])
            s_chg = s_tgt != s_prev_tgt
            s_icon = "🚨 변경" if s_chg else "✅ 유지"
            msg += (
                f"\n━━━━━━━━━━━━━━━━━━━━\n"
                f"⚡ [반도체(^SOX) 레짐 전략]\n"
                f"• 목표: {PORTFOLIO_DESC.get(s_tgt, s_tgt)} ({s_icon})\n"
                f"• 레짐: {st_today['state']} / SOX {st_today['sox']:,.1f} (250일선 {st_today['ma250']:,.1f})\n"
                f"• 52주 낙폭(DD): -{st_today['dd']*100:.2f}%"
            )
        except Exception:
            pass

    dashboard_url = os.environ.get("DASHBOARD_URL", "").strip()
    if dashboard_url:
        msg += f"\n━━━━━━━━━━━━━━━━━━━━\n📱 모바일 대시보드:\n{dashboard_url}"
    return msg


def send_telegram(msg: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": msg}, timeout=15)
    resp.raise_for_status()
    print("[성공] 텔레그램 메시지 전송 완료")
    return True


def refresh_kakao_access_token(rest_api_key: str, refresh_token: str) -> str:
    url = "https://kauth.kakao.com/oauth/token"
    data = {
        "grant_type": "refresh_token",
        "client_id": rest_api_key,
        "refresh_token": refresh_token,
    }
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()
    if client_secret:
        data["client_secret"] = client_secret

    resp = requests.post(url, data=data, timeout=15)
    resp.raise_for_status()
    return resp.json()["access_token"]


def send_kakao_memo(msg: str) -> bool:
    access_token = os.environ.get("KAKAO_ACCESS_TOKEN", "").strip()
    rest_api_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()

    if rest_api_key and refresh_token:
        access_token = refresh_kakao_access_token(rest_api_key, refresh_token)

    if not access_token:
        return False

    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {"Authorization": f"Bearer {access_token}"}
    dash_url = os.environ.get("DASHBOARD_URL", "").strip() or "https://finance.yahoo.com/quote/%5ENDX"
    template_object = {
        "object_type": "text",
        "text": msg[:990],  # 카카오톡 텍스트 템플릿 최대 길이 제한 대응
        "link": {
            "web_url": dash_url,
            "mobile_web_url": dash_url,
        },
        "button_title": "모바일 대시보드 열기",
    }
    resp = requests.post(
        url,
        headers=headers,
        data={"template_object": json.dumps(template_object, ensure_ascii=False)},
        timeout=15,
    )
    resp.raise_for_status()
    print("[성공] 카카오톡 '나에게 보내기' 전송 완료")
    return True


def main():
    load_dotenv()
    msg = build_daily_message()
    print("\n" + msg + "\n")

    if "--dry-run" in sys.argv:
        print("[안내] --dry-run 모드이므로 외부 메신저 전송을 생략합니다.")
        return

    sent_any = False
    try:
        if send_telegram(msg):
            sent_any = True
    except Exception as e:
        print(f"[오류] 텔레그램 전송 실패: {e}")

    try:
        if send_kakao_memo(msg):
            sent_any = True
    except Exception as e:
        print(f"[오류] 카카오톡 전송 실패: {e}")

    if not sent_any:
        print(
            "[안내] 설정된 메신저 토큰이 없습니다. "
            ".env 파일에 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 또는 KAKAO 토큰을 설정해 주세요."
        )


if __name__ == "__main__":
    main()
