"""Strict create-only cross-process Cell handoff study regression."""

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from e12_nonlinear_cert import Law, solve
from e12_study import PROFILES, read_strict, write_once
from e12_cell_boundary_study import produce, review


class BoundaryStudyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.source = self.folder / "original.json"
        self.candidate = self.folder / "candidate.json"
        self.out = self.folder / "review.json"
        rows = [{"profile": asdict(Law(depth=depth, a=a)),
                 "certificate": asdict(solve(Law(depth=depth, a=a)))}
                for depth, a in PROFILES]
        self.source_sha = write_once(str(self.source), {
            "schema": "hepta.e12.nonlinear-stochastic-certified-study.v1",
            "authority": "DENY_ALL",
            "complete_registered_profiles": True,
            "repeat_count": 6,
            "real_pretrained_encoder_forwards": 0,
            "full_lifecycle_cost_or_target_host_attested": False,
            "production_accepted": False,
            "independent_natural_task_outcomes": False,
            "cost_adjusted_online_reasoning_gain": False,
            "continuous_time_fbsde_proven": False,
            "rows": rows,
        })

    def frozen_candidate(self):
        return produce(str(self.source), self.source_sha, str(self.candidate))

    def _mutate_candidate(self, field_edit):
        raw = json.loads(self.candidate.read_text())
        field_edit(raw)
        new = self.folder / "mutated.json"
        digest = write_once(str(new), raw)
        return str(new), digest

    def test_finite_stochastic_six_arm_source_to_independent_review(self):
        digest = self.frozen_candidate()
        result_sha = review(str(self.source), self.source_sha,
                            str(self.candidate), digest, str(self.out))
        self.assertEqual(result_sha, sha256(self.out.read_bytes()).hexdigest())
        obj, _ = read_strict(str(self.out))
        self.assertTrue(obj["whole_public_prefix_graph_checked"])
        self.assertEqual(len(obj["cases"]), 6)
        self.assertEqual([v["review"]["checked_internal_cells"] for v in obj["cases"]],
                         [1, 1, 3, 3, 7, 7])
        self.assertFalse(obj["production_accepted"])
        self.assertFalse(obj["general_continuous_fbsde_or_reasoning_gain_proven"])

    def test_producer_requires_true_preexisting_source_digest(self):
        with self.assertRaises(ValueError):
            produce(str(self.source), "0" * 64, str(self.candidate))
        self.assertFalse(self.candidate.exists())

    def test_reviewer_rejects_wrong_candidate_digest(self):
        self.frozen_candidate()
        with self.assertRaises(ValueError):
            review(str(self.source), self.source_sha, str(self.candidate),
                   "0" * 64, str(self.out))
        self.assertFalse(self.out.exists())

    def test_reviewer_denies_resealed_cross_scope_cell(self):
        self.frozen_candidate()
        path, digest = self._mutate_candidate(
            lambda x: x["cases"][0]["bundle"]["segments"][0].__setitem__(
                "scope_digest", "f" * 64))
        with self.assertRaises(ValueError):
            review(str(self.source), self.source_sha, path, digest, str(self.out))

    def test_reviewer_denies_resealed_wrong_continuation_and_z(self):
        self.frozen_candidate()
        for field in ("y_left", "z", "x_left"):
            path = self.folder / (field + ".json")
            data = json.loads(self.candidate.read_text())
            data["cases"][0]["bundle"]["segments"][0][field] = "0"
            digest = write_once(str(path), data)
            with self.subTest(field=field), self.assertRaises(ValueError):
                review(str(self.source), self.source_sha, str(path), digest, str(self.out))

    def test_reviewer_denies_resealed_tiny_global_bound(self):
        self.frozen_candidate()
        path, digest = self._mutate_candidate(
            lambda x: x["cases"][5]["bundle"].__setitem__(
                "claimed_global_error_bound", "0"))
        with self.assertRaises(ValueError):
            review(str(self.source), self.source_sha, path, digest, str(self.out))

    def test_reviewer_denies_missing_cell_and_extra_field(self):
        self.frozen_candidate()
        for modify in (
            lambda x: x["cases"][5]["bundle"]["segments"].pop(),
            lambda x: x["cases"][0]["bundle"].__setitem__("credential", "false"),
        ):
            data = json.loads(self.candidate.read_text())
            modify(data)
            path = self.folder / ("changed_" + str(len(tuple(self.folder.iterdir()))) + ".json")
            digest = write_once(str(path), data)
            with self.assertRaises(ValueError):
                review(str(self.source), self.source_sha, str(path), digest, str(self.out))

    def test_false_production_claim_or_source_forgery_denied(self):
        self.frozen_candidate()
        for target in ("production_accepted", "natural_reasoning_gain_proven",
                       "producer_has_verified_global_solution"):
            data = json.loads(self.candidate.read_text())
            data[target] = True
            path = self.folder / (target + ".json")
            digest = write_once(str(path), data)
            with self.subTest(field=target), self.assertRaises(ValueError):
                review(str(self.source), self.source_sha, str(path), digest, str(self.out))

    def test_create_only_does_not_overwrite_sealed_evidence(self):
        self.frozen_candidate()
        with self.assertRaises(FileExistsError):
            produce(str(self.source), self.source_sha, str(self.candidate))
        with self.assertRaises(ValueError):
            review(str(self.source), "0"*64, str(self.candidate),
                   sha256(self.candidate.read_bytes()).hexdigest(), str(self.out))


if __name__ == "__main__":
    unittest.main()
