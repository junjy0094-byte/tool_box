"""도구 도움말 브라우저.

각 도구 클래스의 ``summary`` / ``help_text`` 를 모아 한 창에서 보여 준다.
런처의 [도움말] 버튼, 도구 목록의 [?] 버튼, 도구 창 상단의 [도움말] 버튼이
모두 이 창을 연다 (창은 하나만 뜨고, 이미 떠 있으면 해당 도구로 이동한다).
"""

import tkinter as tk
from tkinter import ttk
from typing import List, Optional, Type

from tools.base_tool import BaseTool

OVERVIEW_TITLE = "Tool Box 개요"

OVERVIEW = """\
[ Tool Box 는 무엇인가 ]
  반도체 패키지 해석 업무에서 반복되는 작업들을 도구 하나씩으로 묶어 둔
  모음이다. 왼쪽(런처)에서 도구 이름을 누르면 그 도구만 별도 창으로 열리고,
  창을 닫으면 메모리에서 해제된다. 쓰지 않는 도구는 아예 로드되지 않는다.

[ 도움말 보는 법 ]
  · 런처의 [도움말] 버튼 — 이 창을 연다.
  · 도구 이름 옆 [?] 버튼 — 그 도구 설명으로 바로 이동한다.
  · 도구 창 위쪽 [도움말] 버튼 — 작업 중에도 같은 설명을 볼 수 있다.
  · 왼쪽 목록에서 도구를 고르면 오른쪽에 설명이 나온다. 위의 검색창에
    단어를 넣으면 이름·요약·본문에서 찾아 목록을 좁힌다.

[ 도구들이 공통으로 따르는 규칙 ]
  · 설정 저장 : 일부 도구는 마지막에 넣은 값을 프로그램 폴더의 config.json 에
    저장해 두었다가 다음에 열 때 그대로 보여 준다.
  · 드래그 앤 드롭 : 파일 목록이나 설정 폼에 파일을 끌어다 놓을 수 있다
    (tkinterdnd2 가 설치되어 있을 때).
  · 무거운 의존성(numpy, scipy, matplotlib, shapely, pcb-tools, PyMAPDL)은
    해당 도구를 열 때만 로드된다. 패키지가 없으면 그 도구 창에만 안내가 뜬다.
  · 그리기 계열 도구(Bump array 내 sub zone 생성기, Leadframe 그리기)는
    설정 폼에서 값을 넣고 [그리기 창 열기] 를 누르면 별도 작업 창이 뜬다.
    작업 창에는 단축키와 1:1로 대응하는 명령 버튼과 로그 창이 함께 있다.

[ 자주 이어 쓰는 조합 ]
  · Ball Map 생성기 → (좌표 txt) → Ball Map 변환기 : 배치를 0/1 맵으로
  · Ball Map 생성기 → (좌표 txt) → Bump array 내 sub zone 생성기 : 구역 나누고 APDL 로
  · Trace Mapping → (격자 CSV) : 배선층을 등가 물성으로
  · Leadframe 그리기 → (geom.mac) : 이미지 형상을 APDL 면으로
  · DB → INP 변환기 : 완성된 ANSYS 모델을 Abaqus 로

[ 설치 ]
  pip install -r requirements.txt
  (도구별로 필요한 패키지는 각 도움말 맨 아래에 적어 두었다)
"""


class HelpWindow(tk.Toplevel):
    """도구 목록 + 설명 본문."""

    def __init__(self, master: tk.Misc, tools: List[Type[BaseTool]]):
        super().__init__(master)
        self.tools = list(tools)
        self.title("Tool Box 도움말")
        self.geometry("980x680")
        self.minsize(720, 480)

        self._entries = [(OVERVIEW_TITLE, "", OVERVIEW)] + [
            (getattr(t, "name", t.__name__),
             getattr(t, "summary", ""),
             getattr(t, "help_text", "") or "이 도구에는 아직 설명이 없습니다.")
            for t in self.tools
        ]
        self._shown: List[int] = []

        self._build()
        self._apply_filter()
        self.select(OVERVIEW_TITLE)

    # ── UI ────────────────────────────────────────────
    def _build(self) -> None:
        top = ttk.Frame(self, padding=(10, 8, 10, 4))
        top.pack(fill="x")
        ttk.Label(top, text="Tool Box 도움말",
                  font=("", 13, "bold")).pack(side="left")
        ttk.Label(top, text="도구를 고르면 설명이 표시됩니다.",
                  foreground="gray").pack(side="left", padx=(10, 0))

        search = ttk.Frame(self, padding=(10, 0, 10, 6))
        search.pack(fill="x")
        ttk.Label(search, text="검색:").pack(side="left")
        self._q = tk.StringVar()
        self._q.trace_add("write", lambda *_a: self._apply_filter())
        ent = ttk.Entry(search, textvariable=self._q)
        ent.pack(side="left", fill="x", expand=True, padx=(6, 6))
        ttk.Button(search, text="지우기",
                   command=lambda: self._q.set("")).pack(side="left")

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = ttk.Frame(body)
        body.add(left, weight=1)
        self._listbox = tk.Listbox(left, activestyle="none", exportselection=False,
                                   width=30)
        lsb = ttk.Scrollbar(left, orient="vertical",
                            command=self._listbox.yview)
        self._listbox.configure(yscrollcommand=lsb.set)
        lsb.pack(side="right", fill="y")
        self._listbox.pack(side="left", fill="both", expand=True)
        self._listbox.bind("<<ListboxSelect>>", lambda _e: self._on_select())

        right = ttk.Frame(body)
        body.add(right, weight=3)
        self._title = ttk.Label(right, text="", font=("", 12, "bold"))
        self._title.pack(anchor="w", padx=(8, 0))
        self._summary = ttk.Label(right, text="", foreground="gray",
                                  wraplength=620, justify="left")
        self._summary.pack(anchor="w", padx=(8, 0), pady=(2, 6))

        text_wrap = ttk.Frame(right)
        text_wrap.pack(fill="both", expand=True)
        self._text = tk.Text(text_wrap, wrap="word", state="disabled",
                             font=("Consolas", 10), padx=8, pady=6,
                             relief="flat", background="#FBFBFB")
        tsb = ttk.Scrollbar(text_wrap, orient="vertical",
                            command=self._text.yview)
        self._text.configure(yscrollcommand=tsb.set)
        tsb.pack(side="right", fill="y")
        self._text.pack(side="left", fill="both", expand=True)
        self._text.tag_configure("head", foreground="#1155BB",
                                 font=("Consolas", 10, "bold"))

        self._status = tk.StringVar()
        ttk.Label(self, textvariable=self._status, foreground="gray",
                  anchor="w").pack(fill="x", padx=12, pady=(0, 8))

    # ── 동작 ──────────────────────────────────────────
    def _apply_filter(self) -> None:
        q = self._q.get().strip().lower()
        keep = self._current_name()
        self._listbox.delete(0, "end")
        self._shown = []
        for i, (name, summary, body) in enumerate(self._entries):
            if q and q not in (name + " " + summary + " " + body).lower():
                continue
            self._shown.append(i)
            self._listbox.insert("end", name)
        self._status.set(f"도구 {len(self._entries) - 1}개  |  표시 "
                         f"{len(self._shown)}개")
        if keep and not self.select(keep, silent=True):
            if self._shown:
                self._listbox.selection_set(0)
                self._on_select()

    def _current_name(self) -> Optional[str]:
        sel = self._listbox.curselection()
        if not sel:
            return None
        return self._listbox.get(sel[0])

    def _on_select(self) -> None:
        sel = self._listbox.curselection()
        if not sel:
            return
        name, summary, body = self._entries[self._shown[sel[0]]]
        self._title.configure(text=name)
        self._summary.configure(text=summary)
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        for line in body.splitlines():
            tag = "head" if line.startswith("[") else ""
            self._text.insert("end", line + "\n", tag)
        self._text.configure(state="disabled")
        self._text.yview_moveto(0.0)

    def select(self, name: str, silent: bool = False) -> bool:
        """이름으로 항목을 고른다. 필터에 걸려 안 보이면 필터를 지운다."""
        for pos, idx in enumerate(self._shown):
            if self._entries[idx][0] == name:
                self._listbox.selection_clear(0, "end")
                self._listbox.selection_set(pos)
                self._listbox.see(pos)
                self._on_select()
                return True
        if silent:
            return False
        if self._q.get():
            self._q.set("")          # 필터 때문에 숨은 경우 → 필터 해제 후 재시도
            return self.select(name, silent=True)
        return False


_window: Optional[HelpWindow] = None


def open_help(master: tk.Misc, tools: List[Type[BaseTool]],
              tool_cls: Optional[Type[BaseTool]] = None) -> HelpWindow:
    """도움말 창을 연다 (이미 열려 있으면 앞으로 가져오고 항목만 이동)."""
    global _window
    if _window is None or not _window.winfo_exists():
        _window = HelpWindow(master.winfo_toplevel(), tools)
    _window.deiconify()
    _window.lift()
    try:
        _window.focus_force()
    except tk.TclError:
        pass
    if tool_cls is not None:
        _window.select(getattr(tool_cls, "name", tool_cls.__name__))
    return _window


class _Tooltip:
    """마우스를 올리면 요약을 띄우는 가벼운 툴팁."""

    def __init__(self, widget: tk.Misc, text: str, delay: int = 450):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._cancel()
        self._after = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def _show(self):
        if self._tip is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        except tk.TclError:
            return
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self._tip, text=self.text, justify="left",
                 background="#FFFFE0", relief="solid", borderwidth=1,
                 wraplength=320, padx=6, pady=3).pack()

    def _hide(self, _e=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


def attach_tooltip(widget: tk.Misc, text: str) -> None:
    """위젯에 요약 툴팁을 붙인다."""
    if text:
        _Tooltip(widget, text)
