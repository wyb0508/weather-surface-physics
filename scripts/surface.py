"""Image-space transport. All water stores use the same relative load unit."""
import numpy as np
from PIL import Image, ImageDraw

# Retention of intercepted snow, surface film capacity, uptake per time step.
MATERIALS = {
    "air": (0, 0, 0), "water": (0, 0, 0), "hard": (.82, .065, 0),
    "porous": (.90, .12, .009), "foliage": (.55, .09, .003),
    "smooth": (.58, .035, 0),
}
LABELS = {
    "air": {"sky"}, "water": {"water", "sea", "river", "lake", "swimming pool", "waterfall"},
    "porous": {"grass", "earth", "land", "sand", "field", "path", "rug", "dirt track"},
    "foliage": {"tree", "plant", "palm", "flower"},
    "smooth": {"car", "bus", "truck", "windowpane", "mirror"},
    "hard": {"table", "coffee table", "desk", "counter", "road", "floor", "sidewalk",
             "wall", "building", "house", "fence", "railing", "rock", "mountain", "bridge"},
}
DIRECTIONS = {"left": (0, -1), "right": (0, 1), "down": (1, 0),
              "up": (-1, 0), "still": (0, 0)}


def material_for(label, group):
    reviewed = {"sky": "air", "water": "water", "track": "hard", "caption": "air", "footer": "air", "metadata": "air"}
    if group in reviewed:
        return reviewed[group]
    return next((name for name, labels in LABELS.items() if label in labels), "hard")


def fraction(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ValueError("比例值须在 0 到 1 之间。")
    return value


def footprint(ids, item, field="polygon"):
    mask = ids == item["region_id"]
    if not mask.any():
        raise ValueError("修正引用了不存在的区块。")
    if field in item:
        h, w = ids.shape
        points = item[field]
        if len(points) < 3 or any(len(p) != 2 or any(type(n) is not int for n in p)
                                  or not (0 <= p[0] < w and 0 <= p[1] < h) for p in points):
            raise ValueError("多边形须使用分析图内的整数像素坐标。")
        layer = Image.new("1", (w, h))
        ImageDraw.Draw(layer).polygon([tuple(p) for p in points], fill=1)
        mask &= np.asarray(layer)
    if not mask.any():
        raise ValueError("多边形与指定区块没有交集。")
    return mask


def prepare(ids, rows, groups, depth_geometry, motion, sheltered, ground_snow, merge, config):
    depth, up, exposure = [np.array(a, np.float32, copy=True) for a in depth_geometry]
    surface = np.zeros(ids.shape, np.uint8)
    old_snow = np.full(ids.shape, fraction(config.get("old_snow", 0)), np.float32)
    ground_gain = np.ones_like(up)
    directions = np.full(ids.shape, list(DIRECTIONS).index("down"), np.uint8)
    descriptions = {}
    for row in rows:
        rid, raw = row["id"], row["label"]
        label = merge.get(raw, raw)
        group = groups[rid]
        kind = material_for(label, group if raw == label else None)
        if group in {"caption", "metadata", "footer"}:
            kind = "air"
        mask = ids == rid
        surface[mask] = list(MATERIALS).index(kind)
        descriptions[rid] = kind
        if label in {"road", "floor", "earth", "path", "sidewalk", "land", "runway"} or group in {"track", "ground"}:
            ground_gain[mask] = {"wet": .25, "natural": .8, "cold": 1}[ground_snow]
    for patch in config.get("patches", []):
        if set(patch) - {"region_id", "polygon", "up", "exposure", "material", "flow", "old_snow", "note"}:
            raise ValueError("修正中包含未知字段。")
        mask = footprint(ids, patch)
        if groups[patch["region_id"]] in {"caption", "footer", "metadata"}:
            raise ValueError("题字和信息栏不接受表面修订。")
        for key, array in (("up", up), ("exposure", exposure), ("old_snow", old_snow)):
            if key in patch:
                array[mask] = fraction(patch[key])
        if "material" in patch:
            surface[mask] = list(MATERIALS).index(patch["material"])
        if "flow" in patch:
            directions[mask] = list(DIRECTIONS).index(patch["flow"])
    exposure[sheltered] = 0
    air = surface == list(MATERIALS).index("air")
    water = surface == list(MATERIALS).index("water")
    solid = ~(air | water)
    retention, capacity, uptake = np.array(list(MATERIALS.values()), np.float32)[surface].transpose(2, 0, 1)
    support = solid * up * retention * motion * ground_gain
    # Unknown grade on near-level surfaces: store liquid locally until a reviewed grade is supplied.
    mobility = (1 - up) * solid
    for patch in config.get("patches", []):
        if "flow" in patch:
            mobility[footprint(ids, patch)] = 0 if patch["flow"] == "still" else 1
    return dict(depth=depth, up=up, exposure=exposure, support=support, solid=solid,
                water=water, air=air, material=surface, old=old_snow * support, capacity=capacity,
                uptake=uptake, mobility=mobility, directions=directions), descriptions


def routes(ids, fields, config):
    moves = []
    solid = fields["solid"]
    for code, (dy, dx) in enumerate(DIRECTIONS.values()):
        if dy == dx == 0:
            continue
        y, x = np.nonzero((fields["directions"] == code) & solid)
        valid = (y + dy >= 0) & (y + dy < ids.shape[0]) & (x + dx >= 0) & (x + dx < ids.shape[1])
        y, x = y[valid], x[valid]
        sy, sx = y + dy, x + dx
        keep = (ids[y, x] == ids[sy, sx]) & solid[sy, sx]
        moves.append(((y[keep], x[keep]), (sy[keep], sx[keep])))
    links = []
    used = np.zeros_like(solid)
    for link in config.get("drains", []):
        a, b = link["from"], link["to"]
        if "polygon" not in a or "polygon" not in b:
            raise ValueError("滴落出口和落点都需要局部多边形。")
        src, dst = footprint(ids, a), footprint(ids, b)
        if (src & (used | ~solid | dst)).any() or (dst & fields["air"]).any():
            raise ValueError("出口须位于独立的固体区域，落点须在固体或水面。")
        used |= src
        links.append((src, dst))
    return moves, links


def simulate(ids, f, config, rain, snowfall, temperature):
    snow = f["old"].copy()
    film = np.zeros_like(snow)
    absorbed_map = np.zeros_like(snow)
    moves, links = routes(ids, f, config)
    # Weak wind-driven contact on vertical faces. Snow retention still requires support.
    incident = f["exposure"] * (~f["air"]) * np.where(f["water"], 1, .10 + .90 * f["up"])
    rain_in = rain * incident / 24
    snow_in = snowfall * f["exposure"] * f["support"] / 24
    melt_rate = .0015 * max(temperature, 0) * (1 + rain_in * 8)
    snapshots = []
    total_in = absorbed = drained_water = 0.
    initial = snow.sum(dtype=np.float64)
    runoff = np.zeros_like(snow)
    drip = np.zeros_like(snow)
    landing = np.zeros_like(snow)
    for step in range(25):
        if step in (0, 12, 24):
            snapshots.append(dict(snow=snow.copy(), film=film.copy(), runoff=runoff.copy(),
                                  drip=drip.copy(), landing=landing.copy(), absorbed=absorbed_map.copy()))
        if step == 24:
            break
        total_in += (rain_in + snow_in).sum(dtype=np.float64)
        snow += snow_in
        melt = np.minimum(snow, melt_rate)
        snow -= melt
        film += rain_in + melt
        uptake = np.minimum(film, f["uptake"])
        absorbed += uptake.sum(dtype=np.float64)
        absorbed_map += uptake
        film -= uptake
        runoff.fill(0)
        drip.fill(0)
        landing.fill(0)
        excess = np.maximum(film - f["capacity"], 0)
        for src, dst in links:
            drip[src] = excess[src] * .65
            landing[dst] += drip[src].sum(dtype=np.float64) / dst.sum()
        mobile = (excess - drip) * f["mobility"] * .55
        for src, dst in moves:
            amount = mobile[src]
            film[src] -= amount
            film[dst] += amount
            runoff[src] = amount
        film += landing - drip
        drained_water += film[f["water"]].sum(dtype=np.float64)
        film[f["water"]] = 0
    final = (film + snow).sum(dtype=np.float64)
    balance = dict(initial=float(initial), received=float(total_in), absorbed=float(absorbed),
                   joined_water=float(drained_water), stored=float(final),
                   residual=float(initial + total_in - absorbed - drained_water - final))
    return snapshots, incident * rain, snow_in * 24, balance
