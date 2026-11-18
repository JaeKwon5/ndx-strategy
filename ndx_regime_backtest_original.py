"""
NDX 250일선 레짐 + VIX10 + 52주 낙폭 레버리지 전략 백테스트 (원본)
- 기준지수: ^NDX / VIX10 = VIX 종가 10일 SMA / 낙폭 = 52주(252거래일) 고점 대비
- 신호: 당일 종가 기준 -> 체결: 다음 거래일 수익률부터 적용 (룩어헤드 방지)
- QQQ/QLD/TQQQ: ^NDX 일수익률 기반 합성 (보수 + 레버리지 자금조달비용 반영)
- 주의: ^NDX는 가격지수(배당 제외) → 절대수익률은 총수익 대비 연 약 0.7~1%p 낮게 나옴
실행:  pip install yfinance pandas numpy matplotlib
       python ndx_regime_backtest_original.py            (실데이터)
       python ndx_regime_backtest_original.py --synthetic (코드 동작 점검용 가상 데이터)
"""
import sys
import numpy as np
import pandas as pd

# ---------------- 파라미터 ----------------
P = dict(up=1.01, dn=0.95, vix_hi=28.0, vix_lo=18.0, dd_lim=0.09)
START = "1990-01-02"          # VIX 데이터 시작 시점에 맞춤
TRADE_COST = 0.0005           # 편도 0.05% (슬리피지+수수료 가정)
ER = {"QQQ": 0.0020, "QLD": 0.0095, "TQQQ": 0.0095}   # 연 보수(가정치)
LEV = {"QQQ": 1.0, "QLD": 2.0, "TQQQ": 3.0}
TD = 252


# ---------------- 데이터 ----------------
def load_real():
    import yfinance as yf
    raw = yf.download(["^NDX", "^VIX", "^IRX"], start="1985-10-01",
                      auto_adjust=False, progress=False)["Close"]
    raw = raw.rename(columns={"^NDX": "ndx", "^VIX": "vix", "^IRX": "irx"})
    raw["irx"] = raw["irx"].ffill().bfill() / 100.0
    return raw.dropna(subset=["ndx", "vix"])


def load_synthetic(n=9000, seed=7):
    rng = np.random.default_rng(seed)
    vol = np.clip(0.18 + 0.12 * np.sin(np.arange(n) / 400) + rng.normal(0, .02, n), .08, .6)
    r = rng.normal(0.0004, vol / np.sqrt(TD))
    idx = pd.bdate_range("1990-01-02", periods=n)
    ndx = pd.Series(500 * np.exp(np.cumsum(r)), idx)
    vix = pd.Series(vol * 100 * (1 + rng.normal(0, .05, n)), idx)
    return pd.DataFrame({"ndx": ndx, "vix": vix, "irx": 0.02}, index=idx)


# ---------------- 신호 ----------------
def build_signal(df, up, dn, vix_hi, vix_lo, dd_lim):
    ndx = df["ndx"]
    ma250 = ndx.rolling(250).mean()
    vix10 = df["vix"].rolling(10).mean()
    dd = 1 - ndx / ndx.rolling(252, min_periods=252).max()   # 52주 고점 대비 낙폭(양수)

    state, out = None, []
    for p, m in zip(ndx.values, ma250.values):
        if np.isnan(m):
            out.append(None); continue
        if p > m * up:
            state = "BULL"
        elif p < m * dn:
            state = "BEAR"
        elif state is None:                      # 초기값: 밴드 안이면 선/후 판단
            state = "BULL" if p > m else "BEAR"
        out.append(state)                        # 밴드 안이면 이전 상태 유지 (규칙 3)
    st = pd.Series(out, index=ndx.index)

    def pick(s, v, d):
        if s is None or np.isnan(v) or np.isnan(d):
            return None
        if s == "BULL":
            return "TQQQ" if (v < vix_hi and d <= dd_lim) else "QQQ50_QLD50"
        return "QQQ50_QLD50" if v < vix_lo else "CASH"

    tgt = pd.Series([pick(s, v, d) for s, v, d in zip(st, vix10, dd)], index=ndx.index)
    return pd.DataFrame({"state": st, "vix10": vix10, "dd": dd, "target": tgt})


WEIGHTS = {"TQQQ": {"TQQQ": 1.0}, "QQQ50_QLD50": {"QQQ": .5, "QLD": .5},
           "CASH": {}, None: {}}


# ---------------- 합성 ETF 수익률 ----------------
def etf_returns(df):
    r = df["ndx"].pct_change()
    rf = df["irx"] / TD
    out = {}
    for k in LEV:
        out[k] = LEV[k] * r - (LEV[k] - 1) * rf - ER[k] / TD
    return pd.DataFrame(out), rf


# ---------------- 백테스트 ----------------
def backtest(df, **kw):
    prm = {**P, **kw}
    sig = build_signal(df, **prm)
    etf, rf = etf_returns(df)
    tgt = sig["target"].shift(1)                       # 다음 거래일 체결
    ok = tgt.notna()
    w = pd.DataFrame(0.0, index=df.index, columns=["QQQ", "QLD", "TQQQ", "CASH"])
    for name, mp in WEIGHTS.items():
        if name is None:
            continue
        m = tgt == name
        for k, v in mp.items():
            w.loc[m, k] = v
        w.loc[m, "CASH"] = 1 - sum(mp.values())
    ret = (w[["QQQ", "QLD", "TQQQ"]] * etf).sum(axis=1) + w["CASH"] * rf
    turn = w.diff().abs().sum(axis=1).fillna(0) / 2    # 편도 거래대금 비중
    ret = (ret - turn * TRADE_COST * 2)[ok]            # 매도+매수 비용
    changed = (tgt != tgt.shift(1)) & ok & tgt.shift(1).notna()
    return ret.loc[START:], sig, tgt, changed.loc[START:]


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
    etf, rf = etf_returns(df)

    ret, sig, tgt, chg = backtest(df)
    rows = {"전략": metrics(ret, rf)}
    for k in LEV:
        rows[f"{k} 보유(합성)"] = metrics(etf[k].loc[ret.index], rf)
    tbl = pd.DataFrame({k: fmt(v) for k, v in rows.items()}).T
    print("\n[1] 전체 기간 성과 (%s ~ %s)" % (ret.index[0].date(), ret.index[-1].date()))
    print(tbl.to_string())

    # 기간별
    periods = {"1990-1999": ("1990", "1999"), "2000-2002 닷컴": ("2000", "2002"),
               "2003-2007": ("2003", "2007"), "2008 금융위기": ("2008", "2008"),
               "2009-2019": ("2009", "2019"), "2020 코로나": ("2020", "2020"),
               "2021": ("2021", "2021"), "2022 긴축": ("2022", "2022"),
               "2023-현재": ("2023", "2099")}
    rows = []
    for nm, (a, b) in periods.items():
        s = ret.loc[a:b]
        if len(s) < 20:
            continue
        m, t = metrics(s, rf), metrics(etf["TQQQ"].loc[s.index], rf)
        rows.append([nm, f"{m['CAGR']:.1%}", f"{m['MDD']:.1%}", f"{t['CAGR']:.1%}", f"{t['MDD']:.1%}"])
    print("\n[2] 구간별 (전략 vs TQQQ 보유)")
    print(pd.DataFrame(rows, columns=["구간", "전략CAGR", "전략MDD", "TQQQ CAGR", "TQQQ MDD"]).to_string(index=False))

    # 상태/배분 일수, 거래 횟수
    t = tgt.loc[START:].dropna()
    print("\n[3] 배분 비중(일수 기준)")
    print((t.value_counts(normalize=True)).map("{:.1%}".format).to_string())
    s2 = sig.loc[START:].dropna(subset=["target"])
    bear_lo = ((s2["state"] == "BEAR") & (s2["vix10"] < P["vix_lo"])).sum()
    print(f"하락장 & VIX10<{P['vix_lo']:.0f} 일수(규칙 6 해당): {bear_lo}일 / 하락장 전체 {(s2['state']=='BEAR').sum()}일")
    yrs = len(ret) / TD
    print(f"포지션 변경 횟수: {int(chg.sum())}회 (연 {chg.sum()/yrs:.1f}회)")

    # 민감도: VIX 상단 x 낙폭
    print("\n[4] 민감도 ① VIX 상단 × 낙폭한도  (셀: CAGR / MDD)")
    vs, ds = [24, 26, 28, 30, 32], [0.07, 0.09, 0.11]
    g = pd.DataFrame(index=[f"VIX≥{v}" for v in vs], columns=[f"DD>{d:.0%}" for d in ds])
    for v in vs:
        for d in ds:
            m = metrics(backtest(df, vix_hi=v, dd_lim=d)[0], rf)
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
    out = pd.DataFrame({"strategy_ret": ret, "equity": (1 + ret).cumprod()})
    out = out.join(sig[["state", "vix10", "dd", "target"]])
    out.to_csv("backtest_result_original.csv", encoding="utf-8-sig")
    tbl.to_csv("backtest_summary_original.csv", encoding="utf-8-sig")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(11, 5))
        ax.plot((1 + ret).cumprod(), label="Strategy")
        ax.plot((1 + etf["TQQQ"].loc[ret.index]).cumprod(), label="TQQQ B&H (synthetic)", alpha=.6)
        ax.plot((1 + etf["QQQ"].loc[ret.index]).cumprod(), label="QQQ B&H (synthetic)", alpha=.6)
        ax.set_yscale("log"); ax.legend(); ax.grid(alpha=.3)
        ax.set_title("NDX regime strategy (log scale)")
        fig.tight_layout(); fig.savefig("backtest_equity_original.png", dpi=120)
    except Exception as e:
        print("차트 생략:", e)
    print("\n저장: backtest_result_original.csv / backtest_summary_original.csv / backtest_equity_original.png")


if __name__ == "__main__":
    main()
