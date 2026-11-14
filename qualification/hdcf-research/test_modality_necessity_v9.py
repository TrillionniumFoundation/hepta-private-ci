"""All results here are synthetic; not actual Encoder inference."""
import copy
import hashlib
import unittest

from modality_necessity_v9 import Denied, seal_predictions, score_postseal


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def fixture():
    cases = [{"id": f"case{i}", "family": f"source{i//8}",
              "event_sha256": sha(f"event{i}")} for i in range(16)]
    arms = {}
    for name, offset in (("full", .65), ("ablated", .35)):
        arms[name] = [dict(row, p1=offset if i % 2 == 0 else 1-offset)
                      for i, row in enumerate(cases)]
    payload = {"schema": "hepta.hdcf.modality-necessity-pair.v9",
               "modality": "image", "source_digest": sha("source"),
               "full_model_digest": sha("model"), "ablated_model_digest": sha("model"),
               "cases": cases, "full": arms["full"], "ablated": arms["ablated"],
               "work": {"full_forward_count": 16, "ablated_forward_count": 16,
                        "full_cpu_ns": 12, "ablated_cpu_ns": 13}}
    seal = seal_predictions(payload)
    labels = {"seal_digest": seal["seal_digest"],
              "targets": [{"id": f"case{i}", "target": int(i % 2 == 0)}
                          for i in range(16)]}
    return payload, seal, labels


class NecessityTests(unittest.TestCase):
    def test_seal_and_reviewer(self):
        payload, seal, labels = fixture()
        out = score_postseal(payload, seal, labels)
        self.assertEqual(out["full_only"], 16)
        self.assertEqual(out["ablation_only"], 0)
        self.assertEqual(out["nominal_p"], 2 / 2**16)
        self.assertEqual(out["disposition"], "HOLD_NO_GO")
        self.assertFalse(out["modality_necessary_verified"])

    def test_model_not_real(self):
        self.assertFalse(fixture()[1]["model_provenance_verified"])

    def test_inert_modality_rejected(self):
        p, _, _ = fixture()
        p["ablated"] = copy.deepcopy(p["full"])
        with self.assertRaises(Denied):
            seal_predictions(p)

    def test_source_collision_rejected(self):
        p, _, _ = fixture()
        p["cases"][1]["event_sha256"] = p["cases"][0]["event_sha256"]
        with self.assertRaises(Denied):
            seal_predictions(p)

    def test_family_diversity_floor(self):
        p, _, _ = fixture()
        for row in p["cases"]:
            row["family"] = "one-source"
        with self.assertRaises(Denied):
            seal_predictions(p)

    def test_target_never_in_train_input(self):
        p, _, _ = fixture()
        p["cases"][0]["target"] = 1
        with self.assertRaises(Denied):
            seal_predictions(p)

    def test_wrong_targets_rejected(self):
        p, seal, labels = fixture()
        labels["targets"][0]["id"] = "case1"
        with self.assertRaises(Denied):
            score_postseal(p, seal, labels)

    def test_tampered_sealed_predictions_rejected(self):
        p, seal, labels = fixture()
        p["full"][0]["p1"] = .75
        with self.assertRaises(Denied):
            score_postseal(p, seal, labels)

    def test_wrong_seal_digest_rejected(self):
        p, seal, labels = fixture()
        labels["seal_digest"] = sha("fake")
        with self.assertRaises(Denied):
            score_postseal(p, seal, labels)

    def test_negative_work_rejected(self):
        p, _, _ = fixture()
        p["work"]["full_cpu_ns"] = -1
        with self.assertRaises(Denied):
            seal_predictions(p)

    def test_nan_rejected(self):
        p, _, _ = fixture()
        p["ablated"][0]["p1"] = float("nan")
        with self.assertRaises(Denied):
            seal_predictions(p)

    def test_bool_work_rejected(self):
        p, _, _ = fixture()
        p["work"]["full_forward_count"] = True
        with self.assertRaises(Denied):
            seal_predictions(p)


if __name__ == "__main__":
    unittest.main()
