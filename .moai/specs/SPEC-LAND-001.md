# SPEC-LAND-001 — 토지 1차 스크리닝 (Tier 2-①)

- **Tier / Milestone**: Tier 2-① / M2
- **Intent**: 정밀 평가 없이 **숨은 토지가치 후보**를 자동 추출.

## Scope (프록시 신호)

- 회계정책 = **원가모형** (재평가모형이면 제외).
- 토지 장부가액이 시가총액 대비 큼.
- **장부가/면적 비율**이 비정상적으로 낮음 (= 오래전 취득 추정).
- **투자부동산 공정가치 주석**(IFRS 공시의무) 존재 시 시가 직접 활용.

## Outputs

- 후보 종목 + 신호 점수 + SPEC-LAND-002로 보낼 숏리스트.

## Acceptance Criteria

1. GIVEN 재평가모형 기업, WHEN 스크리닝, THEN 후보에서 제외된다.
2. GIVEN 투자부동산 공정가치 주석 존재, WHEN 파싱, THEN 해당 시가가 추출되어 즉시 괴리 산출에 쓰인다.
3. GIVEN 토지 장부가/면적이 동종 분포 하위 X%, WHEN 평가, THEN "노후 취득 의심" 플래그가 부착된다.

## @MX 위험구역

- 주석 텍스트 파싱(비정형 → 오탐), 면적 단위(㎡/평 혼재 → 정규화).

## 의존성

- SPEC-CORE-001.

## 구현 매핑

- `valuation/land_screen.py` — `screen_land`, `LandScreenResult`(signal_score, shortlisted,
  flags), 투자부동산 공정가치 즉시 활용, 면적당 장부가 분위수 플래그.
