from .utils import fmt_num, prop_rows, value_for_temp, temps_from_rows


def _cte_rows(props, axis):
    """CTE property rows for one axis: prefer CTEx/y/z, fall back to ALPx/y/z."""
    rows = prop_rows(props, f"cte{axis}")
    if rows:
        return rows
    return prop_rows(props, f"alp{axis}")


# Abaqus C3D8 local face → local node indices (0-based).
_C3D8_FACES = (
    (1, (0, 1, 2, 3)),  # S1: 1-2-3-4  (bottom)
    (2, (4, 5, 6, 7)),  # S2: 5-6-7-8  (top)
    (3, (0, 1, 5, 4)),  # S3: 1-2-6-5
    (4, (1, 2, 6, 5)),  # S4: 2-3-7-6
    (5, (2, 3, 7, 6)),  # S5: 3-4-8-7
    (6, (3, 0, 4, 7)),  # S6: 4-1-5-8
)


def _hex_faces(conn):
    """Return [(face_id_1to6, (n1,n2,n3,n4)), ...] for a C3D8 connectivity."""
    return [(fid, tuple(conn[i] for i in idx)) for fid, idx in _C3D8_FACES]


def _axis_aligned_plane(face_coords, tol):
    """Return (axis, offset) if the 4 face nodes lie on an axis-aligned plane."""
    xs = [p[0] for p in face_coords]
    ys = [p[1] for p in face_coords]
    zs = [p[2] for p in face_coords]
    if max(xs) - min(xs) <= tol:
        return ("x", sum(xs) / len(xs))
    if max(ys) - min(ys) <= tol:
        return ("y", sum(ys) / len(ys))
    if max(zs) - min(zs) <= tol:
        return ("z", sum(zs) / len(zs))
    return None


def split_tie_surface_planes(elems_all, nodes, tie_eids, tie_surface_nodes, tol_dist, log_fn=None):
    """Split tie volume elements by axis-aligned surface planes.

    Parameters
    ----------
    elems_all : dict[int, list[int]]
        {eid: [n1..n8]} full element connectivity.
    nodes : dict[int, tuple[float,float,float]]
        Node coordinates (after scale).
    tie_eids : iterable[int]
        Tie-side volume element IDs.
    tie_surface_nodes : iterable[int] | None
        Exact surface node IDs from CE data; if empty, boundary faces are
        detected geometrically.
    tol_dist : float
        Axis-alignment and offset-grouping tolerance.

    Returns
    -------
    list[dict]  [{"axis": str, "offset": float, "faces": [(eid, face_id), ...]}, ...]
    """
    tie_eid_set = {int(e) for e in tie_eids or []}
    surface_node_set = {int(n) for n in tie_surface_nodes or []}

    candidate_faces = []
    if surface_node_set:
        for eid in tie_eid_set:
            conn = elems_all.get(eid)
            if not conn or len(conn) < 8:
                continue
            for fid, fnodes in _hex_faces(conn):
                if all(n in surface_node_set for n in fnodes):
                    candidate_faces.append((eid, fid, fnodes))
    else:
        counter = {}
        bucket = {}
        for eid in tie_eid_set:
            conn = elems_all.get(eid)
            if not conn or len(conn) < 8:
                continue
            for fid, fnodes in _hex_faces(conn):
                key = frozenset(fnodes)
                counter[key] = counter.get(key, 0) + 1
                bucket.setdefault(key, []).append((eid, fid, fnodes))
        for key, cnt in counter.items():
            if cnt == 1:
                candidate_faces.extend(bucket[key])

    typed = []
    skipped_non_axis = 0
    for eid, fid, fnodes in candidate_faces:
        coords = [nodes.get(int(n)) for n in fnodes]
        if any(c is None for c in coords):
            continue
        plane = _axis_aligned_plane(coords, tol_dist)
        if plane is None:
            skipped_non_axis += 1
            continue
        axis, offset = plane
        typed.append((axis, offset, eid, fid))
    if skipped_non_axis and log_fn:
        log_fn(f"  plane split: skipped {skipped_non_axis} non-axis-aligned face(s)")

    groups = []
    for axis in ("x", "y", "z"):
        subset = sorted([t for t in typed if t[0] == axis], key=lambda t: t[1])
        i = 0
        while i < len(subset):
            members = [(subset[i][2], subset[i][3])]
            offsets = [subset[i][1]]
            j = i + 1
            while j < len(subset) and subset[j][1] - offsets[-1] <= tol_dist:
                members.append((subset[j][2], subset[j][3]))
                offsets.append(subset[j][1])
                j += 1
            groups.append({
                "axis": axis,
                "offset": sum(offsets) / len(offsets),
                "faces": members,
            })
            i = j

    groups.sort(key=lambda g: (g["axis"], g["offset"]))
    return groups


def _write_tie_plane_section(f, side, tie_eids, plane_groups):
    """Write ELSET/SURFACE blocks for one tie side (master or slave)."""
    tie_eids = sorted(set(int(e) for e in tie_eids or []))
    prefix = f"{side}_tie"

    f.write(f"*ELSET, ELSET={prefix}\n")
    if tie_eids:
        for k in range(0, len(tie_eids), 16):
            f.write(", ".join(str(v) for v in tie_eids[k:k + 16]) + "\n")
    else:
        f.write("** TODO: fill element IDs\n")

    if not plane_groups:
        if tie_eids:
            f.write(f"*SURFACE, NAME={prefix}, TYPE=ELEMENT\n")
            f.write(f"{prefix}, S1\n")
            f.write(f"** WARNING: {prefix} plane split failed, using single face S1 fallback\n")
        else:
            f.write(f"** NOTE: {prefix} surface skipped (empty element set)\n")
        return

    union_face_entries = []
    for idx, grp in enumerate(plane_groups, start=1):
        by_fid = {}
        for eid, fid in grp["faces"]:
            by_fid.setdefault(fid, set()).add(int(eid))
        for fid in sorted(by_fid.keys()):
            eids = sorted(by_fid[fid])
            elset_name = f"{prefix}_p{idx}_S{fid}"
            f.write(f"*ELSET, ELSET={elset_name}\n")
            for k in range(0, len(eids), 16):
                f.write(", ".join(str(v) for v in eids[k:k + 16]) + "\n")
            union_face_entries.append((elset_name, fid))

        surf_name = f"{prefix}_p{idx}"
        f.write(f"*SURFACE, NAME={surf_name}, TYPE=ELEMENT\n")
        for fid in sorted(by_fid.keys()):
            f.write(f"{prefix}_p{idx}_S{fid}, S{fid}\n")
        f.write(
            f"** tie plane {idx}: axis={grp['axis']} "
            f"offset={grp['offset']:.6g} faces={len(grp['faces'])}\n"
        )

    f.write(f"*SURFACE, NAME={prefix}, TYPE=ELEMENT\n")
    for elset_name, fid in union_face_entries:
        f.write(f"{elset_name}, S{fid}\n")


def _write_material_isotropic(f, props):
    ex_rows = prop_rows(props, "ex")
    nu_rows = prop_rows(props, "nuxy")
    alpha_rows = _cte_rows(props, "x")

    elastic_temps = temps_from_rows(ex_rows + nu_rows)
    f.write("*ELASTIC\n")
    if elastic_temps:
        for t in elastic_temps:
            ex = value_for_temp(ex_rows, t)
            nu = value_for_temp(nu_rows, t)
            if ex is not None and nu is not None:
                f.write(f"{fmt_num(ex)}, {fmt_num(nu)}, {fmt_num(t)}\n")
    else:
        ex = value_for_temp(ex_rows, 0.0)
        nu = value_for_temp(nu_rows, 0.0)
        if ex is None or nu is None:
            f.write("** TODO: fill E, nu\n")
        else:
            f.write(f"{fmt_num(ex)}, {fmt_num(nu)}\n")

    exp_temps = temps_from_rows(alpha_rows)
    f.write("*EXPANSION\n")
    if exp_temps:
        for t in exp_temps:
            a = value_for_temp(alpha_rows, t)
            if a is not None:
                f.write(f"{fmt_num(a)}, {fmt_num(t)}\n")
    else:
        a = value_for_temp(alpha_rows, 0.0)
        if a is None:
            f.write("** TODO: fill CTE\n")
        else:
            f.write(f"{fmt_num(a)}\n")


def _write_material_orthotropic(f, props):
    keys_main = ["ex", "ey", "ez", "nuxy", "nuxz", "nuyz", "gxy", "gxz", "gyz"]
    rows_all = []
    for k in keys_main:
        rows_all.extend(prop_rows(props, k))
    temps = temps_from_rows(rows_all)

    f.write("*ELASTIC, TYPE=ENGINEERING CONSTANTS\n")
    if temps:
        for t in temps:
            vals = [value_for_temp(prop_rows(props, k), t) for k in keys_main]
            if any(v is None for v in vals):
                continue
            f.write(", ".join(fmt_num(v) for v in vals[:8]) + "\n")
            f.write(f"{fmt_num(vals[8])}, {fmt_num(t)}\n")
    else:
        vals = [value_for_temp(prop_rows(props, k), 0.0) for k in keys_main]
        if any(v is None for v in vals):
            f.write("** TODO: fill engineering constants\n")
        else:
            f.write(", ".join(fmt_num(v) for v in vals[:8]) + "\n")
            f.write(f"{fmt_num(vals[8])}\n")

    ctex_rows = _cte_rows(props, "x")
    ctey_rows = _cte_rows(props, "y")
    ctez_rows = _cte_rows(props, "z")
    cte_temps = temps_from_rows(ctex_rows + ctey_rows + ctez_rows)

    f.write("*EXPANSION, TYPE=ORTHOTROPIC\n")
    if cte_temps:
        for t in cte_temps:
            vx = value_for_temp(ctex_rows, t)
            vy = value_for_temp(ctey_rows, t)
            vz = value_for_temp(ctez_rows, t)
            if vx is None or vy is None or vz is None:
                continue
            f.write(f"{fmt_num(vx)}, {fmt_num(vy)}, {fmt_num(vz)}, {fmt_num(t)}\n")
    else:
        vx = value_for_temp(ctex_rows, 0.0)
        vy = value_for_temp(ctey_rows, 0.0)
        vz = value_for_temp(ctez_rows, 0.0)
        if vx is None or vy is None or vz is None:
            f.write("** TODO: fill orthotropic CTE\n")
        else:
            f.write(f"{fmt_num(vx)}, {fmt_num(vy)}, {fmt_num(vz)}\n")


def _is_orthotropic_mat(mid, has_orthotropic, ortho_mat_range):
    if not has_orthotropic:
        return False
    lo, hi = ortho_mat_range
    return lo <= mid <= hi


def write_template_inp(inp_path, nodes, elems_by_mat, mat_ids, nsets, mat_info, log_fn=None,
                       is_submodel=False, symmetry_mode="quarter",
                       init_temp=183.0, final_temp=25.0,
                       has_orthotropic=True, ortho_mat_range=(9990, 9999)):
    """Write the Abaqus INP template file.

    ``symmetry_mode`` ("quarter" or "full") selects the NSET/BOUNDARY scheme
    used for a non-submodel run; see ``_write_nsets_full``/``_write_step_full``
    for the full-model 3-point fixation scheme. "half" is not implemented and
    must be filtered out by the caller before reaching this function.

    ``has_orthotropic``/``ortho_mat_range`` select which material IDs (if
    any) are treated as orthotropic effective materials; all others are
    written as isotropic.
    """
    with open(inp_path, "w") as f:
        f.write("*NODE\n")
        for nid in sorted(nodes):
            x, y, z = nodes[nid]
            f.write(f"{nid}, {x:.12g}, {y:.12g}, {z:.12g}\n")

        for mid in mat_ids:
            es = f"eset{mid}"
            f.write(f"*ELEMENT,TYPE=C3D8I,ELSET={es}\n")
            for eid, conn in sorted(elems_by_mat.get(mid, []), key=lambda x: x[0]):
                f.write(f"{eid}, " + ", ".join(str(n) for n in conn) + "\n")

        eff_mats = []
        for mid in mat_ids:
            es = f"eset{mid}"
            mat = mat_info.get(mid, {}).get("name", f"mat{mid}")
            if _is_orthotropic_mat(mid, has_orthotropic, ortho_mat_range):
                eff_mats.append((es, mat))
            else:
                f.write(f"*SOLID SECTION, ELSET={es}, MATERIAL={mat}\n")

        if eff_mats:
            f.write("*Orientation, name=Ori-1\n")
            f.write("1,0,0,0,1,0\n")
            f.write("1,0\n")
            for es, mat in eff_mats:
                f.write(f"*SOLID SECTION, ELSET={es}, orientation=Ori-1, MATERIAL={mat}\n")

        if is_submodel:
            _write_nsets_submodel(f, nsets)
        else:
            if symmetry_mode == "full":
                _write_nsets_full(f, nsets)
            else:
                _write_nsets_quarter(f, nsets)
            _write_tie_sections(f, nsets, nodes, elems_by_mat, log_fn)

        for mid in mat_ids:
            mat = mat_info.get(mid, {}).get("name", f"mat{mid}")
            f.write(f"*MATERIAL, NAME={mat}\n")
            props = mat_info.get(mid, {}).get("props", {})
            if _is_orthotropic_mat(mid, has_orthotropic, ortho_mat_range):
                _write_material_orthotropic(f, props)
            else:
                _write_material_isotropic(f, props)

        if is_submodel:
            _write_step_submodel(f, init_temp, final_temp)
        else:
            if symmetry_mode == "full":
                _write_step_full(f, init_temp, final_temp)
            else:
                _write_step_quarter(f, init_temp, final_temp)


def _write_nsets_quarter(f, nsets):
    """Write the four symmetry NSETs for a quarter-symmetry (non-submodel) model."""
    for ns in ["nset_temperature", "nset_bc_y", "nset_bc_x", "nset_bc_all"]:
        f.write(f"*NSET, NSET={ns}\n")
        ids = nsets.get(ns, [])
        for k in range(0, len(ids), 16):
            f.write(", ".join(str(v) for v in ids[k:k + 16]) + "\n")
        if not ids:
            f.write("** TODO: fill node IDs\n")


def _write_nsets_full(f, nsets):
    """Write NSETs for a full (non-symmetric) model: temperature + the
    3-point rigid-body-motion fixation nsets (see _write_step_full)."""
    for ns in ["nset_temperature", "nset_bc_fixall", "nset_bc_fixyz", "nset_bc_fixz"]:
        f.write(f"*NSET, NSET={ns}\n")
        ids = nsets.get(ns, [])
        for k in range(0, len(ids), 16):
            f.write(", ".join(str(v) for v in ids[k:k + 16]) + "\n")
        if not ids:
            f.write("** TODO: fill node IDs\n")


def _write_nsets_submodel(f, nsets):
    """Write NSETs for a submodel: temperature + outermost-plane BC nset."""
    for ns in ["nset_temperature", "nset_bc_sub"]:
        f.write(f"*NSET, NSET={ns.upper()}\n")
        ids = nsets.get(ns, [])
        for k in range(0, len(ids), 16):
            f.write(", ".join(str(v) for v in ids[k:k + 16]) + "\n")
        if not ids:
            f.write("** TODO: fill node IDs\n")
    f.write("**HM_UNSUPPORTED_CARDS_MIDDLE\n")
    f.write("*Submodel, type=NODE, exteriorTolerance=0.05\n")
    f.write("NSET_BC_Sub,\n")


def _write_tie_sections(f, nsets, nodes, elems_by_mat, log_fn):
    """Write ELSET/SURFACE tie sections for a regular model."""
    master_eids = nsets.get("master_tie", []) or nsets.get("tie_master", [])
    slave_eids = nsets.get("slave_tie", []) or nsets.get("tie_slave", [])
    master_surf_nodes = nsets.get("master_tie_nodes", []) or nsets.get("tie_master_nodes", [])
    slave_surf_nodes = nsets.get("slave_tie_nodes", []) or nsets.get("tie_slave_nodes", [])

    elems_all = {}
    for _mid, _lst in elems_by_mat.items():
        for _eid, _conn in _lst:
            elems_all[int(_eid)] = _conn

    tie_tol = 0.001
    master_planes = split_tie_surface_planes(
        elems_all, nodes, master_eids, master_surf_nodes, tol_dist=tie_tol, log_fn=log_fn
    )
    slave_planes = split_tie_surface_planes(
        elems_all, nodes, slave_eids, slave_surf_nodes, tol_dist=tie_tol, log_fn=log_fn
    )
    if log_fn:
        log_fn(
            f"  tie plane split: master={len(master_planes)} "
            f"slave={len(slave_planes)} (tol_dist={tie_tol})"
        )
        for idx, grp in enumerate(master_planes, start=1):
            log_fn(
                f"    master_tie_p{idx}: axis={grp['axis']} "
                f"offset={grp['offset']:.6g} faces={len(grp['faces'])}"
            )
        for idx, grp in enumerate(slave_planes, start=1):
            log_fn(
                f"    slave_tie_p{idx}: axis={grp['axis']} "
                f"offset={grp['offset']:.6g} faces={len(grp['faces'])}"
            )

    _write_tie_plane_section(f, "master", master_eids, master_planes)
    _write_tie_plane_section(f, "slave", slave_eids, slave_planes)


def _write_step_quarter(f, init_temp, final_temp):
    """Write the STEP block for a quarter-symmetry model."""
    f.write("*TIE, NAME=tie-1\n")
    f.write("slave_tie, master_tie\n")
    f.write("*INITIAL CONDITIONS, TYPE=TEMPERATURE\n")
    f.write(f"NSET_TEMPERATURE,{fmt_num(init_temp)}\n")
    f.write("*STEP, INC=10000, NAME=step, NLGEOM=NO\n")
    f.write("*STATIC\n")
    f.write("1.0, 1.0, 1.0e-15, 1.0\n")
    f.write("*TEMPERATURE, OP=NEW\n")
    f.write(f"NSET_TEMPERATURE, {fmt_num(final_temp)}\n")
    f.write("*BOUNDARY\n")
    f.write("NSET_BC_Y,YSYMM\n")
    f.write("NSET_BC_X,XSYMM\n")
    f.write("NSET_BC_ALL,3,,0\n")
    f.write("*END STEP\n")


def _write_step_full(f, init_temp, final_temp):
    """Write the STEP block for a full (non-symmetric) model.

    Rigid-body motion is removed with a 3-point kinematic constraint instead
    of symmetry planes: the (minX,minY,minZ) node is fully fixed, the
    (maxX,minY,minZ) node is fixed in Uy/Uz, and the (minX,maxY,minZ) node
    is fixed in Uz.
    """
    f.write("*TIE, NAME=tie-1\n")
    f.write("slave_tie, master_tie\n")
    f.write("*INITIAL CONDITIONS, TYPE=TEMPERATURE\n")
    f.write(f"NSET_TEMPERATURE,{fmt_num(init_temp)}\n")
    f.write("*STEP, INC=10000, NAME=step, NLGEOM=NO\n")
    f.write("*STATIC\n")
    f.write("1.0, 1.0, 1.0e-15, 1.0\n")
    f.write("*TEMPERATURE, OP=NEW\n")
    f.write(f"NSET_TEMPERATURE, {fmt_num(final_temp)}\n")
    f.write("*BOUNDARY\n")
    f.write("NSET_BC_FIXALL,1,3\n")
    f.write("NSET_BC_FIXYZ,2,3\n")
    f.write("NSET_BC_FIXZ,3,3\n")
    f.write("*END STEP\n")


def _write_step_submodel(f, init_temp, final_temp):
    """Write the STEP block for a submodel."""
    f.write("*INITIAL CONDITIONS, TYPE=TEMPERATURE\n")
    f.write(f"NSET_TEMPERATURE,{fmt_num(init_temp)}\n")
    f.write("*STEP, INC=10000, NAME=step, NLGEOM=NO\n")
    f.write("*STATIC\n")
    f.write("1.0, 1.0, 1.0e-15, 1.0\n")
    f.write("*TEMPERATURE, OP=NEW\n")
    f.write(f"NSET_TEMPERATURE, {fmt_num(final_temp)}\n")
    f.write("*boundary, submodel, step=1\n")
    f.write("NSET_BC_Sub,1,1\n")
    f.write("NSET_BC_Sub,2,2\n")
    f.write("NSET_BC_Sub,3,3\n")
    f.write("*END STEP\n")
