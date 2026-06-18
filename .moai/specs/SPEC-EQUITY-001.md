# SPEC-EQUITY-001 — 보유 상장지분 숨은가치 (Tier 1 ⭐)

- **Tier / Milestone**: Tier 1 / M1
- **Intent**: 보유 **상장주식 / 상장 관계·종속기업 지분**의 시가 − 장부가 괴리를 **정밀 자동** 산출.
- **Scope**: 타법인출자현황 파싱 → 피투자사 상장여부 판정 → 시가 결합 → 종목별 지분 미실현이익.

## 데이터 계약 / 공식

- `시가_지분 = 보유주식수 × 피투자사_현재가`  (또는 `지분율 × 피투자사_시가총액`)
- `미실현이익_지분 = 시가_지분 − 장부가액(지분법 또는 원가법 계상액)`
- **반드시 별도재무제표(separate FS) 기준** 보유분을 사용한다 (연결은 상계되어 사라짐). ← 불변량

## Acceptance Criteria

1. GIVEN A사가 상장 B사 주식 N주를 장부가 V로 보유, WHEN 평가, THEN `미실현이익 = N×P_B − V`가 정확히 계산된다.
2. GIVEN 피투자사가 비상장, WHEN 평가, THEN Tier 1에서 제외되고 **Tier 3 큐**로 라우팅된다.
3. GIVEN 연결·별도 둘 다 존재, WHEN 평가, THEN **별도재무제표** 수치를 선택한다 (테스트로 강제).
4. GIVEN 지분율·주식수 불일치 공시, WHEN 검증, THEN **경고 플래그**를 부착하되 중단하지 않는다.

## @MX 위험구역

- 별도 vs 연결 선택(틀리면 결과 무의미), 단위/통화(천원·백만원), 주식수×가격 정밀도(Decimal).

## 의존성

- SPEC-CORE-001.

## 구현 매핑

- `valuation/equity.py` — `select_separate_fs_holdings`, `value_equity_holdings`,
  비상장 → `tier3_queue`, 지분율/주식수 교차검증 → `warnings`.
