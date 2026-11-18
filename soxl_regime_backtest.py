"""
SOXL + (USD 50% + QQQM 50%) + CASH 레짐 전략 백테스트 (^SOX 신호 기준 메인)
- 기존 NDX 250일선 레짐 + VIX10 + 52주 낙폭 전략과 완전히 동일한 조건 적용:
  1) 익일 시가(Next-Open) 체결 + 거래비용(편도 0.05%)
  2) SOXL 진입·이탈 히스테리시스 (이탈: VIX10>=28 또는 DD>9% / 복귀: VIX10<25 및 DD<=7%)
  3) USD50_QQQM50 구간 유지 시 비중 자연 드리프트(Buy & Hold) 반영
- 실행 시 backtest_result_soxl.csv 생성 (web_dashboard.py 반도체 탭 연동용)
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

BASE_DIR = Path(__file__).resolve().parent

# ---------------- 파라미터 (기존과 100% 동일) ----------------
P = dict(
    up=1.01, dn=0.95,
    vix_hi=28.0, vix_re=25.0,
    vix_lo=18.0,
    dd_lim=0.09, dd_re=0.07,
)
TRADE_COST = 0.0005             # 편도 0.05%
DIV_YIELD_NDX = 0.0080          # ^NDX 연평균 배당수익률 가정 (0.80%)
DIV_YIELD_SOX = 0.0100          # ^SOX 연평균 배당수익률 가정 (1.00%)
SWAP_SPREAD = 0.0050            # 레버리지 스왑 조달 가산금리 (연 0.50%p)
ER = {
    "QQQ": 0.0020,
    "QQQM": 0.0015,             # QQQM 운용보수 연 0.15%
    "QLD": 0.0095,
    "TQQQ": 0.0095,
    "USD": 0.0095,              # ProShares Ultra Semiconductors (2x) 연 0.95%
    "SOXL": 0.0076,             # Direxion Daily Semiconductor Bull 3X 연 0.76%
}
TD = 252

TARGET_NAMES_SOX = {
    "AGG_3X": "SOXL",
    "DEF_1.5X": "USD50_QQQM50",
    "CASH": "CASH",
    None: None,
}


def load_market_data():
    tickers = ["^NDX", "^SOX", "^VIX", "^IRX", "SOXL", "USD", "QQQ", "TQQQ", "QLD"]
    raw = yf.download(tickers, start="1994-01-01", auto_adjust=True, progress=False)

    close = raw["Close"]
    open_p = raw["Open"]

    df = pd.DataFrame(index=close.index)
    for t, col in [("^NDX", "ndx"), ("^SOX", "sox"), ("^VIX", "vix"), ("^IRX", "irx"),
                   ("SOXL", "soxl_real"), ("USD", "usd_real"), ("QQQ", "qqq_real"),
                   ("TQQQ", "tqqq_real"), ("QLD", "qld_real")]:
        if t in close.columns:
            df[col] = close[t]
        if t in open_p.columns and col not in ("vix", "irx"):
            o = open_p[t]
            df[col + "_open"] = o.where(o > 0, df[col].shift(1)).fillna(df[col])

    df["irx"] = df["irx"].ffill().bfill() / 100.0
    return df.dropna(subset=["ndx", "sox", "vix"])


def build_signal(df, price_col="sox", up=1.01, dn=0.95, vix_hi=28.0, vix_re=25.0,
                 vix_lo=18.0, dd_lim=0.09, dd_re=0.07):
    px = df[price_col]
    ma250 = px.rolling(250).mean()
    vix10 = df["vix"].rolling(10).mean()
    dd = 1 - px / px.rolling(252, min_periods=252).max()

    state = None
    bull_defensive = False
    st_out, tgt_out = [], []

    for p, m, v, d in zip(px.values, ma250.values, vix10.values, dd.values):
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

        if np.isnan(v) or np.isnan(d):
            tgt_out.append(None)
            continue

        if state == "BULL":
            if prev_state != "BULL":
                bull_defensive = not (v < vix_hi and d <= dd_lim)
            elif bull_defensive:
                if v < vix_re and d <= dd_re:
                    bull_defensive = False
            else:
                if v >= vix_hi or d > dd_lim:
                    bull_defensive = True

            tgt_out.append("DEF_1.5X" if bull_defensive else "AGG_3X")
        else:
            bull_defensive = True
            tgt_out.append("DEF_1.5X" if v < vix_lo else "CASH")

    return pd.DataFrame({"state": st_out, "vix10": vix10, "dd": dd, "target": tgt_out}, index=px.index)


def synthetic_etf_returns(df):
    """^NDX 및 ^SOX 기반 합성 ETF 수익률 (종가~종가, 오버나잇, 장중)"""
    rf = df["irx"] / TD
    borrow_d = rf + SWAP_SPREAD / TD

    specs = {
        "QQQ":  ("ndx", 1.0, DIV_YIELD_NDX, ER["QQQ"]),
        "QQQM": ("ndx", 1.0, DIV_YIELD_NDX, ER["QQQM"]),
        "QLD":  ("ndx", 2.0, DIV_YIELD_NDX, ER["QLD"]),
        "TQQQ": ("ndx", 3.0, DIV_YIELD_NDX, ER["TQQQ"]),
        "USD":  ("sox", 2.0, DIV_YIELD_SOX, ER["USD"]),
        "SOXL": ("sox", 3.0, DIV_YIELD_SOX, ER["SOXL"]),
    }

    cc_dict, ov_dict, id_dict = {}, {}, {}
    for k, (col, L, div_y, er) in specs.items():
        prev_c = df[col].shift(1)
        open_p = df[col + "_open"]
        curr_c = df[col]

        r_cc = curr_c / prev_c - 1
        r_ov = (open_p / prev_c - 1).fillna(0.0)

        div_d = div_y / TD
        daily_drag = (L - 1) * borrow_d + er / TD

        cc_dict[k] = L * (r_cc + div_d) - daily_drag
        ov_dict[k] = L * (r_ov + div_d / 3.0) - daily_drag / 3.0
        id_dict[k] = (1 + cc_dict[k]) / (1 + ov_dict[k]) - 1

    cc_dict["CASH"] = rf
    ov_dict["CASH"] = rf / 3.0
    id_dict["CASH"] = rf * (2.0 / 3.0)

    return pd.DataFrame(cc_dict), pd.DataFrame(ov_dict), pd.DataFrame(id_dict), rf


def real_etf_returns(df):
    """2010년 3월 이후 실제 상장 ETF(SOXL, USD, QQQ, TQQQ, QLD) 시가/종가 수익률"""
    rf = df["irx"] / TD
    mapping = {
        "SOXL": "soxl_real",
        "USD": "usd_real",
        "QQQM": "qqq_real",
        "QQQ": "qqq_real",
        "QLD": "qld_real",
        "TQQQ": "tqqq_real",
    }
    cc_dict, ov_dict, id_dict = {}, {}, {}
    for k, col in mapping.items():
        prev_c = df[col].shift(1)
        open_p = df[col + "_open"]
        curr_c = df[col]

        r_cc = curr_c / prev_c - 1
        r_ov = (open_p / prev_c - 1).fillna(0.0)
        if k == "QQQM":
            r_cc = r_cc + (0.0020 - 0.0015) / TD
        cc_dict[k] = r_cc
        ov_dict[k] = r_ov
        id_dict[k] = (1 + cc_dict[k]) / (1 + ov_dict[k]) - 1

    cc_dict["CASH"] = rf
    ov_dict["CASH"] = rf / 3.0
    id_dict["CASH"] = rf * (2.0 / 3.0)
    return pd.DataFrame(cc_dict), pd.DataFrame(ov_dict), pd.DataFrame(id_dict), rf


def run_portfolio_backtest(df, sig, etf_cc, etf_ov, etf_id, asset_cols, weights_map,
                           start_date, exec_mode="next_open"):
    tgt_series = sig["target"].shift(1)
    ok = tgt_series.notna() & etf_cc[asset_cols].notna().all(axis=1)

    cc_arr = etf_cc[asset_cols].values
    ov_arr = etf_ov[asset_cols].values
    id_arr = etf_id[asset_cols].values
    tgt_vals = tgt_series.values
    ok_vals = ok.values

    n = len(df)
    port_ret = np.full(n, np.nan)
    changed = np.zeros(n, dtype=bool)
    w_curr = None
    prev_tgt = None

    for i in range(n):
        if not ok_vals[i]:
            continue
        t = tgt_vals[i]
        w_target = weights_map[t]

        if w_curr is None:
            w_curr = w_target.copy()
            r_day = np.dot(w_curr, cc_arr[i])
            w_curr = w_curr * (1 + cc_arr[i]) / (1 + r_day)
            port_ret[i] = r_day
            prev_tgt = t
            continue

        if t != prev_tgt:
            changed[i] = True
            if exec_mode == "next_open":
                r_ov = np.dot(w_curr, ov_arr[i])
                w_open = w_curr * (1 + ov_arr[i]) / (1 + r_ov)
                turn = np.abs(w_target - w_open).sum() / 2.0
                cost = turn * TRADE_COST * 2.0
                r_id = np.dot(w_target, id_arr[i])
                port_ret[i] = (1 + r_ov) * (1 - cost) * (1 + r_id) - 1
                w_curr = w_target * (1 + id_arr[i]) / (1 + r_id)
            else:
                turn = np.abs(w_target - w_curr).sum() / 2.0
                cost = turn * TRADE_COST * 2.0
                r_day = np.dot(w_target, cc_arr[i])
                port_ret[i] = r_day - cost
                w_curr = w_target * (1 + cc_arr[i]) / (1 + r_day)
        else:
            r_day = np.dot(w_curr, cc_arr[i])
            port_ret[i] = r_day
            w_curr = w_curr * (1 + cc_arr[i]) / (1 + r_day)

        prev_tgt = t

    ret_s = pd.Series(port_ret, index=df.index).dropna().loc[start_date:]
    chg_s = pd.Series(changed, index=df.index).loc[ret_s.index]
    return ret_s, chg_s


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


def generate_soxl_backtest_csv(df=None):
    """^SOX 신호 기준 SOXL + (USD 50% + QQQM 50%) + CASH 백테스트 결과를 CSV로 저장"""
    if df is None:
        df = load_market_data()

    sig_sox = build_signal(df, price_col="sox", **P)
    syn_cc, syn_ov, syn_id, rf = synthetic_etf_returns(df)
    real_cc, real_ov, real_id, _ = real_etf_returns(df)

    cols_sox = ["QQQM", "USD", "SOXL", "CASH"]
    w_sox = {
        "AGG_3X":   np.array([0.0, 0.0, 1.0, 0.0]),
        "DEF_1.5X": np.array([0.5, 0.5, 0.0, 0.0]),
        "CASH":     np.array([0.0, 0.0, 0.0, 1.0]),
    }

    start_syn = "1995-05-05"
    ret_syn, _ = run_portfolio_backtest(
        df, sig_sox, syn_cc, syn_ov, syn_id, cols_sox, w_sox, start_syn
    )
    ret_real, _ = run_portfolio_backtest(
        df, sig_sox, real_cc, real_ov, real_id, cols_sox, w_sox, "2010-03-15"
    )

    # 2010-03-15 이전은 합성 수익률, 이후는 실제 상장 ETF(SOXL, USD, QQQM) 수익률을 결합한 하이브리드 시계열도 제공
    ret_hybrid = ret_syn.copy()
    ret_hybrid.loc[ret_real.index] = ret_real

    out = pd.DataFrame({
        "sox": df["sox"].loc[ret_syn.index],
        "ma250": df["sox"].rolling(250).mean().loc[ret_syn.index],
        "high252": df["sox"].rolling(252, min_periods=252).max().loc[ret_syn.index],
        "strategy_ret": ret_syn,
        "strategy_ret_real": ret_real.reindex(ret_syn.index),
        "strategy_ret_hybrid": ret_hybrid,
        "equity": (1 + ret_syn).cumprod(),
        "equity_hybrid": (1 + ret_hybrid).cumprod(),
        "state": sig_sox["state"].loc[ret_syn.index],
        "vix10": sig_sox["vix10"].loc[ret_syn.index],
        "dd": sig_sox["dd"].loc[ret_syn.index],
        "target": sig_sox["target"].loc[ret_syn.index].map(TARGET_NAMES_SOX),
    })
    out.to_csv(BASE_DIR / "backtest_result_soxl.csv", encoding="utf-8-sig")
    return df, sig_sox, syn_cc, syn_ov, syn_id, real_cc, real_ov, real_id, rf


def main():
    df, sig_sox, syn_cc, syn_ov, syn_id, real_cc, real_ov, real_id, rf = generate_soxl_backtest_csv()
    sig_ndx = build_signal(df, price_col="ndx", **P)

    cols_ndx = ["QQQ", "QLD", "TQQQ", "CASH"]
    w_ndx = {
        "AGG_3X":   np.array([0.0, 0.0, 1.0, 0.0]),
        "DEF_1.5X": np.array([0.5, 0.5, 0.0, 0.0]),
        "CASH":     np.array([0.0, 0.0, 0.0, 1.0]),
    }

    cols_sox = ["QQQM", "USD", "SOXL", "CASH"]
    w_sox = {
        "AGG_3X":   np.array([0.0, 0.0, 1.0, 0.0]),
        "DEF_1.5X": np.array([0.5, 0.5, 0.0, 0.0]),
        "CASH":     np.array([0.0, 0.0, 0.0, 1.0]),
    }

    start_syn = "1995-05-05"
    ret_tqqq_strat, _ = run_portfolio_backtest(
        df, sig_ndx, syn_cc, syn_ov, syn_id, cols_ndx, w_ndx, start_syn
    )
    ret_soxl_ndx_sig, _ = run_portfolio_backtest(
        df, sig_ndx, syn_cc, syn_ov, syn_id, cols_sox, w_sox, start_syn
    )
    ret_soxl_sox_sig, _ = run_portfolio_backtest(
        df, sig_sox, syn_cc, syn_ov, syn_id, cols_sox, w_sox, start_syn
    )

    common_idx = ret_tqqq_strat.index.intersection(ret_soxl_sox_sig.index)
    ret_tqqq_strat = ret_tqqq_strat.loc[common_idx]
    ret_soxl_ndx_sig = ret_soxl_ndx_sig.loc[common_idx]
    ret_soxl_sox_sig = ret_soxl_sox_sig.loc[common_idx]

    rows_syn = {
        "① SOXL + USD50/QQQM50 (NDX 레짐신호)": metrics(ret_soxl_ndx_sig, rf),
        "② SOXL + USD50/QQQM50 (SOX 레짐신호)": metrics(ret_soxl_sox_sig, rf),
        "③ 기존 TQQQ + QLD50/QQQ50 (NDX 신호)": metrics(ret_tqqq_strat, rf),
        "SOXL 단순보유 (합성 3x)": metrics(syn_cc["SOXL"].loc[common_idx], rf),
        "USD 단순보유 (합성 2x)": metrics(syn_cc["USD"].loc[common_idx], rf),
        "TQQQ 단순보유 (합성 3x)": metrics(syn_cc["TQQQ"].loc[common_idx], rf),
        "QQQM 단순보유 (합성 1x)": metrics(syn_cc["QQQM"].loc[common_idx], rf),
    }
    tbl_syn = pd.DataFrame({k: fmt(v) for k, v in rows_syn.items()}).T
    print(f"\n==========================================================================")
    print(f"[A] 장기 합성 백테스트 성과 비교 ({common_idx[0].date()} ~ {common_idx[-1].date()})")
    print(f"==========================================================================")
    print(tbl_syn.to_string())

    start_real = "2010-03-15"
    r_real_soxl_ndx, _ = run_portfolio_backtest(
        df, sig_ndx, real_cc, real_ov, real_id, cols_sox, w_sox, start_real
    )
    r_real_soxl_sox, _ = run_portfolio_backtest(
        df, sig_sox, real_cc, real_ov, real_id, cols_sox, w_sox, start_real
    )
    r_real_tqqq, _ = run_portfolio_backtest(
        df, sig_ndx, real_cc, real_ov, real_id, cols_ndx, w_ndx, start_real
    )
    r_idx = r_real_soxl_ndx.index.intersection(r_real_tqqq.index)

    rows_real = {
        "① 실제 SOXL + USD50/QQQM50 (NDX 신호)": metrics(r_real_soxl_ndx.loc[r_idx], rf),
        "② 실제 SOXL + USD50/QQQM50 (SOX 신호)": metrics(r_real_soxl_sox.loc[r_idx], rf),
        "③ 실제 TQQQ + QLD50/QQQ50 (NDX 신호)": metrics(r_real_tqqq.loc[r_idx], rf),
        "실제 SOXL 단순보유": metrics(real_cc["SOXL"].loc[r_idx], rf),
        "실제 USD 단순보유": metrics(real_cc["USD"].loc[r_idx], rf),
        "실제 TQQQ 단순보유": metrics(real_cc["TQQQ"].loc[r_idx], rf),
        "실제 QQQM(QQQ) 단순보유": metrics(real_cc["QQQM"].loc[r_idx], rf),
    }
    tbl_real = pd.DataFrame({k: fmt(v) for k, v in rows_real.items()}).T
    print(f"\n==========================================================================")
    print(f"[B] 실제 상장 ETF 백테스트 ({r_idx[0].date()} ~ {r_idx[-1].date()}, 실제 SOXL/USD/TQQQ 주가)")
    print(f"==========================================================================")
    print(tbl_real.to_string())

    tbl_syn.to_csv(BASE_DIR / "backtest_summary_soxl_synthetic.csv", encoding="utf-8-sig")
    tbl_real.to_csv(BASE_DIR / "backtest_summary_soxl_real.csv", encoding="utf-8-sig")
    print("\n저장 완료: backtest_result_soxl.csv / backtest_summary_soxl_synthetic.csv / backtest_summary_soxl_real.csv")


if __name__ == "__main__":
    main()
