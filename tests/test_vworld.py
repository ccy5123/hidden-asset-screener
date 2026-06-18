"""V-World geocoder PNU parsing (SPEC-LAND-002).

The getcoord response carries the 19-digit PNU at response.refined.structure.level4LC
(NOT in `result`, which holds x/y coordinates). Shapes below are real API responses.
"""

from asset_play.sources.vworld import VWorldClient


def test_parse_pnu_from_refined_structure():
    payload = {
        "response": {
            "status": "OK",
            "refined": {
                "structure": {"level4L": "태평로1가", "level4LC": "1114010300100010000", "level5": "1"}
            },
            "result": {"crs": "EPSG:4326", "point": {"x": "126.97", "y": "37.56"}},
        }
    }
    assert VWorldClient._parse_pnu(payload) == "1114010300100010000"


def test_parse_pnu_none_when_level4lc_blank():
    # road-type addresses do not carry a parcel PNU → blank → None (→ review queue)
    payload = {"response": {"status": "OK", "refined": {"structure": {"level4LC": ""}}}}
    assert VWorldClient._parse_pnu(payload) is None


def test_parse_pnu_none_on_not_ok():
    assert VWorldClient._parse_pnu({"response": {"status": "NOT_FOUND"}}) is None
    assert VWorldClient._parse_pnu({}) is None
