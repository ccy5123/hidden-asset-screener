"""CLI .env loader — quote/export tolerance and no-override semantics."""

import os

from asset_play.__main__ import _load_dotenv


def test_load_dotenv_strips_quotes_and_export_prefix(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "\n"
        "ASSET_PLAY_TEST_PLAIN=abc123\n"
        'ASSET_PLAY_TEST_DQ="def456"\n'
        "ASSET_PLAY_TEST_SQ='ghi789'\n"
        "export ASSET_PLAY_TEST_EXPORT=jkl\n",
        encoding="utf-8",
    )
    for k in (
        "ASSET_PLAY_TEST_PLAIN",
        "ASSET_PLAY_TEST_DQ",
        "ASSET_PLAY_TEST_SQ",
        "ASSET_PLAY_TEST_EXPORT",
    ):
        monkeypatch.delenv(k, raising=False)

    _load_dotenv(str(env))

    assert os.environ["ASSET_PLAY_TEST_PLAIN"] == "abc123"
    assert os.environ["ASSET_PLAY_TEST_DQ"] == "def456"  # double quotes stripped
    assert os.environ["ASSET_PLAY_TEST_SQ"] == "ghi789"  # single quotes stripped
    assert os.environ["ASSET_PLAY_TEST_EXPORT"] == "jkl"  # export prefix handled


def test_load_dotenv_does_not_override_real_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("ASSET_PLAY_TEST_X=fromfile\n", encoding="utf-8")
    monkeypatch.setenv("ASSET_PLAY_TEST_X", "fromenv")

    _load_dotenv(str(env))

    assert os.environ["ASSET_PLAY_TEST_X"] == "fromenv"


def test_load_dotenv_missing_file_is_noop(tmp_path):
    _load_dotenv(str(tmp_path / "nope.env"))  # must not raise
