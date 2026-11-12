"""Actual optimizer/native owner contracts on synthetic utility/latent fixtures.

These tests make no real-image, capture, fresh-source or task-benefit claim.
They fail instead of skipping when the explicitly required native binary is absent.
"""

import copy
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

import numpy as np
from perc1.acquisition import features
from perc1.mlp_head import predict, train_head
from perc1.schema import canonical, sha
from perc1_trained_native import envelope
from test_perc1_acquisition import pair


class TrainedNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = Path(os.environ["PERC1_TRAINED_NATIVE_BINARY"]).resolve(
            strict=True
        )
        cls.recipe = sha("synthetic native feature recipe")

        def example(group, split, value):
            item = pair(group, split, value)
            item["features"]["task_goal"] = [0.0]
            item["features"]["acquired_latent"] = [
                value / (i + 1) for i in range(4) for _ in range(16)
            ]
            return item

        cls.train = [
            example("t" + str(i), "train", x)
            for i, x in enumerate((-1.0, -0.5, 0.5, 1.0))
        ]
        cls.dev = [
            example("d" + str(i), "dev", x) for i, x in enumerate((-1.0, 0.0, 1.0))
        ]
        groups = {
            "train": [p["source_group"] for p in cls.train],
            "dev": [p["source_group"] for p in cls.dev],
            "confirmation": ["unused"],
        }
        cls.head = train_head(
            cls.train,
            cls.dev,
            groups,
            feature_extractor_sha256=cls.recipe,
            seed=3,
            steps=256,
            hidden=8,
        )
        cls.bindings = {
            key: sha("synthetic fixture/" + key)
            for key in (
                "feature_profile_sha256",
                "original_image_sha256",
                "producer_wire_sha256",
                "latent_receipt_sha256",
                "source_evidence_sha256",
                "source_manifest_sha256",
                "projection_sha256",
            )
        }
        cls.bindings["feature_extractor_sha256"] = cls.recipe

    def setUp(self):
        retained = os.environ.get("PERC1_NATIVE_TEST_ARTIFACTS")
        if retained:
            self.root = Path(retained) / self._testMethodName
            self.root.mkdir(parents=True, exist_ok=False)
        else:
            temporary = tempfile.TemporaryDirectory(prefix="perc-trained-native-")
            self.addCleanup(temporary.cleanup)
            self.root = Path(temporary.name)
        self.sequence = 0

    def candidate(self, sign=1.0, name="extra"):
        public = copy.deepcopy(self.dev[-1]["features"])
        public["acquired_latent"] = [
            sign / (i + 1) for i in range(4) for _ in range(16)
        ]
        return dict(id=name, upper_cost=4, features=public)

    def inputs(self, candidates=None, mutate=None, head=None):
        self.sequence += 1
        folder = self.root / str(self.sequence)
        folder.mkdir()
        raw = canonical(self.head if head is None else head) + b"\n"
        value = envelope(raw, candidates or [self.candidate()], self.bindings)
        if mutate:
            mutate(value)
        (folder / "head.json").write_bytes(raw)
        (folder / "features.json").write_bytes(canonical(value) + b"\n")
        return folder

    def invoke(self, folder, mode="start", refusal=None, output="output.json"):
        args = [str(self.binary), mode, str(folder / "owner")]
        if mode != "read":
            args += [str(folder / "features.json"), str(folder / "head.json")]
        args += [str(folder / output)]
        result = subprocess.run(args, capture_output=True, timeout=20)
        (folder / (output + ".stdout.log")).write_bytes(result.stdout)
        (folder / (output + ".stderr.log")).write_bytes(result.stderr)
        self.assertEqual(result.returncode, 1 if refusal else 0, result.stderr.decode())
        if refusal:
            self.assertIn(refusal, result.stderr.decode())
            self.assertFalse((folder / output).exists())
            return None
        return json.loads((folder / output).read_bytes())

    def snapshot(self, folder):
        return {
            str(p.relative_to(folder)): sha(p.read_bytes())
            for p in folder.rglob("*")
            if p.is_file()
        }

    def test_native_fp64_parity_visual_change_and_cold_replay(self):
        choices = []
        for sign in (-1.0, 1.0):
            candidate = self.candidate(sign)
            folder = self.inputs([candidate])
            first = self.invoke(folder)
            x = (
                np.asarray(features(candidate["features"])) - self.head["means"]
            ) / self.head["scales"]
            p = self.head["parameters"]
            expected = (
                np.tanh(x @ p["w1"] + p["b1"]) @ p["w2"]
                + p["b2"]
                + self.head["calibration"]["bias"]
            )
            np.testing.assert_allclose(
                first["raw_outputs_f64"][0], expected, rtol=5e-12, atol=5e-12
            )
            self.assertEqual(first["trained_head_inference_executions"], 1)
            self.assertTrue(first["cell_selection_matches_native_fp64"])
            choices.append(first["decision"]["selected_candidate"])
            cold = self.invoke(folder, "read", output="cold.json")
            self.assertEqual(
                (
                    cold["status"],
                    cold["trained_head_inference_executions"],
                    cold["inference_readbacks"],
                ),
                ("REPLAYED", 0, 0),
            )
            for key in ("raw_bits_u64", "decision", "carrier_q24"):
                self.assertEqual(cold[key], first[key])
        self.assertEqual(choices, ["abstain", "extra"])

    def test_lost_ack_recovers_original_without_new_mlp_execution(self):
        folder = self.inputs()
        pending = self.invoke(folder, "lose-ack")
        recovered = self.invoke(folder, "read", output="recovered.json")
        self.assertEqual(
            (pending["status"], pending["trained_head_inference_executions"]),
            ("PENDING_ORIGINAL_READBACK", 1),
        )
        self.assertEqual(
            (
                recovered["status"],
                recovered["trained_head_inference_executions"],
                recovered["inference_readbacks"],
            ),
            ("COMMITTED", 0, 1),
        )
        self.assertEqual(recovered["raw_bits_u64"], pending["raw_bits_u64"])

    def test_ties_keep_catalog_order_and_budget_mask_is_enforced(self):
        candidates = [self.candidate(name=name) for name in ("z", "a", "m")]
        folder = self.inputs(candidates)
        value = self.invoke(folder)
        self.assertEqual(value["decision"]["selected_candidate"], "z")
        candidates[0]["upper_cost"] = 101
        folder = self.inputs(candidates)
        self.assertEqual(self.invoke(folder)["decision"]["selected_candidate"], "a")

    def test_large_log_budget_and_three_dense_rows_use_lossless_carrier(self):
        candidates = [
            self.candidate(name=name) for name in ("upper", "middle", "lower")
        ]
        for i, candidate in enumerate(candidates):
            candidate["features"]["remaining_budget"] = 4_000_000
            candidate["features"]["task_goal"] = [i / 4]
            candidate["features"]["acquired_latent"][-1] = float.fromhex(
                "0x1.23456789abcdep-3"
            )
        folder = self.inputs(candidates)
        value = self.invoke(folder)
        self.assertLessEqual(len(value["carrier_q24"]), 512)
        self.assertEqual(
            value["feature_rows_sha256"],
            json.loads((folder / "features.json").read_bytes())["feature_rows_sha256"],
        )

    def test_sub_q24_positive_margin_and_near_tie_keep_fp64_choice(self):
        candidate = self.candidate()
        gain = predict(self.head, candidate["features"])["expected_gain"]
        head = copy.deepcopy(self.head)
        head["threshold"] = gain - 0.25 / (1 << 24)
        folder = self.inputs([candidate], head=head)
        value = self.invoke(folder)
        self.assertEqual(value["decision"]["selected_candidate"], "extra")
        self.assertTrue(value["cell_selection_matches_native_fp64"])
        candidates = [
            self.candidate(0.1, "earlier"),
            self.candidate(0.1 + 1e-10, "later"),
        ]
        scores = [
            predict(self.head, c["features"])["expected_gain"] for c in candidates
        ]
        self.assertTrue(0 < scores[1] - scores[0] < 0.5 / (1 << 24), scores)
        folder = self.inputs(candidates)
        value = self.invoke(folder)
        self.assertEqual(value["decision"]["selected_candidate"], "later")
        self.assertTrue(value["cell_selection_matches_native_fp64"])

    def test_identity_and_catalog_errors_reject_before_dispatch(self):
        for key in (
            "head_sha256",
            "head_canonical_sha256",
            "feature_rows_sha256",
            "carrier_digest",
        ):
            folder = self.inputs(mutate=lambda v: v.update({key: "0" * 64}))
            reason = (
                "head raw/canonical"
                if key.startswith("head_")
                else "lossless feature/carrier"
            )
            self.invoke(folder, refusal=reason)
            self.assertFalse((folder / "owner/head-claim.bin").exists())
        folder = self.inputs(
            mutate=lambda v: v["source_bindings"].update(
                feature_extractor_sha256="0" * 64
            )
        )
        self.invoke(folder, refusal="source/feature recipe binding")
        folder = self.inputs([self.candidate(), self.candidate()])
        self.invoke(folder, refusal="invalid candidate catalog")

    def test_invalid_normalization_rejects_before_owner_admission(self):
        folder = self.inputs()
        head = copy.deepcopy(self.head)
        head["scales"][0] = 0.0
        raw = canonical(head) + b"\n"
        (folder / "head.json").write_bytes(raw)
        value = json.loads((folder / "features.json").read_bytes())
        value.update(head_sha256=sha(raw), head_canonical_sha256=sha(canonical(head)))
        (folder / "features.json").write_bytes(canonical(value) + b"\n")
        self.invoke(folder, refusal="invalid trained acquisition head")
        self.assertFalse((folder / "owner").exists())

    def test_excess_carrier_refuses_without_clipping_or_substitution(self):
        def exceed(value):
            width = len(value["rows"][0])
            value.update(
                rows=[
                    [float(i * width + j) + 0.125 for j in range(width)]
                    for i in range(3)
                ],
                candidate_ids=["a", "b", "c"],
                upper_costs=[4, 4, 4],
            )

        folder = self.inputs(mutate=exceed)
        self.invoke(folder, refusal="original 512 scalar cap")
        self.assertFalse((folder / "owner").exists())

    def test_source_tamper_does_not_mutate_owner(self):
        folder = self.inputs()
        self.invoke(folder)
        path = folder / "owner/features.json"
        path.write_bytes(path.read_bytes() + b" ")
        before = self.snapshot(folder / "owner")
        self.invoke(
            folder, "read", refusal="retained source changed", output="refused.json"
        )
        self.assertEqual(before, self.snapshot(folder / "owner"))

    def test_rewritten_outputs_cannot_replace_journal_commitment(self):
        for repair_vectors in (False, True):
            folder = self.inputs()
            self.invoke(folder)
            owner = folder / "owner"
            path = owner / "head-receipt.json"
            value = json.loads(path.read_bytes())
            raw = [
                struct.unpack("<d", struct.pack("<Q", v))[0]
                for v in value["raw_bits_u64"][0]
            ]
            raw[0] += 0.25
            value["raw_bits_u64"][0] = [
                struct.unpack("<Q", struct.pack("<d", v))[0] for v in raw
            ]
            if repair_vectors:
                net = max(-1, min(1, raw[0])) - self.head["cost_value"] * max(
                    0, raw[1] * 1e6
                )
                value["drive_q24"][0] = (
                    (1 << 24) // 4 if net > self.head["threshold"] else 0
                )
                value["prediction_q24"] = list(
                    bytes.fromhex(sha(struct.pack("<dd", *raw)))
                )
            retained = canonical(value)
            path.write_bytes(retained)
            (owner / "head-receipt.sha256").write_bytes(bytes.fromhex(sha(retained)))
            before = self.snapshot(owner)
            reason = (
                "committed trained output mismatch"
                if repair_vectors
                else "retained trained output mismatch"
            )
            self.invoke(folder, "read", refusal=reason, output="refused.json")
            self.assertEqual(before, self.snapshot(owner))

    def test_missing_original_output_never_reexecutes(self):
        folder = self.inputs()
        self.invoke(folder, "lose-ack")
        (folder / "owner/head-receipt.json").unlink()
        before = self.snapshot(folder / "owner")
        self.invoke(
            folder,
            "read",
            refusal="original trained output receipt unavailable",
            output="missing.json",
        )
        self.assertEqual(before, self.snapshot(folder / "owner"))


if __name__ == "__main__":
    unittest.main()
