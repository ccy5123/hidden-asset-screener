# SPEC-NAV-001 — 통합 집계·랭킹·리포트

- **Tier / Milestone**: 집계 / M2
- **Intent**: 자산군별 미실현이익을 종목별로 합산하고 랭킹·리포트 산출.

## 공식

- `미실현이익_총(세전) = Σ(지분 + 토지 + 투자부동산 + 기타)`
- `net_surplus(세후) = 미실현이익_총 × (1 − 법인세율)`  ← 이연법인세 보정
- `surplus_ratio = net_surplus / 시가총액`  (핵심 랭킹 지표; holdco discount 탐지)
- 각 종목에 **데이터 신뢰도 등급** 부착 (예: 지분=高, 토지정밀=中, 토지프록시=低).

## Acceptance Criteria

1. GIVEN 자산군별 미실현이익, WHEN 집계, THEN 세전·세후·surplus_ratio가 모두 산출된다.
2. GIVEN net_surplus 내림차순, WHEN 랭킹, THEN 신뢰도 등급이 함께 노출된다 (프록시 종목이 정밀 종목과 섞여 오인되지 않도록).
3. GIVEN 리포트 생성, WHEN 출력, THEN 종목별 근거(소스·as_of·가정)가 추적 가능하다.

## @MX 위험구역

- 법인세율 가정, **이중계상 방지**(같은 자산을 지분+토지로 중복 합산 금지), surplus_ratio 분모 정의.

## 의존성

- SPEC-EQUITY-001, SPEC-LAND-001/002.

## 구현 매핑

- `aggregate/nav.py` — `aggregate_nav`(세전·세후·ratio, 자산 식별키 기반 dedup,
  종합 신뢰도=최저 등급), `aggregate/rank.py` — `rank_by_net_surplus`.
- `report/csv_report.py`, `report/html_report.py` — 근거(source/as_of/가정) 추적 가능 출력.
