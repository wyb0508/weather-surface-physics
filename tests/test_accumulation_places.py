import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from placement import RULES, compile_placement, decide
from infer_places import classify


class PlacementTests(unittest.TestCase):
    def test_tree_crown_trunk_and_shelter(self):
        ids = np.full((32, 30), 2)
        ids[5:15, 7:23] = 1
        ids[15:30, 14:17] = 1
        rows = [dict(id=1, label="tree"), dict(id=2, label="sky")]
        rgb = np.full((32, 30, 3), [28, 110, 30], dtype=np.uint8)
        rgb[15:30, 14:17] = [90, 60, 40]
        up = np.zeros(ids.shape)
        up[5:12] = .8
        up[15:30] = .5  # Conflicting depth estimate on the narrow trunk.
        rgb[22:30, 14:17] = [106, 106, 106]
        up[22:30] = .9
        exposure = np.ones_like(up)
        exposure[8:12, 10:14] = .3
        parts, locations, img = classify(ids, rows, {1: "trees", 2: "sky"}, rgb,
                                         np.zeros_like(up), up, exposure)
        part_ids = np.asarray(img)
        def at(y, x):
            return parts[int(part_ids[y, x]) - 1]
        self.assertTrue((part_ids > 0).all())
        for loc in locations:
            self.assertTrue((ids[part_ids == loc["id"]] == loc["region_id"]).all())
        self.assertEqual(decide(at(5, 12), "积雪")[0], "会")
        self.assertEqual(decide(at(9, 12), "积雪")[0], "不会")
        self.assertIn("树干", at(20, 15)["name"])
        self.assertEqual(decide(at(20, 15), "积雪")[0], "不会")
        self.assertEqual(decide(at(20, 15), "冻雨挂冰")[0], "会")
        self.assertEqual(decide(at(25, 15), "积雪")[0], "不会")
        self.assertEqual(decide(at(3, 15), "积雪")[0], "不会")

    def test_event_rules(self):
        hollow = dict(kind="solid", direct=False, inflow=True, pools=True, wet=True, freezes=True,
                      frost_ready=False, dew_ready=False, traps_hail=True, inflow_hail=True)
        for effect in ("积水", "积水再冻结", "冰雹堆积"):
            self.assertEqual(decide(hollow, effect)[0], "会")
        for effect in ("积雪", "冻雨挂冰", "结霜", "凝露"):
            self.assertEqual(decide(hollow, effect)[0], "不会")
        self.assertEqual(decide({"kind": "solid"}, "积水")[0], "保守略过")
        for effect in RULES:
            self.assertEqual(decide({"kind": "air"}, effect)[0], "不会")

    def test_inventory_must_cover_current_pack(self):
        data = dict(sha256="photo", regions=[dict(id=1, label="sky")],
                    groups=[dict(key="sky", region_ids=[1])])
        spec = dict(manifest_sha256="pack", parts=[])
        with self.assertRaises(ValueError):
            compile_placement(data, spec, "pack", ["大雪"])
        spec["parts"] = [dict(region_id=1, kind="air", name="天空")]
        with self.assertRaises(ValueError):
            compile_placement(data, spec, "other", ["大雪"])
        out = compile_placement(data, spec, "pack", ["大雪"])
        self.assertEqual(out["regions"][0]["placement"]["大雪"]["不会"], ["天空"])
