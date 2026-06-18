# SPEC-CATALYST-001 — 카탈리스트 점수·value-trap 필터

- **Tier / Milestone**: 집계 / M3 (SPEC-NAV-001 rev.3 확장)
- **Status**: v1 구현 (공시검색 기반)
- **Intent**: 한국 시장에서 '숨은 가치가 풀릴지'는 카탈리스트에 달려 있다. 2024~2026 밸류업 +
  상법 3종 개정으로 지배주주에게 가치를 풀 법적 압력이 생긴 만큼, 공시 신호로 `catalyst_score`를
  산출해 `nav_discount` 상위 후보 중 value trap을 가려낸다.

## 핵심 필터 (SPEC-NAV-001 rev.3 연계)

- (realizable 또는 카탈리스트 有) + `nav_discount` 高 = **우선 후보**.
- recognition-only + 카탈리스트 無 = **value trap 경계** (`catalyst_value_trap` 플래그).

## 신호 (v1 = DART 공시검색, list.json)

| 신호 | report_nm 키워드 | 가중치 |
|------|------------------|--------|
| `value_up` (밸류업) | 기업가치제고계획 | 0.40 |
| `buyback_cancel` (자사주 소각·취득) | 주식소각결정 / 자기주식취득 | 0.35 |
| `dividend` (현금배당) | 현금ㆍ현물배당결정 | 0.25 |

```
catalyst_score = 0.40·value_up + 0.35·buyback_cancel + 0.25·dividend   ∈ [0, 1]
catalyst_value_trap = nav_discount ≥ 0.30  AND  realizable_surplus ≤ 0  AND  catalyst_score == 0
```

- 데이터 소스 추가 없음 — 기존 DART `list.json` 공시검색 재사용.
- opt-in: 종목당 공시검색 1회 추가 → CLI `--catalyst` 플래그로만 활성화.

## Acceptance Criteria

1. GIVEN 종목 공시목록, WHEN 분류, THEN value_up·buyback_cancel·dividend 신호가 report_nm
   키워드로 판정된다.
2. GIVEN 신호, WHEN 점수, THEN `catalyst_score`가 가중합 [0,1]로 산출된다.
3. GIVEN nav_discount 高 + recognition-only + 무카탈리스트, WHEN 판정, THEN
   `catalyst_value_trap`가 True로 플래그된다.
4. GIVEN `--catalyst` 미사용, WHEN screen, THEN 공시검색을 호출하지 않는다(쿼터 보호) →
   `catalyst_score = None`.

## @MX 위험구역

- report_nm 키워드 오탐(자회사 공시 `(자회사의 주요경영사항)` 포함 여부 — 본사 신호와 구분 가능하나
  v1은 보수적으로 포함). value-trap 임계값(0.30)은 설정 가능해야 함.

## 한계 (v1 범위 밖 → 향후)

- 지배구조 신호(집중투표·독립이사 비중·3%룰): 기업지배구조보고서 narrative 파싱 필요 → 자동화 보류.
- 총주주환원율(TSR)·배당성향 정량화: 배당금/당기순이익 — 계정명 정합성 작업 필요 → v2.
- 밸류업 공시의 '이행 단계'(예고/이행/미이행) 구분 → v2.

## 의존성

- SPEC-NAV-001 rev.3 (`nav_discount`, `realizable_surplus`), SPEC-CORE-001 (DART list.json).

## 구현 매핑

- `sources/dart_client.py` — `get_disclosures`(list.json).
- `valuation/catalyst.py` — `catalyst_signals`, `catalyst_score`, `is_value_trap`.
- `domain/models.py` — `NAVResult.catalyst_score`, `catalyst_value_trap`.
- `pipeline.py` — opt-in `compute_catalyst`; `__main__.py` — `--catalyst`.
- `report/{csv,html}_report.py` — catalyst_score / value_trap 컬럼.
