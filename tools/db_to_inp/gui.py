"""ANSYS .db -> Abaqus .inp 변환 GUI.

원본은 단독 실행 앱(converter_app.py)이었으며, tool_box 런처가 넘겨주는
parent 프레임 안에 임베드할 수 있도록 ``build_gui(parent)`` 를 추가했다.
"""

import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox
import threading
import os
import shutil

from . import mapdl_ops, cdb_utils, inp_writer, utils


NOTES_TEXT = """\
ANSYS -> Abaqus Converter : 참고 사항 (Notes)
================================================

1. Effective Material (직교이방성 재질)
   - "Orthotropic material present" 체크박스가 켜져 있을 때만 동작합니다.
     꺼져 있으면 모든 재질을 등방성(ISOTROPIC)으로 처리합니다.
   - Material # range(기본값 9990-9999)에 해당하는 재질 번호만 직교이방성
     (ENGINEERING CONSTANTS + ORTHOTROPIC EXPANSION)으로 처리되고, 범위 밖 재질은
     등방성으로 처리됩니다. 해당 번호대의 재질을 ANSYS에 미리 정의해 두어야 합니다.
   - 범위는 Model Configuration에서 "9990-9999"처럼 직접 수정할 수 있습니다.
   - CTE(열팽창계수) 값은 CTEX/CTEY/CTEZ를 먼저 찾고, 없으면 ALPX/ALPY/ALPZ 값을
     사용합니다 (등방성 재질은 X축 값만 사용).

2. 좌표 스케일 (Scale)
   - 노드 좌표는 항상 x1000 배율이 자동 적용됩니다 (예: ANSYS 모델 단위가 m일 때
     Abaqus에서 mm 단위로 쓰기 위함). 코드에 고정되어 있으며 UI에서 바꿀 수 없습니다.
   - 원본 모델 단위가 m가 아니면 결과 좌표가 잘못될 수 있으니 실행 전 반드시 확인하세요.

3. Mesh Type
   - 현재는 8절점 Hex 요소(C3D8I)만 지원합니다.
   - "Free Mesh" 체크박스는 UI에 준비만 되어 있고 실제 변환 로직은 아직 없습니다.
     체크한 채로 Run 하면 실행이 차단됩니다. (추후 업데이트 예정)

4. 대칭 모드 (Symmetry Mode)
   - Quarter (1/4): X=0, Y=0 대칭면 기준 BC를 자동 적용합니다. (기본값, 기존 동작과 동일)
   - Full model (대칭 없음): 전체 모델의 min/max X,Y,Z 좌표를 구해
       * (minX, minY, minZ) 노드  -> 전체 고정 (Ux,Uy,Uz)
       * (maxX, minY, minZ) 노드  -> Uy, Uz 고정
       * (minX, maxY, minZ) 노드  -> Uz 고정
     의 3점 구속으로 강체운동만 제거합니다. 대칭 경계조건은 적용하지 않습니다.
   - Half (1/2): 아직 미구현입니다. 선택 후 Run 하면 실행이 차단됩니다. (추후 업데이트 예정)

5. Tie 처리
   - CE(Constraint Equation) 또는 컴포넌트 이름 패턴(TIE_MASTER/TIE_SLAVE 등)으로
     tie 표면을 자동 탐지합니다.
   - tie 표면을 축정렬 평면(axis-aligned plane) 단위로 분리하는 tolerance는 0.001
     (좌표 스케일 적용 후 기준)로 코드에 고정되어 있습니다.

6. Orientation
   - 직교이방성 재질(999x)에는 로컬 좌표계 (1,0,0,0,1,0)이 모든 재질에 동일하게
     적용됩니다. 실제 방향이 다르면 생성된 INP에서 직접 수정해야 합니다.

7. Submodel 모드
   - exteriorTolerance=0.05로 코드에 고정되어 있습니다.
   - .db 파일명이 "sub"로 끝나면(대소문자 무관, 예: model_sub.db) Sub-model 체크가
     자동으로 켜지고, 그렇지 않으면 자동으로 꺼집니다. File Selection 칸에서 직접
     체크/해제로 덮어쓸 수도 있습니다.

8. MAPDL 실행 옵션
   - 병렬 모드는 SMP(-smp)로 고정되어 있습니다. MPI 등 다른 옵션이 필요하면
     코드 수정이 필요합니다.

9. 초기/최종 온도
   - Settings에서 직접 설정 가능합니다 (기본값: 초기 183.0, 최종 25.0).
"""


class ConverterApp:
    def __init__(self, root):
        # root 는 Tk/Toplevel 이거나, tool_box 런처가 넘겨준 Frame 일 수 있다.
        # 창 속성은 실제 창일 때만 설정한다 (Frame 에는 해당 메서드가 없다).
        self.root = root
        if isinstance(root, (tk.Tk, tk.Toplevel)):
            root.title("ANSYS → Abaqus Converter")
            root.geometry("720x880")
            root.resizable(False, False)

        self.db_path = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.data_dir = tk.StringVar()
        self.node_tol = tk.StringVar(value="1e-6")
        self.init_temp = tk.StringVar(value="183.0")
        self.final_temp = tk.StringVar(value="25.0")
        # UNBLOCKED CDWRITE format expands ETBLOCK into classic ET/KEYOPT
        # cards so older HyperMesh versions can read the .cdb. Default on.
        # NOTE: the built-in CDB parser (Step 2) requires BLOCKED nblock/eblock,
        # so a full Step 2 run forces BLOCKED regardless of this flag.
        self.cdwrite_unblocked = tk.BooleanVar(value=True)
        self.is_submodel = tk.BooleanVar(value=False)
        self.free_mesh = tk.BooleanVar(value=False)
        self.symmetry_options = [
            "Quarter (1/4 symmetry)",
            "Half (1/2 symmetry) - not yet supported",
            "Full model (no symmetry)",
        ]
        self.symmetry_mode = tk.StringVar(value=self.symmetry_options[0])
        self.has_orthotropic = tk.BooleanVar(value=True)
        self.ortho_mat_range = tk.StringVar(value="9990-9999")
        self.mapdl_version = tk.StringVar(value="242")
        self.nproc = tk.StringVar(value="4")
        self.license_type = tk.StringVar(value="preppost")

        self._step1_log_path = None
        self.db_path.trace_add("write", self._on_db_path_change)
        self._build_ui()

    # -----------------------------------------------------------------------
    # UI construction
    # -----------------------------------------------------------------------

    def _build_ui(self):
        frm_file = tk.LabelFrame(self.root, text="File Selection", padx=10, pady=5)
        frm_file.pack(fill="x", padx=10, pady=(10, 5))

        tk.Label(frm_file, text="ANSYS .db:").grid(row=0, column=0, sticky="w")
        tk.Entry(frm_file, textvariable=self.db_path, width=55).grid(row=0, column=1, padx=5)
        tk.Button(frm_file, text="Browse", command=self._browse_db).grid(row=0, column=2)

        tk.Checkbutton(
            frm_file,
            text="Sub-model (.db is a submodel — skips tie processing, uses submodel BCs; "
                 "auto-set when filename ends with 'sub')",
            variable=self.is_submodel,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(3, 0))

        frm_set = tk.LabelFrame(self.root, text="Settings", padx=10, pady=5)
        frm_set.pack(fill="x", padx=10, pady=5)

        tk.Label(frm_set, text="Node Merge Tol:").grid(row=0, column=0, sticky="w")
        tk.Entry(frm_set, textvariable=self.node_tol, width=12).grid(row=0, column=1, sticky="w", padx=5)

        tk.Label(frm_set, text="Initial Temp:").grid(row=0, column=2, sticky="w", padx=(20, 0))
        tk.Entry(frm_set, textvariable=self.init_temp, width=10).grid(row=0, column=3, sticky="w", padx=5)

        tk.Label(frm_set, text="Final Temp:").grid(row=0, column=4, sticky="w", padx=(20, 0))
        tk.Entry(frm_set, textvariable=self.final_temp, width=10).grid(row=0, column=5, sticky="w", padx=5)

        tk.Checkbutton(
            frm_set,
            text="CDWRITE UNBLOCKED (HyperMesh compatible; auto-disabled for full Step 2 run)",
            variable=self.cdwrite_unblocked,
        ).grid(row=1, column=0, columnspan=6, sticky="w", pady=(5, 0))

        frm_model = tk.LabelFrame(self.root, text="Model Configuration", padx=10, pady=5)
        frm_model.pack(fill="x", padx=10, pady=5)

        tk.Checkbutton(
            frm_model,
            text="Free Mesh (tet / mixed elements) — NOT YET SUPPORTED (run disabled if checked)",
            variable=self.free_mesh,
        ).grid(row=0, column=0, columnspan=4, sticky="w")

        tk.Label(frm_model, text="Symmetry Mode:").grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.symmetry_menu = tk.OptionMenu(frm_model, self.symmetry_mode, *self.symmetry_options)
        self.symmetry_menu.config(width=32)
        self.symmetry_menu.grid(row=1, column=1, columnspan=3, sticky="w", padx=5, pady=(5, 0))

        tk.Checkbutton(
            frm_model,
            text="Orthotropic (effective) material present",
            variable=self.has_orthotropic,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 0))
        tk.Label(frm_model, text="Material # range:").grid(row=2, column=2, sticky="w", padx=(10, 0), pady=(5, 0))
        tk.Entry(frm_model, textvariable=self.ortho_mat_range, width=14).grid(
            row=2, column=3, sticky="w", padx=5, pady=(5, 0)
        )

        frm_mapdl = tk.LabelFrame(self.root, text="MAPDL Launch Settings", padx=10, pady=5)
        frm_mapdl.pack(fill="x", padx=10, pady=5)

        tk.Label(frm_mapdl, text="Version:").grid(row=0, column=0, sticky="w")
        tk.Entry(frm_mapdl, textvariable=self.mapdl_version, width=10).grid(row=0, column=1, sticky="w", padx=5)

        tk.Label(frm_mapdl, text="Processors:").grid(row=0, column=2, sticky="w", padx=(15, 0))
        tk.Entry(frm_mapdl, textvariable=self.nproc, width=6).grid(row=0, column=3, sticky="w", padx=5)

        tk.Label(frm_mapdl, text="License Type:").grid(row=1, column=0, sticky="w", pady=(5, 0))
        license_options = ["preppost", "ansys", "mech", "struct", "dyna", "enterprise"]
        tk.OptionMenu(frm_mapdl, self.license_type, *license_options).grid(
            row=1, column=1, sticky="w", padx=5, pady=(5, 0)
        )

        frm_run = tk.Frame(self.root, pady=5)
        frm_run.pack(fill="x", padx=10)

        step_options = ["Step 1 (MAPDL Cleanup + CDWRITE)", "Step 2 (Full - Build INP)"]
        self.run_until = tk.StringVar(value=step_options[-1])
        tk.Label(frm_run, text="Run up to:").pack(side="left", padx=(0, 5))
        self.run_upto_menu = tk.OptionMenu(frm_run, self.run_until, *step_options)
        self.run_upto_menu.config(width=28, height=1)
        self.run_upto_menu.pack(side="left", padx=(0, 15))

        self.btn_run = tk.Button(
            frm_run, text="Run", command=self._run, width=14, height=1,
            bg="#2E8B57", fg="white", activebackground="#3BA66B", activeforeground="white",
        )
        self.btn_show_step1 = tk.Button(
            frm_run, text="Show Step 1 Commands", command=self._show_step1_log, width=22, height=1,
        )
        self.btn_notes = tk.Button(
            frm_run, text="Notes / Help", command=self._show_notes, width=14, height=1,
        )
        self.btn_run.pack(side="right")
        self.btn_show_step1.pack(side="right", padx=(0, 8))
        self.btn_notes.pack(side="right", padx=(0, 8))

        frm_log = tk.LabelFrame(self.root, text="Log", padx=10, pady=5)
        frm_log.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        self.log = scrolledtext.ScrolledText(frm_log, height=15, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True)

    # -----------------------------------------------------------------------
    # UI callbacks
    # -----------------------------------------------------------------------

    def _symmetry_key(self):
        val = self.symmetry_mode.get()
        if val.startswith("Half"):
            return "half"
        if val.startswith("Full"):
            return "full"
        return "quarter"

    def _browse_db(self):
        path = filedialog.askopenfilename(filetypes=[("ANSYS DB", "*.db"), ("All", "*.*")])
        if path:
            self.db_path.set(path)
            self.output_dir.set(os.path.dirname(path))

    def _on_db_path_change(self, *_args):
        """Auto-toggle Sub-model when the .db filename ends with 'sub' (case-insensitive)."""
        stem = os.path.splitext(os.path.basename(self.db_path.get()))[0]
        self.is_submodel.set(stem.lower().endswith("sub"))

    def _parse_ortho_mat_range(self):
        text = self.ortho_mat_range.get().strip()
        parts = [p.strip() for p in text.replace("~", "-").split("-") if p.strip()]
        if len(parts) != 2:
            raise ValueError(f"Material # range must be like '9990-9999'. Got: '{text}'")
        try:
            lo, hi = int(parts[0]), int(parts[1])
        except ValueError:
            raise ValueError(f"Material # range must be like '9990-9999'. Got: '{text}'")
        return (lo, hi) if lo <= hi else (hi, lo)

    def _show_step1_log(self):
        log_path = self._step1_log_path
        if not log_path or not os.path.exists(log_path):
            search_dirs = [self.data_dir.get(), self.output_dir.get()]
            for d in search_dirs:
                if not d:
                    continue
                candidate = os.path.join(d, "step1_apdl.log")
                if os.path.exists(candidate):
                    log_path = candidate
                    break
        if not log_path or not os.path.exists(log_path):
            messagebox.showinfo("Step 1 Commands", "No Step 1 APDL log found yet. Run Step 1 first.")
            return

        win = tk.Toplevel(self.root)
        win.title(f"Step 1 - MAPDL Commands ({os.path.basename(log_path)})")
        win.geometry("800x600")
        txt = scrolledtext.ScrolledText(win, wrap="none")
        txt.pack(fill="both", expand=True, padx=5, pady=5)
        try:
            with open(log_path, "r") as f:
                content = f.read()
            if not content.strip():
                content = "(log file is empty - Step 1 may still be running)"
            txt.insert("1.0", content)
        except Exception as e:
            txt.insert("1.0", f"Error reading log: {e}")
        txt.config(state="disabled")
        tk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 5))

    def _show_notes(self):
        win = tk.Toplevel(self.root)
        win.title("Notes / Help")
        win.geometry("800x600")
        txt = scrolledtext.ScrolledText(win, wrap="word")
        txt.pack(fill="both", expand=True, padx=5, pady=5)
        txt.insert("1.0", NOTES_TEXT)
        txt.config(state="disabled")
        tk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 5))

    def _log(self, msg):
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.config(state="disabled")
        self.root.update_idletasks()

    def _run(self):
        db_path = self.db_path.get()
        if not db_path:
            messagebox.showwarning("Warning", "Select an ANSYS .db file first.")
            return
        if self.free_mesh.get():
            messagebox.showwarning(
                "Not Supported",
                "Free mesh (tet / mixed element) mode is not yet implemented.\n"
                "This feature is planned for a future update. Uncheck it to run with hex mesh.",
            )
            return
        if self._symmetry_key() == "half":
            messagebox.showwarning(
                "Not Supported",
                "Half (1/2) symmetry mode is not yet implemented.\n"
                "This feature is planned for a future update.",
            )
            return
        out_dir = os.path.dirname(os.path.abspath(db_path))
        data_dir = os.path.join(out_dir, "_data")
        os.makedirs(data_dir, exist_ok=True)
        self.output_dir.set(out_dir)
        self.data_dir.set(data_dir)
        self.btn_run.config(state="disabled")
        threading.Thread(target=self._run_pipeline, daemon=True).start()

    # -----------------------------------------------------------------------
    # Pipeline
    # -----------------------------------------------------------------------

    def _run_pipeline(self):
        until = self.run_until.get()
        try:
            self._step1_cleanup()
            if until.startswith("Step 1"):
                self._log("\n=== Stopped after Step 1 ===")
                return
            cdb_path = os.path.join(self.data_dir.get(), "clean_model.cdb")
            self._step2_build_inp(cdb_path)
            self._log("\n=== All steps completed ===")
        except Exception as e:
            self._log(f"\n[ERROR] {e}")
        finally:
            self.btn_run.config(state="normal")

    def _step1_cleanup(self):
        """PyMAPDL: cleanup model and CDWRITE."""
        self._log("=== Step 1: PyMAPDL cleanup + CDWRITE ===")

        from ansys.mapdl.core import launch_mapdl

        out_dir = self.data_dir.get()
        os.makedirs(out_dir, exist_ok=True)

        version_str = self.mapdl_version.get().strip()
        if version_str:
            try:
                version = int(version_str)
            except ValueError:
                raise ValueError(
                    f"MAPDL Version must be an integer (e.g. 192, 211, 242). Got: '{version_str}'"
                )
        else:
            version = 242

        nproc = int(self.nproc.get().strip()) if self.nproc.get().strip() else 4
        license_type = self.license_type.get().strip() or "preppost"

        mapdl = launch_mapdl(
            run_location=out_dir,
            override=True,
            version=version,
            nproc=nproc,
            license_type=license_type,
            additional_switches="-smp",
        )
        self._log(f"MAPDL launched (v{mapdl.version})")

        self._step1_log_path = os.path.join(out_dir, "step1_apdl.log")
        try:
            mapdl.open_apdl_log(self._step1_log_path, mode="w")
            self._log(f"APDL command log: {self._step1_log_path}")
        except Exception as e:
            self._log(f"  (APDL log not started: {e})")

        try:
            db_src = self.db_path.get()
            db_dst = os.path.join(out_dir, os.path.basename(db_src))
            if os.path.normpath(db_src) != os.path.normpath(db_dst):
                shutil.copy2(db_src, db_dst)
                self._log(f"Copied .db to run_location: {db_dst}")
            db_name = os.path.splitext(os.path.basename(db_src))[0]
            mapdl.resume(db_name, "db")
            self._log(f"Resumed: {db_name}")

            mapdl.prep7()

            self._log("Merging duplicate nodes...")
            tol = float(self.node_tol.get())
            mapdl.nummrg("NODE", tol)

            self._log("Processing tie (CE) conditions and loads...")
            mapdl_ops.handle_ties_and_loads(mapdl, self._log, is_submodel=self.is_submodel.get())

            self._log("Removing unused material properties...")
            mapdl_ops.remove_unused_mats(mapdl, self._log)

            mapdl.allsel("ALL")

            db_name = "clean_model"
            self._log(f"Saving cleaned model as {db_name}.db ...")
            mapdl.save(db_name, "db")
            self._log(f"{db_name}.db saved.")

            cdb_name = "clean_model"
            is_full_run = self.run_until.get().startswith("Step 2")
            user_wants_unblocked = bool(self.cdwrite_unblocked.get())
            use_unblocked = user_wants_unblocked and not is_full_run
            if user_wants_unblocked and is_full_run:
                self._log(
                    "  (UNBLOCKED requested, but full Step 2 run requires "
                    "BLOCKED for the CDB parser — overriding.)"
                )
            fmat = "UNBLOCKED" if use_unblocked else ""
            self._log(
                f"Writing {cdb_name}.cdb "
                f"({'UNBLOCKED' if use_unblocked else 'BLOCKED'} format) ..."
            )
            mapdl.cdwrite("DB", cdb_name, "cdb", fmat=fmat)
            self._log("CDWRITE complete.")

            if not use_unblocked:
                cdb_path = os.path.join(out_dir, f"{cdb_name}.cdb")
                expanded = cdb_utils.expand_etblock(cdb_path)
                if expanded:
                    self._log(f"  Expanded ETBLOCK -> {expanded} ET/KEYOPT card(s).")
                rewritten = cdb_utils.rewrite_mp_mpdata_to_classic(cdb_path)
                if rewritten:
                    self._log(
                        f"  Rewrote {rewritten} MP/MPDATA line(s) to "
                        f"classic format (abaqus fromansys compatible)."
                    )

            self._export_step1_metadata(mapdl, out_dir)

        finally:
            try:
                mapdl.exit()
            except Exception:
                try:
                    mapdl.exit(force=True)
                except Exception as e:
                    self._log(f"MAPDL exit warning: {e}")
            self._log("MAPDL closed.")

    def _export_step1_metadata(self, mapdl, out_dir):
        """Save nset/material metadata from MAPDL to text files."""
        nset_path = os.path.join(out_dir, "step1_nsets.txt")
        mplist_path = os.path.join(out_dir, "step1_mplist.txt")

        nset_data = mapdl_ops.collect_nset_data(
            mapdl, self._log,
            is_submodel=self.is_submodel.get(),
            symmetry_mode=self._symmetry_key(),
        )
        with open(nset_path, "w") as f:
            for name, ids in nset_data.items():
                f.write(f"[{name}]\n")
                for i in range(0, len(ids), 16):
                    f.write(", ".join(str(v) for v in ids[i:i + 16]) + "\n")
                f.write("\n")
        self._log(f"Saved nset metadata: {nset_path}")

        mapdl_ops.dump_mapdl_mplist(mapdl, mplist_path)
        self._log(f"Saved material metadata: {mplist_path}")

    def _step2_build_inp(self, cdb_path):
        """CDB 직접 파싱 → Abaqus INP 템플릿 생성."""
        self._log("\n=== Step 2: direct text INP build (no fromansys) ===")

        out_dir = self.output_dir.get()
        data_dir = self.data_dir.get() or out_dir
        db_src = self.db_path.get()
        inp_stem = (
            os.path.splitext(os.path.basename(db_src))[0]
            if db_src else "converted_model"
        )
        inp_path = os.path.join(out_dir, f"{inp_stem}.inp")

        try:
            init_temp = float(self.init_temp.get())
            final_temp = float(self.final_temp.get())
        except ValueError:
            raise ValueError(
                "Initial/Final Temp must be numeric. "
                f"Got init='{self.init_temp.get()}' final='{self.final_temp.get()}'"
            )
        ortho_mat_range = self._parse_ortho_mat_range()

        nodes = cdb_utils.parse_cdb_nodes(cdb_path)
        elems_by_mat = cdb_utils.parse_cdb_elements_by_mat(cdb_path)
        nset_txt = os.path.join(data_dir, "step1_nsets.txt")
        mplist_txt = os.path.join(data_dir, "step1_mplist.txt")
        cdb_nsets = cdb_utils.parse_cdb_nsets(cdb_path)

        if os.path.exists(nset_txt):
            nsets = cdb_utils.read_nsets_txt(nset_txt)
            for k, vals in cdb_nsets.items():
                if not nsets.get(k):
                    nsets[k] = vals
        else:
            nsets = cdb_nsets

        mat_info = (
            cdb_utils.read_materials_from_mplist_txt(mplist_txt)
            if os.path.exists(mplist_txt) else {}
        )
        mat_ids = sorted(mat_info.keys()) if mat_info else sorted(elems_by_mat.keys())

        if not nodes:
            raise RuntimeError("NBLOCK에서 노드를 읽지 못했습니다.")
        if not elems_by_mat:
            raise RuntimeError("EBLOCK에서 요소를 읽지 못했습니다.")

        utils.log_node_coordinate_stats(nodes, "NBLOCK raw", self._log)
        nodes = utils.scale_nodes(nodes, 1000.0)
        utils.log_node_coordinate_stats(nodes, "Scaled x1000", self._log)
        self._log("Applied coordinate scale-up: x1000")

        inp_writer.write_template_inp(
            inp_path, nodes, elems_by_mat, mat_ids, nsets, mat_info, self._log,
            is_submodel=self.is_submodel.get(),
            symmetry_mode=self._symmetry_key(),
            init_temp=init_temp,
            final_temp=final_temp,
            has_orthotropic=self.has_orthotropic.get(),
            ortho_mat_range=ortho_mat_range,
        )
        self._log(f"INP created: {inp_path}")
        self._log(
            "NOTE: 재료 상세(온도의존/ENG CONSTANTS/CTE)는 템플릿 자리만 생성됩니다. "
            "실제 값은 INP에서 채워주세요."
        )


def build_gui(parent):
    """tool_box 런처가 넘겨준 parent 프레임 안에 GUI 를 구성한다."""
    return ConverterApp(parent)


def main():
    """단독 실행용 (python -m tools.db_to_inp.gui)."""
    root = tk.Tk()
    ConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
