"""Load human-/Claude-reviewed land assets for Tier-2 valuation (SPEC-LAND-002).

Productizes the human-in-loop step: a reviewer (or Claude Code in-session) extracts
투자부동산 공정가치 / 토지 figures from a business-report note and records them in a file;
the ``screen`` CLI reads it and feeds the existing land pipeline. There is no network
or LLM call at runtime — the file IS the reviewed artifact (TRUST invariant: traceable,
no auto-confirmation of low-confidence parcels).

Formats (selected by extension):

- ``.json`` — ``{"<stock_or_corp_code>": [ {LandAsset fields...}, ... ], ...}``
- ``.csv``  — header row with a ``code`` column (stock or corp code) plus LandAsset
              field columns; one row per parcel, rows grouped by ``code``.

Recognized asset fields: location_text, area_sqm, book_value, fair_value,
official_price_per_sqm, measurement_model, land_category, pnu, holder_corp_code.
Amounts are in 원. ``measurement_model`` accepts an enum name (COST/REVALUATION/UNKNOWN)
or value (원가/재평가/불명).
"""

from __future__ import annotations

import csv
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Union

from .domain.enums import MeasurementModel
from .domain.models import LandAsset

_NUMERIC_FIELDS = {"area_sqm", "book_value", "fair_value", "official_price_per_sqm"}
_STR_FIELDS = {"location_text", "land_category", "pnu", "holder_corp_code"}
_ALLOWED_FIELDS = _NUMERIC_FIELDS | _STR_FIELDS | {"measurement_model"}
_CODE_COLUMNS = ("code", "stock_code", "corp_code")


def _coerce_model(value) -> MeasurementModel:
    if isinstance(value, MeasurementModel):
        return value
    s = str(value).strip()
    try:
        return MeasurementModel[s.upper()]  # enum name: COST / REVALUATION / UNKNOWN
    except KeyError:
        pass
    try:
        return MeasurementModel(s)  # enum value: 원가 / 재평가 / 불명
    except ValueError as exc:
        raise ValueError(f"invalid measurement_model: {value!r}") from exc


def _build_asset(d: dict) -> LandAsset:
    fields: dict = {}
    for key, value in d.items():
        if value is None or value == "":
            continue
        if key not in _ALLOWED_FIELDS:
            raise ValueError(f"unknown land field: {key!r}")
        if key in _NUMERIC_FIELDS:
            try:
                fields[key] = Decimal(str(value))
            except (InvalidOperation, ValueError) as exc:
                raise ValueError(f"invalid number for {key!r}: {value!r}") from exc
        elif key == "measurement_model":
            fields[key] = _coerce_model(value)
        else:
            fields[key] = str(value).strip()
    return LandAsset(**fields)


def load_land_assets(path: Union[str, Path]) -> dict[str, list[LandAsset]]:
    """Parse a land file into ``{code: [LandAsset, ...]}`` keyed by the code as written."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"land file not found: {p}")
    suffix = p.suffix.lower()
    if suffix == ".json":
        return _load_json(p)
    if suffix == ".csv":
        return _load_csv(p)
    raise ValueError(f"unsupported land file type {suffix!r} (use .json or .csv)")


def _load_json(p: Path) -> dict[str, list[LandAsset]]:
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("land JSON must be an object of the form {code: [asset, ...]}")
    out: dict[str, list[LandAsset]] = {}
    for code, assets in raw.items():
        if not isinstance(assets, list):
            raise ValueError(f"land JSON value for {code!r} must be a list of assets")
        out[str(code).strip()] = [_build_asset(a) for a in assets]
    return out


def _load_csv(p: Path) -> dict[str, list[LandAsset]]:
    out: dict[str, list[LandAsset]] = {}
    with p.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for line_no, row in enumerate(reader, start=2):
            code = ""
            for col in _CODE_COLUMNS:
                if row.get(col):
                    code = row.pop(col).strip()
                    break
            if not code:
                raise ValueError(f"row {line_no}: missing code column (one of {_CODE_COLUMNS})")
            asset = _build_asset({k: v for k, v in row.items() if k and k not in _CODE_COLUMNS})
            out.setdefault(code, []).append(asset)
    return out
