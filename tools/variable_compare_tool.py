"""ANSYS APDL 입력 파일 변수 비교 도구."""

import os
import re
import tkinter as tk
from tkinter import ttk, filedialog
from typing import Dict, List, Tuple

from tools.base_tool import BaseTool
from tools._dnd_helper import has_dnd, register_drop_target
from tools.file_compare_tool import _path_tail

_HELP = """\
[ 무엇을 하는 도구인가 ]
  여러 개의 ANSYS APDL 입력 파일에서 변수 정의를 뽑아내, 파일별 값을 한 표에
  나란히 놓고 비교한다. "이번 해석과 지난 해석의 조건이 어디가 다른가"를
  파일을 일일이 열어보지 않고 확인하기 위한 도구다.

[ 입력 ]
  · APDL 입력 파일 여러 개 (.txt .inp .ans .mac .dat .cdb — 확장자 제한 없음)
  · [파일 추가] 버튼 또는 목록에 드래그 앤 드롭
  · 인식하는 형식 두 가지
      VAR = VALUE          (예: BUMP_H = 0.05)
      *SET,VAR,VALUE       (예: *SET,BUMP_H,0.05)
    '!' 뒤쪽은 주석으로 버린다.

[ 출력 ]
  · 화면의 비교 표 (변수 1열 + 파일별 값). 파일로 저장하지는 않는다.
  · 값이 서로 다르거나 한쪽에만 있는 행은 분홍색으로 강조된다.
  · 상태줄에 "총 변수 / 차이 / 표시" 개수가 나온다.

[ 사용 순서 ]
  1. 비교할 파일을 2개 이상 추가한다.
  2. [비교] 를 누른다.
  3. [차이만 표시] 를 켜면 값이 다른 변수만 남는다.
  4. 변수 필터에 문자열을 넣으면 이름에 그 문자열이 든 변수만 본다.
  5. 파일 이름이 겹쳐 구분이 안 되면 '경로 깊이' 를 올려 상위 폴더까지 표시한다.

[ 참고 ]
  · 변수 이름은 대문자로 통일해 비교한다.
  · 값은 문자열 그대로 비교하므로 0.05 와 5e-2 는 '다름' 으로 나온다.
  · 같은 변수가 파일 안에서 여러 번 정의되면 마지막 값이 표에 남는다.
  · 값이 비어 있는 칸은 그 파일에 해당 변수가 없다는 뜻이다.
"""



def parse_apdl_variables(filepath: str) -> Dict[str, str]:
    """APDL 입력 파일에서 변수 할당을 파싱한다.

    형식: VARIABLE = VALUE  (! 이후는 주석으로 무시)
    *SET, VARIABLE, VALUE 형태도 지원한다.
    """
    variables: Dict[str, str] = {}
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for line in f:
                # 주석 제거
                line = line.split("!")[0].strip()
                if not line:
                    continue

                # 패턴 1: VAR = VALUE
                m = re.match(
                    r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$", line
                )
                if m:
                    var_name = m.group(1).upper()
                    value = m.group(2).strip().rstrip(",")
                    variables[var_name] = value
                    continue

                # 패턴 2: *SET,VAR,VALUE
                m = re.match(
                    r"^\*SET\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*(.+)$",
                    line,
                    re.IGNORECASE,
                )
                if m:
                    var_name = m.group(1).upper()
                    value = m.group(2).strip().rstrip(",")
                    variables[var_name] = value
    except OSError:
        pass
    return variables


class VariableCompareTool(BaseTool):
    """여러 ANSYS APDL 입력 파일의 변수를 비교하는 도구."""

    name = "input 변수 비교"
    summary = "여러 APDL 입력 파일의 변수 값을 한 표에서 비교 (차이 강조)"
    help_text = _HELP

    _FILETYPES = [
        ("APDL 파일", "*.txt *.inp *.ans *.mac *.dat *.cdb"),
        ("모든 파일", "*.*"),
    ]

    # ── UI 구성 ──────────────────────────────────────

    def build_ui(self, parent: tk.Frame) -> None:  # noqa: C901
        self._files: List[str] = []
        self._all_vars: Dict[str, Dict[str, str]] = {}  # {filepath: {var: val}}

        # ── 상단: 파일 목록 ──────────────────────────────────────────────────
        list_lf = ttk.LabelFrame(
            parent,
            text="파일 목록" + ("  (외부 파일 드래그 앤 드롭 지원)" if has_dnd() else ""),
        )
        list_lf.pack(fill="x", padx=6, pady=(6, 2))

        btn_row = ttk.Frame(list_lf)
        btn_row.pack(fill="x", padx=4, pady=(4, 2))

        ttk.Button(btn_row, text="파일 추가", command=self._add_files).pack(side="left", padx=(0, 3))
        ttk.Button(btn_row, text="선택 제거", command=self._remove_selected).pack(side="left", padx=(0, 3))
        ttk.Button(btn_row, text="전체 제거", command=self._clear_files).pack(side="left")

        # 경로 깊이 설정 (우측)
        ttk.Label(btn_row, text="경로 깊이:").pack(side="right")
        self._depth_var = tk.IntVar(value=3)
        depth_sb = ttk.Spinbox(
            btn_row, from_=1, to=8, width=3, textvariable=self._depth_var,
            command=self._on_depth_changed,
        )
        depth_sb.pack(side="right", padx=(0, 4))
        depth_sb.bind("<Return>", lambda _e: self._on_depth_changed())

        lb_row = ttk.Frame(list_lf)
        lb_row.pack(fill="x", padx=4, pady=(0, 4))

        self._file_listbox = tk.Listbox(
            lb_row, height=5, selectmode="extended", activestyle="none"
        )
        self._file_listbox.pack(side="left", fill="both", expand=True)
        file_scroll = ttk.Scrollbar(
            lb_row, orient="vertical", command=self._file_listbox.yview
        )
        file_scroll.pack(side="left", fill="y")
        self._file_listbox.configure(yscrollcommand=file_scroll.set)

        if has_dnd():
            register_drop_target(self._file_listbox, self._load_paths)

        # ── 중단: 필터 + 비교 버튼 ──────────────────────────────────────────
        mid = ttk.Frame(parent)
        mid.pack(fill="x", padx=6, pady=4)

        ttk.Button(mid, text="비교", command=self._compare).pack(side="left", padx=(0, 8))

        ttk.Label(mid, text="변수 필터:").pack(side="left")
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(mid, textvariable=self._filter_var, width=20).pack(
            side="left", padx=(4, 8)
        )

        self._diff_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            mid, text="차이만 표시", variable=self._diff_only_var,
            command=self._apply_filter,
        ).pack(side="left")

        # 하단: 비교 결과 테이블
        table_frame = ttk.Frame(parent)
        table_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        self._tree = ttk.Treeview(table_frame, show="headings", selectmode="browse")
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self._tree.yview)
        hsb = ttk.Scrollbar(
            table_frame, orient="horizontal", command=self._tree.xview
        )
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        # 상태 바
        self._status_var = tk.StringVar(value="파일을 추가하고 비교 버튼을 누르세요.")
        ttk.Label(parent, textvariable=self._status_var, anchor="w").pack(
            fill="x", padx=6, pady=(0, 4)
        )

        # 행 태그 (차이 강조)
        self._tree.tag_configure("diff", background="#FFDDDD")
        self._tree.tag_configure("same", background="#FFFFFF")

    # ── 파일 관리 ────────────────────────────────────

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=self._FILETYPES)
        self._load_paths(list(paths))

    def _load_paths(self, paths: List[str]) -> None:
        for p in paths:
            if os.path.isfile(p) and p not in self._files:
                self._files.append(p)
        self._refresh_listbox()
        self._status_var.set(f"파일 {len(self._files)}개 로드됨")

    def _remove_selected(self) -> None:
        indices = list(self._file_listbox.curselection())
        for idx in reversed(indices):
            self._files.pop(idx)
            self._file_listbox.delete(idx)
        self._status_var.set(f"파일 {len(self._files)}개 로드됨")

    def _clear_files(self) -> None:
        self._files.clear()
        self._file_listbox.delete(0, "end")
        self._all_vars.clear()
        self._clear_table()
        self._status_var.set("파일을 추가하고 비교 버튼을 누르세요.")

    # ── 비교 로직 ────────────────────────────────────

    def _compare(self) -> None:
        if len(self._files) < 2:
            self._status_var.set("비교하려면 2개 이상의 파일이 필요합니다.")
            return

        self._all_vars.clear()
        for fp in self._files:
            self._all_vars[fp] = parse_apdl_variables(fp)

        self._rebuild_table()

    def _rebuild_table(self) -> None:
        """결과 테이블을 현재 데이터로 다시 구성한다."""
        self._clear_table()

        short_names = self._short_names()

        columns = ("variable",) + tuple(short_names)
        self._tree["columns"] = columns

        self._tree.heading("variable", text="변수", anchor="w")
        self._tree.column("variable", width=140, minwidth=80, anchor="w")
        for sn in short_names:
            self._tree.heading(sn, text=sn, anchor="w")
            self._tree.column(sn, width=120, minwidth=60, anchor="w")

        # 모든 변수 이름 수집
        all_var_names: set[str] = set()
        for var_dict in self._all_vars.values():
            all_var_names.update(var_dict.keys())

        self._rows: List[Tuple[str, List[str], bool]] = []
        for var in sorted(all_var_names):
            values = [self._all_vars[fp].get(var, "") for fp in self._files]
            non_empty = [v for v in values if v]
            is_diff = len(set(non_empty)) > 1 or any(v == "" for v in values)
            self._rows.append((var, values, is_diff))

        self._apply_filter()

    def _apply_filter(self) -> None:
        """필터/차이만 표시 옵션에 따라 행을 표시한다."""
        self._tree.delete(*self._tree.get_children())

        if not hasattr(self, "_rows"):
            return

        pattern = self._filter_var.get().strip().upper()
        diff_only = self._diff_only_var.get()
        short_names = self._short_names()
        shown = 0
        total_diff = 0

        for var, values, is_diff in self._rows:
            if is_diff:
                total_diff += 1
            if pattern and pattern not in var:
                continue
            if diff_only and not is_diff:
                continue
            tag = "diff" if is_diff else "same"
            self._tree.insert(
                "", "end", values=(var, *values), tags=(tag,)
            )
            shown += 1

        self._status_var.set(
            f"총 변수 {len(self._rows)}개 | 차이 {total_diff}개 | 표시 {shown}개"
        )

    def _clear_table(self) -> None:
        self._tree.delete(*self._tree.get_children())
        self._tree["columns"] = ()

    def _short_names(self) -> List[str]:
        """파일 경로를 경로 깊이 설정에 따라 짧은 표시 이름으로 변환한다."""
        depth = max(1, self._depth_var.get())
        return [_path_tail(fp, depth) for fp in self._files]

    def _refresh_listbox(self) -> None:
        """경로 깊이에 맞춰 파일 리스트박스를 갱신한다."""
        self._file_listbox.delete(0, "end")
        for sn in self._short_names():
            self._file_listbox.insert("end", sn)

    def _on_depth_changed(self) -> None:
        """경로 깊이 변경 시 리스트박스와 테이블 헤더를 갱신한다."""
        self._refresh_listbox()
        if hasattr(self, "_rows") and self._rows:
            self._rebuild_table()
