"""Export weather decisions on the original, EXIF-oriented region grid."""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from surface import LABELS

ENCODING = {"不会": 0, "保守略过": 127, "会": 255}


def apply_spatial_review(regions, sample_map, parts, owners, labels, review):
    """Nearest-neighbour expansion is valid only inside the original region."""
    grid = np.array(sample_map.resize(regions.shape[::-1], Image.Resampling.NEAREST), dtype=np.uint32)
    parent = np.array([-1] + [p["region_id"] for p in parts], dtype=np.int64)
    grid[parent[grid] != regions] = 0
    reserved = {}
    for rid, group in owners.items():
        if group in {"caption", "footer", "metadata"}:
            reserved[rid] = ("题字或拍摄信息栏", {"kind": "air"})
        elif group == "sky" or labels[rid] == "sky":
            reserved[rid] = ("天空", {"kind": "air"})
        elif group == "water" or labels[rid] in LABELS["water"]:
            reserved[rid] = ("开阔水面", {"kind": "water", "water_freezes": False})
    for rid in owners:
        if rid in reserved:
            name, facts = reserved[rid]
            area = regions == rid
        else:
            name, facts = "原尺寸边界细部", {"kind": "unknown"}
            area = (grid == 0) & (regions == rid)
        if area.any():
            parts.append(dict(region_id=rid, name=name, **facts))
            grid[area] = len(parts)

    if review:
        size = review["size"]
        if (not isinstance(size, list) or len(size) != 2
                or any(type(n) is not int or n < 1 for n in size)):
            raise ValueError("修订坐标网格 size 应是两个正整数。")
        w, h = size
        for item in review["patches"]:
            part = dict(item)
            points = part.pop("polygon")
            if isinstance(part.get("name"), str):
                part["name"] = part["name"].strip()
            rid = part["region_id"]
            if rid not in owners or rid in reserved:
                raise ValueError("修订目标不存在或为题字、天空、水面保护区。")
            if (len(points) < 3 or any(len(p) != 2 or any(type(v) is not int for v in p)
                                      or not (0 <= p[0] < w and 0 <= p[1] < h) for p in points)):
                raise ValueError("修订多边形超出坐标网格或格式错误。")
            polygon = Image.new("1", regions.shape[::-1])
            xy = [(min(regions.shape[1]-1, int((x+.5)*regions.shape[1]/w)),
                   min(regions.shape[0]-1, int((y+.5)*regions.shape[0]/h))) for x, y in points]
            ImageDraw.Draw(polygon).polygon(xy, fill=1)
            area = np.asarray(polygon) & (regions == rid)
            if not area.any():
                raise ValueError(f"修订部位 {part['name']} 与指定区块无交集。")
            if part in parts:
                idx = parts.index(part) + 1
            else:
                parts.append(part)
                idx = len(parts)
            grid[area] = idx
    active = np.unique(grid)
    if 0 in active or len(active) > 65535:
        raise ValueError("部位图编号无效。")
    lookup = np.zeros(len(parts) + 1, np.uint16)
    lookup[active] = np.arange(1, len(active) + 1)
    return [parts[k-1] for k in active], lookup[grid]


def write_maps(folder, photo, grid, parts, output):
    Image.fromarray(grid).save(folder / "部位编号.png")
    output["locations"] = dict(map="部位编号.png", size=list(grid.shape[::-1]),
                               orientation="exif-transposed", parts=[
                                   dict(id=i, region_id=p["region_id"], name=p["name"])
                                   for i, p in enumerate(parts, 1)])
    output["encoding"] = {str(value): key for key, value in ENCODING.items()}
    output["maps"], output["previews"] = {}, {}
    index = {(p["region_id"], p["name"]): i for i, p in enumerate(parts, 1)}
    thumb = photo.copy()
    thumb.thumbnail((850, 850))
    thumb.save(folder / "参考.jpg", quality=90)
    rgb = np.asarray(thumb, dtype=np.float32)
    output["reference"] = "参考.jpg"
    for subdir in ("位置", "预览"):
        (folder / subdir).mkdir()
    for weather in output["weather"]:
        lut = np.zeros(len(parts)+1, np.uint8)
        for row in output["regions"]:
            for state, items in row["placement"][weather].items():
                for item in items:
                    name = item if isinstance(item, str) else item["部位"]
                    lut[index[row["region_id"], name]] = ENCODING[state]
        mask = Image.fromarray(lut[grid])
        file = Path("位置") / (weather + ".png")
        mask.save(folder / file)
        output["maps"][weather] = file.as_posix()
        small = np.asarray(mask.resize(thumb.size, Image.Resampling.NEAREST))
        overlay = rgb.copy()
        for value, colour, weight in [(255, [0, 203, 146], .59), (127, [251, 177, 58], .34)]:
            selected = small == value
            overlay[selected] = rgb[selected] * (1-weight) + np.array(colour) * weight
        preview = Path("预览") / (weather + ".jpg")
        Image.fromarray(overlay.astype(np.uint8)).save(folder / preview, quality=89)
        output["previews"][weather] = preview.as_posix()
