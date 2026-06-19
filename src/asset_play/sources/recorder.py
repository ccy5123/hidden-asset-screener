"""API 원문 호출 기록(tap) — 실행 중 외부 API 호출을 가로채 요청/응답 원문을 모은다.

Streamlit 앱이 "근거 추적성"(TRUST 5)을 위해 사용한다. ``with use_recorder() as rec:`` 블록
안에서 일어난 모든 ``HttpSource`` 호출(+ J-Quants·GSI)이 ``rec.calls`` 에 쌓인다. contextvar
기반이라 소스 생성자에 무엇도 주입할 필요가 없고, recorder가 없으면 완전 no-op(런타임 불변).

[HARD] API 키는 절대 기록하지 않는다 — params 의 민감 키는 ``mask_params`` 로 ``***`` 치환,
헤더 인증(J-Quants x-api-key 등)은 애초에 기록 대상에서 제외.
"""

from __future__ import annotations

import contextvars
import json
from dataclasses import dataclass, field
from typing import Any, Optional

_active: contextvars.ContextVar = contextvars.ContextVar("asset_play_api_recorder", default=None)

# 값이 가려져야 하는 파라미터 이름 조각(소문자 부분일치) — 키/토큰류.
_SENSITIVE = (
    "key", "subscription-key", "x-api-key", "servicekey", "crtfc_key",
    "authkey", "token", "secret", "password", "apikey",
)


def _is_sensitive(name: str) -> bool:
    n = str(name).lower()
    return any(s in n for s in _SENSITIVE)


def mask_params(params: Optional[dict]) -> dict:
    """민감 키 값은 ``***`` 로 치환한 사본을 반환(원본 불변)."""
    if not params:
        return {}
    return {k: ("***" if _is_sensitive(k) else v) for k, v in params.items()}


def preview_text(value: Any, limit: int = 4000) -> str:
    """응답을 사람이 읽을 미리보기 문자열로 — dict/list는 들여쓴 JSON, 길면 잘라 표시."""
    if isinstance(value, (bytes, bytearray)):
        return f"<binary {len(value):,} bytes>"
    if isinstance(value, (dict, list)):
        try:
            s = json.dumps(value, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            s = str(value)
    else:
        s = str(value)
    if len(s) > limit:
        return s[:limit] + f"\n… (생략됨 — 전체 {len(s):,}자)"
    return s


@dataclass
class ApiCall:
    source: str               # 출처명 (DART/EDINET/J-Quants/KRX/GSI/...)
    method: str
    url: str
    params: dict              # 마스킹된 파라미터
    status: Optional[int]     # HTTP status (캐시 적중·헤더인증 시 None일 수 있음)
    elapsed_ms: float
    cache_hit: bool
    preview: str              # 응답 원문 미리보기(잘릴 수 있음)
    ok: bool = True


@dataclass
class RequestRecorder:
    """호출 기록 버퍼. ``max_calls`` 초과분은 버린다(폭주 방지)."""

    max_calls: int = 400
    calls: list = field(default_factory=list)

    def add(self, call: ApiCall) -> None:
        if len(self.calls) < self.max_calls:
            self.calls.append(call)


def active_recorder() -> Optional[RequestRecorder]:
    return _active.get()


def record(
    source: str,
    url: str,
    *,
    method: str = "GET",
    params: Optional[dict] = None,
    status: Optional[int] = None,
    elapsed_ms: float = 0.0,
    cache_hit: bool = False,
    preview: str = "",
    ok: bool = True,
) -> None:
    """활성 recorder가 있으면 한 건 기록(없으면 no-op). 호출부는 항상 안전하게 부를 수 있다."""
    rec = _active.get()
    if rec is None:
        return
    rec.add(ApiCall(
        source=source, method=method, url=url, params=mask_params(params),
        status=status, elapsed_ms=round(elapsed_ms, 1), cache_hit=cache_hit,
        preview=preview, ok=ok,
    ))


class _RecorderCtx:
    def __init__(self, rec: RequestRecorder) -> None:
        self.rec = rec
        self._token = None

    def __enter__(self) -> RequestRecorder:
        self._token = _active.set(self.rec)
        return self.rec

    def __exit__(self, *exc: object) -> bool:
        if self._token is not None:
            _active.reset(self._token)
        return False


def use_recorder(rec: Optional[RequestRecorder] = None) -> _RecorderCtx:
    """``with use_recorder() as rec:`` — 블록 동안 호출을 ``rec`` 에 기록."""
    return _RecorderCtx(rec or RequestRecorder())
