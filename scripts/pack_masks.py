"""Adapt existing binary cutouts to the wallpaper project's region-map contract."""
import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.vision import load_photo, oriented_size


def pack(photo, spec_file, folder):
    spec = json.loads(spec_file.read_text())
    size = oriented_size(photo)
    sha = hashlib.sha256(photo.read_bytes()).hexdigest()
    if spec.get("sha256") != sha:
        raise ValueError("蒙版说明与原图指纹不匹配。")
    grid = load_photo(photo)
    grid.thumbnail((1024, 1024))
    classes = json.loads((ROOT / "models/classes.json").read_text())["id2label"]
    lookup = {label.strip(): int(idx) for idx, label in classes.items()}
    ids = np.zeros(size[::-1], np.uint16)
    labels = np.empty(size[::-1], np.uint8)
    regions, groups = [], {}
    keys = set()
    for rid, item in enumerate(spec["regions"], 1):
        key, label = item["key"], item["label"]
        if key in keys or label not in lookup or rid > 65535:
            raise ValueError("每个区块需有唯一 key 和有效的 ADE20K 标签，区块数上限为 65535。")
        keys.add(key)
        with Image.open(spec_file.parent / item["mask"]) as mask:
            if mask.size != size:
                raise ValueError(f"{key} 蒙版尺寸与已旋转的原图不符。")
            channel = mask.getchannel("A") if "A" in mask.getbands() else mask.convert("L")
            pixels = np.asarray(channel)
            if not np.isin(pixels, [0, 255]).all():
                raise ValueError(f"{key} 需提供二值蒙版。")
            selected = pixels == 255
        if not selected.any() or ids[selected].any():
            raise ValueError(f"{key} 为空或与之前的可见区块重叠。")
        ids[selected], labels[selected] = rid, lookup[label]
        regions.append(dict(id=rid, key=key, class_id=lookup[label], label=label))
        groups.setdefault(item.get("group", key), []).append(rid)
    if not ids.all():
        raise ValueError("可见区块未覆盖全图，请给剩余区域提供区块蒙版。")
    region_image = Image.fromarray(ids)
    if len(np.unique(region_image.resize(grid.size, Image.Resampling.NEAREST))) != len(regions):
        raise ValueError("存在小于分析网格的区块，请先核实或合并。")
    region_image.save(folder / "regions.png")
    Image.fromarray(labels).save(folder / "classes.png")
    layers = []
    for gid, (key, members) in enumerate(groups.items(), 1):
        name = f"group-{gid}.png"
        Image.fromarray(np.isin(ids, members).astype(np.uint8) * 255).save(folder / name)
        layers.append(dict(id=gid, key=key, region_ids=members, mask=name))
    data = dict(schema="scene-regions/v1", source=photo.name, sha256=sha, size=size,
                analysis_size=grid.size, orientation="exif-transposed", regions=regions,
                region_map="regions.png", class_map="classes.png", groups=layers)
    (folder / "manifest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("photo", type=Path)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("请指定新的分区目录。")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with TemporaryDirectory(dir=args.out.parent) as tmp:
            stage = Path(tmp) / "pack"
            stage.mkdir()
            pack(args.photo, args.spec, stage)
            stage.rename(args.out)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"蒙版导入失败：{exc}\n")
    print(args.out / "manifest.json")


if __name__ == "__main__":
    main()
