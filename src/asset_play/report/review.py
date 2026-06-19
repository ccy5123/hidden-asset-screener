"""선택적 Claude 검수 (opt-in) — 결정론 리포트를 LLM으로 적대적 점검. 기본 OFF.

이 도구의 런타임은 결정론(LLM 0회)이 기본이다. ``--review``를 켤 때만 Claude Code CLI(``claude -p``)로
생성된 리포트의 내부 정합성·중복계상·단위·과대평가·분류·value-trap을 점검해 별도 ``_review.md``로 낸다.
claude CLI가 없거나 실패하면 graceful no-op(원 리포트는 불변·결정론 유지).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional, Union

_QUESTION = (
    "위 입력(stdin)은 숨은자산(NAV) 가치평가 리포트다. 투자 판단 전 점검할 오류·위험을 적대적으로 "
    "검토하라. 특히 ① 중복계상(회사 공시 시가 🟢 와 공시지가 추정 🟡🔴 가 같은 토지를 겹치는지) "
    "② 단위 오류(억/원/엔·1000배 혼동) ③ 과대평가(🔴 추정치가 비현실적인지) "
    "④ 분류 오류(실현가능 vs 인식형) ⑤ value-trap(高할인 + 무카탈리스트). "
    "리포트 내부 정합성 위주로(원문서는 없음), 발견사항과 '사람이 직접 확인할 것'을 간결한 목록으로. 한국어로."
)


def claude_review(
    report_path: Union[str, Path], *, model: Optional[str] = None, timeout: int = 180
) -> Optional[str]:
    """``claude -p``로 리포트 검수 → 검수 텍스트. claude 미설치/실패 시 None (no-op)."""
    claude = shutil.which("claude")
    if not claude:
        return None
    report_text = Path(report_path).read_text(encoding="utf-8")
    cmd = [claude, "-p", _QUESTION]
    if model:
        cmd += ["--model", model]
    try:
        r = subprocess.run(
            cmd, input=report_text, capture_output=True, text=True, timeout=timeout
        )
    except Exception:
        return None
    out = (r.stdout or "").strip()
    return out or None
