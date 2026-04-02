"""드래그 앤 드롭 등록 헬퍼 (tkinterdnd2 기반).

tkinterdnd2 를 사용하려면 반드시 루트 창이 TkinterDnD.Tk() 여야 한다.
main.py 에서 이를 보장한다.
"""

from typing import Callable, List


def has_dnd() -> bool:
    try:
        from tkinterdnd2 import DND_FILES  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


def register_drop_target(widget, callback: Callable[[List[str]], None]) -> None:
    """위젯에 파일 드롭을 등록한다.

    - <<DropEnter>> / <<DropPosition>> 에서 'copy' 를 반환해야
      OS 가 드롭 허용으로 판단하고 금지 커서 대신 복사 커서를 표시한다.
    - callback(paths) 은 메인 스레드에서 호출된다.
    """
    try:
        from tkinterdnd2 import DND_FILES  # type: ignore
    except Exception:
        return

    def _on_drop(event):
        try:
            files = event.widget.tk.splitlist(event.data)
        except Exception:
            files = [p.strip("{}") for p in event.data.split() if p.strip("{}")]
        callback([f for f in files if f])
        return event.action

    widget.drop_target_register(DND_FILES)
    widget.dnd_bind("<<DropEnter>>",    lambda e: "copy")
    widget.dnd_bind("<<DropPosition>>", lambda e: "copy")
    widget.dnd_bind("<<DropLeave>>",    lambda e: "copy")
    widget.dnd_bind("<<Drop>>",         _on_drop)
