import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from batch import match_photo, unpack
from location_maps import apply_spatial_review, write_maps
from placement import compile_placement, check_group_masks


class PortableHandoffTests(unittest.TestCase):
    def test_full_size_review_and_caption_share_one_decision_table(self):
        regions = np.array([[1, 1, 2, 1]] * 4)
        small = Image.fromarray(np.array([[1, 2]], dtype=np.uint16))
        parts = [dict(region_id=1, name="面板", kind="solid", direct=True, holds_snow=True),
                 dict(region_id=2, name="信息栏", kind="air")]
        patch = dict(size=[4, 4], patches=[dict(region_id=1, name="垂直边", kind="solid",
                    holds_snow=False, polygon=[[0, 0], [1, 0], [1, 1], [0, 1]])])
        parts, grid = apply_spatial_review(regions, small, parts, {1: "subject", 2: "caption"},
                                           {1: "car", 2: "road"}, patch)
        data = dict(sha256="source", regions=[dict(id=1, label="car"), dict(id=2, label="road")],
                    groups=[dict(key="subject", region_ids=[1]), dict(key="caption", region_ids=[2])])
        report = compile_placement(data, dict(manifest_sha256="m", parts=parts), "m", ["大雪"])
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            write_maps(folder, Image.new("RGB", (4, 4)), grid, parts, report)
            with Image.open(folder / report["maps"]["大雪"]) as mask:
                px = np.array(mask)
            self.assertTrue((px[:, 2] == 0).all())
            self.assertTrue((px[:, 3] == 127).all())
            self.assertEqual(px[0, 0], 0)
            self.assertEqual(px[3, 0], 255)
            for loc in report["locations"]["parts"]:
                self.assertTrue((regions[grid == loc["id"]] == loc["region_id"]).all())

    def test_renamed_photo_and_conflicting_group_mask(self):
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)
            a, b = d / "same.jpg", d / "renamed.jpg"
            a.write_bytes(b"other")
            b.write_bytes(b"matches")
            manifest = dict(source=a.name, sha256=hashlib.sha256(b.read_bytes()).hexdigest())
            self.assertEqual(match_photo(manifest, [a, b], {}), b)
            Image.new("L", (2, 1), 255).save(d / "mask.png")
            with self.assertRaises(ValueError):
                check_group_masks(d / "manifest.json", dict(groups=[dict(key="sky", mask="mask.png",
                                  region_ids=[1])]), np.array([[1, 2]]))

    def test_archive_cannot_write_outside_stage(self):
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)
            with ZipFile(d / "bad.zip", "w") as z:
                z.writestr("../escaped", b"bad")
            with self.assertRaises(ValueError):
                unpack(d / "bad.zip", d / "stage")
            self.assertFalse((d / "escaped").exists())
