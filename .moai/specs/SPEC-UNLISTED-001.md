# SPEC-UNLISTED-001 — 비상장 지분 근사 (Tier 3, 후순위)

- **Tier / Milestone**: Tier 3 / M4
- **Intent**: 비상장 피투자사 지분을 **순자산 기반**으로 근사.
- **Scope**: 피투자사가 DART 공시 대상이면 `순자산 × 지분율`, 아니면 추정/제외.
  **근사임을 등급으로 명시.**

## Acceptance Criteria

1. GIVEN 비상장 피투자사 재무 공시 존재, WHEN 평가, THEN `순자산 × 지분율`로 근사하고 신뢰도=低.
2. GIVEN 재무 미공시, WHEN 평가, THEN 취득원가 유지 + 미평가 플래그.

## 의존성

- SPEC-CORE-001, SPEC-EQUITY-001.

## 구현 매핑

- `valuation/unlisted.py` — `value_unlisted_holding`. 재무 공시 시 순자산×지분율(신뢰도 LOW),
  미공시 시 `book_value` 유지 + `unvalued` 플래그.
