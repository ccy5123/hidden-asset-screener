# SPEC-IPNOTE-001 — 투자부동산 공정가치 주석 자동 파서

- **Tier / Milestone**: 정밀(Tier-2) 자동화 / M4
- **Status**: v1 구현
- **Intent**: 책 2단계의 병목인 **수작업 토지 추출**을 제거한다. 사업보고서
  `document.xml`의 XBRL 태그(`ACODE`/`ACONTEXT`)에서 **별도(OFS) 투자부동산
  토지/건물의 장부가·공정가치**를 회사 무관하게 자동 추출하고, 단위(천원/백만원)는
  구조화 BS 투자부동산 총액과 **대사**해 자동 검출한다. 대사 실패 시 None(날조 금지).

## 배경 (SPEC-NAV/CATALYST 후속)

경방 검증에서 회사 공시 투자부동산 공정가치(별도 토지 7,453억)가 geocoding 단일
PNU(6,549억)보다 **포괄적·정확**함이 확인됐다. 이 값은 `document.xml` 주석에만 있고
구조화 API에 없어, 지금까지 사람이 수작업으로 land-file에 입력했다. 본 SPEC은 그 추출을
자동화한다.

## XBRL 태그 규약 (DART 표준)

```
장부가:   ACODE = ifrs-full_InvestmentProperty
공정가치: ACODE contains FairValueOfInvestmentProperty
기준:     ACONTEXT contains _SeparateMember_   (별도; _ConsolidatedMember_ = 연결 제외)
유형:     ACONTEXT contains _LandMember | _BuildingsMember
```

표준 IFRS taxonomy라 회사 무관. 단위만 표 헤더(`단위:천원`)에 있어 회사마다 다름.

## 단위 자동검출 (대사 안전망)

```
표단위값 land_book + building_book, 배수 u ∈ {1, 1000, 1_000_000}
(land_book + building_book) × u ≈ BS 별도 투자부동산(원)  →  그 u 채택 (오차 < 2%)
대사되는 u 없음  →  reconciled=False (자동주입 금지, 사람 검토)
```

## 데이터 소스

- 사업보고서 rcept_no: DART `list.json` (report_nm "사업보고서", 해당 사업연도)
- 주석 본문: DART `document.xml?rcept_no=...` (ZIP → 최대 멤버 XML)
- BS 투자부동산(별도, 원): `fnlttSinglAcntAll(fs_div=OFS)` 의 "투자부동산" 계정

## Acceptance Criteria

1. GIVEN document.xml, WHEN 파싱, THEN 별도 토지/건물의 장부·공정가치를 표단위로 추출(연결 제외).
2. GIVEN 표단위값 + BS 투자부동산(원), WHEN 단위검출, THEN 대사되는 배수를 반환(없으면 None).
3. GIVEN 대사 성공, WHEN get_investment_property_fair_value, THEN 원 단위 값 + reconciled=True.
4. GIVEN `report --auto-land`, WHEN 실행, THEN 투자부동산 토지가 수작업 파일 없이 NAV에 반영.
5. GIVEN 공정가치 주석 부재, WHEN 파싱, THEN None(에러 아님) — 호출부는 graceful 처리.

## @MX 위험구역

- 단위 오판(1000배) = 치명. 반드시 BS 대사로 검출, 실패 시 자동주입 금지.
- 별도/연결 혼용 금지(`_SeparateMember_`만). 토지/건물 혼용 금지(`_LandMember`만 NAV 토지로).

## 의존성

- SPEC-CORE-001(DART), SPEC-LAND-002(투자부동산 path), SPEC-NAV-001 rev.3.

## 구현 매핑

- `sources/dart_document.py` — `parse_ip_fair_value_cells`, `unit_multiplier_by_reconcile`, `InvestmentPropertyFairValue`.
- `sources/dart_client.py` — `get_investment_property_fair_value`, `_latest_annual_rcept`, `get_document_xml`.
- `__main__.py` — `report --auto-land`.
