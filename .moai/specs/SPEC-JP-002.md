# SPEC-JP-002 — 일본 영업용 토지 含み益 추정 (公示地価/地価調査)

- **Tier / Milestone**: 멀티마켓 / M7
- **Status**: 구현 완료(part1 가격 인덱스+추정 · part2 設備현황 type=1 파서+리포트 배선+중복가드)
- **Intent**: 賃貸등不動산 時価 注記(SPEC-JP-001)에 안 잡히는 **자사전용(영업용) 토지**의 含み益을
  추정. 일본 有報는 BS·設備현황에 토지 **취득원가만** 공시(현재가 없음) → たーちゃん처럼 公示地価로
  직접 추정. 한국 V-World 개별공시지가 경로의 일본판.

## 핵심 설계 (보수적 — 스크리닝 신호용, 감정평가 아님)

- 데이터: **国土数値情報 L01(地価公示)/L02(地価調査) GeoJSON** — 키 불필요·무료 일괄. 標準地·基準地
  円/㎡(L02_006) + 주소(L02_022) + 用途(L02_025) + 좌표. 전국 ~2.1만(L02)/2.6만(L01)점.
- 인덱스: `市区町村 × 用途카테고리(industrial/commercial/residential) → median 円/㎡`.
- 매칭: 設備현황 시설 用途로 카테고리 추정 → 동일 用途 표준지 우선. 없으면 **ALL median × 보수할인**
  (공업 0.6·상업 0.85). 公示地価 그대로(도시 시가배율 미적용).
- 신뢰도: 🟡(用途 직접매칭) / 🔴(할인 폴백·미커버). 정밀은 사람이 路線価図로(たーちゃん 방식).

## たーちゃん 정합

『50万円を50億円に増やした』의 資産バリュー株投資 = 본 도구. 작가도 정밀공식 없이 큰 필지만 거칠게
추정 → 우리는 그 거친 추정을 투명·보수적으로 자동화하고, 마지막 정밀(큰 필지 路線価)은 사람 몫.

## Acceptance Criteria

1. GIVEN L02 GeoJSON, WHEN 로드, THEN 市区町村×用途 円/㎡ 인덱스 생성(키 불필요).
2. GIVEN 시설(所在地·면적·취득원가·用途), WHEN 추정, THEN 동일 用途 우선·없으면 보수할인 → 円/㎡×면적.
3. GIVEN 用途 표준지 부재, WHEN 폴백, THEN ALL median×할인 + 🔴 신뢰도.
4. (후속) GIVEN 設備현황 텍스트블록, WHEN 파싱, THEN 시설별 [所在地·면적·취득원가·세그먼트].
5. (후속) GIVEN 不動産業 세그먼트, WHEN 영업용 추정, THEN 賃貸등不動산 중복분 제외(중복계상 가드).

## @MX 위험구역

- 用途 오매핑(공장↔주택) = 단가 과대/과소 → 카테고리 키워드 + 보수 할인.
- 賃貸등不動산(이미 時価 공시)과 **중복계상 금지**(경방 6,549억 교훈) — 영업용은 不動産業 세그먼트 제외.
- 표본 標準地·구 median = 근사. 항상 🟡🔴, 🟢(감정/공시) 아님.

## 라이브 검증 (西日本鉄道 9031, 영업용 車庫/工場)

筑紫野市(101,559㎡, 장부 8.1억엔) 工業 표준지 없음→ALL×0.6 70,200円🔴(+63억), 福岡市東区 industrial
159,000円🟡(+28억), 柳川市 17,800円🟡(+4억). 합계 含み益 ~+95억엔. (賃貸등 +1,407억과 **별도**)

## 구현 매핑

- `sources/jp_landprice.py` — `JpLandPriceIndex`, `estimate_operating_land`, `category_of`,
  `muni_token`, `load_l02_points`, `LandPricePoint`, `OperatingLandEstimate` (part1).
- `sources/jp_edinet_document.py` — `parse_facilities_html`(type=1 iXBRL 그리드 파서, colspan/rowspan
  전개·헤더 기반 土地 컬럼 식별·賃貸面積 표 제외=중복가드) (part2).
- `sources/jp_edinet.py` — `EdinetClient.get_document_html`(type=1) (part2).
- `sources/adapter.py` — `JpAdapter(landprice_index=)` + `operating_land()` (part2).
- `report/markdown_report.py` — '영업용 토지 含み益' 섹션(🟡🔴, est_high=추정 → S2 상한 가산,
  추정<장부는 제외) (part2).
- (후속) L01(地価公示) 로더 추가·用途 정밀화·좌표 최근접 매칭.
