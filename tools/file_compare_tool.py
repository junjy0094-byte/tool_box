"""텍스트 파일 비교 도구 (Notepad++ Compare 유사)."""

import difflib
import hashlib
import os
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Dict, List, Tuple

from tools.base_tool import BaseTool
from tools._dnd_helper import has_dnd, register_drop_target


def _file_hash(filepath: str) -> str:
    """파일 MD5 해시를 반환한다."""
    h = hashlib.md5()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _read_lines(filepath: str) -> List[str]:
    """파일을 줄 단위로 읽는다."""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            return f.readlines()
    except OSError:
        return []




class FileCompareTool(BaseTool):
    """여러 텍스트 파일을 비교하는 도구."""

    _FILETYPES = [
        ("텍스트/APDL 파일", "*.txt *.ans *.inp *.mac *.dat *.cdb *.log *.out"),
        ("모든 파일", "*.*"),
    ]

    @property
    def name(self) -> str:
        return "파일 비교"

    # ── UI 구성 ───────────────────────────────────────────────────────────────

    def build_ui(self, parent: tk.Frame) -> None:
        self._files: List[str] = []

        # 상단: 파일 목록
        list_frame = ttk.LabelFrame(
            parent,
            text="파일 목록" + ("  (드래그 앤 드롭 지원)" if has_dnd() else ""),
        )
        list_frame.pack(fill="x", padx=6, pady=(6, 3))

        btn_row = ttk.Frame(list_frame)
        btn_row.pack(fill="x", padx=4, pady=(4, 2))

        ttk.Button(btn_row, text="파일 추가", command=self._add_files).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(btn_row, text="선택 제거", command=self._remove_selected).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(btn_row, text="전체 제거", command=self._clear_files).pack(
            side="left", padx=(0, 16)
        )
        ttk.Button(btn_row, text="동일/다름 판단", command=self._check_similarity).pack(
            side="left"
        )

        lb_frame = ttk.Frame(list_frame)
        lb_frame.pack(fill="x", padx=4, pady=(0, 4))

        self._file_lb = tk.Listbox(
            lb_frame, height=5, selectmode="extended", activestyle="none"
        )
        self._file_lb.pack(side="left", fill="both", expand=True)

        sb = ttk.Scrollbar(lb_frame, orient="vertical", command=self._file_lb.yview)
        sb.pack(side="left", fill="y")
        self._file_lb.configure(yscrollcommand=sb.set)

        if has_dnd():
            register_drop_target(self._file_lb, self._load_paths)

        # 요약 레이블
        self._summary_var = tk.StringVar(
            value="파일을 추가하고 '동일/다름 판단' 버튼을 누르세요."
        )
        ttk.Label(parent, textvariable=self._summary_var, anchor="w").pack(
            fill="x", padx=10, pady=(0, 2)
        )

        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=6, pady=4)

        # 하단: 상세 비교
        detail_frame = ttk.LabelFrame(parent, text="상세 비교")
        detail_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        # 파일 선택 콤보
        sel_row = ttk.Frame(detail_frame)
        sel_row.pack(fill="x", padx=4, pady=(4, 2))

        ttk.Label(sel_row, text="파일 A:").pack(side="left")
        self._combo_a = ttk.Combobox(sel_row, state="readonly", width=28)
        self._combo_a.pack(side="left", padx=(4, 10))

        ttk.Label(sel_row, text="파일 B:").pack(side="left")
        self._combo_b = ttk.Combobox(sel_row, state="readonly", width=28)
        self._combo_b.pack(side="left", padx=(4, 10))

        ttk.Button(sel_row, text="상세 비교", command=self._do_diff).pack(side="left")

        # 차이 요약
        self._diff_summary_var = tk.StringVar(value="")
        ttk.Label(detail_frame, textvariable=self._diff_summary_var, anchor="w").pack(
            fill="x", padx=4, pady=(0, 2)
        )

        # Side-by-side diff 뷰
        diff_pw = ttk.PanedWindow(detail_frame, orient="horizontal")
        diff_pw.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        left_pane = ttk.Frame(diff_pw)
        right_pane = ttk.Frame(diff_pw)
        diff_pw.add(left_pane, weight=1)
        diff_pw.add(right_pane, weight=1)

        self._lbl_a = ttk.Label(left_pane, text="파일 A", anchor="w", foreground="#444")
        self._lbl_a.pack(fill="x")
        self._txt_a = self._make_text_view(left_pane, side="left")

        self._lbl_b = ttk.Label(right_pane, text="파일 B", anchor="w", foreground="#444")
        self._lbl_b.pack(fill="x")
        self._txt_b = self._make_text_view(right_pane, side="right")

        # 동기 스크롤
        self._txt_a.configure(yscrollcommand=self._scroll_sync_a)
        self._txt_b.configure(yscrollcommand=self._scroll_sync_b)
        self._vsb_a.configure(command=self._yview_both)
        self._vsb_b.configure(command=self._yview_both)

    def _make_text_view(self, parent: ttk.Frame, side: str) -> tk.Text:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)

        txt = tk.Text(
            frame, wrap="none", state="disabled",
            font=("Consolas", 9), relief="flat",
        )
        if side == "left":
            self._vsb_a = ttk.Scrollbar(frame, orient="vertical")
            self._hsb_a = ttk.Scrollbar(frame, orient="horizontal", command=txt.xview)
            txt.configure(xscrollcommand=self._hsb_a.set)
            vsb = self._vsb_a
            hsb = self._hsb_a
        else:
            self._vsb_b = ttk.Scrollbar(frame, orient="vertical")
            self._hsb_b = ttk.Scrollbar(frame, orient="horizontal", command=txt.xview)
            txt.configure(xscrollcommand=self._hsb_b.set)
            vsb = self._vsb_b
            hsb = self._hsb_b

        txt.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        txt.tag_configure("added",   background="#C8FFC8")
        txt.tag_configure("removed", background="#FFC8C8")
        txt.tag_configure("changed", background="#FFFACC")
        txt.tag_configure("same",    background="#FFFFFF")
        txt.tag_configure("empty",   background="#F0F0F0")
        txt.tag_configure("linenum", foreground="#999999")

        return txt

    # ── 스크롤 동기화 ──────────────────────────────────────────────────────────

    def _scroll_sync_a(self, *args):
        self._vsb_a.set(*args)
        self._txt_b.yview_moveto(args[0])

    def _scroll_sync_b(self, *args):
        self._vsb_b.set(*args)
        self._txt_a.yview_moveto(args[0])

    def _yview_both(self, *args):
        self._txt_a.yview(*args)
        self._txt_b.yview(*args)

    # ── 파일 관리 ─────────────────────────────────────────────────────────────

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=self._FILETYPES)
        self._load_paths(list(paths))

    def _load_paths(self, paths: List[str]) -> None:
        for p in paths:
            if os.path.isfile(p) and p not in self._files:
                self._files.append(p)
                self._file_lb.insert("end", os.path.basename(p))
        self._update_combos()
        self._summary_var.set(
            f"파일 {len(self._files)}개 로드됨  |  '동일/다름 판단' 버튼을 누르세요."
        )

    def _remove_selected(self) -> None:
        for idx in reversed(self._file_lb.curselection()):
            self._files.pop(idx)
            self._file_lb.delete(idx)
        self._update_combos()
        self._summary_var.set(f"파일 {len(self._files)}개 로드됨")

    def _clear_files(self) -> None:
        self._files.clear()
        self._file_lb.delete(0, "end")
        self._update_combos()
        self._clear_diff()
        self._summary_var.set("파일을 추가하고 '동일/다름 판단' 버튼을 누르세요.")

    def _update_combos(self) -> None:
        names = self._short_names()
        self._combo_a["values"] = names
        self._combo_b["values"] = names
        if names:
            if self._combo_a.get() not in names:
                self._combo_a.current(0)
            if self._combo_b.get() not in names:
                self._combo_b.current(min(1, len(names) - 1))
        else:
            self._combo_a.set("")
            self._combo_b.set("")

    # ── 동일/다름 판단 ────────────────────────────────────────────────────────

    def _check_similarity(self) -> None:
        if len(self._files) < 2:
            self._summary_var.set("비교하려면 2개 이상의 파일이 필요합니다.")
            return

        hash_groups: Dict[str, List[str]] = {}
        for fp in self._files:
            h = _file_hash(fp)
            hash_groups.setdefault(h, []).append(fp)

        # 파일별 그룹 번호 맵
        file_group: Dict[str, int] = {}
        for gid, fps in enumerate(hash_groups.values(), 1):
            for fp in fps:
                file_group[fp] = gid

        short_names = self._short_names()
        name_map = dict(zip(self._files, short_names))

        # 리스트박스 재구성 (색상 포함)
        self._file_lb.delete(0, "end")
        same_cnt = 0
        unique_cnt = 0

        for fp in self._files:
            gid = file_group[fp]
            group_size = sum(1 for g in file_group.values() if g == gid)
            is_dup = group_size > 1

            badge = "● 동일" if is_dup else "● 고유"
            self._file_lb.insert("end", f"{badge}  {name_map[fp]}")
            self._file_lb.itemconfig(
                "end",
                foreground="#1155BB" if is_dup else "#BB2222",
            )
            if is_dup:
                same_cnt += 1
            else:
                unique_cnt += 1

        groups = len(hash_groups)
        self._summary_var.set(
            f"파일 {len(self._files)}개  |  그룹 {groups}개  "
            f"|  동일(중복) {same_cnt}개  |  고유 {unique_cnt}개"
        )

    # ── 상세 비교 ─────────────────────────────────────────────────────────────

    def _do_diff(self) -> None:
        names = self._short_names()
        name_a = self._combo_a.get()
        name_b = self._combo_b.get()

        if not name_a or not name_b:
            self._diff_summary_var.set("파일 A와 파일 B를 선택하세요.")
            return
        if name_a == name_b:
            self._diff_summary_var.set("같은 파일을 선택했습니다. 서로 다른 파일을 선택하세요.")
            return

        name_to_path = dict(zip(names, self._files))
        path_a = name_to_path.get(name_a)
        path_b = name_to_path.get(name_b)

        if not path_a or not path_b:
            return

        self._lbl_a.config(text=name_a)
        self._lbl_b.config(text=name_b)

        lines_a = _read_lines(path_a)
        lines_b = _read_lines(path_b)
        self._render_diff(lines_a, lines_b)

    def _render_diff(
        self,
        lines_a: List[str],
        lines_b: List[str],
    ) -> None:
        """SequenceMatcher 결과를 Side-by-Side로 렌더링한다."""
        matcher = difflib.SequenceMatcher(None, lines_a, lines_b, autojunk=False)

        # (tag, linenum_str, text) 목록
        left_buf: List[Tuple[str, str, str]] = []
        right_buf: List[Tuple[str, str, str]] = []

        added = deleted = changed = 0

        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            if op == "equal":
                for li, ri in zip(range(i1, i2), range(j1, j2)):
                    left_buf.append(("same", str(li + 1), lines_a[li]))
                    right_buf.append(("same", str(ri + 1), lines_b[ri]))

            elif op == "replace":
                l_block = lines_a[i1:i2]
                r_block = lines_b[j1:j2]
                changed += max(len(l_block), len(r_block))
                for k in range(max(len(l_block), len(r_block))):
                    if k < len(l_block):
                        left_buf.append(("changed", str(i1 + k + 1), l_block[k]))
                    else:
                        left_buf.append(("empty", "", ""))
                    if k < len(r_block):
                        right_buf.append(("changed", str(j1 + k + 1), r_block[k]))
                    else:
                        right_buf.append(("empty", "", ""))

            elif op == "delete":
                deleted += i2 - i1
                for li in range(i1, i2):
                    left_buf.append(("removed", str(li + 1), lines_a[li]))
                    right_buf.append(("empty", "", ""))

            elif op == "insert":
                added += j2 - j1
                for ri in range(j1, j2):
                    left_buf.append(("empty", "", ""))
                    right_buf.append(("added", str(ri + 1), lines_b[ri]))

        self._fill_text(self._txt_a, left_buf)
        self._fill_text(self._txt_b, right_buf)

        self._diff_summary_var.set(
            f"추가: +{added}줄  |  삭제: -{deleted}줄  |  변경: ~{changed}줄"
        )

    def _fill_text(
        self,
        txt: tk.Text,
        content: List[Tuple[str, str, str]],
    ) -> None:
        txt.config(state="normal")
        txt.delete("1.0", "end")
        for tag, linenum, text in content:
            num_str = f"{linenum:>6} " if linenum else "       "
            txt.insert("end", num_str, "linenum")
            line_text = text if text else "\n"
            txt.insert("end", line_text, tag)
            if line_text and not line_text.endswith("\n"):
                txt.insert("end", "\n", tag)
        txt.config(state="disabled")

    def _clear_diff(self) -> None:
        for txt in (self._txt_a, self._txt_b):
            txt.config(state="normal")
            txt.delete("1.0", "end")
            txt.config(state="disabled")
        self._diff_summary_var.set("")

    def _short_names(self) -> List[str]:
        basenames = [os.path.basename(fp) for fp in self._files]
        if len(basenames) == len(set(basenames)):
            return basenames
        return [
            os.path.join(os.path.basename(os.path.dirname(fp)), os.path.basename(fp))
            for fp in self._files
        ]
