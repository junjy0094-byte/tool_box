import re
from collections import defaultdict


MP_LABELS = frozenset({
    "EX", "EY", "EZ", "GXY", "GYZ", "GXZ",
    "NUXY", "NUYZ", "NUXZ", "PRXY", "PRYZ", "PRXZ",
    "DENS", "ALPX", "ALPY", "ALPZ", "CTEX", "CTEY", "CTEZ",
    "KXX", "KYY", "KZZ", "C", "ENTH", "HF", "EMIS",
    "VISC", "SONC", "MU", "DMPR", "DMPS",
    "MURX", "MURY", "MURZ", "MGXX", "MGYY", "MGZZ",
    "RSVX", "RSVY", "RSVZ", "PERX", "PERY", "PERZ",
    "LSST", "BETD", "REFT",
})


def expand_etblock(cdb_path):
    """Replace every ETBLOCK block in a .cdb with ET/KEYOPT cards.

    Returns the number of expanded element-type rows, or 0 if no ETBLOCK found.
    """
    try:
        with open(cdb_path, "r") as f:
            lines = f.readlines()
    except (FileNotFoundError, OSError):
        return 0

    out_lines = []
    expanded = 0
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.lstrip().upper().startswith("ETBLOCK"):
            i += 1
            if i < n and lines[i].lstrip().startswith("("):
                i += 1
            while i < n:
                row = lines[i].strip()
                if not row:
                    i += 1
                    continue
                if row.startswith("-1"):
                    i += 1
                    break
                parts = row.split()
                try:
                    itype = int(parts[0])
                    ename = parts[1]
                    keyopts = [int(p) for p in parts[2:]]
                except (ValueError, IndexError):
                    out_lines.append(lines[i])
                    i += 1
                    continue
                inline_kops = keyopts[:6]
                while inline_kops and inline_kops[-1] == 0:
                    inline_kops.pop()
                et_line = f"ET,{itype},{ename}"
                if inline_kops:
                    et_line += "," + ",".join(str(k) for k in inline_kops)
                out_lines.append(et_line + "\n")
                for extra_idx in range(6, len(keyopts)):
                    kop = keyopts[extra_idx]
                    if kop != 0:
                        out_lines.append(f"KEYOPT,{itype},{extra_idx + 1},{kop}\n")
                expanded += 1
                i += 1
            continue
        out_lines.append(line)
        i += 1

    if expanded:
        with open(cdb_path, "w") as f:
            f.writelines(out_lines)
    return expanded


def rewrite_mp_mpdata_to_classic(cdb_path):
    """Convert MP / MPDATA lines to the classic comma-separated form.

    Modern MAPDL CDWRITE (BLOCKED) inserts a release/version tag before
    the material number; abaqus fromansys expects the property label first.
    Returns the number of converted lines.
    """
    try:
        with open(cdb_path, "r") as f:
            lines = f.readlines()
    except (FileNotFoundError, OSError):
        return 0

    def _split_csv(payload):
        return [tok.strip() for tok in payload.split(",")]

    changed = 0
    out_lines = []
    for line in lines:
        stripped = line.lstrip()
        upper = stripped.upper()
        matched_cmd = None
        for cmd in ("MPDATA", "MP"):
            if upper.startswith(cmd + ",") or upper.startswith(cmd + " "):
                matched_cmd = cmd
                break
            if upper.rstrip() == cmd:
                matched_cmd = cmd
                break
            head = upper[: len(cmd)]
            tail = upper[len(cmd):].lstrip()
            if head == cmd and tail.startswith(","):
                matched_cmd = cmd
                break
        if matched_cmd is None:
            out_lines.append(line)
            continue

        comma = stripped.find(",")
        if comma < 0:
            out_lines.append(line)
            continue
        payload = stripped[comma + 1:].rstrip("\n")
        tokens = _split_csv(payload)
        if len(tokens) < 3:
            out_lines.append(line)
            continue

        tok0_upper = tokens[0].upper()
        tok2_upper = tokens[2].upper() if len(tokens) > 2 else ""

        classic_ok = tok0_upper in MP_LABELS
        blocked_ok = tok0_upper not in MP_LABELS and tok2_upper in MP_LABELS

        if classic_ok or not blocked_ok:
            out_lines.append(line)
            continue

        tag, mat, lab, *rest = tokens
        while rest and rest[-1] == "":
            rest.pop()
        new_line = f"{matched_cmd}," + ",".join([lab, mat, *rest]) + "\n"
        out_lines.append(new_line)
        changed += 1

    if changed:
        with open(cdb_path, "w") as f:
            f.writelines(out_lines)
    return changed


def parse_cdb_nodes(cdb_path):
    """Parse NBLOCK and return {node_id: (x, y, z)}.

    Uses Fortran fixed-width column parsing based on the format specifier
    line (e.g. ``(3i9,6e21.13e3)``). Default widths: int_count=3,
    int_width=9, float_width=21.
    """
    with open(cdb_path, "r") as f:
        lines = f.readlines()

    nodes = {}
    in_nblock = False
    format_read = False
    int_count = 3
    int_width = 9
    float_width = 21
    fmt_pat = re.compile(r"\(\s*(\d+)\s*[iI]\s*(\d+)\s*,\s*\d+\s*[eEdDfFgG]\s*(\d+)")

    for raw in lines:
        line = raw.rstrip("\r\n")
        stripped = line.strip()

        if not in_nblock:
            if stripped.upper().startswith("NBLOCK"):
                in_nblock = True
                format_read = False
            continue

        if not format_read:
            format_read = True
            if stripped.startswith("("):
                m = fmt_pat.match(stripped)
                if m:
                    int_count = int(m.group(1))
                    int_width = int(m.group(2))
                    float_width = int(m.group(3))
                continue

        if stripped.startswith("-1") or not stripped:
            in_nblock = False
            continue

        node_field = line[0:int_width]
        try:
            nid = int(node_field.strip())
        except ValueError:
            in_nblock = False
            continue

        coord_start = int_count * int_width
        coords = [0.0, 0.0, 0.0]
        for i in range(3):
            a = coord_start + i * float_width
            b = a + float_width
            seg = line[a:b].strip()
            if seg:
                coords[i] = float(seg.replace("D", "E").replace("d", "e"))

        nodes[nid] = (coords[0], coords[1], coords[2])

    return nodes


def parse_cdb_elements_by_mat(cdb_path):
    """Parse EBLOCK and return {mat_id: [(eid, [n1..n8]), ...]}."""
    with open(cdb_path, "r") as f:
        lines = f.readlines()

    elems_by_mat = defaultdict(list)
    in_eblock = False
    skip_format = False
    int_pat = re.compile(r"[-+]?\d+")

    for raw in lines:
        s = raw.strip()
        u = s.upper()
        if not in_eblock and u.startswith("EBLOCK"):
            in_eblock = True
            skip_format = True
            continue
        if not in_eblock:
            continue
        if skip_format:
            skip_format = False
            continue
        if s.startswith("-1"):
            in_eblock = False
            continue
        if not s:
            continue

        vals = [int(x) for x in int_pat.findall(s)]
        if len(vals) < 10:
            continue

        mat_id = vals[0]
        eid = vals[-9]
        conn = vals[-8:]
        if len(conn) == 8:
            elems_by_mat[mat_id].append((eid, conn))

    return elems_by_mat


def parse_cdb_nsets(cdb_path):
    """Parse CMBLOCKs (NODE and ELEM) and return {name_lower: [ids]}.

    ELEM type CMBLOCKs are stored as element id lists under their lowercased name.
    """
    with open(cdb_path, "r") as f:
        lines = f.readlines()

    nsets = {}
    i = 0
    n = len(lines)
    int_pat = re.compile(r"[-+]?\d+")

    while i < n:
        line = lines[i].strip()
        if not line.upper().startswith("CMBLOCK"):
            i += 1
            continue

        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            i += 1
            continue
        name = parts[1]
        ent_type = parts[2].upper()
        try:
            num_items = int(parts[3])
        except ValueError:
            num_items = 0
        i += 1
        if i < n and lines[i].lstrip().startswith("("):
            i += 1
        if ent_type not in {"NODE", "ELEM", "ELEMENT"}:
            continue

        ids = []
        while i < n and len(ids) < num_items:
            s = lines[i].strip()
            if not s:
                i += 1
                continue
            if not re.match(r"^[\s\-+0-9]", lines[i]):
                break
            tokens = int_pat.findall(s)
            if not tokens:
                break
            for tok in tokens:
                try:
                    v = int(tok)
                except ValueError:
                    continue
                if v > 0:
                    ids.append(v)
                if len(ids) >= num_items:
                    break
            i += 1
        if ids:
            nsets[name.lower()] = sorted(set(ids))

    return nsets


def read_nsets_txt(nset_path):
    """Read nset metadata file written by _export_step1_metadata."""
    nsets = {}
    cur = None
    int_pat = re.compile(r"[-+]?\d+")
    with open(nset_path, "r") as f:
        for raw in f:
            s = raw.strip()
            if not s:
                continue
            if s.startswith("[") and s.endswith("]"):
                cur = s[1:-1].strip().lower()
                nsets[cur] = []
                continue
            if cur is None:
                continue
            for tok in int_pat.findall(s):
                nsets[cur].append(int(tok))
    for k in list(nsets.keys()):
        nsets[k] = sorted(set(nsets[k]))
    return nsets


def read_materials_from_mplist_txt(mplist_path):
    """Parse MPLIST-like text tables.

    Returns:
        {mat_id: {'name': str, 'props': {prop_key: {'ref_temp': float|None,
                  'rows': [(temp|None, value), ...]}}, 'raw_lines': [...]}}
    """
    mats = {}
    cur_id = None
    cur_prop = None
    num_re = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?")

    def _to_float(tok):
        try:
            return float(tok)
        except ValueError:
            return None

    with open(mplist_path, "r") as f:
        for raw in f:
            line = raw.rstrip("\n")
            s = line.strip()
            if not s:
                continue

            m = re.search(r"MATERIAL\s+NUMBER\s*=?\s*(\d+)", s, re.IGNORECASE)
            if m:
                cur_id = int(m.group(1))
                mats[cur_id] = {"name": f"mat{cur_id}", "raw_lines": [], "props": {}}
                cur_prop = None
                continue
            if cur_id is None:
                continue
            mats[cur_id]["raw_lines"].append(line)

            if re.match(r"^\s*temp\b", s, re.IGNORECASE):
                parts = s.split()
                if len(parts) >= 2:
                    cur_prop = parts[1].strip().lower()
                    ref_match = re.search(
                        r"reference\s*temp\.?\s*=\s*(" + num_re.pattern + ")",
                        s, re.IGNORECASE,
                    )
                    ref_temp = float(ref_match.group(1)) if ref_match else None
                    mats[cur_id]["props"].setdefault(cur_prop, {"ref_temp": ref_temp, "rows": []})
                    if ref_temp is not None:
                        mats[cur_id]["props"][cur_prop]["ref_temp"] = ref_temp
                continue

            if not cur_prop:
                continue
            nums = re.findall(num_re, s)
            if len(nums) == 1:
                val = _to_float(nums[0])
                if val is not None:
                    mats[cur_id]["props"][cur_prop]["rows"].append((None, val))
                continue
            t = _to_float(nums[0]) if len(nums) >= 1 else None
            v = _to_float(nums[1]) if len(nums) >= 2 else None
            if t is not None and v is not None:
                mats[cur_id]["props"][cur_prop]["rows"].append((t, v))

    return mats
