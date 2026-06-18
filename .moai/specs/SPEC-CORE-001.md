# SPEC-CORE-001 — 데이터 수집 기반 (Foundation)

- **Tier / Milestone**: 공통 / M1 (최우선)
- **Intent**: 종목 유니버스·재무제표·시세를 가져오는 **캐시드 클라이언트 계층**.
- **Scope**: DART corpCode 동기화, 종목 메타(시총·회계정책 추출), KRX 시세 어댑터,
  로컬 캐시(SQLite), 호출 한도 관리·재시도.
- **Inputs → Outputs**: `(corp_code | stock_code)` → `Company`, 시세 시계열.

## Acceptance Criteria

1. GIVEN 유효 DART 키, WHEN corpCode 동기화, THEN 전체 `corp_code ↔ stock_code` 매핑이 로컬에 저장된다.
2. GIVEN 캐시된 호출, WHEN 동일 요청 재호출, THEN 외부 API를 다시 치지 않는다 (캐시 적중 검증).
3. GIVEN 회계정책 주석, WHEN 파싱, THEN 토지 측정모형이 `원가 | 재평가 | 불명`으로 분류된다.
4. GIVEN 일일 한도 초과 상황(mock), WHEN 호출, THEN 백오프·명확한 예외가 발생하고 부분결과가 보존된다.

## @MX 위험구역

- API 한도/키 관리, 캐시 무효화 로직(잘못되면 stale 데이터).

## 의존성

- 없음.

## 구현 매핑

- `cache/store.py` — SQLite KV 캐시 (TTL, 적중 카운터).
- `sources/base.py` — HTTP 세션, 백오프 재시도, 레이트리미터, `QuotaExceededError`.
- `sources/dart_client.py` — corpCode 동기화, 기업개황(`corp_cls`→market), 재무제표(OFS),
  타법인출자현황, 회계정책 텍스트→`classify_land_measurement_model`.
- `sources/krx.py` — `PriceProvider` 프로토콜 + FinanceDataReader/pykrx 어댑터(주입가능).
