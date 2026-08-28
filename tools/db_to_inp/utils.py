def fmt_num(v):
    if isinstance(v, (int, float)):
        return f"{v:.9g}"
    return str(v)


def scale_nodes(nodes, factor):
    if factor == 1.0:
        return nodes
    return {
        nid: (xyz[0] * factor, xyz[1] * factor, xyz[2] * factor)
        for nid, xyz in nodes.items()
    }


def log_node_coordinate_stats(nodes, label, log_fn):
    if not nodes:
        log_fn(f"{label}: no nodes")
        return
    xs = [xyz[0] for xyz in nodes.values()]
    ys = [xyz[1] for xyz in nodes.values()]
    zs = [xyz[2] for xyz in nodes.values()]

    def _axis_stat(vals):
        vmin, vmax = min(vals), max(vals)
        return vmin, vmax, vmax - vmin

    x0, x1, dx = _axis_stat(xs)
    y0, y1, dy = _axis_stat(ys)
    z0, z1, dz = _axis_stat(zs)
    log_fn(
        f"{label} node stats: count={len(nodes)} | "
        f"x=[{x0:.9g}, {x1:.9g}] Δ={dx:.9g}, "
        f"y=[{y0:.9g}, {y1:.9g}] Δ={dy:.9g}, "
        f"z=[{z0:.9g}, {z1:.9g}] Δ={dz:.9g}"
    )


def prop_rows(props, key):
    return props.get(key, {}).get("rows", [])


def value_for_temp(rows, temp):
    exact = [v for t, v in rows if t is not None and abs(t - temp) <= 1e-12]
    if exact:
        return exact[-1]
    consts = [v for t, v in rows if t is None]
    return consts[-1] if consts else None


def temps_from_rows(rows):
    return sorted({t for t, _ in rows if t is not None})
