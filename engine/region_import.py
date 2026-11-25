"""Read a scene-regions export on the wallpaper engine's analysis grid."""
import hashlib
import json

import numpy as np
from PIL import Image

from .vision import ROOT, oriented_size


def import_regions(manifest, source, photo):
    folder = manifest.resolve().parent
    data = json.loads(manifest.read_text(encoding="utf-8"))
    with source.open("rb") as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    if data.get("schema") != "scene-regions/v1" or data.get("sha256") != digest.hexdigest():
        raise ValueError("分区清单版本或原图指纹不匹配。")
    small = photo.copy()
    small.thumbnail((1024, 1024))
    if data.get("analysis_size") != list(small.size) or data.get("size") != list(oriented_size(source)):
        raise ValueError("分区清单的分析尺寸与原图不匹配。")

    def read_map(field):
        file = (folder / data[field]).resolve()
        if not file.is_relative_to(folder):
            raise ValueError("类别图和区块图应位于分区包内。")
        with Image.open(file) as image:
            if image.mode not in ("L", "I", "I;16") or list(image.size) != data["size"]:
                raise ValueError("分区图的尺寸或像素格式不符合清单。")
            return image.copy()

    try:
        class_image = read_map("class_map")
        region_image = read_map("region_map")
        full_regions = np.asarray(region_image)
        names = json.loads((ROOT / "models/classes.json").read_text())["id2label"]
        rows = data["regions"]
        known = {r["id"]: r["class_id"] for r in rows}
        if (len(known) != len(rows) or set(np.unique(full_regions)) != known.keys()
                or any(names[str(r["class_id"])].strip() != r["label"] for r in rows)):
            raise ValueError("区块表与模型类别不匹配。")
        lookup = np.zeros(int(full_regions.max()) + 1, np.uint16)
        for rid, cid in known.items():
            lookup[rid] = cid
        full_classes = np.asarray(class_image)
        for top in range(0, region_image.height, 512):
            band = slice(top, top + 512)
            if not np.array_equal(full_classes[band], lookup[full_regions[band]]):
                raise ValueError("区块图与原始类别图不一致。")
        # Sample a single ID grid; a subpixel island can vanish on this smaller grid.
        regions = np.asarray(region_image.resize(small.size, Image.Resampling.NEAREST))
        labels = lookup[regions]
        groups = {}
        assigned = []
        for group in data["groups"]:
            key = group["key"]
            members = group["region_ids"]
            if key in groups or not members:
                raise ValueError("分组键重复或缺少区块。")
            groups[key] = np.isin(regions, members)
            assigned.extend(members)
        if sorted(assigned) != sorted(known):
            raise ValueError("每个区块须恰好归属一个分组。")
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("分区清单缺少有效的类别或分组。") from error
    # Tie subsequent interview answers to the actual masks and grouping.
    signature = hashlib.sha256(labels.tobytes())
    for name, mask in sorted(groups.items()):
        signature.update(name.encode() + b"\0" + np.packbits(mask).tobytes())
    return (small, labels.astype(np.uint8), names), groups, signature.hexdigest()
