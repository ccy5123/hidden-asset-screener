# SPEC-NAV-001 (rev.3) — 통합 NAV·괴리·랭킹

- **Tier / Milestone**: 집계 / M2
- **Status**: 구현 완료 (rev.3)
- **Intent**: 자산군별 미실현이익을 종목별로 집계하여, 단순 '숨은 차익 크기'가 아니라
  **재평가 NAV 대비 시장가 할인(`nav_discount`)** 을 1차 신호로 랭킹한다. 목적 = 자산 대비
  저평가 종목(자산가치주) 식별. (PBR이 구조적으로 못 보는 원가모형 토지·지분법 보유주식의
  미인식 가치 포착이 핵심 엣지.)

## 변경 이력

- **rev.1 → rev.2**: (a) `revalued_NAV`+`nav_discount`를 1차 랭킹 신호로(`surplus_ratio`는 보조),
  (b) 세전·세후 병기, (c) 영업용 vs 실현가능 자산 분류.
- **rev.2 → rev.3**: `reported_book_equity`를 **별도(OFS) 자본총계**로 확정(연결 지배주주지분
  아님). 보유지분 surplus가 별도 취득원가 기준이므로 정합하고, 연결을 쓰면 자회사 잉여가
  이중계상되어 `revalued_nav` 과대 → 가짜 '싼' 신호가 된다. CFS 호출 불필요(쿼터 추가 없음).

## 도메인 모델 (NAVResult)

| 필드 | 의미 |
|------|------|
| `total_unrealized_pretax` | 세전 미실현이익 합 (asset_id 이중계상 제거 후) |
| `total_unrealized_posttax` | 세후 (= `net_surplus`, alias) |
| `reported_book_equity` | **별도(OFS) 자본총계** (모회사 단독 자기자본; surplus와 동일 기준) |
| `revalued_nav` | `reported_book_equity + total_unrealized_posttax` |
| `nav_discount` | `1 − market_cap / revalued_nav` (1차 신호; ≤0 NAV → N/A) |
| `surplus_ratio` | `total_unrealized_posttax / market_cap` (보조 지표) |
| `realizable_surplus` / `recognition_only_surplus` | 자산 분류별 세전 소계 |
| `overall_confidence` | 자산군별 신뢰도 가중 등급 |

## 공식

```
total_pretax  = Σ(class.unrealized_gain)              # asset_id 이중계상 제거
total_posttax = total_pretax × (1 − t)  if total_pretax > 0
              = total_pretax              otherwise      # 손실엔 세금환급 가정 안 함
revalued_nav  = reported_book_equity(별도 OFS) + total_posttax
nav_discount  = 1 − market_cap / revalued_nav            # >0 → NAV 대비 할인(쌈)
surplus_ratio = total_posttax / market_cap               # 보조
```

- 세율 `t = 22% 단일` (config `ASSET_PLAY_CORPORATE_TAX_RATE`).
- 랭킹: `nav_discount` 내림차순(주) + `surplus_ratio`(보조) + `confidence_grade` 동시 노출.
- 영구 보유 자산 비교용으로 세전(pretax)도 함께 출력 — 실현 안 되면 세금이 트리거되지 않으므로
  pretax가 re-rating 상한의 의미를 가짐.

## 영업용 vs 실현가능 분류 (c)

각 자산을 분류하고 소계를 분리한다:

- **realizable(실현가능)**: 투자부동산, 유휴 토지, 단순투자목적 보유 상장주식 → 매각·환원으로 unlock 가능.
- **recognition-only(인식형)**: 영업용 토지, 지배·경영참여목적 지분(종속/관계) → 매각 불가, '인식'으로만 re-rating.
- 분류 휴리스틱(기본값):
  - 투자부동산 주석 → realizable
  - 유형자산 토지(영업용) → recognition-only
  - 보유 상장지분: 출자목적(`invstmnt_purps`) = '경영참여' → recognition-only, '단순투자' → realizable
  - 저신뢰 분류 → `manual_override` 플래그(자동 확정 금지) → 보수적으로 recognition-only에 합산.

의의: '풀릴 수 있는 가치(realizable)'와 '인식에 달린 가치(recognition-only)'를 가르는 핵심.
영업용 자산 + 무카탈리스트 조합은 value trap 위험 신호.

## Acceptance Criteria

1. GIVEN 자산군별 미실현이익 + 별도 자기자본, WHEN 집계, THEN
   `total_pretax·total_posttax·revalued_nav·nav_discount·surplus_ratio`가 모두 산출된다.
2. GIVEN `total_pretax < 0`, WHEN 세후 계산, THEN 세금환급을 가정하지 않는다(`posttax = pretax`).
3. GIVEN `revalued_nav ≤ 0`, WHEN `nav_discount` 계산, THEN 0除算 없이 `None + 플래그`로 처리한다.
4. GIVEN 별도(OFS)·연결(CFS) 재무제표가 모두 존재, WHEN `reported_book_equity` 선택, THEN
   **별도(OFS) 자본총계**를 쓴다 — 연결 지배주주지분 아님(자회사 잉여 double-count 방지). 테스트로 강제.
5. GIVEN 자산 분류, WHEN 집계, THEN `realizable_surplus` / `recognition_only_surplus` 소계가 분리 출력된다.
6. GIVEN 랭킹 출력, WHEN 정렬, THEN `nav_discount` 1차 정렬 + `confidence_grade`가 병기된다
   (프록시 기반 종목이 정밀 종목과 섞여 오인되지 않도록).

## @MX 위험구역

- 세후 규칙(순이익에만 과세, 손실 세금환급 금지), `revalued_nav` 분모 가드(≤0).
- **전 모델 별도(OFS) 기준 통일** — 자기자본·보유지분·토지 surplus 모두 별도. 연결/별도 혼용 시
  자회사 잉여가 두 번 잡혀 `revalued_nav` 과대 → `nav_discount` 과대(가짜 '싼' 신호).
- `asset_id` 이중계상 방지(지분+토지 중복 합산 금지).
- 영업용/실현가능 분류 신뢰도(오분류 시 unlock 가능성 오판).

## 한계

- 자회사 내부에 묻힌 토지·자산은 look-through 안 됨(보수적 누락). 다층 지주사는 SPEC-LAND-002
  deep-dive에서 개별 처리.

## 의존성

- SPEC-EQUITY-001, SPEC-LAND-001/002, SPEC-CORE-001(별도 OFS 자본총계 추출).

## 구현 매핑

- `aggregate/nav.py` — `aggregate_nav`(pretax/posttax, revalued_nav/nav_discount, realizable/recognition
  소계, asset_id dedup, 종합 신뢰도=최저 등급), `SimpleValuation.liquidity`.
- `aggregate/rank.py` — `rank_by_nav_discount`(1차, N/A 후순위) + `rank_by_surplus_ratio`(보조).
- `sources/dart_client.py` — `get_separate_total_equity`(OFS BS 자본총계), `extract_account_amount(sj_div=)`,
  `_parse_holding`의 `invstmnt_purps` 파싱.
- `domain/enums.py` — `LiquidityClass`(+`from_purpose`).
- `valuation/{equity,unlisted,land_precise}.py` — 항목별 `liquidity` 분류.
- `report/{csv,html}_report.py` — revalued_nav/nav_discount/realizable/recognition/pretax/posttax 컬럼,
  nav_discount 정렬.

## (선택) 향후 확장 — SPEC-CATALYST-001

'가치가 풀릴지'는 카탈리스트에 달려 있다(밸류업 + 상법 3종 개정). `catalyst_score`로 `nav_discount`
상위 후보를 재정렬. 별도 SPEC 참조: `.moai/specs/SPEC-CATALYST-001.md`.
