"""Local weather material preparation."""
import numpy as np
from PIL import Image

from .vision import ROOT, MEAN, STD, grayscale, infer, load_photo, segment_scene, soften, tensor

GROUPS = {
    "sky": "sky",
    "trees": "tree plant palm flower",
    "grass": "grass field",
    "ground": "road sidewalk earth path sand runway land stairs stairway step",
    "water": "water sea river lake waterfall",
    "structure": "wall building house bridge skyscraper tower fence railing",
    "terrain": "mountain hill rock",
}
# Chinese labels and inspector colours use the same keys as the renderer.
LEGEND = {
    "subject": ("主体", "#ff995e"), "sky": ("天空", "#679de5"),
    "trees": ("树木／灌木", "#438b63"), "grass": ("草坪／田地", "#aaca55"), "ground": ("地面", "#cfa956"),
    "water": ("水面", "#4fbfc3"), "structure": ("建筑", "#ac91cc"),
    "terrain": ("山石", "#bd8976"), "other": ("其他", "#747b80"),
}


def geometry(photo, size):
    # Preserve aspect ratio and cap patch count for panoramic inputs.
    scale = 518 / max(photo.size)
    dims = tuple(max(14, round(n * scale / 14) * 14) for n in photo.size)
    rgb = np.asarray(photo.resize(dims, Image.Resampling.BICUBIC), dtype=np.float32) / 255
    pixels = np.ascontiguousarray(((rgb - MEAN) / STD).transpose(2, 0, 1)[None])
    prediction = infer("depth.onnx", pixels)
    raw = np.asarray(Image.fromarray(prediction).resize(size, Image.Resampling.BILINEAR))
    low, high = np.percentile(raw, [1, 99])
    disparity = np.clip((raw-low)/max(high-low, 1e-5), 0, 1)
    # Approximate a perspective surface from relative inverse depth, assuming an
    # upright camera. Its camera-up component is a deposition cue, not a measured angle.
    inverse_z = .25 + soften(disparity, 1.6)
    def gradient(axis):
        if inverse_z.shape[axis] < 2:
            return np.zeros_like(inverse_z)
        return np.gradient(inverse_z, axis=axis)
    focal = max(size)*.8
    dx, dy = gradient(1)*focal, gradient(0)*focal
    yy, xx = np.indices(raw.shape)
    nz = inverse_z - (xx-size[0]/2)*dx/focal - (yy-size[1]/2)*dy/focal
    upward = np.clip(dy / np.sqrt(dx*dx + dy*dy + nz*nz + 1e-6), 0, 1)
    # A nearer surface directly overhead can shelter the one behind it.
    exposure = np.ones_like(disparity)
    for distance in (max(1,size[1]//80), max(2,size[1]//28)):
        delta = disparity[:-distance] - disparity[distance:]
        exposure[distance:] *= 1 - .5*np.clip((delta-.08)*4, 0, 1)
    return disparity, upward, exposure


def analyze(photo, scene, plan, folder, groups=None):
    groups = groups or {}
    small, original_labels, names = scene
    w, h = small.size
    ids = {name.strip():int(idx) for idx,name in names.items()}
    labels = original_labels.copy()
    for source, target in plan["merge_into"].items():
        labels[original_labels == ids[source]] = ids[target]
    selected = plan["subject"]
    if selected == "none":
        fg = np.zeros((h, w), dtype=np.float32)
    elif selected.startswith("group:"):
        fg = soften(groups[selected[6:]], .7)
    elif selected == "salient":
        raw = infer("foreground.onnx", tensor(photo, 320, relative=True))[0]
        fg = np.asarray(grayscale(raw).resize((w,h), Image.Resampling.BILINEAR), dtype=np.float32)/255
        if (fg>.5).mean() < .001 or (fg>.5).mean() > .99:
            raise ValueError("显著主体边界不明确，请在分区图中指定主体类别。")
    else:
        fg = soften(labels == ids[selected], .7)

    depth, up, exposure = geometry(photo, (w,h))
    grayscale(depth).save(folder / "相对深度.png")
    grayscale(up).save(folder / "朝上表面估计.png")
    for key in plan["sheltered"]:
        if key.startswith("group:"):
            exposure *= ~groups[key[6:]]
        else:
            exposure *= (1-fg) if key=="salient" else (labels!=ids[key])
    # Interpret reviewed surface groups while preserving subsequent explicit class merges.
    surface = {}
    for key, material in (("track", "ground"), ("ground", "ground"), ("sky", "sky"), ("water", "water")):
        if key in groups:
            mask = groups[key] & (labels == original_labels)
            surface[material] = surface.get(material, False) | mask
    reviewed = np.logical_or.reduce(list(surface.values())) if surface else np.zeros_like(labels, bool)
    materials = {}
    for key, group in GROUPS.items():
        valid = set(group.split())
        if key == "water":
            valid.add("swimming pool")
        if key == "ground":
            valid.add("dirt track")
        raw_mask = np.isin(labels, [ids[n] for n in valid if n in ids])
        materials[key] = soften((raw_mask & ~reviewed) | surface.get(key, False), .7)
    # Physics uses material even when the user selects it as the main subject.
    # Selection changes its motion/occlusion, not what it is made of.
    rgb = np.asarray(small,dtype=np.float32)/255
    lum = rgb @ np.array([.2126,.7152,.0722],dtype=np.float32)
    edges = np.clip((lum-soften(lum,max(1,w/145)))*4.5,0,1)
    offset = max(1,round(h*.009))
    rim = np.clip(fg-np.pad(fg,((offset,0),(0,0)),mode="edge")[:-offset],0,1)
    ground_gain = {"wet":.23,"natural":.72,"cold":1.}[plan["ground_snow"]]
    snow = (ground_gain*materials["ground"]*(.38+.62*up) +
            materials["grass"]*(.50+.34*up+.16*edges) +
            materials["trees"]*(.07+.30*up+.52*edges) +
            materials["terrain"]*(.10+.70*up+.20*edges) +
            materials["structure"]*(.64*up+.16*edges))
    unknown = np.clip(1-sum(materials.values()),0,1)
    snow += unknown*(.65*up+.30*rim+.08*edges)
    motion_gain = {None:1., "stationary":1., "moving":.55, "high_speed":.12}[plan["motion"]]
    snow *= (1-fg*(1-motion_gain)) * exposure
    rng = np.random.default_rng(73)
    # Blend broad drifts with finer grains to preserve the original surface texture.
    patch_grid = rng.uniform(.4, 1, (max(2,h//26), max(2,w//26))).astype("float32")
    patches = np.asarray(Image.fromarray(patch_grid).resize((w,h), Image.Resampling.BICUBIC))
    snow *= (.35 + .65*patches) * rng.uniform(.90,1,(h,w))
    snow = np.clip(snow*(1-materials["sky"])*(1-materials["water"]),0,1)
    wet_surface = (.48*materials["ground"] + .25*materials["water"] + .18*materials["grass"]+
                   .13*materials["trees"]+.15*materials["structure"]+.18*unknown)
    rain = np.clip(exposure*wet_surface,0,1)
    masks = {k:v*(1-fg) for k,v in materials.items()}
    masks["subject"] = fg
    masks["other"] = np.clip(1-sum(masks.values()),0,1)
    debug = np.zeros_like(rgb)
    for key,(_,color) in LEGEND.items():
        debug += masks[key][...,None]*np.array(tuple(bytes.fromhex(color[1:])))/255
    inspector = Image.fromarray((np.clip(.30*rgb+.70*debug,0,1)*255).astype("uint8"))
    water = materials["water"]*exposure
    ys,xs = np.where(water>.75)
    points = []
    if len(xs) >= max(16,round(w*h*.003)):
        for i in np.random.default_rng(91).choice(len(xs),size=min(80,len(xs)),replace=False):
            points.append([round(float(xs[i]+.5)/w,5), round(float(ys[i]+.5)/h,5)])
    coverage = {k:round(float(v.mean()),4) for k,v in masks.items()}
    surface_report = {}
    for idx in np.unique(labels):
        region = labels==idx
        surface_report[names[str(idx)].strip()] = {
            "pixels":int(region.sum()), "exposure":round(float(exposure[region].mean()),3),
            "snow_mean":round(float(snow[region].mean()),3), "rain_mean":round(float(rain[region].mean()),3)}
    report = {"subject_class":selected,"subject_motion":plan["motion"],"coverage":coverage,
              "scene_classes":{k:round(v["pixels"]/labels.size,4) for k,v in surface_report.items()},
              "surface_effects":surface_report,"water_points":points,"size":list(photo.size)}
    render_masks = dict(subject=fg*(1-materials["sky"])*(1-materials["water"]),
                        sky=materials["sky"], water=water)
    return render_masks, snow, rain, inspector, report
