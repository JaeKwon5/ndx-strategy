"""
NDX(나스닥100) & SOX(필라델피아 반도체) 250일선 레짐 + VIX10 + 52주 낙폭 전략 모바일/웹 대시보드
- 스마트폰 최적화(반응형 UI + 홈 화면 웹앱/PWA 메타태그) 지원
- 상단 탭 전환으로 [나스닥 TQQQ / QLD+QQQ] 전략과 [반도체 SOXL / USD+QQQM (^SOX 신호)] 전략을 즉시 비교
- GitHub Pages 정적 배포용 index.html 및 로컬 확인용 dashboard.html 동시 생성
"""
import sys
import json
import socket
import webbrowser
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import pandas as pd
from ndx_regime_backtest import P


BASE_DIR = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))


def _extract_strategy_payload(csv_path: Path, index_col_name: str, index_label: str,
                              agg_name: str, agg_label: str, def_name: str, def_label: str,
                              ret_col_prefer: str = "strategy_ret"):
    df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    valid = df.dropna(subset=["target"])

    today_dt = valid.index[-1]
    prev_dt = valid.index[-2]
    today = valid.loc[today_dt]
    prev = valid.loc[prev_dt]

    curr_tgt = str(today["target"])
    prev_tgt = str(prev["target"])
    changed = curr_tgt != prev_tgt
    curr_state = str(today["state"])
    curr_vix10 = float(today["vix10"])
    curr_dd = float(today["dd"]) * 100.0

    has_px = index_col_name in valid.columns and pd.notna(today.get(index_col_name))
    curr_px = float(today[index_col_name]) if has_px else None
    curr_ma250 = float(today["ma250"]) if ("ma250" in valid.columns and pd.notna(today.get("ma250"))) else None
    curr_ma_ratio = (curr_px / curr_ma250 * 100.0) if (curr_px and curr_ma250) else (104.0 if curr_state == "BULL" else 92.0)

    sub_text = (
        f"{index_label} {curr_px:,.1f} / 250일선 {curr_ma250:,.1f} ({curr_ma_ratio:.1f}%)"
        if (curr_px and curr_ma250)
        else f"상향돌파 ×{P['up']} / 하향이탈 ×{P['dn']}"
    )

    ret_col = ret_col_prefer if ret_col_prefer in valid.columns else "strategy_ret"

    yearly_stats = {}
    start_yr = max(1991, int(valid.index[0].year))
    for yr in range(start_yr, int(today_dt.year) + 1):
        sub = valid.loc[str(yr):, ret_col].dropna()
        if len(sub) < 10:
            continue
        eq = (1 + sub).cumprod()
        mult = float(eq.iloc[-1])
        yrs_cnt = len(sub) / 252.0
        cagr = float((mult ** (1 / yrs_cnt) - 1) * 100) if yrs_cnt > 0 else 0.0
        mdd = float((eq / eq.cummax() - 1).min() * 100)
        yearly_stats[str(yr)] = {
            "mult": round(mult, 2),
            "cagr": round(cagr, 1),
            "mdd": round(mdd, 1),
            "start_date": str(sub.index[0].date()),
        }

    recent30 = []
    for dt, row in valid.tail(30).iloc[::-1].iterrows():
        r_val = row.get(ret_col, row["strategy_ret"])
        recent30.append({
            "date": dt.strftime("%Y-%m-%d"),
            "state": str(row["state"]),
            "vix10": round(float(row["vix10"]), 2),
            "dd": round(float(row["dd"]) * 100, 2),
            "target": str(row["target"]),
            "ret": round(float(r_val) * 100, 2),
        })

    if curr_tgt == agg_name:
        hero_title = f"🔥 {agg_label}"
        short_badge = f"🔥 {agg_name} (3x)"
        prev_sim = "BULL_AGG"
    elif curr_tgt == def_name:
        hero_title = f"🛡️ {def_label}"
        short_badge = "🛡️ 1.5x 방어"
        prev_sim = "BULL_DEF" if curr_state == "BULL" else "BEAR"
    else:
        hero_title = "💵 현금 100% (0.0배 대피)"
        short_badge = "💵 CASH (0x)"
        prev_sim = "BEAR"

    return {
        "date": today_dt.strftime("%Y-%m-%d"),
        "index_label": index_label,
        "agg_name": agg_name,
        "agg_label": agg_label,
        "def_name": def_name,
        "def_label": def_label,
        "curr_tgt": curr_tgt,
        "prev_tgt": prev_tgt,
        "changed": changed,
        "curr_state": curr_state,
        "curr_vix10": round(curr_vix10, 2),
        "curr_dd": round(curr_dd, 2),
        "curr_ma_ratio": round(curr_ma_ratio, 1),
        "sub_text": sub_text,
        "hero_title": hero_title,
        "short_badge": short_badge,
        "prev_sim": prev_sim,
        "yearly": yearly_stats,
        "recent30": recent30,
    }


def generate_dashboard(csv_path="backtest_result.csv", out_html="dashboard.html",
                       soxl_csv_path="backtest_result_soxl.csv"):
    p_ndx = Path(csv_path) if Path(csv_path).is_absolute() else (BASE_DIR / csv_path)
    if not p_ndx.exists():
        raise FileNotFoundError(f"{p_ndx} 파일이 없습니다. 먼저 ndx_regime_backtest.py를 실행해 주세요.")

    p_sox = Path(soxl_csv_path) if Path(soxl_csv_path).is_absolute() else (BASE_DIR / soxl_csv_path)
    out_html_path = Path(out_html) if Path(out_html).is_absolute() else (BASE_DIR / out_html)
    if not p_sox.exists():
        try:
            from soxl_regime_backtest import generate_soxl_backtest_csv
            generate_soxl_backtest_csv()
        except Exception as e:
            print(f"[경고] {soxl_csv_path} 자동 생성 실패 ({e}), 기본 CSV로 대체합니다.")
            p_sox = p_ndx

    ndx_data = _extract_strategy_payload(
        p_ndx,
        index_col_name="ndx",
        index_label="NDX",
        agg_name="TQQQ",
        agg_label="TQQQ 100% (3.0배 공격)",
        def_name="QQQ50_QLD50",
        def_label="QQQ 50% + QLD 50% (1.5배 방어)",
        ret_col_prefer="strategy_ret",
    )

    sox_data = _extract_strategy_payload(
        p_sox if p_sox.exists() else p_ndx,
        index_col_name="sox",
        index_label="SOX",
        agg_name="SOXL",
        agg_label="SOXL 100% (3.0배 공격)",
        def_name="USD50_QQQM50",
        def_label="USD 50% + QQQM 50% (1.5배 방어)",
        ret_col_prefer="strategy_ret_hybrid",
    )

    strategies = {"NDX": ndx_data, "SOX": sox_data}
    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <meta name="theme-color" content="#020617" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
  <meta name="apple-mobile-web-app-title" content="레짐전략 대시보드" />
  <title>NDX &amp; SOX 레짐 전략 모바일 대시보드</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body {{
      font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
      -webkit-tap-highlight-color: transparent;
    }}
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen pb-10">
  <!-- 모바일 상단 고정 상태바 + 전략 전환 탭 -->
  <div class="sticky top-0 z-20 backdrop-blur-md bg-slate-950/90 border-b border-slate-800 px-4 py-2.5">
    <div class="max-w-5xl mx-auto space-y-2.5">
      <div class="flex items-center justify-between text-xs">
        <div class="flex items-center gap-2">
          <span class="inline-block w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          <span class="font-semibold text-slate-200">미국장 기준일: <span id="top-date">{ndx_data['date']}</span></span>
        </div>
        <span class="text-slate-400 font-mono">갱신: {now_kst}</span>
      </div>

      <!-- 전략 선택 탭 (NDX vs SOX) -->
      <div class="grid grid-cols-2 gap-2 bg-slate-900 p-1 rounded-xl border border-slate-800">
        <button id="tab-NDX" onclick="switchTab('NDX')" class="flex flex-col sm:flex-row items-center justify-between px-3 py-2 rounded-lg text-xs font-bold transition bg-indigo-600 text-white shadow">
          <span class="flex items-center gap-1.5">📈 나스닥 100 (<span class="font-mono">^NDX</span>)</span>
          <span class="mt-0.5 sm:mt-0 px-2 py-0.5 rounded-full text-[11px] bg-black/25 font-mono">{ndx_data['short_badge']}</span>
        </button>
        <button id="tab-SOX" onclick="switchTab('SOX')" class="flex flex-col sm:flex-row items-center justify-between px-3 py-2 rounded-lg text-xs font-bold transition text-slate-400 hover:text-slate-200">
          <span class="flex items-center gap-1.5">⚡ 반도체 (<span class="font-mono">^SOX</span>)</span>
          <span class="mt-0.5 sm:mt-0 px-2 py-0.5 rounded-full text-[11px] bg-slate-800 font-mono">{sox_data['short_badge']}</span>
        </button>
      </div>
    </div>
  </div>

  <div class="max-w-5xl mx-auto px-4 pt-4 space-y-5">

    <!-- 1. 오늘의 최종 투자 판단 카드 -->
    <div id="hero-card" class="rounded-2xl bg-gradient-to-br from-slate-900 via-slate-900 to-indigo-950 border border-slate-800 p-5 shadow-xl">
      <div class="flex flex-wrap items-center justify-between gap-2 mb-3">
        <span id="hero-subtitle" class="text-xs font-medium text-indigo-300">오늘의 목표 포트폴리오 (^NDX 신호 · 익일 시가 기준)</span>
        <span id="hero-badge" class="px-2.5 py-1 rounded-full text-xs font-bold"></span>
      </div>

      <div id="hero-title" class="text-2xl sm:text-3xl font-extrabold tracking-tight text-white"></div>
      <p id="hero-desc" class="text-xs sm:text-sm text-slate-300 mt-1.5"></p>

      <!-- 모바일 핵심 지표 그리드 -->
      <div class="grid grid-cols-2 sm:grid-cols-3 gap-3 mt-5">
        <div class="bg-slate-900/90 border border-slate-800 rounded-xl p-3.5">
          <div id="lbl-regime" class="text-xs text-slate-400">시장 레짐 (NDX 250일선)</div>
          <div id="val-regime" class="text-lg font-bold mt-0.5"></div>
          <div id="sub-regime" class="text-[11px] text-slate-400 mt-0.5 truncate"></div>
        </div>

        <div class="bg-slate-900/90 border border-slate-800 rounded-xl p-3.5">
          <div class="text-xs text-slate-400">VIX 10일 평균 (VIX10)</div>
          <div id="val-vix" class="text-lg font-bold mt-0.5 font-mono"></div>
          <div class="text-[11px] text-slate-400 mt-0.5">방어 ≥{P['vix_hi']:.0f} / 복귀 &lt;{P['vix_re']:.0f}</div>
        </div>

        <div class="col-span-2 sm:col-span-1 bg-slate-900/90 border border-slate-800 rounded-xl p-3.5">
          <div id="lbl-dd" class="text-xs text-slate-400">52주 고점 대비 낙폭 (NDX DD)</div>
          <div id="val-dd" class="text-lg font-bold mt-0.5 font-mono"></div>
          <div class="text-[11px] text-slate-400 mt-0.5">방어 전환 &gt;{P['dd_lim']*100:.0f}% / 3x 복귀 ≤{P['dd_re']*100:.0f}%</div>
        </div>
      </div>
    </div>

    <!-- 2. 전략 투자 판단 기준표 & 조건 시뮬레이터 -->
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-5">
      <div class="lg:col-span-7 bg-slate-900 border border-slate-800 rounded-2xl p-4 sm:p-6 space-y-3">
        <div class="flex items-center justify-between">
          <h2 id="tbl-title" class="text-base sm:text-lg font-bold">전략 투자 판단 기준표 (^NDX 신호)</h2>
          <span class="text-xs text-indigo-300">현재 적용 규칙 하이라이트</span>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-left border-collapse text-xs sm:text-sm">
            <thead>
              <tr class="border-b border-slate-800 text-xs text-slate-400">
                <th class="py-2 px-2.5">구분</th>
                <th id="th-ma" class="py-2 px-2.5">NDX 250일선</th>
                <th class="py-2 px-2.5">VIX10 &amp; 낙폭(DD)</th>
                <th class="py-2 px-2.5">목표 자산</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800/70">
              <tr id="rule-bull-tqqq" class="transition">
                <td class="py-2.5 px-2.5 font-semibold text-emerald-400 whitespace-nowrap">BULL 공격</td>
                <td class="py-2.5 px-2.5 font-mono text-xs">&gt; MA250×1.01</td>
                <td class="py-2.5 px-2.5 text-xs">
                  유지: VIX10&lt;28 &amp; DD≤9%<br>
                  <span class="text-slate-400">복귀: VIX10&lt;25 &amp; DD≤7%</span>
                </td>
                <td id="td-asset-agg" class="py-2.5 px-2.5 font-bold whitespace-nowrap">🔥 TQQQ (3x)</td>
              </tr>
              <tr id="rule-bull-def" class="transition">
                <td class="py-2.5 px-2.5 font-semibold text-indigo-400 whitespace-nowrap">BULL 방어</td>
                <td class="py-2.5 px-2.5 font-mono text-xs">&gt; MA250×1.01</td>
                <td class="py-2.5 px-2.5 text-xs">
                  VIX10≥28 또는 DD&gt;9%<br>
                  <span class="text-slate-400">(복귀 조건 충족 전까지 유지)</span>
                </td>
                <td id="td-asset-def1" class="py-2.5 px-2.5 font-bold whitespace-nowrap">🛡️ QQQ+QLD (1.5x)</td>
              </tr>
              <tr id="rule-bear-dip" class="transition">
                <td class="py-2.5 px-2.5 font-semibold text-amber-400 whitespace-nowrap">BEAR 역발상</td>
                <td class="py-2.5 px-2.5 font-mono text-xs">&lt; MA250×0.95</td>
                <td class="py-2.5 px-2.5 text-xs">하락장 중 VIX10 &lt; 18</td>
                <td id="td-asset-def2" class="py-2.5 px-2.5 font-bold whitespace-nowrap">🛡️ QQQ+QLD (1.5x)</td>
              </tr>
              <tr id="rule-bear-cash" class="transition">
                <td class="py-2.5 px-2.5 font-semibold text-rose-400 whitespace-nowrap">BEAR 대피</td>
                <td class="py-2.5 px-2.5 font-mono text-xs">&lt; MA250×0.95</td>
                <td class="py-2.5 px-2.5 text-xs">하락장 중 VIX10 ≥ 18</td>
                <td class="py-2.5 px-2.5 font-bold whitespace-nowrap">💵 CASH (0x)</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 모의 판정 시뮬레이터 -->
      <div class="lg:col-span-5 bg-slate-900 border border-slate-800 rounded-2xl p-4 sm:p-6 space-y-4">
        <div class="flex items-center justify-between">
          <h2 class="text-base sm:text-lg font-bold">조건 시뮬레이터</h2>
          <button id="sim-reset" class="px-2.5 py-1 text-xs rounded bg-slate-800 hover:bg-slate-700 text-slate-200 transition">
            오늘 수치로 복원
          </button>
        </div>

        <div class="p-3.5 rounded-xl bg-slate-950 border border-slate-800 flex items-center justify-between">
          <div>
            <div class="text-xs text-slate-400" id="sim-reason">판정 결과</div>
            <div class="text-base sm:text-lg font-bold text-indigo-400 mt-0.5" id="sim-result"></div>
          </div>
          <span id="sim-regime" class="px-2.5 py-1 rounded text-xs font-bold bg-emerald-500/20 text-emerald-300">BULL</span>
        </div>

        <div class="space-y-3 text-xs">
          <div>
            <div class="flex justify-between mb-1">
              <span id="sim-lbl-ma" class="text-slate-400">① NDX / 250일선 비율 (돌파 101% / 이탈 95%)</span>
              <span id="sim-ma-txt" class="font-mono font-bold"></span>
            </div>
            <input id="sim-ma" type="range" min="80" max="125" step="0.2" value="104.0" class="w-full accent-indigo-500" />
          </div>

          <div>
            <div class="flex justify-between mb-1">
              <span class="text-slate-400">② VIX 10일 평균 (역발상 18 / 복귀 25 / 이탈 28)</span>
              <span id="sim-vix-txt" class="font-mono font-bold"></span>
            </div>
            <input id="sim-vix" type="range" min="11" max="42" step="0.1" value="18.0" class="w-full accent-indigo-500" />
          </div>

          <div>
            <div class="flex justify-between mb-1">
              <span id="sim-lbl-dd" class="text-slate-400">③ 52주 고점 대비 낙폭 (복귀 7% / 이탈 9%)</span>
              <span id="sim-dd-txt" class="font-mono font-bold"></span>
            </div>
            <input id="sim-dd" type="range" min="0" max="35" step="0.1" value="3.0" class="w-full accent-indigo-500" />
          </div>

          <div class="pt-1 flex items-center justify-between text-slate-400">
            <span>직전 상태:</span>
            <div class="flex gap-2.5">
              <label class="inline-flex items-center gap-1 cursor-pointer">
                <input type="radio" name="sim-prev" value="BULL_AGG" class="accent-indigo-500" />
                <span id="sim-radio-agg">TQQQ중</span>
              </label>
              <label class="inline-flex items-center gap-1 cursor-pointer">
                <input type="radio" name="sim-prev" value="BULL_DEF" class="accent-indigo-500" />
                <span>1.5x방어중</span>
              </label>
              <label class="inline-flex items-center gap-1 cursor-pointer">
                <input type="radio" name="sim-prev" value="BEAR" class="accent-indigo-500" />
                <span>BEAR중</span>
              </label>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 3. 원금 & 진입 연도별 수익 계산기 -->
    <div class="bg-slate-900 border border-slate-800 rounded-2xl p-4 sm:p-6 space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="calc-title" class="text-base sm:text-lg font-bold">원금 &amp; 진입 연도별 성과 계산기</h2>
          <p id="calc-note" class="text-xs text-slate-400 mt-0.5"></p>
        </div>
        <div class="flex items-center gap-2 text-xs sm:text-sm">
          <input id="cap-input" type="number" value="1000" min="10" step="100" class="w-24 px-2.5 py-1.5 rounded bg-slate-950 border border-slate-700 text-right font-mono font-bold text-indigo-300" />
          <span class="text-slate-400">만원</span>
          <select id="yr-select" class="px-2.5 py-1.5 rounded bg-slate-950 border border-slate-700 font-mono font-bold text-emerald-300"></select>
        </div>
      </div>

      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div class="p-3.5 rounded-xl bg-slate-950 border border-slate-800">
          <div class="text-xs text-slate-400">최종 평가금액</div>
          <div id="calc-final" class="text-base sm:text-xl font-bold text-emerald-400 mt-1">-</div>
        </div>
        <div class="p-3.5 rounded-xl bg-slate-950 border border-slate-800">
          <div class="text-xs text-slate-400">누적 배수</div>
          <div id="calc-mult" class="text-base sm:text-xl font-bold text-slate-100 mt-1">-</div>
        </div>
        <div class="p-3.5 rounded-xl bg-slate-950 border border-slate-800">
          <div class="text-xs text-slate-400">연평균 (CAGR)</div>
          <div id="calc-cagr" class="text-base sm:text-xl font-bold text-indigo-400 mt-1">-</div>
        </div>
        <div class="p-3.5 rounded-xl bg-slate-950 border border-slate-800">
          <div class="text-xs text-slate-400">최대낙폭 (MDD)</div>
          <div id="calc-mdd" class="text-base sm:text-xl font-bold text-rose-400 mt-1">-</div>
        </div>
      </div>
    </div>

    <!-- 4. 최근 30거래일 신호 일지 -->
    <div class="bg-slate-900 border border-slate-800 rounded-2xl p-4 sm:p-6 space-y-3">
      <h2 id="recent-title" class="text-base sm:text-lg font-bold">최근 30거래일 신호 일지</h2>
      <div class="overflow-x-auto max-h-72">
        <table class="w-full text-left border-collapse text-xs">
          <thead class="sticky top-0 bg-slate-900 border-b border-slate-800 text-slate-400">
            <tr>
              <th class="py-2 px-2.5">날짜</th>
              <th class="py-2 px-2.5">레짐</th>
              <th class="py-2 px-2.5">VIX10</th>
              <th class="py-2 px-2.5">낙폭(DD)</th>
              <th class="py-2 px-2.5">목표 자산</th>
              <th class="py-2 px-2.5 text-right">수익률</th>
            </tr>
          </thead>
          <tbody id="recent-tbody" class="divide-y divide-slate-800/60 font-mono"></tbody>
        </table>
      </div>
    </div>

  </div>

  <script>
    const STRATEGIES = {json.dumps(strategies, ensure_ascii=False)};
    let currentTab = 'NDX';

    const simMa = document.getElementById('sim-ma');
    const simVix = document.getElementById('sim-vix');
    const simDd = document.getElementById('sim-dd');
    const simMaTxt = document.getElementById('sim-ma-txt');
    const simVixTxt = document.getElementById('sim-vix-txt');
    const simDdTxt = document.getElementById('sim-dd-txt');
    const simResult = document.getElementById('sim-result');
    const simReason = document.getElementById('sim-reason');
    const simRegime = document.getElementById('sim-regime');
    const yrSelect = document.getElementById('yr-select');
    const capInput = document.getElementById('cap-input');

    const ruleRows = {{
      'BULL_TQQQ': document.getElementById('rule-bull-tqqq'),
      'BULL_DEF': document.getElementById('rule-bull-def'),
      'BEAR_DIP': document.getElementById('rule-bear-dip'),
      'BEAR_CASH': document.getElementById('rule-bear-cash'),
    }};

    function updateSim() {{
      const d = STRATEGIES[currentTab];
      const ma = parseFloat(simMa.value);
      const vix = parseFloat(simVix.value);
      const dd = parseFloat(simDd.value);
      const prevEl = document.querySelector('input[name="sim-prev"]:checked');
      const prev = prevEl ? prevEl.value : 'BULL_AGG';

      simMaTxt.textContent = ma.toFixed(1) + '%';
      simVixTxt.textContent = vix.toFixed(2);
      simDdTxt.textContent = '-' + dd.toFixed(2) + '%';

      let state = 'BULL';
      if (ma > 101.0) state = 'BULL';
      else if (ma < 95.0) state = 'BEAR';
      else state = (prev === 'BEAR') ? 'BEAR' : 'BULL';

      let key = '';
      if (state === 'BULL') {{
        let def = false;
        if (prev === 'BEAR') def = !(vix < 28 && dd <= 9);
        else if (prev === 'BULL_DEF') def = !(vix < 25 && dd <= 7);
        else def = (vix >= 28 || dd > 9);

        if (def) {{
          key = 'BULL_DEF';
          simResult.textContent = '🛡️ ' + d.def_label;
          simReason.textContent = 'BULL 방어 모드 (과열/조정 감속)';
        }} else {{
          key = 'BULL_TQQQ';
          simResult.textContent = '🔥 ' + d.agg_label;
          simReason.textContent = 'BULL 공격 모드 (변동성·낙폭 안정)';
        }}
        simRegime.textContent = 'BULL';
        simRegime.className = 'px-2.5 py-1 rounded text-xs font-bold bg-emerald-500/20 text-emerald-300';
      }} else {{
        simRegime.textContent = 'BEAR';
        simRegime.className = 'px-2.5 py-1 rounded text-xs font-bold bg-amber-500/20 text-amber-300';
        if (vix < 18) {{
          key = 'BEAR_DIP';
          simResult.textContent = '🛡️ ' + d.def_label;
          simReason.textContent = 'BEAR 역발상 모드 (VIX10 < 18)';
        }} else {{
          key = 'BEAR_CASH';
          simResult.textContent = '💵 CASH 100% (0.0x)';
          simReason.textContent = 'BEAR 현금 대피 모드 (VIX10 ≥ 18)';
        }}
      }}

      Object.entries(ruleRows).forEach(([k, tr]) => {{
        tr.className = (k === key)
          ? 'bg-indigo-950/80 border-l-4 border-indigo-400'
          : 'opacity-50 hover:opacity-90 transition';
      }});
    }}

    function formatKRW(manwon) {{
      if (manwon >= 10000) {{
        const eok = Math.floor(manwon / 10000);
        const rem = Math.round(manwon % 10000);
        return rem > 0 ? `약 ${{eok.toLocaleString()}}억 ${{rem.toLocaleString()}}만` : `약 ${{eok.toLocaleString()}}억 원`;
      }}
      return `약 ${{Math.round(manwon).toLocaleString()}}만 원`;
    }}

    function updateCalc() {{
      const d = STRATEGIES[currentTab];
      const yr = yrSelect.value;
      const cap = parseFloat(capInput.value) || 1000;
      const stat = d.yearly[yr];
      if (!stat) return;
      document.getElementById('calc-final').textContent = formatKRW(cap * stat.mult);
      document.getElementById('calc-mult').textContent = stat.mult.toLocaleString() + '배';
      document.getElementById('calc-cagr').textContent = '+' + stat.cagr + '%';
      document.getElementById('calc-mdd').textContent = stat.mdd + '%';
    }}

    function switchTab(tabKey) {{
      currentTab = tabKey;
      const d = STRATEGIES[tabKey];

      // 탭 버튼 스타일 업데이트
      const btnNdx = document.getElementById('tab-NDX');
      const btnSox = document.getElementById('tab-SOX');
      if (tabKey === 'NDX') {{
        btnNdx.className = 'flex flex-col sm:flex-row items-center justify-between px-3 py-2 rounded-lg text-xs font-bold transition bg-indigo-600 text-white shadow';
        btnSox.className = 'flex flex-col sm:flex-row items-center justify-between px-3 py-2 rounded-lg text-xs font-bold transition text-slate-400 hover:text-slate-200';
      }} else {{
        btnSox.className = 'flex flex-col sm:flex-row items-center justify-between px-3 py-2 rounded-lg text-xs font-bold transition bg-emerald-600 text-white shadow';
        btnNdx.className = 'flex flex-col sm:flex-row items-center justify-between px-3 py-2 rounded-lg text-xs font-bold transition text-slate-400 hover:text-slate-200';
      }}

      document.getElementById('top-date').textContent = d.date;

      // 1. 상단 히어로 카드 업데이트
      document.getElementById('hero-subtitle').textContent =
        tabKey === 'NDX'
          ? '오늘의 목표 포트폴리오 (^NDX 나스닥 100 신호 · 익일 시가 기준)'
          : '오늘의 목표 포트폴리오 (^SOX 반도체 신호 · 익일 시가 기준)';

      const badge = document.getElementById('hero-badge');
      if (d.changed) {{
        badge.className = 'px-2.5 py-1 rounded-full text-xs font-bold bg-rose-500/20 text-rose-300 border border-rose-500/40';
        badge.textContent = `🚨 포지션 변경 (${{d.prev_tgt}} ➔ ${{d.curr_tgt}})`;
      }} else {{
        badge.className = 'px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40';
        badge.textContent = `✅ 포지션 유지 (${{d.curr_tgt}})`;
      }}

      document.getElementById('hero-title').textContent = d.hero_title;
      document.getElementById('hero-desc').textContent = d.changed
        ? `오늘 밤 미국장 시가(Open)에 ${{d.curr_tgt}} 비중으로 리밸런싱이 필요합니다.`
        : '전일과 목표 포지션이 동일하므로 매매 없이 현재 비중을 그대로 유지합니다.';

      document.getElementById('lbl-regime').textContent = `시장 레짐 (${{d.index_label}} 250일선)`;
      const valRegime = document.getElementById('val-regime');
      valRegime.textContent = `${{d.curr_state}} (${{d.curr_state === 'BULL' ? '상승장' : '하락장'}})`;
      valRegime.className = 'text-lg font-bold mt-0.5 ' + (d.curr_state === 'BULL' ? 'text-emerald-400' : 'text-amber-400');
      document.getElementById('sub-regime').textContent = d.sub_text;

      const valVix = document.getElementById('val-vix');
      valVix.textContent = d.curr_vix10.toFixed(2);
      valVix.className = 'text-lg font-bold mt-0.5 font-mono ' + (d.curr_vix10 >= 28 ? 'text-rose-400' : 'text-slate-100');

      document.getElementById('lbl-dd').textContent = `52주 고점 대비 낙폭 (${{d.index_label}} DD)`;
      const valDd = document.getElementById('val-dd');
      valDd.textContent = `-${{d.curr_dd.toFixed(2)}}%`;
      valDd.className = 'text-lg font-bold mt-0.5 font-mono ' + (d.curr_dd > 9 ? 'text-amber-400' : 'text-slate-100');

      // 2. 기준표 및 시뮬레이터 업데이트
      document.getElementById('tbl-title').textContent = `전략 투자 판단 기준표 (^${{d.index_label}} 신호)`;
      document.getElementById('th-ma').textContent = `${{d.index_label}} 250일선`;
      document.getElementById('td-asset-agg').textContent = `🔥 ${{d.agg_name}} (3x)`;
      document.getElementById('td-asset-def1').textContent = tabKey === 'NDX' ? '🛡️ QQQ+QLD (1.5x)' : '🛡️ USD+QQQM (1.5x)';
      document.getElementById('td-asset-def2').textContent = tabKey === 'NDX' ? '🛡️ QQQ+QLD (1.5x)' : '🛡️ USD+QQQM (1.5x)';

      document.getElementById('sim-lbl-ma').textContent = `① ${{d.index_label}} / 250일선 비율 (돌파 101% / 이탈 95%)`;
      document.getElementById('sim-lbl-dd').textContent = `③ ${{d.index_label}} 52주 고점 대비 낙폭 (복귀 7% / 이탈 9%)`;
      document.getElementById('sim-radio-agg').textContent = `${{d.agg_name}}중`;

      simMa.value = d.curr_ma_ratio.toFixed(1);
      simVix.value = d.curr_vix10.toFixed(2);
      simDd.value = d.curr_dd.toFixed(2);
      const radioToCheck = document.querySelector(`input[name="sim-prev"][value="${{d.prev_sim}}"]`);
      if (radioToCheck) radioToCheck.checked = true;
      updateSim();

      // 3. 연도별 성과 계산기 업데이트
      document.getElementById('calc-title').textContent =
        tabKey === 'NDX'
          ? '원금 & 진입 연도별 성과 계산기 (나스닥 TQQQ / QLD+QQQ)'
          : '원금 & 진입 연도별 성과 계산기 (반도체 SOXL / USD+QQQM)';
      document.getElementById('calc-note').textContent =
        tabKey === 'NDX'
          ? '^NDX 합성 수익률 (배당·스왑스프레드·익일시가 체결 반영)'
          : '1995~2010년 ^SOX 합성 + 2010.03 이후 실제 SOXL/USD/QQQM 상장 ETF 주가 반영';

      const prevYr = yrSelect.value || '2011';
      yrSelect.innerHTML = '';
      const yrs = Object.keys(d.yearly);
      yrs.forEach(yr => {{
        const opt = document.createElement('option');
        opt.value = yr;
        opt.textContent = yr + '년 초';
        yrSelect.appendChild(opt);
      }});
      if (d.yearly[prevYr]) yrSelect.value = prevYr;
      else if (d.yearly['2011']) yrSelect.value = '2011';
      else if (yrs.length > 0) yrSelect.value = yrs[0];
      updateCalc();

      // 4. 최근 30거래일 신호 일지 업데이트
      document.getElementById('recent-title').textContent =
        `최근 30거래일 신호 일지 (^${{d.index_label}} ➔ ${{d.agg_name}} / ${{tabKey === 'NDX' ? 'QLD+QQQ' : 'USD+QQQM'}})`;
      const tbody = document.getElementById('recent-tbody');
      tbody.innerHTML = '';
      d.recent30.forEach(r => {{
        const tr = document.createElement('tr');
        tr.className = 'hover:bg-slate-800/40';
        const retColor = r.ret >= 0 ? 'text-emerald-400' : 'text-rose-400';
        tr.innerHTML = `
          <td class="py-2 px-2.5 whitespace-nowrap">${{r.date}}</td>
          <td class="py-2 px-2.5">${{r.state}}</td>
          <td class="py-2 px-2.5">${{r.vix10.toFixed(2)}}</td>
          <td class="py-2 px-2.5">-${{r.dd.toFixed(2)}}%</td>
          <td class="py-2 px-2.5 font-bold text-indigo-300 whitespace-nowrap">${{r.target}}</td>
          <td class="py-2 px-2.5 text-right ${{retColor}}">${{r.ret >= 0 ? '+' : ''}}${{r.ret.toFixed(2)}}%</td>
        `;
        tbody.appendChild(tr);
      }});
    }}

    [simMa, simVix, simDd].forEach(el => el.addEventListener('input', updateSim));
    document.querySelectorAll('input[name="sim-prev"]').forEach(el => el.addEventListener('change', updateSim));
    document.getElementById('sim-reset').addEventListener('click', () => {{
      const d = STRATEGIES[currentTab];
      simMa.value = d.curr_ma_ratio.toFixed(1);
      simVix.value = d.curr_vix10.toFixed(2);
      simDd.value = d.curr_dd.toFixed(2);
      const radioToCheck = document.querySelector(`input[name="sim-prev"][value="${{d.prev_sim}}"]`);
      if (radioToCheck) radioToCheck.checked = true;
      updateSim();
    }});
    yrSelect.addEventListener('change', updateCalc);
    capInput.addEventListener('input', updateCalc);

    // 초기 렌더링
    switchTab('NDX');
  </script>
</body>
</html>
"""
    out_p = out_html_path.resolve()
    out_p.write_text(html, encoding="utf-8")
    idx_p = out_p.parent / "index.html"
    idx_p.write_text(html, encoding="utf-8")

    print(f"[완료] 모바일/웹 대시보드(NDX + SOX 탭 통합) 생성 완료: {out_p} (및 index.html)")
    if "--no-open" not in sys.argv and "--serve" not in sys.argv:
        webbrowser.open(out_p.as_uri())
    return out_p


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def serve_dashboard(port=8080):
    generate_dashboard(out_html="dashboard.html")
    ip = get_local_ip()
    print("=" * 60)
    print("📱 스마트폰 접속 주소 (동일 Wi-Fi 연결 시):")
    print(f"   http://{ip}:{port}/dashboard.html")
    print(f"💻 PC 접속 주소:")
    print(f"   http://localhost:{port}/dashboard.html")
    print("=" * 60)
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()


if __name__ == "__main__":
    if "--update" in sys.argv:
        import ndx_regime_backtest
        ndx_regime_backtest.main()
    elif "--serve" in sys.argv:
        serve_dashboard()
    else:
        generate_dashboard()
