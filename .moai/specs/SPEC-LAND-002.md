# SPEC-LAND-002 — 토지 정밀 NAV (Tier 2-②, human-in-loop)

- **Tier / Milestone**: Tier 2-② / M3
- **Intent**: 숏리스트 종목의 토지를 **필지 단위로 정밀 평가**.

## Scope

- 공시 원문에서 소재지·면적 추출 → V-World 주소→PNU → 개별공시지가/실거래가 조회 → 시가보정.
- `토지_추정시가 = Σ(필지면적 × 개별공시지가 × 시가보정계수)`
- 매칭 실패·저신뢰 필지는 **검토 큐**로 보내 사람이 확인 (자동 확정 금지).

## Acceptance Criteria

1. GIVEN 정상 주소+면적, WHEN PNU 변환·공시지가 조회, THEN 필지 추정시가가 산출되고 신뢰도 등급이 매겨진다.
2. GIVEN 주소 매칭 실패, WHEN 평가, THEN 자동 확정하지 않고 **검토 큐**에 적재한다 (불변량).
3. GIVEN 보정계수 c, WHEN 적용, THEN 공시지가 기반 시가가 `공시지가 × c`로 일관 적용된다 (설정값, 출처 기록).

## @MX 위험구역

- 주소→PNU 매칭 정확도(오매칭 시 평가 전부 오염), 보정계수 가정의 투명성.

## 의존성

- SPEC-LAND-001, SPEC-CORE-001.

## 구현 매핑

- `valuation/land_precise.py` — `value_land_precise` → `(PreciseLandValuation[], review_queue)`.
  저신뢰/매칭실패는 `ReviewQueueItem`으로만 적재(불변량), 보정계수·출처 스냅샷 기록.
