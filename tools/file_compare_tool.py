"""텍스트 파일 비교 도구 (Notepad++ Compare 유사)."""

import difflib
import hashlib
import os
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Tuple

from tools.base_tool import BaseTool
from tools._dnd_helper import has_dnd, register_drop_target

# 그룹별 색상 (최대 8색 순환)
_GROUP_COLORS = [
    "#1155BB",  # blue
    "#117711",  # green
    "#882299",  # purple
    "#AA5500",  # brown
    "#008888",  # teal
    "#AA2222",  # red
    "#666600",  # olive
    "#005577",  # navy
]


def _file_hash(filepath: str) -> str:
    h = hashlib.md5()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _read_lines(filepath: str) -> List[str]:
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            return f.readlines()
    except OSError:
        return []


def _path_tail(filepath: str, depth: int) -> str:
    """파일 경로의 마지막 depth 개 구성요소를 반환한다."""
    parts: List[str] = []
    p = filepath
    for _ in range(depth):
        head, tail = os.path.split(p)
        if tail:
            parts.insert(0, tail)
            p = head
        else:
            if p:
                parts.insert(0, p)
            break
    return os.path.join(*parts) if parts else filepath


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
        # 마지막 similarity 결과: {filepath: gid}  /  None = 미실행
        self._group_map: Optional[Dict[str, int]] = None
        # 내부 드래그 추적
        self._drag_idx: Optional[int] = None
        self._drag_start: Optional[Tuple[int, int]] = None

        # ── 상단: 파일 목록 ──────────────────────────────────────────────────
        list_lf = ttk.LabelFrame(
            parent,
            text="파일 목록" + ("  (외부 파일 드래그 앤 드롭 지원)" if has_dnd() else ""),
        )
        list_lf.pack(fill="x", padx=6, pady=(6, 2))

        btn_row = ttk.Frame(list_lf)
        btn_row.pack(fill="x", padx=4, pady=(4, 2))

        ttk.Button(btn_row, text="파일 추가",    command=self._add_files).pack(side="left", padx=(0, 3))
        ttk.Button(btn_row, text="선택 제거",    command=self._remove_selected).pack(side="left", padx=(0, 3))
        ttk.Button(btn_row, text="전체 제거",    command=self._clear_files).pack(side="left", padx=(0, 10))
        ttk.Button(btn_row, text="동일/다름 판단", command=self._check_similarity).pack(side="left", padx=(0, 3))
        ttk.Button(btn_row, text="선택 파일 동기화", command=self._sync_selected).pack(side="left")

        # 경로 깊이 설정 (우측)
        ttk.Label(btn_row, text="경로 깊이:").pack(side="right")
        self._depth_var = tk.IntVar(value=3)
        depth_sb = ttk.Spinbox(
            btn_row, from_=1, to=8, width=3, textvariable=self._depth_var,
            command=self._on_depth_changed,
        )
        depth_sb.pack(side="right", padx=(0, 4))
        depth_sb.bind("<Return>", lambda _e: self._on_depth_changed())

        # 파일 리스트박스
        lb_row = ttk.Frame(list_lf)
        lb_row.pack(fill="x", padx=4, pady=(0, 4))

        self._file_lb = tk.Listbox(
            lb_row, height=5, selectmode="extended", activestyle="none",
        )
        self._file_lb.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(lb_row, orient="vertical", command=self._file_lb.yview)
        sb.pack(side="left", fill="y")
        self._file_lb.configure(yscrollcommand=sb.set)

        # 외부 파일 드롭
        if has_dnd():
            register_drop_target(self._file_lb, self._load_paths)

        # 내부 드래그 (목록 → A/B 패널) + 드래그 범위 선택 차단
        self._file_lb.bind("<ButtonPress-1>",  self._on_lb_press)
        self._file_lb.bind("<B1-Motion>",       self._on_lb_motion)
        self._file_lb.bind("<ButtonRelease-1>", self._on_lb_release)

        # 우클릭 컨텍스트 메뉴 (외부 편집기에서 열기)
        self._file_lb.bind("<Button-3>", self._on_lb_right_click)

        # 요약
        self._summary_var = tk.StringVar(
            value="파일을 추가하고 '동일/다름 판단' 버튼을 누르세요."
        )
        ttk.Label(parent, textvariable=self._summary_var, anchor="w").pack(
            fill="x", padx=10, pady=(0, 2)
        )

        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=6, pady=3)

        # ── 하단: 상세 비교 ──────────────────────────────────────────────────
        detail_lf = ttk.LabelFrame(
            parent,
            text="상세 비교  ─  위 목록에서 아래 A·B 영역으로 드래그하여 파일 지정",
        )
        detail_lf.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        sel_row = ttk.Frame(detail_lf)
        sel_row.pack(fill="x", padx=4, pady=(4, 2))

        ttk.Label(sel_row, text="파일 A:").pack(side="left")
        self._combo_a = ttk.Combobox(sel_row, state="readonly", width=26)
        self._combo_a.pack(side="left", padx=(4, 8))

        ttk.Label(sel_row, text="파일 B:").pack(side="left")
        self._combo_b = ttk.Combobox(sel_row, state="readonly", width=26)
        self._combo_b.pack(side="left", padx=(4, 8))

        ttk.Button(sel_row, text="상세 비교", command=self._do_diff).pack(side="left")

        self._diff_summary_var = tk.StringVar(value="")
        ttk.Label(detail_lf, textvariable=self._diff_summary_var, anchor="w").pack(
            fill="x", padx=4, pady=(0, 2)
        )

        diff_pw = ttk.PanedWindow(detail_lf, orient="horizontal")
        diff_pw.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        self._frame_a = ttk.Frame(diff_pw)
        self._frame_b = ttk.Frame(diff_pw)
        diff_pw.add(self._frame_a, weight=1)
        diff_pw.add(self._frame_b, weight=1)

        # 각 패널의 드롭 헤더 레이블 (드래그 힌트 겸 드롭 타겟)
        self._lbl_a = tk.Label(
            self._frame_a,
            text="[ 파일 A ]  ← 위 목록에서 드래그",
            anchor="w", bg="#E8EEF8", fg="#336",
            relief="groove", padx=4,
        )
        self._lbl_a.pack(fill="x")

        self._lbl_b = tk.Label(
            self._frame_b,
            text="[ 파일 B ]  ← 위 목록에서 드래그",
            anchor="w", bg="#E8EEF8", fg="#336",
            relief="groove", padx=4,
        )
        self._lbl_b.pack(fill="x")

        self._txt_a = self._make_text_view(self._frame_a, "left")
        self._txt_b = self._make_text_view(self._frame_b, "right")

        self._txt_a.configure(yscrollcommand=self._scroll_sync_a)
        self._txt_b.configure(yscrollcommand=self._scroll_sync_b)
        self._vsb_a.configure(command=self._yview_both)
        self._vsb_b.configure(command=self._yview_both)

    def _make_text_view(self, parent: ttk.Frame, side: str) -> tk.Text:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)

        txt = tk.Text(frame, wrap="none", state="disabled",
                      font=("Consolas", 9), relief="flat")
        if side == "left":
            self._vsb_a = ttk.Scrollbar(frame, orient="vertical")
            self._hsb_a = ttk.Scrollbar(frame, orient="horizontal", command=txt.xview)
            txt.configure(xscrollcommand=self._hsb_a.set)
            vsb, hsb = self._vsb_a, self._hsb_a
        else:
            self._vsb_b = ttk.Scrollbar(frame, orient="vertical")
            self._hsb_b = ttk.Scrollbar(frame, orient="horizontal", command=txt.xview)
            txt.configure(xscrollcommand=self._hsb_b.set)
            vsb, hsb = self._vsb_b, self._hsb_b

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

    # ── 스크롤 동기화 ─────────────────────────────────────────────────────────

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
        added = 0
        for p in paths:
            if os.path.isfile(p) and p not in self._files:
                self._files.append(p)
                added += 1
        if added:
            self._group_map = None  # similarity 결과 초기화
            self._refresh_listbox()
            self._update_combos()
            self._summary_var.set(
                f"파일 {len(self._files)}개 로드됨  |  '동일/다름 판단' 버튼을 누르세요."
            )

    def _remove_selected(self) -> None:
        for idx in reversed(self._file_lb.curselection()):
            self._files.pop(idx)
        self._group_map = None
        self._refresh_listbox()
        self._update_combos()
        self._summary_var.set(f"파일 {len(self._files)}개 로드됨")

    def _clear_files(self) -> None:
        self._files.clear()
        self._group_map = None
        self._file_lb.delete(0, "end")
        self._update_combos()
        self._clear_diff()
        self._summary_var.set("파일을 추가하고 '동일/다름 판단' 버튼을 누르세요.")

    def _on_depth_changed(self) -> None:
        """경로 깊이 변경 시 리스트박스 레이블을 갱신한다."""
        self._refresh_listbox()
        self._update_combos()

    def _refresh_listbox(self) -> None:
        """현재 self._files 와 self._group_map 상태로 리스트박스를 다시 그린다."""
        self._file_lb.delete(0, "end")
        names = self._short_names()
        if self._group_map is None:
            for name in names:
                self._file_lb.insert("end", name)
        else:
            # similarity 결과 포함 렌더링
            group_sizes: Dict[int, int] = {}
            for gid in self._group_map.values():
                group_sizes[gid] = group_sizes.get(gid, 0) + 1

            for fp, name in zip(self._files, names):
                gid = self._group_map.get(fp, 0)
                size = group_sizes.get(gid, 1)
                badge = "동일" if size > 1 else "고유"
                color = _GROUP_COLORS[(gid - 1) % len(_GROUP_COLORS)]
                self._file_lb.insert("end", f"[G{gid}] {badge}  {name}")
                self._file_lb.itemconfig("end", foreground=color)

    def _update_combos(self) -> None:
        names = self._short_names()
        cur_a = self._combo_a.get()
        cur_b = self._combo_b.get()
        self._combo_a["values"] = names
        self._combo_b["values"] = names
        if names:
            self._combo_a.set(cur_a if cur_a in names else names[0])
            self._combo_b.set(cur_b if cur_b in names else names[min(1, len(names) - 1)])
        else:
            self._combo_a.set("")
            self._combo_b.set("")

    # ── 동일/다름 판단 (클러스터링) ───────────────────────────────────────────

    def _check_similarity(self) -> None:
        if len(self._files) < 2:
            self._summary_var.set("비교하려면 2개 이상의 파일이 필요합니다.")
            return

        hash_to_fps: Dict[str, List[str]] = {}
        for fp in self._files:
            h = _file_hash(fp)
            hash_to_fps.setdefault(h, []).append(fp)

        # 그룹 ID 부여: 해시별로 오름차순 번호
        self._group_map = {}
        for gid, fps in enumerate(hash_to_fps.values(), 1):
            for fp in fps:
                self._group_map[fp] = gid

        # 동일 파일끼리 인접하도록 그룹 ID 기준 정렬 (같은 그룹 내 원래 순서 유지)
        self._files.sort(key=lambda fp: self._group_map.get(fp, 0))

        self._refresh_listbox()
        self._update_combos()

        total = len(self._files)
        n_groups = len(hash_to_fps)
        dup_cnt = sum(1 for fp in self._files
                      if sum(1 for g in self._group_map.values()
                             if g == self._group_map[fp]) > 1)
        uniq_cnt = total - dup_cnt
        self._summary_var.set(
            f"파일 {total}개  |  그룹 {n_groups}개  "
            f"|  동일(중복) {dup_cnt}개  |  고유 {uniq_cnt}개"
        )

    # ── 선택 파일 동기화 ──────────────────────────────────────────────────────

    def _sync_selected(self) -> None:
        """팝업에서 덮어쓸 파일을 멀티 선택하고 기준 파일을 지정해 동기화한다."""
        if len(self._files) < 2:
            messagebox.showinfo("선택 파일 동기화", "파일이 2개 이상 필요합니다.")
            return

        names = self._short_names()
        # 현재 메인 리스트박스 선택을 초기 선택으로 활용
        pre_sel = set(self._file_lb.curselection())

        dlg = tk.Toplevel()
        dlg.title("선택 파일 동기화")
        dlg.resizable(True, True)
        dlg.grab_set()

        # ① 덮어쓸 파일 목록 (멀티 선택)
        ttk.Label(
            dlg, text="① 덮어쓸 파일 선택  (Ctrl / Shift 로 복수 선택):",
        ).pack(anchor="w", padx=10, pady=(10, 2))

        tgt_frame = ttk.Frame(dlg)
        tgt_frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        tgt_lb = tk.Listbox(tgt_frame, selectmode="extended", height=8, width=52)
        tgt_sb = ttk.Scrollbar(tgt_frame, orient="vertical", command=tgt_lb.yview)
        tgt_lb.configure(yscrollcommand=tgt_sb.set)
        tgt_lb.pack(side="left", fill="both", expand=True)
        tgt_sb.pack(side="left", fill="y")

        for i, name in enumerate(names):
            tgt_lb.insert("end", name)
            if i in pre_sel:          # 메인 리스트박스 선택 상태 반영
                tgt_lb.selection_set(i)

        # ② 기준 파일 (소스)
        ttk.Label(dlg, text="② 기준 파일 선택  (이 파일의 내용으로 덮어씁니다):").pack(
            anchor="w", padx=10, pady=(0, 2)
        )
        src_var = tk.StringVar(value=names[0])
        src_cb = ttk.Combobox(dlg, textvariable=src_var, values=names,
                               state="readonly", width=50)
        src_cb.pack(fill="x", padx=10, pady=(0, 8))

        def do_sync():
            tgt_indices = list(tgt_lb.curselection())
            if not tgt_indices:
                messagebox.showinfo("동기화", "덮어쓸 파일을 선택하세요.", parent=dlg)
                return
            name_to_path = dict(zip(names, self._files))
            src_path = name_to_path.get(src_var.get())
            if not src_path:
                return
            real_targets = [self._files[i] for i in tgt_indices
                            if self._files[i] != src_path]
            if not real_targets:
                messagebox.showinfo("동기화", "기준 파일 외 덮어쓸 파일이 없습니다.", parent=dlg)
                return
            msg = (
                f"선택한 {len(real_targets)}개 파일을\n"
                f"  기준: {os.path.basename(src_path)}\n"
                "의 내용으로 덮어씁니다.\n\n"
                "이 작업은 되돌릴 수 없습니다. 계속하시겠습니까?"
            )
            if not messagebox.askyesno("덮어쓰기 확인", msg, parent=dlg):
                return
            errors = []
            for tp in real_targets:
                try:
                    with open(src_path, "rb") as fsrc, open(tp, "wb") as fdst:
                        fdst.write(fsrc.read())
                except OSError as e:
                    errors.append(f"{os.path.basename(tp)}: {e}")
            dlg.destroy()
            if errors:
                messagebox.showerror("동기화 오류", "\n".join(errors))
            else:
                messagebox.showinfo("동기화 완료", f"{len(real_targets)}개 파일 동기화 완료.")
            self._group_map = None
            self._refresh_listbox()

        btn_f = ttk.Frame(dlg)
        btn_f.pack(pady=(0, 10))
        ttk.Button(btn_f, text="덮어쓰기 실행", command=do_sync).pack(side="left", padx=8)
        ttk.Button(btn_f, text="취소", command=dlg.destroy).pack(side="left")

    # ── 내부 드래그 (리스트박스 → A/B 패널) ──────────────────────────────────

    def _on_lb_press(self, event: tk.Event) -> None:
        idx = self._file_lb.nearest(event.y)
        if 0 <= idx < len(self._files):
            self._drag_idx = idx
            self._drag_start = (event.x_root, event.y_root)
        else:
            self._drag_idx = None

    def _on_lb_motion(self, event: tk.Event) -> str:
        # "break" 를 반환해 Listbox 기본 드래그 범위 선택을 항상 차단한다.
        # Ctrl/Shift 클릭 선택은 <ButtonPress-1> 에서 처리되므로 영향 없음.
        if self._drag_idx is not None and self._drag_start is not None:
            dx = abs(event.x_root - self._drag_start[0])
            dy = abs(event.y_root - self._drag_start[1])
            if dx + dy > 6:
                self._file_lb.configure(cursor="fleur")
                # 드롭 타겟 강조
                w = self._file_lb.winfo_containing(event.x_root, event.y_root)
                if self._widget_in(w, self._frame_a):
                    self._lbl_a.configure(bg="#C8D8F8")
                    self._lbl_b.configure(bg="#E8EEF8")
                elif self._widget_in(w, self._frame_b):
                    self._lbl_b.configure(bg="#C8D8F8")
                    self._lbl_a.configure(bg="#E8EEF8")
                else:
                    self._lbl_a.configure(bg="#E8EEF8")
                    self._lbl_b.configure(bg="#E8EEF8")
        return "break"  # 드래그 범위 선택 차단

    def _on_lb_release(self, event: tk.Event) -> None:
        self._file_lb.configure(cursor="")
        self._lbl_a.configure(bg="#E8EEF8")
        self._lbl_b.configure(bg="#E8EEF8")

        if self._drag_idx is None or self._drag_start is None:
            return

        dx = abs(event.x_root - self._drag_start[0])
        dy = abs(event.y_root - self._drag_start[1])
        dragged = dx + dy > 6

        self._drag_start = None
        idx = self._drag_idx
        self._drag_idx = None

        if not dragged:
            return

        w = self._file_lb.winfo_containing(event.x_root, event.y_root)
        names = self._short_names()
        if 0 <= idx < len(names):
            if self._widget_in(w, self._frame_a):
                self._set_diff_file("a", idx)
            elif self._widget_in(w, self._frame_b):
                self._set_diff_file("b", idx)

    def _widget_in(self, widget, frame) -> bool:
        """widget 이 frame 의 자손(또는 자기 자신)이면 True."""
        w = widget
        while w is not None:
            if w == frame:
                return True
            try:
                w = w.master
            except Exception:
                return False
        return False

    def _on_lb_right_click(self, event: tk.Event) -> None:
        """리스트박스 우클릭 시 컨텍스트 메뉴를 표시한다."""
        idx = self._file_lb.nearest(event.y)
        if idx < 0 or idx >= len(self._files):
            return
        # 우클릭한 항목도 선택에 포함
        if idx not in self._file_lb.curselection():
            self._file_lb.selection_clear(0, "end")
            self._file_lb.selection_set(idx)

        menu = tk.Menu(self._file_lb, tearoff=0)
        sel = self._file_lb.curselection()
        if len(sel) == 1:
            menu.add_command(
                label="외부 편집기에서 열기",
                command=lambda: self._open_in_editor(self._files[sel[0]]),
            )
        elif len(sel) > 1:
            menu.add_command(
                label=f"선택한 {len(sel)}개 파일 외부 편집기에서 열기",
                command=lambda: self._open_selected_in_editor(),
            )
        menu.tk_popup(event.x_root, event.y_root)

    def _open_in_editor(self, filepath: str) -> None:
        """OS 기본 연결 프로그램 또는 편집기로 파일을 연다."""
        try:
            if sys.platform == "win32":
                os.startfile(filepath)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", filepath])
            else:
                subprocess.Popen(["xdg-open", filepath])
        except OSError as e:
            messagebox.showerror("열기 실패", f"파일을 열 수 없습니다:\n{e}")

    def _open_selected_in_editor(self) -> None:
        """선택된 모든 파일을 외부 편집기에서 연다."""
        for i in self._file_lb.curselection():
            if 0 <= i < len(self._files):
                self._open_in_editor(self._files[i])

    def _set_diff_file(self, panel: str, idx: int) -> None:
        names = self._short_names()
        name = names[idx]
        if panel == "a":
            self._combo_a.set(name)
            self._lbl_a.configure(text=f"[ 파일 A ]  {name}")
        else:
            self._combo_b.set(name)
            self._lbl_b.configure(text=f"[ 파일 B ]  {name}")
        # 양쪽 모두 지정됐으면 즉시 비교
        if self._combo_a.get() and self._combo_b.get():
            self._do_diff()

    # ── 상세 비교 ─────────────────────────────────────────────────────────────

    def _do_diff(self) -> None:
        names = self._short_names()

        # 리스트박스에서 정확히 2개 선택된 경우 콤보박스에 자동 세팅
        sel = self._file_lb.curselection()
        if len(sel) == 2:
            idx_a, idx_b = sel
            if 0 <= idx_a < len(names) and 0 <= idx_b < len(names):
                self._combo_a.set(names[idx_a])
                self._combo_b.set(names[idx_b])

        name_a = self._combo_a.get()
        name_b = self._combo_b.get()

        if not name_a or not name_b:
            self._diff_summary_var.set("파일 A와 파일 B를 선택하세요.")
            return
        if name_a == name_b:
            self._diff_summary_var.set("같은 파일입니다. 서로 다른 파일을 선택하세요.")
            return

        name_to_path = dict(zip(names, self._files))
        path_a = name_to_path.get(name_a)
        path_b = name_to_path.get(name_b)
        if not path_a or not path_b:
            return

        self._lbl_a.configure(text=f"[ 파일 A ]  {name_a}")
        self._lbl_b.configure(text=f"[ 파일 B ]  {name_b}")

        self._render_diff(_read_lines(path_a), _read_lines(path_b))

    def _render_diff(self, lines_a: List[str], lines_b: List[str]) -> None:
        matcher = difflib.SequenceMatcher(None, lines_a, lines_b, autojunk=False)
        left_buf:  List[Tuple[str, str, str]] = []
        right_buf: List[Tuple[str, str, str]] = []
        added = deleted = changed = 0

        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            if op == "equal":
                for li, ri in zip(range(i1, i2), range(j1, j2)):
                    left_buf.append(("same",    str(li + 1), lines_a[li]))
                    right_buf.append(("same",   str(ri + 1), lines_b[ri]))
            elif op == "replace":
                lb, rb = lines_a[i1:i2], lines_b[j1:j2]
                changed += max(len(lb), len(rb))
                for k in range(max(len(lb), len(rb))):
                    left_buf.append(("changed", str(i1+k+1), lb[k]) if k < len(lb) else ("empty", "", ""))
                    right_buf.append(("changed", str(j1+k+1), rb[k]) if k < len(rb) else ("empty", "", ""))
            elif op == "delete":
                deleted += i2 - i1
                for li in range(i1, i2):
                    left_buf.append(("removed", str(li + 1), lines_a[li]))
                    right_buf.append(("empty",  "", ""))
            elif op == "insert":
                added += j2 - j1
                for ri in range(j1, j2):
                    left_buf.append(("empty",  "", ""))
                    right_buf.append(("added",  str(ri + 1), lines_b[ri]))

        self._fill_text(self._txt_a, left_buf)
        self._fill_text(self._txt_b, right_buf)
        self._diff_summary_var.set(
            f"추가: +{added}줄  |  삭제: -{deleted}줄  |  변경: ~{changed}줄"
        )

    def _fill_text(self, txt: tk.Text, content: List[Tuple[str, str, str]]) -> None:
        txt.config(state="normal")
        txt.delete("1.0", "end")
        for tag, linenum, text in content:
            txt.insert("end", f"{linenum:>6} " if linenum else "       ", "linenum")
            line_text = text or "\n"
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

    # ── 경로 표시 ─────────────────────────────────────────────────────────────

    def _short_names(self) -> List[str]:
        depth = max(1, self._depth_var.get())
        return [_path_tail(fp, depth) for fp in self._files]
