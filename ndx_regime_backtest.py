"""
NDX 250일선 레짐 + VIX10 + 52주 낙폭 레버리지 전략 백테스트 (개선판)
[반영된 보완 사항]
1. 합성 ETF 정밀화: ^NDX 배당수익률(연 0.8% 가정) 가산 + 레버리지 차입 스왑 스프레드(연 0.5%p) 차감
2. 익일 시가(Next-Open) 체결 지원: 종가 신호 발생 후 다음 날 시가(Open)에 리밸런싱
   - 포지션 변경일: 오버나잇(전일 종가→당일 시가)은 기존 포지션 수익률, 장중(당일 시가→당일 종가)은 신규 포지션 수익률 반영
3. QQQ50_QLD50 비중 드리프트(Buy & Hold) 반영: 동일 구간 유지 중 매일 공짜 리밸런싱하지 않고 실제 비중 변화 추적
4. TQQQ 진입/이탈 히스테리시스(Hysteresis): 방어 전환(VIX≥28 또는 DD>9%) 후 복귀 시 더 엄격한 기준(VIX<25 및 DD≤7%) 적용

실행:  pip install yfinance pandas numpy matplotlib
       python ndx_regime_backtest.py            (실데이터)
       python ndx_regime_backtest.py --synthetic (코드 동작 점검용 가상 데이터)
"""
import sys
import numpy as np
import pandas as pd

# ---------------- 파라미터 ----------------
P = dict(
    up=1.01, dn=0.95,
    vix_hi=28.0, vix_re=25.0,   # TQQQ 이탈 VIX 기준 / 복귀 VIX 기준 (히스테리시스)
    vix_lo=18.0,
    dd_lim=0.09, dd_re=0.07,    # TQQQ 이탈 낙폭 기준 / 복귀 낙폭 기준 (히스테리시스)
)
START = "1990-01-02"            # VIX 데이터 시작 시점에 맞춤
TRADE_COST = 0.0005             # 편도 0.05% (슬리피지+수수료 가정)
DIV_YIELD = 0.0080              # ^NDX 연평균 배당수익률 가정 (약 0.80%)
SWAP_SPREAD = 0.0050            # 레버리지 스왑 조달 가산금리 가정 (연 0.50%p)
ER = {"QQQ": 0.0020, "QLD": 0.0095, "TQQQ": 0.0095}   # 연 운용보수
LEV = {"QQQ": 1.0, "QLD": 2.0, "TQQQ": 3.0}
TD = 252


# ---------------- 데이터 ----------------
def load_real():
    import yfinance as yf
    raw = yf.download(["^NDX", "^VIX", "^IRX"], start="1985-10-01",
                      auto_adjust=False, progress=False)
    close = raw["Close"].rename(columns={"^NDX": "ndx", "^VIX": "vix", "^IRX": "irx"})
    open_p = raw["Open"]["^NDX"].rename("ndx_open")

    df = close.join(open_p)
    # 초기 Open 데이터가 없거나 0인 경우 전일 종가로 대체
    df["ndx_open"] = df["ndx_open"].where(df["ndx_open"] > 0, df["ndx"].shift(1)).fillna(df["ndx"])
    df["irx"] = df["irx"].ffill().bfill() / 100.0
    return df.dropna(subset=["ndx", "vix"])


def load_synthetic(n=10500, seed=7):
    rng = np.random.default_rng(seed)
    vol = np.clip(0.18 + 0.12 * np.sin(np.arange(n) / 400) + rng.normal(0, .02, n), .08, .6)
    # 총 일간 수익률을 오버나잇(35% 분산) + 장중(65% 분산)으로 분리 생성
    r_ov = rng.normal(0.00015, (vol / np.sqrt(TD)) * np.sqrt(0.35))
    r_id = rng.normal(0.00025, (vol / np.sqrt(TD)) * np.sqrt(0.65))
    r_tot = (1 + r_ov) * (1 + r_id) - 1

    idx = pd.bdate_range("1985-10-01", periods=n)
    ndx = pd.Series(500 * np.exp(np.cumsum(np.log1p(r_tot))), idx)
    ndx_prev = ndx.shift(1).fillna(500.0)
    ndx_open = ndx_prev * (1 + r_ov)
    vix = pd.Series(vol * 100 * (1 + rng.normal(0, .05, n)), idx)
    return pd.DataFrame({"ndx": ndx, "ndx_open": ndx_open, "vix": vix, "irx": 0.02}, index=idx)


# ---------------- 신호 (TQQQ 복귀 히스테리시스 반영) ----------------
def build_signal(df, up, dn, vix_hi, vix_re, vix_lo, dd_lim, dd_re):
    ndx = df["ndx"]
    ma250 = ndx.rolling(250).mean()
    vix10 = df["vix"].rolling(10).mean()
    dd = 1 - ndx / ndx.rolling(252, min_periods=252).max()   # 52주 고점 대비 낙폭(양수)

    state = None
    bull_defensive = False   # BULL 장세 내 방어모드(QQQ50_QLD50) 진입 여부
    st_out, tgt_out = [], []

    for p, m, v, d in zip(ndx.values, ma250.values, vix10.values, dd.values):
        # 1) 250일선 레짐 판별
        if np.isnan(m):
            st_out.append(None)
            tgt_out.append(None)
            continue

        prev_state = state
        if p > m * up:
            state = "BULL"
        elif p < m * dn:
            state = "BEAR"
        elif state is None:
            state = "BULL" if p > m else "BEAR"
        st_out.append(state)

        # 2) 타겟 포트폴리오 판별 (히스테리시스 적용)
        if np.isnan(v) or np.isnan(d):
            tgt_out.append(None)
            continue

        if state == "BULL":
            # BEAR -> BULL 직후이거나 기존 방어모드일 때: 복귀 조건(vix_re, dd_re) 확인
            if prev_state != "BULL":
                bull_defensive = not (v < vix_hi and d <= dd_lim)
            elif bull_defensive:
                if v < vix_re and d <= dd_re:
                    bull_defensive = False
            else:
                if v >= vix_hi or d > dd_lim:
                    bull_defensive = True

            tgt_out.append("QQQ50_QLD50" if bull_defensive else "TQQQ")
        else:
            bull_defensive = True
            tgt_out.append("QQQ50_QLD50" if v < vix_lo else "CASH")

    return pd.DataFrame({"state": st_out, "vix10": vix10, "dd": dd, "target": tgt_out}, index=ndx.index)


WEIGHTS = {
    "TQQQ": np.array([0.0, 0.0, 1.0, 0.0]),         # [QQQ, QLD, TQQQ, CASH]
    "QQQ50_QLD50": np.array([0.5, 0.5, 0.0, 0.0]),
    "CASH": np.array([0.0, 0.0, 0.0, 1.0]),
}
ASSET_COLS = ["QQQ", "QLD", "TQQQ", "CASH"]


# ---------------- 합성 ETF 수익률 (배당 + 스왑 스프레드 + 시가/종가 분리) ----------------
def etf_returns(df):
    prev_c = df["ndx"].shift(1)
    open_p = df["ndx_open"]
    curr_c = df["ndx"]

    # 일간(Close-to-Close), 오버나잇(Close-to-Open), 장중(Open-to-Close) 지수 수익률
    r_cc = curr_c / prev_c - 1
    r_ov = (open_p / prev_c - 1).fillna(0.0)
    r_id = (curr_c / open_p - 1).fillna(r_cc)

    rf = df["irx"] / TD
    div_d = DIV_YIELD / TD
    borrow_d = rf + SWAP_SPREAD / TD

    cc_dict, ov_dict, id_dict = {}, {}, {}
    for k, L in LEV.items():
        daily_drag = (L - 1) * borrow_d + ER[k] / TD
        # 일간 총수익률 (종가~종가)
        cc_dict[k] = L * (r_cc + div_d) - daily_drag
        # 오버나잇(비용의 1/3 배분) & 장중(비용의 2/3 배분)
        ov_dict[k] = L * (r_ov + div_d / 3.0) - daily_drag / 3.0
        id_dict[k] = (1 + cc_dict[k]) / (1 + ov_dict[k]) - 1

    cc_dict["CASH"] = rf
    ov_dict["CASH"] = rf / 3.0
    id_dict["CASH"] = rf * (2.0 / 3.0)

    return pd.DataFrame(cc_dict), pd.DataFrame(ov_dict), pd.DataFrame(id_dict), rf


# ---------------- 백테스트 (비중 드리프트 + 익일 시가 체결) ----------------
def backtest(df, exec_mode="next_open", **kw):
    prm = {**P, **kw}
    sig = build_signal(df, **prm)
    etf_cc, etf_ov, etf_id, rf = etf_returns(df)

    tgt_series = sig["target"].shift(1)   # 전일 종가 신호 -> 금일 목표 포지션
    ok = tgt_series.notna()

    cc_arr = etf_cc[ASSET_COLS].values
    ov_arr = etf_ov[ASSET_COLS].values
    id_arr = etf_id[ASSET_COLS].values
    tgt_vals = tgt_series.values

    n = len(df)
    port_ret = np.full(n, np.nan)
    changed = np.zeros(n, dtype=bool)
    w_curr = None
    prev_tgt = None

    for i in range(n):
        t = tgt_vals[i]
        if t is None or (isinstance(t, float) and np.isnan(t)):
            continue

        w_target = WEIGHTS[t]

        if w_curr is None:
            # 첫 진입일
            w_curr = w_target.copy()
            r_day = np.dot(w_curr, cc_arr[i])
            w_curr = w_curr * (1 + cc_arr[i]) / (1 + r_day)
            port_ret[i] = r_day
            prev_tgt = t
            continue

        if t != prev_tgt:
            changed[i] = True
            if exec_mode == "next_open":
                # 1) 전일 종가 ~ 당일 시가(오버나잇): 기존 비중(w_curr)으로 수익 반영
                r_ov = np.dot(w_curr, ov_arr[i])
                w_open = w_curr * (1 + ov_arr[i]) / (1 + r_ov)

                # 2) 당일 시가에 목표 비중(w_target)으로 리밸런싱 및 거래비용 차감
                turn = np.abs(w_target - w_open).sum() / 2.0
                cost = turn * TRADE_COST * 2.0

                # 3) 당일 시가 ~ 당일 종가(장중): 신규 비중(w_target)으로 수익 반영
                r_id = np.dot(w_target, id_arr[i])
                port_ret[i] = (1 + r_ov) * (1 - cost) * (1 + r_id) - 1
                w_curr = w_target * (1 + id_arr[i]) / (1 + r_id)
            else:
                # 종가 체결 가정 (기존 방식 + 드리프트 반영)
                turn = np.abs(w_target - w_curr).sum() / 2.0
                cost = turn * TRADE_COST * 2.0
                r_day = np.dot(w_target, cc_arr[i])
                port_ret[i] = r_day - cost
                w_curr = w_target * (1 + cc_arr[i]) / (1 + r_day)
        else:
            # 목표 포지션 동일: 리밸런싱 없이 비중 자연 드리프트(Buy & Hold)
            r_day = np.dot(w_curr, cc_arr[i])
            port_ret[i] = r_day
            w_curr = w_curr * (1 + cc_arr[i]) / (1 + r_day)

        prev_tgt = t

    ret_s = pd.Series(port_ret, index=df.index)[ok]
    chg_s = pd.Series(changed, index=df.index)[ok]
    return ret_s.loc[START:], sig, tgt_series, chg_s.loc[START:]


def metrics(ret, rf=None):
    ret = ret.dropna()
    eq = (1 + ret).cumprod()
    yrs = len(ret) / TD
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    vol = ret.std() * np.sqrt(TD)
    ex = ret - (rf.reindex(ret.index).fillna(0) if rf is not None else 0)
    sharpe = ex.mean() / ret.std() * np.sqrt(TD) if ret.std() > 0 else np.nan
    mdd = (eq / eq.cummax() - 1).min()
    return dict(CAGR=cagr, 변동성=vol, 샤프=sharpe, MDD=mdd,
                칼마=cagr / abs(mdd) if mdd < 0 else np.nan, 최종배수=eq.iloc[-1])


def fmt(d):
    return {k: (f"{v:.1%}" if k in ("CAGR", "변동성", "MDD") else f"{v:.2f}") for k, v in d.items()}


def main():
    synthetic = "--synthetic" in sys.argv
    df = load_synthetic() if synthetic else load_real()
    etf_cc, _, _, rf = etf_returns(df)

    # 개선판 기본 실행 (익일 시가 체결 + 히스테리시스 + 드리프트)
    ret, sig, tgt, chg = backtest(df, exec_mode="next_open")
    # 비교용: 기존 방식 (종가 체결 + 히스테리시스 미적용)
    ret_legacy, _, _, chg_legacy = backtest(
        df, exec_mode="close", vix_re=P["vix_hi"], dd_re=P["dd_lim"]
    )

    rows = {
        "전략(개선: 익일시가+히스테리시스)": metrics(ret, rf),
        "전략(기존: 종가체결+단일임계값)": metrics(ret_legacy, rf),
    }
    for k in LEV:
        rows[f"{k} 보유(합성)"] = metrics(etf_cc[k].loc[ret.index], rf)
    tbl = pd.DataFrame({k: fmt(v) for k, v in rows.items()}).T
    print("\n[1] 전체 기간 성과 (%s ~ %s)" % (ret.index[0].date(), ret.index[-1].date()))
    print(tbl.to_string())

    # 기간별
    periods = {"1990-1999": ("1990", "1999"), "2000-2002 닷컴": ("2000", "2002"),
               "2003-2007": ("2003", "2007"), "2008 금융위기": ("2008", "2008"),
               "2009-2019": ("2009", "2019"), "2020 코로나": ("2020", "2020"),
               "2021": ("2021", "2021"), "2022 긴축": ("2022", "2022"),
               "2023-현재": ("2023", "2099")}
    p_rows = []
    for nm, (a, b) in periods.items():
        s = ret.loc[a:b]
        if len(s) < 20:
            continue
        m, t = metrics(s, rf), metrics(etf_cc["TQQQ"].loc[s.index], rf)
        p_rows.append([nm, f"{m['CAGR']:.1%}", f"{m['MDD']:.1%}", f"{t['CAGR']:.1%}", f"{t['MDD']:.1%}"])
    print("\n[2] 구간별 (개선 전략 vs TQQQ 보유)")
    print(pd.DataFrame(p_rows, columns=["구간", "전략CAGR", "전략MDD", "TQQQ CAGR", "TQQQ MDD"]).to_string(index=False))

    # 상태/배분 일수, 거래 횟수 비교
    t = tgt.loc[START:].dropna()
    print("\n[3] 배분 비중(일수 기준)")
    print((t.value_counts(normalize=True)).map("{:.1%}".format).to_string())
    s2 = sig.loc[START:].dropna(subset=["target"])
    bear_lo = ((s2["state"] == "BEAR") & (s2["vix10"] < P["vix_lo"])).sum()
    print(f"하락장 & VIX10<{P['vix_lo']:.0f} 일수(규칙 6 해당): {bear_lo}일 / 하락장 전체 {(s2['state']=='BEAR').sum()}일")
    yrs = len(ret) / TD
    print(f"포지션 변경 횟수 (히스테리시스 적용 전 -> 후): "
          f"{int(chg_legacy.sum())}회 (연 {chg_legacy.sum()/yrs:.1f}회) -> "
          f"{int(chg.sum())}회 (연 {chg.sum()/yrs:.1f}회)")

    # 민감도: VIX 상단 x 낙폭 (복귀 임계값은 이탈값 대비 VIX -3p, DD -2%p 연동)
    print("\n[4] 민감도 ① VIX 상단 × 낙폭한도  (셀: CAGR / MDD)")
    vs, ds = [24, 26, 28, 30, 32], [0.07, 0.09, 0.11]
    g = pd.DataFrame(index=[f"VIX≥{v}" for v in vs], columns=[f"DD>{d:.0%}" for d in ds])
    for v in vs:
        for d in ds:
            m = metrics(backtest(df, vix_hi=v, vix_re=v - 3.0, dd_lim=d, dd_re=max(0.03, d - 0.02))[0], rf)
            g.loc[f"VIX≥{v}", f"DD>{d:.0%}"] = f"{m['CAGR']:.1%} / {m['MDD']:.0%}"
    print(g.to_string())

    print("\n[5] 민감도 ② 상승밴드 × 하락밴드  (셀: CAGR / MDD)")
    ups, dns = [1.00, 1.01, 1.02], [0.93, 0.95, 0.97]
    g2 = pd.DataFrame(index=[f"up×{u}" for u in ups], columns=[f"dn×{d}" for d in dns])
    for u in ups:
        for d in dns:
            m = metrics(backtest(df, up=u, dn=d)[0], rf)
            g2.loc[f"up×{u}", f"dn×{d}"] = f"{m['CAGR']:.1%} / {m['MDD']:.0%}"
    print(g2.to_string())

    # 저장 (CSV는 UTF-8 BOM)
    out = pd.DataFrame({
        "ndx": df["ndx"].loc[ret.index],
        "ma250": df["ndx"].rolling(250).mean().loc[ret.index],
        "high252": df["ndx"].rolling(252, min_periods=252).max().loc[ret.index],
        "strategy_ret": ret,
        "equity": (1 + ret).cumprod(),
    })
    out = out.join(sig[["state", "vix10", "dd", "target"]])
    out.to_csv("backtest_result.csv", encoding="utf-8-sig")
    tbl.to_csv("backtest_summary.csv", encoding="utf-8-sig")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(11, 5))
        ax.plot((1 + ret).cumprod(), label="Strategy (Improved: Next-Open + Hysteresis)")
        ax.plot((1 + ret_legacy).cumprod(), label="Strategy (Legacy: Close Exec)", linestyle="--", alpha=.75)
        ax.plot((1 + etf_cc["TQQQ"].loc[ret.index]).cumprod(), label="TQQQ B&H (synthetic)", alpha=.5)
        ax.plot((1 + etf_cc["QQQ"].loc[ret.index]).cumprod(), label="QQQ B&H (synthetic)", alpha=.5)
        ax.set_yscale("log"); ax.legend(); ax.grid(alpha=.3)
        ax.set_title("NDX regime strategy (log scale)")
        fig.tight_layout(); fig.savefig("backtest_equity.png", dpi=120)
    except Exception as e:
        print("차트 생략:", e)
    if not synthetic:
        try:
            from soxl_regime_backtest import generate_soxl_backtest_csv
            generate_soxl_backtest_csv()
        except Exception as e:
            print("SOXL 백테스트 CSV 갱신 생략:", e)
    try:
        from web_dashboard import generate_dashboard
        sys.argv.append("--no-open")
        generate_dashboard("backtest_result.csv", "dashboard.html", "backtest_result_soxl.csv")
    except Exception as e:
        print("웹 대시보드 갱신 생략:", e)
    print("\n저장: backtest_result.csv / backtest_summary.csv / backtest_equity.png / dashboard.html")


if __name__ == "__main__":
    main()
