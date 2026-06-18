"""--land-file loader: JSON + CSV → {code: [LandAsset]} (SPEC-LAND-002 human-in-loop input)."""

from decimal import Decimal

import pytest

from asset_play.domain.enums import MeasurementModel
from asset_play.land_file import load_land_assets


def test_load_json_dict_of_lists(tmp_path):
    p = tmp_path / "land.json"
    p.write_text(
        '{"000050": [{"location_text": "타임스퀘어", "book_value": 331337332000, '
        '"fair_value": 726712601000}]}',
        encoding="utf-8",
    )
    data = load_land_assets(p)
    assert list(data) == ["000050"]
    (asset,) = data["000050"]
    assert asset.book_value == Decimal("331337332000")
    assert asset.fair_value == Decimal("726712601000")
    assert asset.location_text == "타임스퀘어"


def test_load_csv_groups_by_code_and_coerces(tmp_path):
    p = tmp_path / "land.csv"
    p.write_text(
        "code,location_text,book_value,fair_value,measurement_model\n"
        "000050,타임스퀘어,331337332000,726712601000,원가\n"
        "000050,영등포2,1000,,COST\n",
        encoding="utf-8",
    )
    data = load_land_assets(p)
    assert len(data["000050"]) == 2
    a, b = data["000050"]
    assert a.fair_value == Decimal("726712601000")
    assert a.measurement_model == MeasurementModel.COST  # value "원가"
    assert b.measurement_model == MeasurementModel.COST  # name "COST"
    assert b.fair_value is None  # empty cell → unset


def test_unknown_field_rejected(tmp_path):
    p = tmp_path / "land.json"
    p.write_text('{"000050": [{"bogus": 1}]}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_land_assets(p)


def test_unsupported_extension(tmp_path):
    p = tmp_path / "land.txt"
    p.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError):
        load_land_assets(p)


def test_missing_file():
    with pytest.raises(FileNotFoundError):
        load_land_assets("does-not-exist.json")
