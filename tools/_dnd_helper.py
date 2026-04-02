"""플랫폼별 드래그 앤 드롭 등록 헬퍼."""

import sys
from typing import Callable, List

# ── Windows: windnd (WM_DROPFILES 방식, 가장 안정적) ────────────────────────
_HAS_WINDND = False
if sys.platform == "win32":
    try:
        import windnd  # type: ignore
        _HAS_WINDND = True
    except ImportError:
        pass

# ── 크로스플랫폼 fallback: tkinterdnd2 ──────────────────────────────────────
_HAS_TKDND = False
_DND_FILES = None
if not _HAS_WINDND:
    try:
        from tkinterdnd2 import DND_FILES as _DND_FILES  # type: ignore
        _HAS_TKDND = True
    except Exception:
        pass


def has_dnd() -> bool:
    """현재 플랫폼에서 드래그 앤 드롭을 사용할 수 있으면 True."""
    return _HAS_WINDND or _HAS_TKDND


def register_drop_target(widget, callback: Callable[[List[str]], None]) -> None:
    """위젯에 파일 드롭을 등록한다.

    callback(paths: List[str]) 형태로 호출되며, paths 는 드롭된 파일 경로 목록이다.
    """
    if _HAS_WINDND:
        _register_windnd(widget, callback)
    elif _HAS_TKDND:
        _register_tkdnd(widget, callback)


# ── windnd 등록 ──────────────────────────────────────────────────────────────

def _register_windnd(widget, callback: Callable[[List[str]], None]) -> None:
    def _handler(files):
        decoded: List[str] = []
        for f in files:
            if isinstance(f, bytes):
                try:
                    decoded.append(f.decode("utf-8"))
                except UnicodeDecodeError:
                    decoded.append(f.decode("mbcs", errors="replace"))
            else:
                decoded.append(f)
        callback(decoded)

    windnd.hook_dropfiles(widget, func=_handler)


# ── tkinterdnd2 등록 ─────────────────────────────────────────────────────────

def _register_tkdnd(widget, callback: Callable[[List[str]], None]) -> None:
    import re

    def _on_enter(event):
        return "copy"

    def _on_drop(event):
        try:
            files = list(event.widget.tk.splitlist(event.data))
        except Exception:
            files = []
            for token in re.findall(r"\{([^}]+)\}|(\S+)", event.data):
                path = token[0] or token[1]
                if path:
                    files.append(path)
        callback(files)
        return event.action

    widget.drop_target_register(_DND_FILES)
    widget.dnd_bind("<<DropEnter>>",    _on_enter)
    widget.dnd_bind("<<DropPosition>>", _on_enter)
    widget.dnd_bind("<<Drop>>",         _on_drop)
