"""Estimate visible accumulation surfaces on the segmented, EXIF-oriented grid."""
import cv2
import numpy as np
from PIL import Image

from engine.analysis import geometry
from surface import LABELS

GROUND = {"road", "floor", "earth", "land", "field", "grass", "sand", "path",
          "sidewalk", "runway", "dirt track", "stairs", "stairway"}
TABLE = {"table", "desk", "coffee table", "counter"}
VEHICLE = {"car", "bus", "truck", "van"}
FENCE = {"fence", "railing", "bannister"}
NAMES = {
    "tree": ("树冠外层朝上的枝叶、可承雪的枝条上侧", "树冠侧面与近直立枝条"),
    "table": ("桌板上侧", "桌板侧边及竖向支撑面"),
    "car": ("车身朝上的面板", "车身陡面与轮侧"),
    "fence": ("栏杆朝上的窄边", "栏杆正面与立柱侧面"),
    "building": ("建筑朝上的屋面与凸沿", "建筑立面"),
    "ground": ("地表可承托处", "陡坡或突起侧壁"),
}


def geometry_parts(photo, small, ids, rows, groups):
    depth, up, exposure = geometry(photo, small.size)
    return classify(ids, rows, groups, np.asarray(small), depth, up, exposure)


def classify(ids, rows, groups, rgb, depth, up, exposure):
    # A local dip must sit behind its neighbours on both axes. Ignore semantic edges.
    # This is evidence of a possible basin, not metric relief on a reconstructed mesh.
    depth = np.asarray(depth, np.float32)
    radius = max(1, min(ids.shape) // 90)
    dips = np.ones(ids.shape, bool)
    for dy, dx in ((0, radius), (0, -radius), (radius, 0), (-radius, 0)):
        neighbour = np.roll(depth, (dy, dx), axis=(0, 1))
        same = np.roll(ids, (dy, dx), axis=(0, 1)) == ids
        if dy > 0:
            same[:dy] = False
        if dy < 0:
            same[dy:] = False
        if dx > 0:
            same[:, :dx] = False
        if dx < 0:
            same[:, dx:] = False
        dips &= same & (neighbour > depth + .004)
    index = np.zeros(ids.shape, np.int32)
    parts, locations = [], []
    def add(mask, title, kind, **facts):
        if not mask.any():
            return
        pid = len(parts) + 1
        parts.append(dict(region_id=rid, name=title, kind=kind, **facts))
        locations.append(dict(id=pid, region_id=rid, name=title))
        index[mask] = pid

    r, g, b = rgb.astype(np.int16).transpose(2, 0, 1)
    for row in rows:
        rid, label = row["id"], row["label"]
        region = ids == rid
        group = groups[rid]
        if not region.any():
            parts.append(dict(region_id=rid, name="小于分析网格的细部", kind="unknown"))
            continue
        if group in {"footer", "metadata", "caption"}:
            add(region, "画面信息栏", "air")
            continue
        if label == "sky" or group == "sky":
            add(region, "天空", "air")
            continue
        if label in LABELS["water"] or group == "water":
            add(region, "可见开阔水面", "water", water_freezes=False)
            continue
        # Visible blue gaps can remain inside a coarse canopy mask.
        if label == "tree":
            gap = region & (b > r + 32) & (b > g + 15) & (b > 130)
            add(gap, "枝间透出的蓝天", "air")
            region = region & ~gap
        vegetation = label in LABELS["foliage"]
        ground = label in GROUND
        family = ("tree" if vegetation else "ground" if ground else "table" if label in TABLE
                  else "car" if label in VEHICLE else "fence" if label in FENCE
                  else "building" if label in {"building", "house", "skyscraper"} else "other")
        upper, side = NAMES.get(family, ("可见朝上承托面", "可见陡面或侧面"))
        if vegetation and label != "tree":
            upper, side = "植株朝上的枝叶", "植株侧面和直立茎部"
        top = up >= .36
        if ground:
            top = np.ones_like(region)  # The ground label provides a support prior at distance.
        if vegetation or family == "fence":
            # The first visible silhouette in each column gives a support cue on thin foliage/rails.
            heights = np.arange(region.shape[0])[:, None]
            first = region.argmax(axis=0)
            top |= region & (heights >= first) & (heights < first + max(1, region.shape[0] // 200))
        exposed = exposure >= .70
        trunk = np.zeros_like(region)
        if label == "tree":
            # Elongated bark-coloured runs provide a stronger trunk cue than a noisy depth edge.
            bark = region & (r > g + 4) & (r < 150) & (g > b) & (up < .6)
            height = max(5, min(ids.shape) // 40)
            broad = cv2.morphologyEx(region.astype(np.uint8), cv2.MORPH_OPEN,
                                     np.ones((1, height), np.uint8)).astype(bool)
            grey = (np.maximum(np.maximum(r, b), g) - np.minimum(np.minimum(r, b), g)) < 22
            narrow_stem = region & ~broad & grey & (r < 175)
            trunk = cv2.morphologyEx((bark | narrow_stem).astype(np.uint8), cv2.MORPH_OPEN,
                                     np.ones((height, 1), np.uint8)).astype(bool)
        can_pool = label in (GROUND | TABLE | {"rock", "roof"}) and label not in {"sand", "grass", "earth"}
        pools = dips & top if can_pool else np.zeros_like(region)
        zones = [(trunk, "直立树干侧面", False, False),
                 (region & ~trunk & pools, upper + "的局部低洼", True, True),
                 (region & ~trunk & top & ~pools, upper, True, False),
                 (region & ~trunk & ~top, side, False, False)]
        for zone, name, support, basin in zones:
            for direct, light in ((True, "外露"), (False, "受遮挡")):
                mask = zone & (exposed == direct)
                # Each event is a separate hypothetical scenario, not a measurement of temperature.
                add(mask, light + "的" + name, "solid", direct=direct, holds_snow=support,
                    pools=None if basin else False, inflow=False, freezes=True, wet=direct and (support or basin),
                    frost_ready=direct, dew_ready=direct, traps_hail=None if basin else False, inflow_hail=False)
    if len(parts) > 65535:
        raise ValueError("分析部位数超过 PNG 编号上限。")
    return parts, locations, Image.fromarray(index.astype(np.uint16))
