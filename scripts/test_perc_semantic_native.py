"""Native boundary tests with archived trained heads; no fresh-source claim."""

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import struct
import tempfile
import unittest

from perc1.schema import canonical, sha
from perc1.semantic_replay_data import load_replay


@unittest.skipUnless(
    os.environ.get("PERC1_SEMANTIC_NATIVE_BINARY"), "native binary not configured"
)
class SemanticNativeBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary = Path(os.environ["PERC1_SEMANTIC_NATIVE_BINARY"]).resolve(
            strict=True
        )
        archive = (
            Path(__file__).resolve().parents[1]
            / "qualification/perc-semantic-owner-20261110/raw-evidence-v1.tar.xz"
        )
        manifest, cases = load_replay(archive)
        cls.source_sha = sha(manifest)
        cls.case = next(case for case in cases if case["split"] == "confirmation")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="perc-semantic-native-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sequence = 0

    def inputs(self, *, head=None, features=None):
        self.sequence += 1
        directory = self.root / str(self.sequence)
        directory.mkdir()
        head_raw = self.case["head_raw"] if head is None else canonical(head) + b"\n"
        head_path = directory / "head.json"
        head_path.write_bytes(head_raw)
        envelope = {
            "schema": "perc1.semantic-native-features.v1",
            "rows": self.case["rows"].tolist()
            if hasattr(self.case["rows"], "tolist")
            else copy.deepcopy(self.case["rows"]),
            "candidate_ids": list(self.case["candidate_ids"]),
            "source_manifest_sha256": self.source_sha,
            "head_sha256": sha(head_raw),
            "projection_sha256": self.case["head"]["projection_sha256"],
        }
        if features is not None:
            features(envelope)
        feature_path = directory / "features.json"
        feature_path.write_bytes(canonical(envelope) + b"\n")
        return directory, feature_path, head_path

    def invoke(self, argv, *, refusal=None):
        result = subprocess.run(
            [str(self.binary), *map(str, argv)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(
            result.returncode,
            1 if refusal else 0,
            result.stderr.decode(errors="replace"),
        )
        if refusal:
            self.assertIn(refusal, result.stderr.decode())
        return result

    def assert_no_dispatch(self, directory):
        self.assertFalse((directory / "output.json").exists())
        self.assertFalse((directory / "owner/head-claim.bin").exists())
        self.assertFalse((directory / "owner/head-receipt.json").exists())

    def test_head_and_projection_binding_refused_before_dispatch(self):
        for key, reason in (
            ("head_sha256", "head byte binding mismatch"),
            ("projection_sha256", "projection binding mismatch"),
        ):
            with self.subTest(key=key):
                directory, features, head = self.inputs(
                    features=lambda value: value.update({key: "0" * 64})
                )
                self.invoke(
                    [
                        "start",
                        directory / "owner",
                        features,
                        head,
                        directory / "output.json",
                    ],
                    refusal=reason,
                )
                self.assert_no_dispatch(directory)

    def test_duplicate_candidate_catalog_refused_before_dispatch(self):
        def duplicate(value):
            value["candidate_ids"][1] = value["candidate_ids"][0]

        directory, features, head = self.inputs(features=duplicate)
        self.invoke(
            ["start", directory / "owner", features, head, directory / "output.json"],
            refusal="invalid candidate catalog",
        )
        self.assert_no_dispatch(directory)

    def test_invalid_trained_model_refused_before_dispatch(self):
        for field in ("scale", "hidden_shape"):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.case["head"])
                if field == "scale":
                    changed["normalization"]["scale"][0] = 0.0
                else:
                    changed["parameters"]["w1"][0].pop()
                directory, features, head = self.inputs(head=changed)
                self.invoke(
                    [
                        "start",
                        directory / "owner",
                        features,
                        head,
                        directory / "output.json",
                    ],
                    refusal="invalid semantic head",
                )
                self.assert_no_dispatch(directory)

    def test_equal_scores_use_candidate_id_order_and_cold_replay(self):
        def ties(value):
            value["rows"] = [copy.deepcopy(value["rows"][0]) for _ in range(4)]
            value["candidate_ids"] = sorted(value["candidate_ids"], reverse=True)

        directory, features, head = self.inputs(features=ties)
        owner, output = directory / "owner", directory / "output.json"
        self.invoke(["start", owner, features, head, output])
        first = json.loads(output.read_bytes())
        self.assertEqual(len(set(first["logits_f64"])), 1)
        self.assertEqual(first["ranking"], sorted(self.case["candidate_ids"]))
        self.assertEqual(first["trained_semantic_head_inference_executions"], 1)
        replay_path = directory / "replay.json"
        self.invoke(["read", owner, replay_path])
        replay = json.loads(replay_path.read_bytes())
        self.assertEqual(replay["status"], "REPLAYED")
        self.assertEqual(replay["trained_semantic_head_inference_executions"], 0)
        self.assertEqual(replay["inference_readbacks"], 0)
        for key in ("logits_f64", "ranking", "decision"):
            self.assertEqual(replay[key], first[key])

    def test_retained_features_tamper_refused_without_owner_change(self):
        directory, features, head = self.inputs()
        owner = directory / "owner"
        self.invoke(["start", owner, features, head, directory / "output.json"])
        with (owner / "features.json").open("ab") as stream:
            stream.write(b" ")
        before = {
            str(path.relative_to(owner)): sha(path.read_bytes())
            for path in owner.rglob("*")
            if path.is_file()
        }
        output = directory / "tampered.json"
        self.invoke(["read", owner, output], refusal="retained source changed")
        after = {
            str(path.relative_to(owner)): sha(path.read_bytes())
            for path in owner.rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)
        self.assertFalse(output.exists())

    def test_rewritten_scores_with_matching_sidecar_refused(self):
        for replace_vectors in (False, True):
            with self.subTest(replace_vectors=replace_vectors):
                directory, features, head = self.inputs()
                owner = directory / "owner"
                self.invoke(["start", owner, features, head, directory / "output.json"])
                path = owner / "head-receipt.json"
                changed = json.loads(path.read_bytes())
                self.assertIn("logits_bits_u64", changed)
                changed["logits_f64"][0] += 0.25
                if replace_vectors:
                    score_bytes = struct.pack("<4d", *changed["logits_f64"])
                    changed["logits_bits_u64"] = list(struct.unpack("<4Q", score_bytes))
                    scaled = [
                        max(-(8 << 24), min(8 << 24, value * (1 << 24)))
                        for value in changed["logits_f64"]
                    ]
                    changed["drive_q24"] = [
                        math.floor(value + 0.5)
                        if value >= 0
                        else math.ceil(value - 0.5)
                        for value in scaled
                    ] + [0] * 28
                    changed["prediction_q24"] = list(
                        hashlib.sha256(score_bytes).digest()
                    )
                # Keep native field order and compact bytes so the stronger case
                # reaches the committed digest rather than a formatting refusal.
                raw = json.dumps(
                    changed, separators=(",", ":"), ensure_ascii=False, allow_nan=False
                ).encode()
                path.write_bytes(raw)
                (owner / "head-receipt.sha256").write_bytes(
                    hashlib.sha256(raw).digest()
                )
                before = {
                    str(path.relative_to(owner)): sha(path.read_bytes())
                    for path in owner.rglob("*")
                    if path.is_file()
                }
                output = directory / "rewritten.json"
                reason = (
                    "committed semantic output mismatch"
                    if replace_vectors
                    else "retained semantic output mismatch"
                )
                self.invoke(["read", owner, output], refusal=reason)
                after = {
                    str(path.relative_to(owner)): sha(path.read_bytes())
                    for path in owner.rglob("*")
                    if path.is_file()
                }
                self.assertEqual(before, after)
                self.assertFalse(output.exists())

    def test_missing_original_scores_refused_without_owner_change(self):
        directory, features, head = self.inputs()
        owner = directory / "owner"
        self.invoke(["start", owner, features, head, directory / "output.json"])
        (owner / "head-receipt.json").unlink()
        before = {
            str(path.relative_to(owner)): sha(path.read_bytes())
            for path in owner.rglob("*")
            if path.is_file()
        }
        output = directory / "missing-scores.json"
        self.invoke(
            ["read", owner, output],
            refusal="original semantic score receipt unavailable",
        )
        after = {
            str(path.relative_to(owner)): sha(path.read_bytes())
            for path in owner.rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)
        self.assertFalse(output.exists())

    def test_cell_policy_catalog_and_selected_source_mapping(self):
        directory, features, head = self.inputs()
        output = directory / "output.json"
        self.invoke(["start", directory / "owner", features, head, output])
        observed = json.loads(output.read_bytes())
        source_ids = self.case["candidate_ids"]
        self.assertEqual(observed["source_candidate_ids"], source_ids)
        reserved = observed["abstain_candidate_id"]
        self.assertNotIn(reserved, source_ids)
        decision = observed["decision"]
        policy_ids = [candidate["candidate_id"] for candidate in decision["policy"]]
        self.assertEqual(len(policy_ids), 5)
        self.assertEqual(set(policy_ids), set(source_ids) | {reserved})
        selected = decision["selected_candidate"]
        self.assertIn(selected, policy_ids)
        if selected in source_ids:
            self.assertEqual(observed["selected_source_candidate"], selected)
            self.assertIs(observed["abstained"], False)
        else:
            self.assertEqual(selected, reserved)
            self.assertIsNone(observed["selected_source_candidate"])
            self.assertIs(observed["abstained"], True)


if __name__ == "__main__":
    unittest.main()
