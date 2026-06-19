# SPEC-JP-001 — 일본(EDINET) 시장 어댑터

- **Tier / Milestone**: 멀티마켓 / M6
- **Status**: part 1 구현(賃貸等不動産 파서) · 후속(EDINET 클라이언트·財務·JpAdapter 배선)
- **Intent**: SPEC-ADAPTER-001 시임 위에 일본 어댑터를 올린다. 책 원전이 일본 기준이고,
  ASBJ 기준 제20호 `賃貸等不動産の時価等の開示`가 한국 투자부동산 공정가치와 1:1 대응한다.

## 라이브 검증으로 확정된 사실 (2026-06)

- **EDINET API v2**: 무료, `Subscription-Key` 쿼리파라미터 인증. `documents.json?date=&type=2`(목록,
  docTypeCode 120=有報, secCode·edinetCode·docID 포함), `documents/{docID}?type=5`(XBRL_TO_CSV,
  UTF-16 탭구분). 재무·주석이 한 CSV에. DART document.xml의 일본 대응.
- **賃貸등不動산 時価**: 한국의 깔끔한 XBRL 수치태그와 달리 **텍스트블록**
  (`jpcrp_cor:NotesRealEstateForLeaseEtc…TextBlock`) 안의 HTML 표로 공시. 2026-06-18 有報 132건
  전부 텍스트블록. 카테고리(賃貸等不動産=실현가능 / 사용겸용=인식형)별 連結B/S計上額(期末 帳簿)과
  期末時価를 前期·当期 2열로 담음 → 텍스트 파싱으로 추출(경방 초기 수작업과 동일 난이도).
- **J-Quants V2**: base `https://api.jquants.com`, 헤더 `x-api-key`. `/v2/equities/master`(종목),
  `/v2/equities/bars/daily`(주가)는 무료 ✅. `/v2/fins/details`(財務)는 **유료** → 財務는 EDINET 사용.
- 선택성: 約 1/12만 賃貸등不動산 보유(한국과 유사). 나머지는 생략 텍스트블록.

## 라이브 검증 사례

西日本鉄道(9031): 賃貸등不動산 장부 538억엔→時価 918억엔(含み益 +380억엔),
사용겸용 장부 1,206억엔→時価 2,233억엔(+1,027억엔). 합계 含み益 +1,407억엔. (일본판 타임스퀘어)

## Acceptance Criteria

1. GIVEN 賃貸등不動산 텍스트블록, WHEN 파싱, THEN 카테고리별 当期 期末 帳簿·時価를 단위 보정해 추출.
2. GIVEN 생략 텍스트블록, WHEN 파싱, THEN 빈 결과(에러 아님).
3. (후속) GIVEN secCode, WHEN EDINET 조회, THEN 최신 有報 docID·CSV 취득.
4. (후속) GIVEN EDINET XBRL, WHEN 재무추출, THEN 総資産·純資産·当期純利益(스크린용).
5. (후속) GIVEN JpAdapter, WHEN MarketAdapter 표면 구현, THEN 코어(screen/NAV/report) 재사용.

## @MX 위험구역

- 텍스트블록 숫자는 前期当期 연접(예 "52,47453,789") → 콤마그룹 단위로 분리, 当期(2번째) 채택.
- 단위(百万円/千円) 오판 = 치명 → 표 머리 '単位：…' 검출, 기본 百万円.
- 賃貸등(실현가능) vs 사용겸용(인식형) 분류는 SPEC-NAV rev.3 AC-5와 정합.

## 구현 매핑

- `sources/jp_edinet_document.py` — `parse_chintai_fudosan`, `ChintaiItem` (part 1, 완료).
- (후속) `sources/jp_edinet.py` — EdinetClient(목록·문서·財務·코드매핑).
- (후속) `sources/adapter.py` — `JpAdapter`(MarketAdapter). 价格=J-Quants/yfinance.
