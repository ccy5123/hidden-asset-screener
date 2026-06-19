"""CLI wiring: `screen --land-file` resolves codes and feeds land into the pipeline."""

from decimal import Decimal

from asset_play import __main__ as cli


class _FakeRun:
    results: list = []
    quota_exhausted = False
    warnings: list = []
    unresolved: list = []


class _FakeDart:
    def corp_code_for_stock(self, stock_code):
        return "00101628" if stock_code == "000050" else None


class _FakePipeline:
    captured: dict = {}

    def __init__(self, config=None):
        # land-file 코드 해석은 멀티마켓 시임을 위해 pipe.adapter 경유 (KR/JP 공통).
        self.adapter = _FakeDart()
        self.dart = self.adapter
        self.cache = None

    def run_and_report(self, **kwargs):
        _FakePipeline.captured = kwargs
        return _FakeRun(), "out/x.csv", "out/x.html"


def test_screen_land_file_feeds_pipeline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "land.json").write_text(
        '{"000050": [{"location_text": "타임스퀘어", "book_value": 331337332000, '
        '"fair_value": 726712601000}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr("asset_play.pipeline.Pipeline", _FakePipeline)

    rc = cli.main(["screen", "--land-file", "land.json", "--out", str(tmp_path / "out")])
    assert rc == 0

    kwargs = _FakePipeline.captured
    # the land-file code became a screen target
    assert "000050" in kwargs["stock_codes"]
    # land resolved to corp_code and reached the pipeline
    land = kwargs["land_assets_by_corp"]["00101628"]
    assert land[0].fair_value == Decimal("726712601000")
