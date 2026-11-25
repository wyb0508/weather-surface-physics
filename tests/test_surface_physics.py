import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT
sys.path.insert(0, str(SKILL / "scripts"))
from surface import prepare, simulate
from pack_masks import pack


class TableRainAndSnow(unittest.TestCase):
    def setUp(self):
        # One region for the table including its legs; a sheltered floor receives drips.
        ids = np.ones((32, 32), np.uint16)
        ids[12:15, 4:27] = 2
        ids[15:25, 6:8] = 2
        ids[25:] = 3
        ids[:4] = 4
        self.ids = ids
        self.rows = [dict(id=i, label=label) for i, label in
                     enumerate(("wall", "table", "floor", "sky"), 1)]
        self.groups = {i: r["label"] for i, r in enumerate(self.rows, 1)}
        self.config = dict(patches=[
            dict(region_id=2, up=0),
            dict(region_id=2, polygon=[[4, 12], [26, 12], [26, 14], [4, 14]],
                 up=1, flow="right", old_snow=.24)],
            drains=[{"from": dict(region_id=2, polygon=[[25, 12], [26, 12], [26, 14], [25, 14]]),
                     "to": dict(region_id=3, polygon=[[25, 26], [26, 26], [26, 27], [25, 27]])}])

    def fields(self):
        zero = np.zeros(self.ids.shape, np.float32)
        return prepare(self.ids, self.rows, self.groups, (zero, zero, zero+1),
                       zero+1, self.ids == 3, "natural", {}, self.config)[0]

    def test_warm_rain_melts_old_snow_and_feeds_sheltered_floor(self):
        f = self.fields()
        frames, contact, deposited, balance = simulate(self.ids, f, self.config, 1, 0, 7)
        self.assertTrue(np.all(deposited == 0))
        self.assertTrue(np.all(contact[self.ids == 3] == 0))
        for plane in (contact, frames[-1]["film"], frames[-1]["snow"]):
            self.assertFalse(plane[self.ids == 4].any())
        self.assertLess(frames[-1]["snow"][13, 10], frames[0]["snow"][13, 10])
        self.assertGreater(frames[-1]["film"][13, 10], 0)
        self.assertGreater(frames[-1]["landing"][26, 25], 0)
        self.assertGreater(frames[-1]["film"][26, 25], 0)
        self.assertAlmostEqual(float(frames[-1]["drip"].sum()), float(frames[-1]["landing"].sum()), places=5)
        self.assertLess(abs(balance["residual"]), balance["received"] * 1e-6)

    def test_snow_lands_on_top_and_not_on_legs(self):
        f = self.fields()
        frames, contact, snow, _ = simulate(self.ids, f, self.config, 0, .68, -3)
        self.assertFalse(contact.any())
        self.assertGreater(snow[13, 10], .4)
        self.assertEqual(snow[18, 7], 0)
        self.assertLess(frames[1]["snow"][13, 10], frames[2]["snow"][13, 10])
        self.assertFalse(frames[-1]["film"].any())

    def test_custom_masks_to_renderer_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            photo = d / "scene.png"
            Image.fromarray((self.ids * 50).astype(np.uint8)).convert("RGB").save(photo)
            spec = dict(sha256=hashlib.sha256(photo.read_bytes()).hexdigest(), regions=[])
            for r in self.rows:
                name = r["label"] + ".png"
                Image.fromarray(255 * (self.ids == r["id"]).astype(np.uint8)).save(d / name)
                spec["regions"].append(dict(key=r["label"], label=r["label"], mask=name))
            (d / "spec.json").write_text(json.dumps(spec))
            pack(photo, d / "spec.json", d)
            config = dict(self.config, manifest_sha256=hashlib.sha256((d / "manifest.json").read_bytes()).hexdigest(),
                          analysis_size=[32, 32])
            (d / "review.json").write_text(json.dumps(config))
            pkg = d / "package"
            cmd = [str(SKILL / "run.sh"), str(photo), "--manifest", str(d / "manifest.json"),
                   "--review", str(d / "review.json"), "--weather", "大雨", "--out", str(pkg)]
            subprocess.run(cmd, check=True, capture_output=True)
            handoff = json.loads((pkg / "handoff.json").read_text())
            self.assertEqual(len(handoff["regions"]), 4)
            np.testing.assert_array_equal(np.asarray(Image.open(pkg / handoff["region_map"])), self.ids)
            for frame in handoff["keyframes"]:
                for path in frame["maps"].values():
                    with Image.open(pkg / path) as img:
                        self.assertEqual(img.size, (32, 32))
            snow = np.asarray(Image.open(pkg / handoff["keyframes"][0]["maps"]["snow"]))
            self.assertGreater(snow[13, 10], 0)
            self.assertEqual(snow[17, 6], 0)
            self.assertEqual(len(handoff["region_pack_sha256"]), 64)
            config["manifest_sha256"] = "mismatch"
            (d / "review.json").write_text(json.dumps(config))
            cmd[-1] = str(d / "wrong")
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertFalse((d / "wrong").exists())
