# SPEC-ADAPTER-001 — MarketAdapter 멀티마켓 시임

- **Tier / Milestone**: 아키텍처 / M5
- **Status**: v1 구현
- **Intent**: 한국 전용 스크리너를 KR/JP/US 멀티마켓으로 확장하기 위한 **시임(seam)**. 평가·스크린·집계·
  리포트 코어는 이미 입력 데이터에만 의존(시장무관)하므로, 시장 결합을 `MarketAdapter` 한 곳으로
  모은다. KR을 `KrAdapter`(DART+KRX 래핑)로 감싸 **동작을 100% 보존**하고, JP(EDINET)·US(EDGAR)는
  어댑터 추가만으로 붙인다(SPEC-JP-001/SPEC-US-001 후속).

## 배경 (JP/US 리서치 결론)

- JP: ASBJ 기준 제20호 `賃貸等不動産の時価` 주석 → 한국 투자부동산 공정가치와 1:1. feasibility 高.
- US: US-GAAP는 투자부동산 공정가치 공시 부재 → 2단계 자동추출 불가(스크린+지분만). feasibility 低.
- 공통: 코어는 시장무관, 4개 소스(공시·재무·가격·지오코더)만 시장별. → 어댑터 패턴이 최소변경 경로.

## MarketAdapter 표면 (코어가 실제 호출하는 메서드)

```
corp_code_for_stock · get_company · get_other_corp_investments
stock_code_for_name · corp_code_for_name · get_net_assets · get_separate_total_equity
get_screen_financials · get_disclosures · get_investment_property_fair_value
get_market_cap · price_as_of
```

KR 외 시장은 이 표면만 구현하면 코어(pipeline·screen·report) 재사용. 공정가치 미공시 시장(US)은
`get_investment_property_fair_value`가 None 반환(날조 금지) → NAV는 스크린+지분만으로 산출.

## Acceptance Criteria

1. GIVEN 기존 KR 동작, WHEN KrAdapter 도입, THEN 전체 회귀 테스트·경방 라이브 결과 불변.
2. GIVEN Pipeline, WHEN adapter 주입(기본 KrAdapter), THEN value_company가 self.adapter 경유로 데이터 취득.
3. GIVEN value_screen·build_company_report, WHEN 실행, THEN pipe.adapter 경유(시장무관).
4. GIVEN 신규 시장 어댑터, WHEN MarketAdapter 표면 구현, THEN 코어 코드 변경 없이 동작.

## @MX 위험구역

- KrAdapter는 순수 델리게이트(로직 0) — 동작 변경 금지. 회귀 테스트가 계약.
- 통화·Market enum·헤더주입은 후속(JP/US 착수 시). 본 SPEC은 시임 도입까지만.

## 구현 매핑

- `sources/adapter.py` — `MarketAdapter`(Protocol), `KrAdapter`.
- `pipeline.py` — `self.adapter = adapter or KrAdapter(dart, price_provider)`; value_company 라우팅.
- `valuation/screen.py`·`report/markdown_report.py` — `pipe.adapter` 경유.
- 후속: SPEC-JP-001(EDINET 어댑터), SPEC-US-001(EDGAR 어댑터, IP 미지원).
