import os
import re
import shutil


# ---------------------------------------------------------------------------
# Component listing / querying
# ---------------------------------------------------------------------------

def list_all_components(mapdl):
    """Return every currently defined component name.

    Runs two CMLIST passes (full + TIE-explicit) and merges the PyMAPDL
    component manager to work around cases where TIE components are omitted
    from the generic CMLIST output.
    """
    names = []
    seen = set()

    def _add(name):
        up = name.upper()
        if up in seen:
            return
        seen.add(up)
        names.append(name)

    macro_path = os.path.join(mapdl.directory, "_dump_cmlist.mac")
    try:
        with open(macro_path, "w") as f:
            f.write("ALLSEL,ALL\n")
            f.write("CMSEL,ALL\n")
            f.write("/OUTPUT,_cmlist_all,txt\n")
            f.write("CMLIST\n")
            f.write("/OUTPUT\n")
            f.write("/NERR,0,99999999\n")
            f.write("CMSEL,S,TIE_MASTER\n")
            f.write("CMSEL,A,TIE_SLAVE\n")
            f.write("CMSEL,A,TIE_MASTER_NODES\n")
            f.write("CMSEL,A,TIE_SLAVE_NODES\n")
            f.write("/NERR,5,99999999\n")
            f.write("/OUTPUT,_cmlist_tie,txt\n")
            f.write("CMLIST\n")
            f.write("/OUTPUT\n")
            f.write("CMSEL,ALL\n")
            f.write("ALLSEL,ALL\n")
        mapdl.input(macro_path)
    except Exception:
        pass

    valid_types = {"NODE", "ELEM", "ELEMENT", "KP", "LINE", "AREA", "VOLU"}
    for fn in ("_cmlist_all.txt", "_cmlist_tie.txt"):
        path = os.path.join(mapdl.directory, fn)
        try:
            with open(path, "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", parts[0]):
                        if parts[1].upper() in valid_types:
                            _add(parts[0])
        except FileNotFoundError:
            continue

    try:
        comp = getattr(mapdl, "components", None)
        if comp is not None:
            for n in list(comp.names):
                _add(n)
    except Exception:
        pass

    return names


def get_component_type(mapdl, target_name):
    """Return component entity type from CMLIST output (NODE/ELEM/...).

    Runs two CMLIST passes to avoid missing TIE components in the standard output.
    """
    macro_path = os.path.join(mapdl.directory, "_dump_cmlist_type.mac")
    try:
        with open(macro_path, "w") as f:
            f.write("ALLSEL,ALL\n")
            f.write("CMSEL,ALL\n")
            f.write("/OUTPUT,_cmlist_type_all,txt\n")
            f.write("CMLIST\n")
            f.write("/OUTPUT\n")
            f.write("/NERR,0,99999999\n")
            f.write("CMSEL,S,TIE_MASTER\n")
            f.write("CMSEL,A,TIE_SLAVE\n")
            f.write("CMSEL,A,TIE_MASTER_NODES\n")
            f.write("CMSEL,A,TIE_SLAVE_NODES\n")
            f.write("/NERR,5,99999999\n")
            f.write("/OUTPUT,_cmlist_type_tie,txt\n")
            f.write("CMLIST\n")
            f.write("/OUTPUT\n")
            f.write("CMSEL,ALL\n")
            f.write("ALLSEL,ALL\n")
        mapdl.input(macro_path)
    except Exception:
        return None

    target_upper = target_name.upper()
    for fn in ("_cmlist_type_tie.txt", "_cmlist_type_all.txt"):
        path = os.path.join(mapdl.directory, fn)
        try:
            with open(path, "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and parts[0].upper() == target_upper:
                        return parts[1].upper()
        except FileNotFoundError:
            continue
    return None


def get_selected_element_ids_from_elist(mapdl):
    """Parse selected element IDs from ELIST text output."""
    try:
        txt = mapdl.elist()
    except Exception:
        return []
    if not txt:
        return []

    ids = set()
    for line in str(txt).splitlines():
        m = re.match(r"^\s*(\d+)\b", line)
        if not m:
            continue
        try:
            ids.add(int(m.group(1)))
        except ValueError:
            pass
    return sorted(ids)


def get_component_element_ids(mapdl, candidates):
    """Select a named component and return its element IDs."""
    existing = {name.upper(): name for name in list_all_components(mapdl)}
    target = None
    for c in candidates:
        if c.upper() in existing:
            target = existing[c.upper()]
            break
    if not target:
        return []

    try:
        ctype = get_component_type(mapdl, target)
        mapdl.allsel("ALL")

        if ctype in {"ELEM", "ELEMENT"}:
            mapdl.cmsel("S", target, "ELEM")
            return sorted(set(get_selected_element_ids_from_elist(mapdl)))

        if ctype == "NODE":
            mapdl.cmsel("S", target, "NODE")
            try:
                mapdl.esln("S")
            except Exception:
                pass
            return sorted(set(get_selected_element_ids_from_elist(mapdl)))

        # Unknown type fallback
        mapdl.cmsel("S", target, "NODE")
        try:
            mapdl.esln("S")
        except Exception:
            pass
        eids = get_selected_element_ids_from_elist(mapdl)
        if eids:
            return sorted(set(eids))

        mapdl.allsel("ALL")
        mapdl.cmsel("S", target, "ELEM")
        eids = get_selected_element_ids_from_elist(mapdl)
        if eids:
            return sorted(set(eids))

        mapdl.allsel("ALL")
        mapdl.cmsel("S", target)
        return sorted(set(get_selected_element_ids_from_elist(mapdl)))
    except Exception:
        return []
    finally:
        try:
            mapdl.allsel("ALL")
        except Exception:
            pass


def get_component_element_ids_by_keywords(mapdl, include):
    """Find a component by name keywords and return its element IDs.

    Example: include=("SLAVE", "TIE") matches TIE_SLAVE, SLAVE_TIE, etc.
    """
    names = list_all_components(mapdl)
    if not names:
        return []
    keys = tuple(k.upper() for k in include)
    for name in names:
        if all(k in name.upper() for k in keys):
            ids = get_component_element_ids(mapdl, [name])
            if ids:
                return ids
    return []


def get_component_node_ids(mapdl, candidates):
    """Select a named component and return its node IDs."""
    existing = {name.upper(): name for name in list_all_components(mapdl)}
    target = None
    for c in candidates:
        if c.upper() in existing:
            target = existing[c.upper()]
            break
    if not target:
        return []
    try:
        mapdl.allsel("ALL")
        mapdl.cmsel("S", target, "NODE")
        ids = [int(v) for v in mapdl.mesh.nnum.tolist()]
        if ids:
            return sorted(set(ids))
        mapdl.allsel("ALL")
        mapdl.cmsel("S", target)
        try:
            mapdl.nsle("S")
        except Exception:
            pass
        ids = [int(v) for v in mapdl.mesh.nnum.tolist()]
        return sorted(set(ids))
    except Exception:
        return []
    finally:
        try:
            mapdl.allsel("ALL")
        except Exception:
            pass


def get_component_node_ids_by_keywords(mapdl, include):
    """Find a component by name keywords and return its node IDs."""
    names = list_all_components(mapdl)
    if not names:
        return []
    keys = tuple(k.upper() for k in include)
    for name in names:
        if all(k in name.upper() for k in keys):
            ids = get_component_node_ids(mapdl, [name])
            if ids:
                return ids
    return []


# ---------------------------------------------------------------------------
# Component creation
# ---------------------------------------------------------------------------

def create_cm_from_node_list(mapdl, cm_name, nodes, as_elements=False, log_fn=None):
    """Select node numbers and save component as NODE or ELEM via macro."""
    if not nodes:
        return False
    macro_path = os.path.join(mapdl.directory, f"_mkcm_{cm_name}.mac")
    try:
        with open(macro_path, "w") as f:
            f.write("ALLSEL,ALL\n")
            f.write("NSEL,NONE\n")
            for node in sorted(nodes):
                f.write(f"NSEL,A,NODE,,{node}\n")
            if as_elements:
                f.write("ESLN,S\n")
                f.write(f"CM,{cm_name},ELEM\n")
            else:
                f.write(f"CM,{cm_name},NODE\n")
            f.write("ALLSEL,ALL\n")
        mapdl.input(macro_path)
        return True
    except Exception as e:
        if log_fn:
            log_fn(f"  Warning: failed to create {cm_name}: {e}")
        return False


def create_cm_from_element_list(mapdl, cm_name, elems, log_fn=None):
    """Select element numbers and save component as ELEM via macro."""
    if not elems:
        return False
    macro_path = os.path.join(mapdl.directory, f"_mkcm_elem_{cm_name}.mac")
    try:
        with open(macro_path, "w") as f:
            f.write("ALLSEL,ALL\n")
            f.write("ESEL,NONE\n")
            for eid in sorted(elems):
                f.write(f"ESEL,A,ELEM,,{eid}\n")
            f.write(f"CM,{cm_name},ELEM\n")
            f.write("ALLSEL,ALL\n")
        mapdl.input(macro_path)
        return True
    except Exception as e:
        if log_fn:
            log_fn(f"  Warning: failed to create {cm_name} from elements: {e}")
        return False


# ---------------------------------------------------------------------------
# CE / constraint equation parsing
# ---------------------------------------------------------------------------

def parse_celist(mapdl):
    """Dump CELIST to a text file and parse it.

    Returns a list of (dep_node, set_of_indep_nodes). The first node in each
    CE block is the dependent (slave); subsequent nodes are the master set.
    """
    macro_path = os.path.join(mapdl.directory, "_dump_celist.mac")
    try:
        with open(macro_path, "w") as f:
            f.write("/OUTPUT,_celist,txt\n")
            f.write("CELIST,ALL,,,ANY\n")
            f.write("/OUTPUT\n")
        mapdl.input(macro_path)
    except Exception:
        try:
            with open(macro_path, "w") as f:
                f.write("/OUTPUT,_celist,txt\n")
                f.write("CELIST\n")
                f.write("/OUTPUT\n")
            mapdl.input(macro_path)
        except Exception:
            return []

    celist_path = os.path.join(mapdl.directory, "_celist.txt")
    equations = []
    current_dep = None
    current_indep = set()
    in_eq = False

    node_patterns = [
        re.compile(r"NODE\s*=\s*(\d+)", re.IGNORECASE),
        re.compile(r"^\s*(\d+)\s+(UX|UY|UZ|ROTX|ROTY|ROTZ|TEMP)\s+[-+0-9.Ee]+", re.IGNORECASE),
    ]
    header_pat = re.compile(r"CONSTRAINT\s+EQUATION", re.IGNORECASE)

    try:
        with open(celist_path, "r") as f:
            for line in f:
                if header_pat.search(line):
                    if current_dep is not None or current_indep:
                        equations.append((current_dep, current_indep))
                    current_dep = None
                    current_indep = set()
                    in_eq = True
                    continue
                if not in_eq:
                    continue
                node_val = None
                for pat in node_patterns:
                    m = pat.search(line)
                    if m:
                        try:
                            node_val = int(m.group(1))
                        except ValueError:
                            node_val = None
                        break
                if node_val is None:
                    continue
                if current_dep is None:
                    current_dep = node_val
                else:
                    current_indep.add(node_val)
        if current_dep is not None or current_indep:
            equations.append((current_dep, current_indep))
    except FileNotFoundError:
        return []

    return equations


# ---------------------------------------------------------------------------
# Parameter / array cleanup
# ---------------------------------------------------------------------------

def delete_array_params(mapdl):
    """Delete every ARRAY or TABLE parameter defined via *DIM."""
    macro_path = os.path.join(mapdl.directory, "_dump_params.mac")
    try:
        with open(macro_path, "w") as f:
            f.write("/OUTPUT,_params,txt\n")
            f.write("*STATUS,_PRM\n")
            f.write("/OUTPUT\n")
        mapdl.input(macro_path)
    except Exception:
        return 0

    params_path = os.path.join(mapdl.directory, "_params.txt")
    target_names = []
    ident_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    target_types = {"ARRAY", "TABLE"}
    try:
        with open(params_path, "r") as f:
            for line in f:
                parts = line.split()
                if not parts:
                    continue
                name = parts[0]
                if not ident_re.match(name):
                    continue
                if name.startswith("_"):
                    continue
                if any(p.upper() in target_types for p in parts[1:]):
                    target_names.append(name)
    except FileNotFoundError:
        return 0

    deleted = 0
    for name in target_names:
        try:
            mapdl.run(f"*DEL,{name},,NOPR")
            deleted += 1
        except Exception:
            pass
    return deleted


# ---------------------------------------------------------------------------
# High-level MAPDL operations
# ---------------------------------------------------------------------------

def handle_ties_and_loads(mapdl, log_fn, is_submodel=False):
    """Detect tie conditions (CE/CEINTF), create TIE_SLAVE/TIE_MASTER
    components, then delete all other components, CEs, loads, and coupled sets.

    When ``is_submodel=True`` the tie detection/creation steps are skipped
    entirely; all existing components are deleted and only loads/CEs/CPs
    and array params are cleaned up.
    """
    mapdl.allsel("ALL")

    load_cmds = [
        ("fdele", ("ALL", "ALL")),
        ("ddele", ("ALL", "ALL")),
        ("sfedele", ("ALL", "ALL", "ALL")),
        ("sfdele", ("ALL", "ALL")),
        ("bfdele", ("ALL", "ALL")),
        ("bfedele", ("ALL", "ALL", "ALL")),
        ("cedele", ("ALL",)),
        ("cpdele", ("ALL",)),
    ]

    if is_submodel:
        log_fn("  Submodel mode: skipping tie detection.")
        existing_cms = list_all_components(mapdl)
        deleted_cm = 0
        for name in existing_cms:
            try:
                mapdl.cmdele(name)
                deleted_cm += 1
            except Exception:
                pass
        log_fn(f"  Removed {deleted_cm} component name(s).")
        for cmd_name, args in load_cmds:
            try:
                getattr(mapdl, cmd_name)(*args)
            except Exception:
                pass
        log_fn("  Deleted all loads / constraint equations / coupled sets.")
        n_arrays = delete_array_params(mapdl)
        log_fn(f"  Deleted {n_arrays} array/table parameter(s).")
        return

    try:
        ce_count = int(mapdl.get("NCE", "CE", 0, "NUM", "COUNT"))
    except Exception:
        ce_count = 0
    log_fn(f"  Found {ce_count} constraint equation(s).")

    slave_nodes = set()
    master_nodes = set()

    if ce_count > 0:
        equations = parse_celist(mapdl)
        log_fn(f"  Parsed {len(equations)} CE block(s) from CELIST.")
        for dep, indeps in equations:
            if dep is not None:
                slave_nodes.add(dep)
            master_nodes.update(indeps)
        master_nodes -= slave_nodes

    if not slave_nodes or not master_nodes:
        existing = [n.upper() for n in list_all_components(mapdl)]
        if not slave_nodes and any(
            name in existing for name in ("TIE_SLAVE", "SLAVE_TIE", "TIE_SLAV", "SLAVE_TI")
        ):
            slave_nodes.update(get_component_node_ids(
                mapdl, ["TIE_SLAVE", "SLAVE_TIE", "TIE_SLAV", "SLAVE_TI", "tie_slave"]
            ))
        if not master_nodes and any(
            name in existing for name in ("TIE_MASTER", "MASTER_TIE", "TIE_MAST", "MASTER_T")
        ):
            master_nodes.update(get_component_node_ids(
                mapdl, ["TIE_MASTER", "MASTER_TIE", "TIE_MAST", "MASTER_T", "tie_master"]
            ))
        if not slave_nodes:
            slave_nodes.update(get_component_node_ids_by_keywords(mapdl, include=("SLAVE", "TIE")))
        if not master_nodes:
            master_nodes.update(get_component_node_ids_by_keywords(mapdl, include=("MASTER", "TIE")))
        if slave_nodes or master_nodes:
            log_fn(
                f"  Fallback components: slave_nodes={len(slave_nodes)} "
                f"master_nodes={len(master_nodes)}"
            )

    created_cms = set()

    if slave_nodes and create_cm_from_node_list(mapdl, "TIE_SLAVE", slave_nodes, as_elements=True, log_fn=log_fn):
        created_cms.add("TIE_SLAVE")
        log_fn(f"  Created CM TIE_SLAVE ({len(slave_nodes)} nodes -> ELEM component)")
    if master_nodes and create_cm_from_node_list(mapdl, "TIE_MASTER", master_nodes, as_elements=True, log_fn=log_fn):
        created_cms.add("TIE_MASTER")
        log_fn(f"  Created CM TIE_MASTER ({len(master_nodes)} nodes -> ELEM component)")

    if slave_nodes and create_cm_from_node_list(mapdl, "TIE_SLAVE_NODES", slave_nodes, as_elements=False, log_fn=log_fn):
        created_cms.add("TIE_SLAVE_NODES")
        log_fn(f"  Created CM TIE_SLAVE_NODES ({len(slave_nodes)} nodes -> NODE component)")
    if master_nodes and create_cm_from_node_list(mapdl, "TIE_MASTER_NODES", master_nodes, as_elements=False, log_fn=log_fn):
        created_cms.add("TIE_MASTER_NODES")
        log_fn(f"  Created CM TIE_MASTER_NODES ({len(master_nodes)} nodes -> NODE component)")

    tie_slave_eids = get_component_element_ids(mapdl, ["TIE_SLAVE"])
    if not tie_slave_eids:
        alt_slave_eids = (
            get_component_element_ids_by_keywords(mapdl, include=("SLAVE", "TIE"))
            or get_component_element_ids_by_keywords(mapdl, include=("SLAVE",))
        )
        if alt_slave_eids and create_cm_from_element_list(mapdl, "TIE_SLAVE", alt_slave_eids, log_fn=log_fn):
            created_cms.add("TIE_SLAVE")
            log_fn(f"  Rebuilt CM TIE_SLAVE from existing element component ({len(alt_slave_eids)} elements)")

    tie_master_eids = get_component_element_ids(mapdl, ["TIE_MASTER"])
    if not tie_master_eids:
        alt_master_eids = (
            get_component_element_ids_by_keywords(mapdl, include=("MASTER", "TIE"))
            or get_component_element_ids_by_keywords(mapdl, include=("MASTER",))
        )
        if alt_master_eids and create_cm_from_element_list(mapdl, "TIE_MASTER", alt_master_eids, log_fn=log_fn):
            created_cms.add("TIE_MASTER")
            log_fn(f"  Rebuilt CM TIE_MASTER from existing element component ({len(alt_master_eids)} elements)")

    mapdl.allsel("ALL")

    existing_cms = list_all_components(mapdl)
    deleted_cm = 0
    for name in existing_cms:
        if name.upper() in created_cms:
            continue
        up = name.upper()
        if "TIE" in up or "MASTER" in up or "SLAVE" in up:
            continue
        try:
            mapdl.cmdele(name)
            deleted_cm += 1
        except Exception:
            pass
    log_fn(f"  Removed {deleted_cm} non-tie component name(s).")

    for cmd_name, args in load_cmds:
        try:
            getattr(mapdl, cmd_name)(*args)
        except Exception:
            pass
    log_fn("  Deleted all loads / constraint equations / coupled sets.")

    n_arrays = delete_array_params(mapdl)
    log_fn(f"  Deleted {n_arrays} array/table parameter(s).")


def remove_unused_mats(mapdl, log_fn):
    """Find and delete unused material properties."""
    mapdl.allsel("ALL")
    elem_count = int(mapdl.get("NELEM", "ELEM", "", "COUNT"))

    if elem_count == 0:
        log_fn("  No elements found, skipping.")
        return

    max_enum = int(mapdl.get("MAXE", "ELEM", "", "NUM", "MAX"))
    try:
        mapdl.run(f"*DIM,_MATARR,ARRAY,{max_enum}")
        mapdl.run("*VGET,_MATARR(1),ELEM,1,ATTR,MAT")
        mat_array = mapdl.parameters["_MATARR"].flatten()
        used_mats = set(int(x) for x in mat_array if x > 0)
    except Exception:
        log_fn("  Warning: Could not bulk-read element MAT attrs, skipping.")
        return

    macro_path = os.path.join(mapdl.directory, "_dump_mplist.mac")
    with open(macro_path, "w") as f:
        f.write("/OUTPUT,_mplist,txt\n")
        f.write("MPLIST,ALL\n")
        f.write("/OUTPUT\n")
    mapdl.input(macro_path)
    mplist_path = os.path.join(mapdl.directory, "_mplist.txt")

    all_mats = set()
    try:
        with open(mplist_path, "r") as f:
            for line in f:
                m = re.search(r"MATERIAL\s+NUMBER\s*=?\s*(\d+)", line, re.IGNORECASE)
                if m:
                    all_mats.add(int(m.group(1)))
    except FileNotFoundError:
        log_fn("  Warning: MPLIST output file not found, skipping.")
        return

    log_fn(f"  {len(used_mats)} material(s) in use, {len(all_mats)} defined.")

    unused = sorted(all_mats - used_mats)
    log_fn(f"  {len(unused)} unused material(s) to delete...")

    deleted = 0
    for mid in unused:
        try:
            mapdl.mpdele("ALL", mid)
        except Exception:
            pass
        try:
            mapdl.tbdele("ALL", mid)
        except Exception:
            pass
        deleted += 1

    log_fn(f"  Deleted {deleted} / {len(all_mats)} unused material(s).")


def _find_corner_node(node_xyz, x, y, z, tol):
    """Return the node id closest to (x, y, z); exact match within tol preferred."""
    candidates = [
        nid for nid, (nx, ny, nz) in node_xyz.items()
        if abs(nx - x) <= tol and abs(ny - y) <= tol and abs(nz - z) <= tol
    ]
    if candidates:
        return min(candidates)
    return min(
        node_xyz.items(),
        key=lambda kv: abs(kv[1][0] - x) + abs(kv[1][1] - y) + abs(kv[1][2] - z),
    )[0]


def _collect_tie_data(mapdl, log_fn):
    """Detect tie master/slave element and surface-node sets (mode-independent)."""
    master = get_component_element_ids(mapdl, [
        "TIE_MASTER", "tie_master", "TIE_MAST", "MASTER_TIE", "master_tie", "MASTER_T",
        "MASTER", "master",
    ])
    slave = get_component_element_ids(mapdl, [
        "TIE_SLAVE", "tie_slave", "TIE_SLAV", "SLAVE_TIE", "slave_tie", "SLAVE_TI",
        "SLAVE", "slave",
    ])

    if not master:
        auto_master = (
            get_component_element_ids_by_keywords(mapdl, include=("MASTER", "TIE"))
            or get_component_element_ids_by_keywords(mapdl, include=("MASTER",))
        )
        if auto_master:
            master = auto_master
            log_fn(f"  tie master fallback by name pattern: {len(master)} element(s)")
    if not slave:
        auto_slave = (
            get_component_element_ids_by_keywords(mapdl, include=("SLAVE", "TIE"))
            or get_component_element_ids_by_keywords(mapdl, include=("SLAVE",))
        )
        if auto_slave:
            slave = auto_slave
            log_fn(f"  tie slave fallback by name pattern: {len(slave)} element(s)")

    log_fn(f"  tie element sets: master={len(master)} slave={len(slave)}")

    master_tie_nodes = get_component_node_ids(mapdl, ["TIE_MASTER_NODES", "tie_master_nodes"])
    slave_tie_nodes = get_component_node_ids(mapdl, ["TIE_SLAVE_NODES", "tie_slave_nodes"])
    log_fn(
        f"  tie surface nodes: master={len(master_tie_nodes)} "
        f"slave={len(slave_tie_nodes)}"
    )
    return master, slave, master_tie_nodes, slave_tie_nodes


def collect_nset_data(mapdl, log_fn, is_submodel=False, symmetry_mode="quarter"):
    """Collect nset/tie metadata directly from node coordinates and components.

    When ``is_submodel=True`` returns ``nset_bc_sub`` (all outermost-plane
    nodes) instead of the symmetry/full-model nsets, and omits tie data.

    ``symmetry_mode`` selects the boundary-condition scheme for a
    non-submodel run:
      - "quarter": X=0/Y=0 symmetry planes + single corner fixation (default).
      - "full": no symmetry: a 3-point kinematic constraint removes rigid
        body motion (see ``_write_step_full`` in inp_writer.py for details).
      - "half": not yet implemented; callers should not reach this branch
        (the GUI blocks a run selecting it).
    """
    mapdl.allsel("ALL")
    nnum = [int(v) for v in mapdl.mesh.nnum.tolist()]
    coords = mapdl.mesh.nodes
    node_xyz = {
        int(nid): (float(xyz[0]), float(xyz[1]), float(xyz[2]))
        for nid, xyz in zip(nnum, coords)
    }
    tol = 1.0e-12
    min_x = min(v[0] for v in node_xyz.values())
    min_y = min(v[1] for v in node_xyz.values())
    min_z = min(v[2] for v in node_xyz.values())

    if is_submodel:
        max_x = max(v[0] for v in node_xyz.values())
        max_y = max(v[1] for v in node_xyz.values())
        max_z = max(v[2] for v in node_xyz.values())
        bc_sub = sorted(
            nid for nid, (x, y, z) in node_xyz.items()
            if (abs(x - min_x) <= tol or abs(x - max_x) <= tol
                or abs(y - min_y) <= tol or abs(y - max_y) <= tol
                or abs(z - min_z) <= tol or abs(z - max_z) <= tol)
        )
        log_fn(f"  nset_bc_sub: {len(bc_sub)} outermost-plane node(s)")
        mapdl.allsel("ALL")
        return {
            "nset_temperature": sorted(nnum),
            "nset_bc_sub": bc_sub,
        }

    if symmetry_mode == "full":
        max_x = max(v[0] for v in node_xyz.values())
        max_y = max(v[1] for v in node_xyz.values())
        max_z = max(v[2] for v in node_xyz.values())
        p_fixall = _find_corner_node(node_xyz, min_x, min_y, min_z, tol)
        p_fixyz = _find_corner_node(node_xyz, max_x, min_y, min_z, tol)
        p_fixz = _find_corner_node(node_xyz, min_x, max_y, min_z, tol)
        log_fn(
            f"  full-model fixation nodes: all-fixed={p_fixall}, "
            f"uy/uz-fixed={p_fixyz}, uz-fixed={p_fixz}"
        )
        master, slave, master_tie_nodes, slave_tie_nodes = _collect_tie_data(mapdl, log_fn)
        mapdl.allsel("ALL")
        return {
            "nset_temperature": sorted(nnum),
            "nset_bc_fixall": [p_fixall],
            "nset_bc_fixyz": [p_fixyz],
            "nset_bc_fixz": [p_fixz],
            "master_tie": master,
            "slave_tie": slave,
            "master_tie_nodes": master_tie_nodes,
            "slave_tie_nodes": slave_tie_nodes,
        }

    # quarter (default)
    bc_x = sorted(nid for nid, (x, _, _) in node_xyz.items() if abs(x - min_x) <= tol)
    bc_y = sorted(nid for nid, (_, y, _) in node_xyz.items() if abs(y - min_y) <= tol)
    bc_all = [_find_corner_node(node_xyz, min_x, min_y, min_z, tol)]

    master, slave, master_tie_nodes, slave_tie_nodes = _collect_tie_data(mapdl, log_fn)
    mapdl.allsel("ALL")

    return {
        "nset_temperature": sorted(nnum),
        "nset_bc_x": bc_x,
        "nset_bc_y": bc_y,
        "nset_bc_all": bc_all,
        "master_tie": master,
        "slave_tie": slave,
        "master_tie_nodes": master_tie_nodes,
        "slave_tie_nodes": slave_tie_nodes,
    }


def dump_mapdl_mplist(mapdl, mplist_path):
    """Export MPLIST to a text file for Step 2 material processing."""
    macro_path = os.path.join(mapdl.directory, "_dump_mplist_for_step4.mac")
    with open(macro_path, "w") as f:
        f.write("/OUTPUT,_mplist_step4,txt\n")
        f.write("MPLIST,ALL\n")
        f.write("/OUTPUT\n")
    mapdl.input(macro_path)
    src = os.path.join(mapdl.directory, "_mplist_step4.txt")
    try:
        shutil.copy2(src, mplist_path)
    except Exception:
        with open(mplist_path, "w") as f:
            f.write("")
