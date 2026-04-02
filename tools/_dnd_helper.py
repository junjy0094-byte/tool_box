"""플랫폼별 드래그 앤 드롭 등록 헬퍼.

Windows  : ctypes 로 WM_DROPFILES 직접 처리 (외부 라이브러리 불필요)
기타     : tkinterdnd2 fallback
"""

import sys
from typing import Callable, List


def has_dnd() -> bool:
    """현재 플랫폼에서 드래그 앤 드롭을 사용할 수 있으면 True."""
    if sys.platform == "win32":
        return True
    try:
        from tkinterdnd2 import DND_FILES  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


def register_drop_target(widget, callback: Callable[[List[str]], None]) -> None:
    """위젯에 파일 드롭을 등록한다.

    callback(paths: List[str]) 은 메인 스레드에서 호출된다.
    """
    if sys.platform == "win32":
        widget.after(0, lambda: _register_win32(widget, callback))
    else:
        _register_tkdnd(widget, callback)


# ── Windows: ctypes WM_DROPFILES ─────────────────────────────────────────────

def _register_win32(widget, callback: Callable[[List[str]], None]) -> None:
    """WndProc 서브클래싱으로 WM_DROPFILES 를 처리한다.

    주의: GetWindowLongPtrW / SetWindowLongPtrW 의 반환·인수 타입을
    반드시 c_void_p (포인터 크기) 로 선언해야 64비트 포인터 잘림을 막는다.
    기본값인 c_int(32비트)를 사용하면 old_proc 가 0으로 잘려
    CallWindowProcW 에서 access violation 이 발생한다.
    """
    import ctypes
    import ctypes.wintypes as wt

    shell32 = ctypes.windll.shell32
    user32  = ctypes.windll.user32

    WM_DROPFILES = 0x0233
    GWL_WNDPROC  = -4
    LRESULT      = ctypes.c_ssize_t

    WNDPROC_T = ctypes.WINFUNCTYPE(
        LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM
    )

    # 64비트/32비트 호환 – 반환형을 c_void_p 로 명시 (포인터 잘림 방지)
    try:
        _gwlp = user32.GetWindowLongPtrW
        _swlp = user32.SetWindowLongPtrW
    except AttributeError:
        _gwlp = user32.GetWindowLongW
        _swlp = user32.SetWindowLongW

    _gwlp.restype  = ctypes.c_void_p          # ← 핵심: 포인터 크기 반환
    _gwlp.argtypes = [wt.HWND, ctypes.c_int]

    _swlp.restype  = ctypes.c_void_p
    _swlp.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_void_p]

    user32.CallWindowProcW.restype  = LRESULT
    user32.CallWindowProcW.argtypes = [
        ctypes.c_void_p,   # lpPrevWndFunc – 포인터 크기
        wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM,
    ]

    shell32.DragAcceptFiles.restype  = None
    shell32.DragAcceptFiles.argtypes = [wt.HWND, wt.BOOL]

    shell32.DragQueryFileW.restype  = wt.UINT
    shell32.DragQueryFileW.argtypes = [
        ctypes.c_void_p,   # hDrop
        wt.UINT,           # iFile
        ctypes.c_wchar_p,  # lpszFile  (None → NULL 로 변환됨)
        wt.UINT,           # cch
    ]

    shell32.DragFinish.restype  = None
    shell32.DragFinish.argtypes = [ctypes.c_void_p]

    try:
        hwnd = widget.winfo_id()
        if not hwnd:
            return

        shell32.DragAcceptFiles(hwnd, True)

        # old_proc: c_void_p 반환 → Python int (64비트 포인터 전체 보존)
        old_proc = _gwlp(hwnd, GWL_WNDPROC)

        @WNDPROC_T
        def _new_proc(hwnd_: int, msg: int, wparam: int, lparam: int) -> int:
            if msg == WM_DROPFILES:
                count = shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                files: List[str] = []
                for i in range(count):
                    n = shell32.DragQueryFileW(wparam, i, None, 0) + 1
                    buf = ctypes.create_unicode_buffer(n)
                    shell32.DragQueryFileW(wparam, i, buf, n)
                    files.append(buf.value)
                shell32.DragFinish(wparam)
                captured = list(files)
                widget.after(0, lambda: callback(captured))
                return 0
            # old_proc 는 Python int → c_void_p 인수로 자동 변환
            return user32.CallWindowProcW(old_proc, hwnd_, msg, wparam, lparam)

        # 콜백 포인터(c_void_p 정수) 를 SetWindowLongPtrW 에 전달
        new_proc_ptr = ctypes.cast(_new_proc, ctypes.c_void_p)
        _swlp(hwnd, GWL_WNDPROC, new_proc_ptr)

        # GC 방지: 참조를 위젯 속성에 보관
        widget._dnd_proc_ref = _new_proc

    except Exception:
        pass


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
