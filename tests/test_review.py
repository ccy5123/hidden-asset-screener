"""선택적 Claude 검수(opt-in) — claude CLI 셸아웃 단위 + report --review 배선.

핵심 불변량: claude CLI가 없거나 실패하면 graceful no-op(원 리포트는 결정론·불변).
"""

from pathlib import Path
from types import SimpleNamespace

from asset_play import __main__ as cli
from asset_play.report import review as rv


def test_claude_review_noop_without_cli(tmp_path, monkeypatch):
    """claude 미설치 → None (실행 안 함)."""
    report = tmp_path / "r.md"
    report.write_text("# 리포트\n", encoding="utf-8")
    monkeypatch.setattr(rv.shutil, "which", lambda _: None)
    assert rv.claude_review(report) is None


def test_claude_review_pipes_report_and_returns_stdout(tmp_path, monkeypatch):
    """claude 발견 → 리포트 텍스트를 stdin으로 전달, stdout을 검수로 반환."""
    report = tmp_path / "r.md"
    report.write_text("# 리포트 본문\n", encoding="utf-8")
    monkeypatch.setattr(rv.shutil, "which", lambda _: "/usr/bin/claude")
    captured: dict = {}

    def _fake_run(cmd, *, input, capture_output, text, timeout):
        captured["cmd"] = cmd
        captured["input"] = input
        return SimpleNamespace(stdout="검수: 중복계상 의심 1건\n", returncode=0)

    monkeypatch.setattr(rv.subprocess, "run", _fake_run)
    out = rv.claude_review(report)
    assert out == "검수: 중복계상 의심 1건"
    assert captured["cmd"][:2] == ["/usr/bin/claude", "-p"]
    assert "리포트 본문" in captured["input"]      # 리포트가 stdin으로 들어감
    assert "--model" not in captured["cmd"]          # 모델 미지정


def test_claude_review_adds_model_flag(tmp_path, monkeypatch):
    report = tmp_path / "r.md"
    report.write_text("x", encoding="utf-8")
    monkeypatch.setattr(rv.shutil, "which", lambda _: "/usr/bin/claude")
    captured: dict = {}

    def _fake_run(cmd, **_):
        captured["cmd"] = cmd
        return SimpleNamespace(stdout="ok", returncode=0)

    monkeypatch.setattr(rv.subprocess, "run", _fake_run)
    rv.claude_review(report, model="opus")
    assert captured["cmd"][-2:] == ["--model", "opus"]


def test_claude_review_noop_on_subprocess_error(tmp_path, monkeypatch):
    report = tmp_path / "r.md"
    report.write_text("x", encoding="utf-8")
    monkeypatch.setattr(rv.shutil, "which", lambda _: "/usr/bin/claude")

    def _boom(*_, **__):
        raise OSError("claude crashed")

    monkeypatch.setattr(rv.subprocess, "run", _boom)
    assert rv.claude_review(report) is None


def test_claude_review_noop_on_empty_stdout(tmp_path, monkeypatch):
    report = tmp_path / "r.md"
    report.write_text("x", encoding="utf-8")
    monkeypatch.setattr(rv.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(
        rv.subprocess, "run", lambda *_, **__: SimpleNamespace(stdout="  \n", returncode=0)
    )
    assert rv.claude_review(report) is None


# -- CLI wiring: report --review writes a separate _review.md ----------------- #


class _FakePipeline:
    def __init__(self, config=None):
        self.dart = None


def _wire_report(monkeypatch, tmp_path, *, review_out):
    """report 커맨드를 가짜 파이프라인/리포트로 배선. review_out=검수 텍스트 또는 None."""
    monkeypatch.setattr("asset_play.pipeline.Pipeline", _FakePipeline)
    report_obj = SimpleNamespace(name="경방", stock_code="000050")

    def _fake_build(*_, **__):
        return report_obj

    def _fake_write(report, path):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# 경방 리포트\n", encoding="utf-8")
        return p

    monkeypatch.setattr("asset_play.report.markdown_report.build_company_report", _fake_build)
    monkeypatch.setattr("asset_play.report.markdown_report.write_markdown", _fake_write)
    monkeypatch.setattr("asset_play.report.review.claude_review", lambda *a, **k: review_out)


def test_report_review_flag_writes_review_file(tmp_path, monkeypatch):
    _wire_report(monkeypatch, tmp_path, review_out="검수 결과: 이상 없음")
    out = tmp_path / "out"
    rc = cli.main(["report", "--stock", "000050", "--review", "--out", str(out)])
    assert rc == 0
    rpath = out / "000050_report_review.md"
    assert rpath.exists()
    body = rpath.read_text(encoding="utf-8")
    assert "검수 (Claude) — 경방 (000050)" in body
    assert "검수 결과: 이상 없음" in body


def test_report_without_review_flag_writes_no_review_file(tmp_path, monkeypatch):
    _wire_report(monkeypatch, tmp_path, review_out="should-not-run")
    out = tmp_path / "out"
    rc = cli.main(["report", "--stock", "000050", "--out", str(out)])
    assert rc == 0
    assert not (out / "000050_report_review.md").exists()


def test_report_review_flag_noop_when_cli_missing(tmp_path, monkeypatch):
    """검수가 None(claude 미발견)이면 _review.md 미생성 — 원 리포트는 그대로."""
    _wire_report(monkeypatch, tmp_path, review_out=None)
    out = tmp_path / "out"
    rc = cli.main(["report", "--stock", "000050", "--review", "--out", str(out)])
    assert rc == 0
    assert (out / "000050_report.md").exists()
    assert not (out / "000050_report_review.md").exists()
