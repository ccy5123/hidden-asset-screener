# Asset-Play Screener (`asset-play`)

> 상장사가 보유한 **토지·부동산 / 상장주식 / 관계·종속기업 지분**의 장부가(취득원가)와 시가의 괴리를
> 종목별로 정밀 정량화(NAV)해, 숨은 자산가치(含み資産, *hidden-asset value*)가 큰 종목을 발굴한다.
> **한국(DART)·일본(EDINET)** 멀티마켓을 같은 코어로 처리한다.
>
> 대표 원형: **阪神電気鉄道**(甲子園 球場이 1924년 취득원가로 장부에 동결) · **경방**(영등포 타임스퀘어).
> 방법론 출처: たーちゃん 『50万円を50億円に増やした 投資家の父から娘への教え』의 資産バリュー株投資.

## 핵심 철학 — "회사가 준 건 읽고, 안 준 건 추정하고, 정밀은 사람이"

자산 含み益은 본질적으로 판단의 영역이라, 정밀 감정을 자동화하려 하지 않는다. 대신:

| 층 | 무엇 | 신뢰도 |
|----|------|--------|
| **회사 공시 시가** | 한국 투자부동산 공정가치 주석 · 일본 賃貸등不動산 時価 주석 (회사가 鑑定/공시지가로 산출) | 🟢 |
| **공시지가 추정** | 회사가 시가를 안 준 영업용 토지 → 면적 × 공시지가로 직접 추정 | 🟡🔴 |
| **정밀 감정** | 큰 필지를 등기부·路線価로 확인 | 사람(human-in-loop) |

자동 스크린이 "여기 含み益 크다"를 거칠게 가리키면, 매수 전 사람이 큰 필지를 정밀 확인한다.

## 2단계 파이프라인 (책의 흐름)

```
1단계  스크린       PBR≤0.5 · 자기자본비율≥60% · PER≤12 · 오래된 회사 → 자산가치주 후보 압축
2단계  정밀 NAV     후보를 종목별로 — 상장지분 시가평가 + 부동산 含み益 + 카탈리스트 → nav_discount 랭킹
```

```
universe → [CORE 수집] → ├─ [EQUITY 정밀]        ─┐
                          ├─ [부동산: 공시시가 🟢 / 공시지가 추정 🟡🔴] ┤→ [NAV 집계·랭킹] → 리포트
                          └─ [UNLISTED 근사]      ─┘
```

## 설치

```bash
pip install -e ".[dev]"          # 코어 + 테스트
pip install -e ".[dev,krx]"      # + KRX 시세(FinanceDataReader/pykrx)
cp .env.example .env             # API 키 입력 (모두 무료)
```

## 사용 (CLI — 한국)

```bash
asset-play sync-corp-codes                              # DART corpCode ↔ stock_code 동기화

# 1단계 — 자산가치주 스크린 (PBR·자기자본비율·PER·창업연도)
asset-play screen-value --stock 000050,000950,004370 --per 12 --founded-before 1980

# 2단계 — 종목별 정밀 점검 리포트 (Markdown, range + 신뢰도)
asset-play report --stock 000050 --auto-land --catalyst --out out/
#   --auto-land : 사업보고서 별도 투자부동산 공정가치 주석을 자동 추출(BS 대사) → 토지 含み益
#   --catalyst  : 밸류업·자사주·배당 공시로 카탈리스트 점수
#   --land-file : 검토한 토지값 수동 주입(human-in-loop)

# 전체 유니버스 NAV 랭킹 → CSV/HTML
asset-play screen --universe KOSPI --land-file land.json --out out/
pytest
```

경방 예시 출력: PBR 0.29 · 자기자본 65% · 창업 1919 → ✅ 통과 → 타임스퀘어 투자부동산 **장부 3,313억 → 공정 7,453억(+4,140억 🟢)**, nav_discount 81.3%.

## 멀티마켓 (SPEC-ADAPTER-001)

코어(스크린·NAV·집계·리포트)는 **시장무관** — 데이터에만 의존한다. 시장 결합은 `MarketAdapter` 한 곳에 모이고, 새 시장은 어댑터만 추가하면 코어를 그대로 재사용한다.

| | 한국 `KrAdapter` | 일본 `JpAdapter` |
|---|---|---|
| 공시·재무 | DART | EDINET 有報 XBRL |
| 가격 | KRX | J-Quants (무료=주가) |
| 회사 공시 시가 🟢 | 투자부동산 공정가치 주석 | 賃貸등不動산 時価 주석 |
| 공시지가 추정 🟡🔴 | V-World 개별공시지가 × 면적 | 設備현황 + 国土数値情報 公示地価/地価調査 |

### 일본 (라이브러리)

```python
from asset_play.config import Config
from asset_play.pipeline import Pipeline
from asset_play.report.markdown_report import build_company_report, write_markdown
from asset_play.sources.adapter import JpAdapter
from asset_play.sources.jp_edinet import EdinetClient, JQuantsClient, recent_business_dates
from asset_play.sources.jp_landprice import build_index_from_files

cfg = Config.from_env()  # ASSET_PLAY_EDINET_KEY, ASSET_PLAY_JQUANTS_KEY
idx = build_index_from_files("L01-25.geojson", "L02-25.geojson")  # 国土数値情報(키 불필요)
adapter = JpAdapter(EdinetClient(cfg), JQuantsClient(cfg),
                    dates=recent_business_dates(40), landprice_index=idx)
report = build_company_report(Pipeline(cfg, adapter=adapter), "9031", auto_land=True)
write_markdown(report, "out/9031_report.md")
# 西日本鉄道: 賃貸등不動산 +1,407억엔(🟢) + 영업용 토지 公示地価 추정(🟡🔴)
```

> 일본 한계(정직): US-GAAP과 달리 일본은 賃貸등不動산 時価를 공시(2010~, ASBJ 제20호)하나, 自社전용 영업용 토지는 취득원가만 공시 → 공시지가 추정(🟡🔴)으로 보완. 정밀은 사람이 路線価図로.

## NAV 공식 (SPEC-NAV-001 rev.3)

```
total_pretax  = Σ(지분 + 토지 + 투자부동산 + 기타)        # asset_id 이중계상 제거
total_posttax = total_pretax × (1 − 법인세율)  if > 0 else total_pretax
revalued_nav  = 별도(OFS)_자본총계 + total_posttax       # JP는 連結 지배지분
nav_discount  = 1 − 시가총액 / revalued_nav              # >0 → NAV 대비 할인(쌈), 1차 신호
```

- **기준 통일**: 자기자본·보유지분·토지 surplus를 한 기준으로(KR 별도 OFS, JP 連結) — 혼용하면 이중계상.
- **실현가능 vs 인식형**: 투자부동산·단순투자 지분 → `realizable`, 영업용 토지·경영참여 → `recognition_only`.
  recognition-only + 무카탈리스트 = value-trap 경계.
- **range + 신뢰도**: 각 자산을 [보수=장부 ~ 추정시가] range로 잡고 🟢🟡🔴 표기. 🔴는 S2 상한에만 가산.

## 데이터 소스 (모두 무료)

| 시장 | 소스 | 제공 | 인증 |
|------|------|------|------|
| KR | DART OpenAPI | corpCode·재무·타법인출자현황·기업개황·**document.xml(투자부동산 공정가치)** | 키, 일일한도→캐시 |
| KR | KRX (`pykrx`/`FinanceDataReader`) | 종가·시총·상장주식수 | 무료 스크래핑 |
| KR | V-World / 행안부 juso | 주소→PNU·개별공시지가·면적 | 키(무료) |
| JP | EDINET API v2 | 有報 XBRL: 財務·賃貸등不動산 時価·設備현황 | 키(무료, Subscription-Key) |
| JP | J-Quants V2 | 주가(무료플랜) | 키(무료, x-api-key) |
| JP | 国土数値情報 L01/L02 · GSI | 公示地価/地価調査(円/㎡)·주소→좌표 | **키 불필요** |

## 아키텍처

```
src/asset_play/
├── domain/        # pydantic 계약: enums, money(단위 정규화), models
├── config.py      # 설정·키·튜닝 가정
├── cache/         # 로컬 SQLite 캐시
├── sources/       # KR: dart_client·dart_document(IP 공정가치)·krx·molit·vworld·juso
│   ├── adapter.py     # MarketAdapter · KrAdapter · JpAdapter · MarketLabels
│   ├── jp_edinet.py / jp_edinet_document.py   # EDINET·J-Quants·GSI · 賃貸등/財務/設備현황 파서
│   └── jp_landprice.py                        # 公示地価/地価調査 인덱스 + 영업용 토지 추정
├── valuation/     # equity · land_screen · land_precise · unlisted · screen · catalyst
├── aggregate/     # nav(세후·이중계상 방지) · rank
├── report/        # csv · html · markdown_report(종목별 range + 시장별 라벨)
├── pipeline.py    # 오케스트레이션 (adapter 주입)
└── __main__.py    # CLI (sync / screen / screen-value / report)
.moai/specs/       # SPEC suite
tests/             # SPEC별 test-first
```

## SPEC suite

| SPEC | 내용 |
|------|------|
| CORE / EQUITY / LAND-001·002 / UNLISTED / NAV-001 | 한국 수집·평가·NAV(rev.3) 코어 |
| SCREEN-001 | 1차 자산가치주 스크린 (PBR·자기자본비율·PER·창업연도) |
| IPNOTE-001 | 투자부동산 공정가치 주석 자동 파서 (`--auto-land`) |
| CATALYST-001 | 공시 기반 catalyst_score + value-trap |
| ADAPTER-001 | MarketAdapter 멀티마켓 시임 |
| JP-001 / JP-002 | 일본 EDINET 어댑터 · 영업용 토지 公示地価 추정 |

## 핵심 불변량 (TRUST 5)

1. 기준 통일(KR 별도 / JP 連結) — 혼용 시 이중계상.
2. 이중계상 금지 — 같은 자산을 지분+토지 또는 공시시가+공시지가추정으로 중복 합산 금지.
3. 저신뢰 토지 자동확정 금지 — 매칭 실패/저신뢰는 검토 큐·🔴.
4. 단위 정규화 — 모든 금액 '원'/'엔' 기준(천원·백만원 혼재 정규화).
5. 추적성 — 모든 시가에 `source` + `as_of_date`.

> ⚠️ 본 도구는 리서치·스크리닝 보조용이며 투자 자문이 아니다. 토지 정밀 NAV는 사람 검토를 전제로 한다.
