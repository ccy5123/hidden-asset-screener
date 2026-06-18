# Asset-Play Screener (`asset-play`)

> 한국 상장사가 보유한 **토지·부동산 / 상장주식 / 관계·종속기업 지분**의 장부가(취득원가)와
> 시가의 괴리를 종목별로 정밀 정량화(NAV)하여, 숨은 자산가치(含み資産, *hidden-asset value*)가
> 큰 종목을 발굴한다.
>
> 대표 원형: **한신전기철도** — 고시엔 구장이 1924년 취득원가(원가모형)로 장부에 남아 시가와 수천 배 괴리.

## 무엇을 계산하나

종목별로 자산군의 **장부가 ↔ 추정시가** 괴리를 합산해 미실현이익(含み益)을 구하고,
이연법인세를 보정한 **세후 net surplus**와 시가총액 대비 비율 **`surplus_ratio`** 로 랭킹한다.
`surplus_ratio`가 높을수록 시장이 숨은 자산을 반영하지 못한 후보(특히 *holdco discount*).

```
surplus_ratio = net_surplus / 시가총액
net_surplus   = 미실현이익_총(세전) × (1 − 법인세율)
미실현이익_총  = Σ(지분 + 토지 + 투자부동산 + 기타)
```

## 2단계 파이프라인 (자동화 수준이 자산군마다 다름)

| Tier | 자산군 | 정밀 NAV 자동화 | 처리 |
|------|--------|----------------|------|
| 1 | 보유 상장주식·상장 관계/종속기업 지분 | **완전 자동** | DART 타법인출자현황 장부가 vs KRX 시가 |
| 2 | 토지·부동산 | 반자동 | ① 자동 1차 스크리닝 → ② 숏리스트 정밀 NAV(human-in-loop) |
| 3 | 비상장·관계기업 지분 | 근사 | 피투자사 순자산 기반 추정 |

```
universe → [CORE 수집] → ├─ [EQUITY 정밀]  ─┐
                          ├─ [LAND 스크리닝] → 숏리스트 → [LAND 정밀(검토 큐)] ─┤→ [NAV 집계·랭킹] → 리포트
                          └─ [UNLISTED 근사] ─┘
```

## 설치

```bash
pip install -e ".[dev]"          # 코어 + 테스트
pip install -e ".[dev,krx]"      # + KRX 시세 어댑터(FinanceDataReader/pykrx)
cp .env.example .env             # API 키 입력 (모두 무료)
```

## 사용

```bash
asset-play sync-corp-codes                 # DART corpCode ↔ stock_code 매핑 동기화
asset-play screen --universe KOSPI --out out/   # 전체 파이프라인 → CSV + HTML 리포트
asset-play screen --land-file land.json --out out/   # 검토된 토지/투자부동산 값 주입 (Tier-2, human-in-loop)
pytest                                     # 테스트 (TDD, SPEC 수용기준 커버)
```

`--land-file`은 사업보고서 주석에서 추출·검토한 토지/투자부동산 값을 파이프라인에 주입한다(필지 정밀 NAV는 사람 검토 전제). 파일에 적힌 종목코드는 자동으로 스크리닝 대상에 포함된다.

```json
// land.json — {종목코드 또는 corp_code: [{LandAsset 필드...}]}  (금액 단위: 원)
{ "000050": [ { "location_text": "영등포 타임스퀘어", "book_value": 331337332000, "fair_value": 726712601000 } ] }
```

CSV도 지원한다: `code,location_text,book_value,fair_value,measurement_model` 헤더에 필지별 1행.

두 가지 평가 경로가 자동 적용된다:
- **공정가치 주석 제공 시** (`fair_value`): 그 값을 시가로 직접 사용 (투자부동산).
- **소재지·면적만 제공 시** (`location_text`/`pnu` + `area_sqm`, `fair_value` 없음): V-World 지오코더로 PNU를
  찾고 MOLIT 개별공시지가를 조회해 `면적 × 공시지가 × 보정계수(1.4)`로 추정한다(`ASSET_PLAY_VWORLD_KEY` 필요,
  파이프라인이 자동 연결). **지번주소 또는 PNU**를 권장한다 — 도로명주소는 PNU로 해석되지 않아 검토 큐로 빠진다.

### 투자처 이름 매칭 (이름→종목코드 DB)

타법인출자현황은 투자처 이름만 주고 종목코드를 주지 않는다(예: `엘지전자(주)`). 매칭 DB
`src/asset_play/data/name_aliases.json`이 표기 변형을 흡수한다 — `transliterations`(엘지→LG 등 약칭),
`names`(전체이름→종목코드 override). **코드 수정 없이 이 파일을 편집**해 매칭을 확장하며, 별도 파일을
`ASSET_PLAY_NAME_ALIASES`로 지정하면 병합된다(사용자 우선).

`screen` 실행 시 상장 매칭에 실패해 비상장으로 분류된 보유분을 장부가순으로 출력하고
`out/unresolved_names.csv`에 기록한다. 상장사인데 누락된 이름이 보이면 위 DB에 추가하면 된다.

라이브러리로:

```python
from asset_play.config import Config
from asset_play.pipeline import Pipeline

pipe = Pipeline(Config.from_env())
results = pipe.run(stock_codes=["000270", "003550"])  # NAVResult 리스트 (랭킹)
```

## 아키텍처

```
src/asset_play/
├── domain/        # pydantic 계약: enums, money(단위 정규화), models
├── config.py      # 설정·튜닝 가정(법인세율·보정계수·유니버스)
├── cache/         # SPEC-CORE 로컬 SQLite 캐시
├── sources/       # dart_client, krx, molit(공시지가/실거래가), vworld  (모두 주입가능)
├── valuation/     # equity / land_screen / land_precise(검토 큐) / unlisted
├── aggregate/     # nav(세후·이중계상 방지) / rank
├── report/        # csv + html
├── pipeline.py    # 오케스트레이션
└── __main__.py    # CLI
.moai/specs/       # SPEC suite (SPEC-First 입력)
tests/             # SPEC별 test-first
```

## 데이터 소스 (모두 무료 키)

| 소스 | 제공 | 인증 |
|------|------|------|
| DART OpenAPI | corpCode, 재무제표, **타법인출자현황**, 기업개황 | 키 필요, 일일 한도 → 캐싱 필수 |
| KRX (`pykrx`/`FinanceDataReader`) | 종가·시가총액·상장주식수 | 무료, 스크래핑 → 재시도·캐시 |
| 공공데이터포털(MOLIT) | 개별공시지가·실거래가 | 키 필요 |
| V-World | 주소→PNU geocoder | 키 필요 |

## 핵심 불변량 (TRUST 5)

1. **별도재무제표(separate FS)** 기준 보유분만 사용 — 연결은 상계되어 사라짐.
2. **이중계상 금지** — 같은 자산을 지분+토지로 중복 합산 금지.
3. **토지 저신뢰 필지 자동확정 금지** — 매칭 실패/저신뢰는 검토 큐로.
4. **단위 정규화** — 모든 금액은 '원' 기준(천원·백만원 혼재 정규화).
5. **추적성** — 모든 시가에 `source` + `as_of_date` 부착.

## 착수 결정 (SPEC §8 — 적용된 값)

| # | 질문 | 적용 |
|---|------|------|
| 1 | 법인세율 | **22% 단일** (설정 가능, `ASSET_PLAY_CORPORATE_TAX_RATE`) |
| 2 | 공시지가 보정계수 | **전국 단일 ×1.4** (지역별 테이블 override 가능) |
| 3 | 유니버스 | **설정 가능 + KOSPI 우선** (`ASSET_PLAY_UNIVERSE`) |
| 4 | Point-in-time 보관 | **최소** — 현재 스냅샷 + `as_of`만(백테스트 엔진은 보류) |
| 5 | 출력 | **CSV + HTML 리포트** |

> ⚠️ 본 도구는 리서치·스크리닝 보조용이며 투자 자문이 아니다. 토지 정밀 NAV는 사람 검토(human-in-loop)를 전제로 한다.
