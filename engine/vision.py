"""Shared local image decoding, inference and semantic segmentation."""
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageFilter, ImageOps
from pillow_heif import register_heif_opener

ROOT = Path(__file__).resolve().parents[1]
MEAN = np.array([.485, .456, .406], dtype=np.float32)
STD = np.array([.229, .224, .225], dtype=np.float32)


def oriented_size(path):
    register_heif_opener()
    with Image.open(path) as image:
        return image.size[::-1] if image.getexif().get(274, 1) in (5, 6, 7, 8) else image.size


def load_photo(path):
    register_heif_opener()
    with Image.open(path) as src:
        img = ImageOps.exif_transpose(src).convert("RGBA")
        img.thumbnail((3200, 3200), Image.Resampling.LANCZOS)
        base = Image.new("RGB", img.size, "#202a34")
        base.paste(img, mask=img.getchannel("A"))
        return base


def infer(model, tensor):
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 3
    session = ort.InferenceSession(str(ROOT / 'models' / model), opts,
                                   providers=["CPUExecutionProvider"])
    return session.run([session.get_outputs()[0].name],
                       {session.get_inputs()[0].name: tensor})[0][0]


def tensor(photo, size, relative=False):
    dims = (size, size) if isinstance(size, int) else size
    a = np.asarray(photo.resize(dims, Image.Resampling.BILINEAR), dtype=np.float32)
    a /= max(float(a.max()), 1) if relative else 255.
    return np.ascontiguousarray(((a - MEAN) / STD).transpose(2, 0, 1)[None])


def grayscale(a):
    return Image.fromarray((np.clip(a, 0, 1) * 255).astype('uint8'))


def soften(a, radius):
    return np.asarray(grayscale(a).filter(ImageFilter.GaussianBlur(radius)), dtype=np.float32) / 255


def predict_scene(photo, detail_model=None):
    """Return semantic labels and optional model-by-model labels on the same grid."""
    small = photo.copy()
    small.thumbnail((1024, 1024))
    w, h = small.size
    names = json.loads((ROOT / 'models/classes.json').read_text())['id2label']
    global_logits = infer("scene.onnx", tensor(photo, 512))
    best = np.full((h, w), -np.inf, dtype=np.float32)
    labels = np.zeros((h, w), dtype=np.uint8)

    if detail_model is not None:
        # Match the 32-pixel encoder stride, keeping the source aspect ratio.
        long_side = min(960, max(512, round(max(photo.size) * 1.5)))
        scale = long_side / max(photo.size)
        dims = tuple(max(32, round(n * scale / 32) * 32) for n in photo.size)
        detail_logits = infer(detail_model, tensor(photo, dims))
        global_best, detail_best = best.copy(), best.copy()
        global_ids, detail_ids = labels.copy(), labels.copy()

    def resized(plane):
        return np.asarray(Image.fromarray(plane).resize((w, h), Image.Resampling.BILINEAR))

    # Stream class planes to avoid allocating 150 full-size score maps per view.
    for idx, plane in enumerate(global_logits):
        scores = resized(plane)
        if detail_model is not None:
            fine = resized(detail_logits[idx])
            global_ids[scores > global_best] = idx
            detail_ids[fine > detail_best] = idx
            np.maximum(global_best, scores, out=global_best)
            np.maximum(detail_best, fine, out=detail_best)
            scores = .25 * scores + .75 * fine
        labels[scores > best] = idx
        np.maximum(best, scores, out=best)
    scene = small, labels, names
    if detail_model is not None:
        return scene, (global_ids, detail_ids)
    return scene, None


def segment_scene(photo):
    return predict_scene(photo)[0]
