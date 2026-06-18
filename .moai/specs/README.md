# Asset-Play Screener — SPEC Suite (SPEC-First)

This directory is the hand-authored **SPEC suite** used as Phase-1 (SPEC) input.
New code is written **test-first (TDD)** and validated against **TRUST 5**.

## SPEC index

| SPEC | Tier / Milestone | Intent |
|------|------------------|--------|
| [SPEC-CORE-001](SPEC-CORE-001.md) | M1 | 데이터 수집 기반 (cached client layer) |
| [SPEC-EQUITY-001](SPEC-EQUITY-001.md) | Tier 1 ⭐ / M1 | 보유 상장지분 숨은가치 (정밀 자동) |
| [SPEC-LAND-001](SPEC-LAND-001.md) | Tier 2-① / M2 | 토지 1차 스크리닝 |
| [SPEC-LAND-002](SPEC-LAND-002.md) | Tier 2-② / M3 | 토지 정밀 NAV (human-in-loop) |
| [SPEC-NAV-001](SPEC-NAV-001.md) | M2 | 통합 집계·랭킹·리포트 |
| [SPEC-UNLISTED-001](SPEC-UNLISTED-001.md) | Tier 3 / M4 | 비상장 지분 근사 |

## 도메인 모델 & 용어

- `Company`: 종목 (corp_code, stock_code, name, market, 시가총액, 회계정책[원가/재평가])
- `EquityHolding`: 보유 지분 (피투자사, 주식수, 지분율, 취득원가, 장부가액[지분법/원가], 상장여부)
- `LandAsset`: 토지 (소재지, 면적, 장부가액, 지목, [PNU, 개별공시지가])
- `ValuationSnapshot`: 평가 시점 (as_of_date, source, 단가/시가)
- `NAVResult`: 종목별 집계 (자산군별 장부가/추정시가/미실현이익(세전·세후), surplus_ratio, 신뢰도)

핵심 용어: **장부가**(취득원가), **원가모형 vs 재평가모형**(재평가 채택사는 후보 제외),
**개별공시지가**(시가의 60~70% → 보정계수 필요), **PNU**(필지고유번호 19자리),
**holdco discount**(지주사 시총 < 보유 NAV 합), **net surplus**(이연법인세 차감 세후 잉여).

## TRUST 5 불변량

1. 별도 FS 사용  2. 이중계상 금지  3. 토지 저신뢰 필지 자동확정 금지
4. 단위 정규화('원' 기준)  5. 모든 시가에 `source` + `as_of_date`.

## @MX 위험구역 (교차 관심사)

- **금융 정확성**: 단위/통화(천원·백만원), 별도 vs 연결, 주식수×가격 정밀도(Decimal), 이연법인세.
- **파싱 취약성**: 토지/면적/소재지 비정형 주석, 주소→PNU 오매칭.
- **API 쿼터/안정성**: DART 일일 한도, KRX 스크래핑 → 캐시·백오프.
- **Look-ahead bias**: 백테스트 시 공시일 기준 point-in-time 데이터만(현 단계는 최소 보관).

## 착수 결정 (§8 open questions — 적용값)

1. 법인세율 = **22% 단일** (설정 가능)
2. 공시지가 보정계수 = **전국 단일 ×1.4** (지역별 override 가능)
3. 유니버스 = **설정 가능 + KOSPI 우선**
4. point-in-time 보관 = **최소** (현재 스냅샷 + `as_of`)
5. 출력 = **CSV + HTML 리포트**

## 마일스톤

- **M1**: CORE-001 + EQUITY-001 → 즉시 동작하는 정밀 지분 NAV 스크리너.
- **M2**: LAND-001 + NAV-001 → 토지 후보 + 통합 랭킹·리포트.
- **M3**: LAND-002 → 토지 정밀 NAV (human-in-loop).
- **M4**: UNLISTED-001 + 보정계수 튜닝.
