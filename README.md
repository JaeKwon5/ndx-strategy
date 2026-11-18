# NDX 250일선 레짐 + VIX10 + 52주 낙폭 레버리지 백테스트

나스닥 100(`^NDX`) 250일 이동평균선 레짐, `VIX` 10일 이동평균, 52주 고점 대비 낙폭(Drawdown)을 결합한 동적 레버리지(TQQQ / QLD+QQQ / CASH) 전략 백테스트 프로젝트입니다.

---

## 파일 구성

- `ndx_regime_backtest.py` : 메인 백테스트 엔진 및 성과/민감도 분석 스크립트
- `requirements.txt` : 필수 파이썬 패키지 목록 (`yfinance`, `pandas`, `numpy`, `matplotlib`)
- `run_backtest.bat` : Windows 원클릭 가상환경 구성 및 실행 배치 스크립트
- **실행 후 생성되는 결과물**
  - `backtest_result.csv` : 일자별 수익률, 누적 자산배수, 레짐 상태(`BULL`/`BEAR`), `VIX10`, 낙폭(`dd`), 목표 포지션 기록
  - `backtest_summary.csv` : 전체 기간 전략 및 합성 ETF(QQQ/QLD/TQQQ) 성과 요약표
  - `backtest_equity.png` : 로그 스케일 누적 수익률 비교 차트

---

## 실행 방법

### 1. 원클릭 실행 (Windows)
`run_backtest.bat` 파일을 더블클릭하거나 터미널에서 실행하면 자동으로 `.venv` 가상환경을 만들고 패키지를 설치한 뒤 백테스트를 수행합니다.

```powershell
# 실데이터 백테스트 (Yahoo Finance 연동)
.\run_backtest.bat

# 가상 데이터(Synthetic) 동작 점검
.\run_backtest.bat --synthetic
```

### 2. 수동 설치 및 실행
```powershell
# 가상환경 생성 및 활성화
python -m venv .venv
.\.venv\Scripts\activate

# 패키지 설치
pip install -r requirements.txt

# 실데이터 실행
python ndx_regime_backtest.py

# 가상 데이터 실행 (오프라인 테스트)
python ndx_regime_backtest.py --synthetic
```

---

## 전략 규칙 요약

| 시장 레짐 (250일선 밴드) | 세부 조건 | 목표 포트폴리오 | 실효 레버리지 |
| :--- | :--- | :--- | :--- |
| **BULL** (`> MA250 × 1.01`) | `VIX10 < 28` 및 `52주 낙폭 ≤ 9%` | `TQQQ` 100% | **3.0x** |
| **BULL** (`> MA250 × 1.01`) | `VIX10 ≥ 28` 또는 `52주 낙폭 > 9%` (방어 전환)<br>*(복귀는 `VIX10 < 25` 및 `낙폭 ≤ 7%` 충족 시)* | `QQQ` 50% + `QLD` 50% | **1.5x** |
| **BEAR** (`< MA250 × 0.95`) | `VIX10 < 18` (하락장 내 저변동성) | `QQQ` 50% + `QLD` 50% | **1.5x** |
| **BEAR** (`< MA250 × 0.95`) | `VIX10 ≥ 18` | `CASH` 100% (`^IRX` 단기금리) | **0.0x** |
