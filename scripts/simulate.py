"""Build a portable renderer handoff from a scene-regions pack."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import sys

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.analysis import geometry
from engine.region_import import import_regions
from engine.vision import infer, load_photo, tensor
from engine.workflow import GAIN, collect
from surface import DIRECTIONS, MATERIALS, fraction, prepare, simulate

# Fixed total reference load over a ten-minute design event.
RAIN = {"小雨": .28, "大雨": 1.0}
SNOW = {"小雪": .16, "中雪": .36, "大雪": .68, "暴雪": 1.0}
DRY = ("晴朗", "日出", "日落", "黄昏", "深夜", "多云", "大风")
TIPS = {
    "air": "仅承载空中粒子；表面通道为零。",
    "water": "在直接雨点或承接滴水的位置生成局部波纹，水量汇入水体。",
    "smooth": "沿局部流向移动水珠，按水膜调整高光；雪随承托能力和运动衰减。",
    "hard": "雨点接触后形成水膜，沿流向输送多余水；雪只在有承托的像素显现。",
    "foliage": "沿枝叶轮廓形成断续的挂水和留雪，保留轮廓中的空隙。",
    "porous": "吸水处先变暗，结合剩余水膜控制高光；让原表面纹理透过薄雪。",
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def save_map(folder, name, values, scale=1.):
    path = name + ".png"
    pixels = np.rint(255 * np.clip(values / scale, 0, 1)).astype(np.uint8)
    Image.fromarray(pixels).save(folder / path)
    return path


def selections(plan, labels, names, groups, photo):
    ids = {name.strip(): int(key) for key, name in names.items()}
    merged = labels.copy()
    for src, dst in plan["merge_into"].items():
        merged[labels == ids[src]] = ids[dst]
    cache = {}
    def mask(key):
        if key == "none":
            return np.zeros_like(labels, bool)
        if key == "salient":
            if key not in cache:
                raw = infer("foreground.onnx", tensor(photo, 320, relative=True))[0]
                small = Image.fromarray(raw).resize(labels.shape[::-1], Image.Resampling.BILINEAR)
                cache[key] = np.asarray(small) > .5
            return cache[key]
        if key.startswith("group:"):
            return groups[key[6:]]
        return merged == ids[key]
    gain = {None: 1, "stationary": 1, "moving": .55, "high_speed": .12}[plan["motion"]]
    motion = np.where(mask(plan["subject"]), gain, 1).astype(np.float32)
    shelter = np.zeros_like(labels, bool)
    for key in plan["sheltered"]:
        shelter |= mask(key)
    return motion, shelter


def preview(folder, small, last, rain, snow_load):
    rgb = np.asarray(small, dtype=float)
    wet = last["film"] + last["absorbed"] + rain * .25
    panels = [rgb]
    wet_scale = max(.25, float(np.percentile(wet, 98)))
    for field, scale, color in ((wet, wet_scale, [39, 158, 235]),
                                (last["snow"], max(.25, snow_load), [251, 247, 239])):
        alpha = np.clip(field / scale, 0, 1)[..., None] * .85
        panels.append(rgb * (1 - alpha) + np.array(color) * alpha)
    Image.fromarray(np.concatenate(panels, axis=1).astype(np.uint8)).save(folder / "preview.jpg", quality=90)


def export(args, folder):
    data = read(args.manifest)
    photo = load_photo(args.image)
    scene, groups, signature = import_regions(args.manifest, args.image, photo)
    small, labels, names = scene
    region_file = args.manifest.parent / data["region_map"]
    with Image.open(region_file) as src:
        ids = np.asarray(src.resize(small.size, Image.Resampling.NEAREST))
    rows = data["regions"]
    owners = {rid: g["key"] for g in data["groups"] for rid in g["region_ids"]}
    config = read(args.review) if args.review else {}
    manifest_hash = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    if args.review and (config.get("manifest_sha256") != manifest_hash or config.get("analysis_size") != list(small.size)):
        raise ValueError("复核文件与分区清单或分析尺寸不匹配。")
    if set(config) - {"manifest_sha256", "analysis_size", "patches", "drains", "old_snow", "note"}:
        raise ValueError("复核文件中包含未知字段。")
    if args.old_snow is not None:
        config["old_snow"] = fraction(args.old_snow)
    if args.answers:
        plan = collect(photo, [dict(label=r["label"], name=r["label"]) for r in rows],
                       args.answers, None, None, groups, signature)
    else:
        plan = dict(subject="none", motion=None, merge_into={}, sheltered=[], ground_snow="natural")
    gain = GAIN[plan["weather"][args.weather]] if args.answers else 1.
    motion, shelter = selections(plan, labels, names, groups, photo)
    f, kinds = prepare(ids, rows, owners, geometry(photo, small.size), motion, shelter,
                       plan["ground_snow"], plan["merge_into"], config)
    temperature = args.temperature if args.temperature is not None else (-3 if args.weather in SNOW else 5)
    if not math.isfinite(temperature):
        raise ValueError("气温需要有限数值。")
    rain = RAIN.get(args.weather, 0) * gain
    snow = SNOW.get(args.weather, 0)
    frames, contact, deposited, balance = simulate(ids, f, config, rain, snow, temperature)
    shutil.copyfile(region_file, folder / "regions.png")
    small.save(folder / "reference.jpg", quality=94)
    static = {name: save_map(folder, name, f[name]) for name in ("depth", "up", "exposure", "support")}
    static["contact"] = save_map(folder, "contact", contact, max(1, rain))
    static["deposition"] = save_map(folder, "deposition", deposited)
    static["ripple"] = save_map(folder, "ripple", f["water"] * contact, max(1, rain))
    Image.fromarray(f["directions"]).save(folder / "direction.png")
    static["direction"] = "direction.png"
    Image.fromarray(f["material"]).save(folder / "material.png")
    static["material"] = "material.png"
    scales = {key: max(.0001, *(float(frame[key].max()) for frame in frames)) for key in frames[0]}
    keyframes = []
    for time, frame in zip((0, 300, 600), frames):
        keyframes.append(dict(seconds=time, maps={k: save_map(folder, f"{time}-{k}", v, scales[k])
                                                  for k, v in frame.items()}))
    report = []
    for row in rows:
        rid = row["id"]
        mask = ids == rid
        means = {k: (round(float(v[mask].mean()), 5) if mask.any() else None) for k, v in
                 dict(contact=contact, deposition=deposited, **frames[-1]).items()}
        report.append(dict(region_id=rid, key=row.get("key", row["label"]), label=row["label"],
                           group=owners[rid], base_material=kinds[rid], response=TIPS[kinds[rid]],
                           patches=[p for p in config.get("patches", []) if p["region_id"] == rid],
                           final_mean=means))
    # Include the decoding instructions in the deliverable so the next skill can run independently.
    shutil.copyfile(Path(__file__).resolve().parents[1] / "references/renderer.md", folder / "特效交接.md")
    output = dict(schema="weather-surface-physics/v1", image_sha256=data["sha256"],
                  manifest_sha256=manifest_hash, region_pack_sha256=signature,
                  size=data["size"], analysis_size=list(small.size), region_map="regions.png",
                  reference="reference.jpg", preview="preview.jpg", instructions="特效交接.md",
                  scenario=dict(weather=args.weather, temperature_c=temperature,
                                temperature_source="specified" if args.temperature is not None else "assumed",
                                old_snow=config.get("old_snow", 0), plan=plan if args.answers else None,
                                motion_source="plan" if args.answers else "assumed_static",
                                total_rain=rain, total_snow=snow, visual_gain=gain),
                  review=config, geometry_method="Depth Anything V2, upright-camera image-space approximation",
                  maps=static, contact_scale=max(1, rain), direction_codes=list(DIRECTIONS), material_codes=list(MATERIALS),
                  state_scales=scales, keyframes=keyframes, regions=report, balance=balance)
    write(folder / "handoff.json", output)
    preview(folder, small, frames[-1], contact, snow)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--weather", required=True, choices=[*RAIN, *SNOW, *DRY])
    parser.add_argument("--answers", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--old-snow", type=float)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("输出目录已存在，请指定新的交接包目录。")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with TemporaryDirectory(dir=args.out.parent) as tmp:
            stage = Path(tmp) / "package"
            stage.mkdir()
            export(args, stage)
            stage.rename(args.out)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"仿真失败：{exc}\n")
    print(args.out / "handoff.json")


if __name__ == "__main__":
    main()
