"""플랫폼별 드래그 앤 드롭 등록 헬퍼.

Windows  : ctypes 로 WM_DROPFILES 직접 처리 (외부 라이브러리 불필요)
기타     : tkinterdnd2 fallback
"""

import sys
from typing import Callable, List


def has_dnd() -> bool:
    """현재 플랫폼에서 드래그 앤 드롭을 사용할 수 있으면 True."""
    if sys.platform == "win32":
        return True  # ctypes 는 표준 라이브러리
    try:
        from tkinterdnd2 import DND_FILES  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


def register_drop_target(widget, callback: Callable[[List[str]], None]) -> None:
    """위젯에 파일 드롭을 등록한다.

    callback(paths: List[str]) 형태로 메인 스레드에서 호출된다.
    """
    if sys.platform == "win32":
        # 위젯이 화면에 그려진 뒤에 HWND가 확정되므로 after()로 지연
        widget.after(0, lambda: _register_win32(widget, callback))
    else:
        _register_tkdnd(widget, callback)


# ── Windows: ctypes WM_DROPFILES ─────────────────────────────────────────────

def _register_win32(widget, callback: Callable[[List[str]], None]) -> None:
    """WndProc 서브클래싱으로 WM_DROPFILES 를 처리한다.

    콜백은 항상 widget.after(0, ...) 를 통해 메인 스레드에서 실행된다.
    GIL 문제가 없고 외부 라이브러리가 필요 없다.
    """
    import ctypes
    import ctypes.wintypes

    shell32 = ctypes.windll.shell32
    user32  = ctypes.windll.user32

    WM_DROPFILES = 0x0233
    GWL_WNDPROC  = -4

    # 64비트/32비트 호환
    try:
        _get_wl = user32.GetWindowLongPtrW
        _set_wl = user32.SetWindowLongPtrW
    except AttributeError:
        _get_wl = user32.GetWindowLongW
        _set_wl = user32.SetWindowLongW

    LRESULT = ctypes.c_ssize_t
    WNDPROC_T = ctypes.WINFUNCTYPE(
        LRESULT,
        ctypes.wintypes.HWND,
        ctypes.wintypes.UINT,
        ctypes.wintypes.WPARAM,
        ctypes.wintypes.LPARAM,
    )

    try:
        hwnd = widget.winfo_id()
        if not hwnd:
            return

        # 이 윈도우가 WM_DROPFILES 를 받도록 허용
        shell32.DragAcceptFiles(hwnd, True)

        # 기존 WndProc 포인터 저장
        old_proc = _get_wl(hwnd, GWL_WNDPROC)

        @WNDPROC_T
        def _new_proc(hwnd_, msg, wparam, lparam):
            if msg == WM_DROPFILES:
                hdrop = wparam
                # 파일 개수 조회 (index = 0xFFFFFFFF)
                count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
                files: List[str] = []
                for i in range(count):
                    buf_len = shell32.DragQueryFileW(hdrop, i, None, 0) + 1
                    buf = ctypes.create_unicode_buffer(buf_len)
                    shell32.DragQueryFileW(hdrop, i, buf, buf_len)
                    files.append(buf.value)
                shell32.DragFinish(hdrop)
                # 반드시 메인 스레드에서 콜백 실행 (GIL 안전)
                captured = list(files)
                widget.after(0, lambda: callback(captured))
                return 0
            return user32.CallWindowProcW(old_proc, hwnd_, msg, wparam, lparam)

        _set_wl(hwnd, GWL_WNDPROC, _new_proc)
        # 가비지 컬렉션 방지: 위젯 속성에 참조 유지
        widget._dnd_proc_ref = _new_proc

    except Exception:
        pass  # DnD 미지원 환경에서 조용히 무시


# ── 비-Windows: tkinterdnd2 fallback ─────────────────────────────────────────

def _register_tkdnd(widget, callback: Callable[[List[str]], None]) -> None:
    try:
        from tkinterdnd2 import DND_FILES  # type: ignore
    except Exception:
        return

    import re

    def _accept(event):
        return "copy"

    def _on_drop(event):
        try:
            files = list(event.widget.tk.splitlist(event.data))
        except Exception:
            files = []
            for tok in re.findall(r"\{([^}]+)\}|(\S+)", event.data):
                p = tok[0] or tok[1]
                if p:
                    files.append(p)
        callback(files)
        return event.action

    widget.drop_target_register(DND_FILES)
    widget.dnd_bind("<<DropEnter>>",    _accept)
    widget.dnd_bind("<<DropPosition>>", _accept)
    widget.dnd_bind("<<Drop>>",         _on_drop)
