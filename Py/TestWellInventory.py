"""Test numerical rules without importing the licensed ArcPy runtime."""
import ast
import math
from pathlib import Path
import unittest

path = Path(__file__).with_name("WellInventory.pyt")
source = path.read_text(encoding="utf-8")
tree = ast.parse(source, filename=str(path))
compile(tree, str(path), "exec")
functions = ast.Module(body=[node for node in tree.body
                            if isinstance(node, ast.FunctionDef)
                            and node.name in ("lane_offsets", "bench_fields", "finite_positive",
                                              "phase_offsets", "merge_intervals", "conflict_decision")],
                       type_ignores=[])
namespace = {"math": math}
exec(compile(functions, str(path), "exec"), namespace)


class PlacementTests(unittest.TestCase):
    def test_bench_mapping(self):
        self.assertEqual(namespace["bench_fields"](["B_1BS_Spacing", "WCA_Spacing", "DSU_Length"]),
                         {"1BS": "B_1BS_Spacing", "WCA": "WCA_Spacing"})

    def test_ambiguous_bench_rejected(self):
        with self.assertRaises(ValueError):
            namespace["bench_fields"](["B_1BS_Spacing", "1BS_Spacing"])

    def test_centering_and_spacing(self):
        offsets = namespace["lane_offsets"](-2300, 2500, 660)
        self.assertAlmostEqual((offsets[0] + offsets[-1]) / 2, 100)
        self.assertTrue(all(-2300 <= v <= 2500 for v in offsets))
        for a, b in zip(offsets, offsets[1:]):
            self.assertAlmostEqual(b - a, 660)

    def test_narrow_dsu_has_center_lane(self):
        self.assertEqual(namespace["lane_offsets"](100, 200, 660), [150])

    def test_invalid_spacing_and_excessive_count(self):
        for spacing in [0, -1, 0.00001]:
            with self.assertRaises(ValueError):
                namespace["lane_offsets"](0, 5280, spacing)

    def test_positive_values(self):
        for value in [None, 0, -10, float("nan"), float("inf")]:
            self.assertFalse(namespace["finite_positive"](value))
        self.assertTrue(namespace["finite_positive"](660))

    def test_overlap_union_not_double_counted(self):
        result = namespace["conflict_decision"](10000, [(0, 300), (200, 500)], 5, 1000, 0)
        self.assertEqual(result, (0, 10000, 500, False))

    def test_excess_overlap_trims(self):
        self.assertEqual(namespace["conflict_decision"](10000, [(0, 501)], 5, 1000, 0),
                         (501, 10000, 0, True))

    def test_long_parallel_conflict_rejected(self):
        self.assertIsNone(namespace["conflict_decision"](10000, [(0, 10000)], 5, 1000, 0))

    def test_short_stick_uses_its_own_denominator(self):
        self.assertEqual(namespace["conflict_decision"](2000, [(0, 200)], 5, 1000, 0),
                         (200, 2000, 0, True))

    def test_interior_conflict_does_not_bridge(self):
        self.assertEqual(namespace["conflict_decision"](10000, [(3000, 5000)], 5, 1000, 0),
                         (5000, 10000, 0, True))

    def test_minimum_applied_after_trimming(self):
        self.assertIsNone(namespace["conflict_decision"](2000, [(500, 1600)], 5, 1000, 0))

    def test_zero_overlap_trims_any_conflict(self):
        self.assertEqual(namespace["conflict_decision"](10000, [(0, 100)], 0, 1000, 0),
                         (100, 10000, 0, True))

    def test_offset_trials_preserve_spacing(self):
        patterns = list(namespace["phase_offsets"](-2300, 2500, 660, 20))
        self.assertEqual(len(patterns), 21)
        for pattern in patterns:
            self.assertTrue(all(-2300 <= x <= 2500 for x in pattern))
            for a, b in zip(pattern, pattern[1:]):
                self.assertAlmostEqual(b - a, 660)
        self.assertEqual(list(namespace["phase_offsets"](0, 2000, 660, 1)),
                         [namespace["lane_offsets"](0, 2000, 660)])


if __name__ == "__main__":
    unittest.main()
