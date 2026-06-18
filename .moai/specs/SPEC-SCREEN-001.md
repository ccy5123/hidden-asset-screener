# SPEC-SCREEN-001 — 자산가치주 1차 스크린

- **Tier / Milestone**: 스크리닝 / M3
- **Status**: v1 구현
- **Intent**: 정밀 NAV(SPEC-NAV-001) *이전*의 진입 필터. 증권사 앱의 'PBR 0.5 이하 + 자기자본비율
  60% 이상' 스크리닝을 자동화해 자산가치주 후보를 압축한다. 통과 종목을 `report`(정밀 점검)로 넘긴다.

## 기준 (책 1단계)

```
PBR          = 시가총액 / 지배주주지분(연결)      ≤ 0.5
자기자본비율  = 자본총계 / 자산총계 (연결)         ≥ 0.60
PER          = 시가총액 / 당기순이익(지배)         ≤ 12  (옵션, 수익성)
창업연도      ≤ Y                                (옵션, 오래된 회사 = 취득원가 stale ↑)
```

- 비율은 **연결(CFS)** 기준 — 증권앱 PBR/자기자본비율 정의와 정합. 지배주주지분 없으면 자본총계로 대체.
- None 지표(자본잠식·적자)는 해당 필터에서 **탈락**(PER None = 적자 → 수익성 미달).

## 데이터 소스

- 시가총액: KRX (`price_provider.get_market_cap`)
- 지배주주지분·자본총계·자산총계·순이익: DART 연결 `fnlttSinglAcntAll(fs_div=CFS)` (`get_screen_financials`)
- 설립연도: DART 기업개황 `est_dt` (`Company.establishment_year`)

## Acceptance Criteria

1. GIVEN 시총·지배주주지분·자본총계·자산총계·순이익, WHEN 계산, THEN PBR·자기자본비율·PER가 산출된다.
2. GIVEN 분모 ≤ 0(자본잠식·적자), WHEN 비율, THEN None(0除算 회피) → 해당 필터 탈락.
3. GIVEN 기준값, WHEN 필터, THEN PBR≤max · 자기자본비율≥min · (옵션)PER≤max · 창업≤year 동시 충족만 통과.
4. GIVEN 통과 후보, WHEN 다음 단계, THEN `report`(SPEC-NAV/CATALYST/LAND)로 정밀 점검.

## @MX 위험구역

- 연결/별도 혼용 금지(PBR은 연결 지배주주지분). 적자·자본잠식 None 처리(수익성/저PBR 오판 방지).

## 의존성

- SPEC-CORE-001(KRX 시총, DART CFS·기업개황). 후속: SPEC-NAV-001 rev.3(정밀 NAV).

## 구현 매핑

- `valuation/screen.py` — `ScreenMetrics`, `compute_screen_metrics`, `passes_value_screen`, `value_screen`.
- `sources/dart_client.py` — `get_screen_financials`(CFS), `get_company`의 `est_dt`→`establishment_year`.
- `__main__.py` — `asset-play screen-value --stock … [--pbr --equity-ratio --per --founded-before]`.
