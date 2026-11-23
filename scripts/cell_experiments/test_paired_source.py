import copy
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from . import chat_protocol, data, paired_source
from .test_data import record


def draft(root, record_id, answer, policy, original, tick):
    payload = data.canonical(original)
    digest = hashlib.sha256(payload).hexdigest()
    (root / "originals").mkdir(exist_ok=True)
    paired_source._publish_bytes(root / "originals" / digest, payload)
    r = record(700)
    r.update(
        record_id=record_id,
        observed_at=tick,
        available_at=tick,
        origin_kind="authorized_agent_run",
        task_id="development-receipt-700",
        source={
            "repository": "hepta-qualification-local",
            "path": record_id,
            "revision": None,
            "sha256": digest,
        },
        authorization={
            "training_allowed": True,
            "evaluation_allowed": True,
            "scope": "locally authored artifact sink exercise, zero human participants",
            "rights_basis": "project-created local experiment",
        },
        final_answer=answer,
    )
    r.pop("verified_outcome", None)
    r["task"] = {
        "input": "Return the JSON integer one for this amber receipt.",
        "verifier": {
            "name": "json_artifact",
            "version": "1",
            "parameters": {"expected": 1},
        },
    }
    r["trajectory"] = [
        {
            "kind": "action",
            "actor": "student",
            "content": answer,
            "index": 0,
            "executed": False,
            "receipt_actor": "student",
            "policy_sha256": policy,
        }
    ]
    return r


def capture(root, tag, answer, policy, raw, tick):
    r = draft(root, tag, answer, policy, raw, tick)
    return paired_source.capture_attempt(
        r, root / (tag + ".artifact"), root / "originals", root / (tag + ".json")
    )


class SourceTests(unittest.TestCase):
    def test_real_create_only_readback_failure_mask_and_bound_source(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            a = capture(root, "failure", "0", "a" * 64, {"action": "0"}, 1)
            b = capture(root, "correction", "1", "b" * 64, {"action": "1"}, 2)
            result = paired_source.derive(a, b, root / "originals")
            self.assertEqual(
                result["derivation"],
                {"failure": data.record_digest(a), "correction": data.record_digest(b)},
            )
            self.assertEqual(result["final_answer"], "1")
            ex = chat_protocol.training_examples(
                [result], "trajectory", chat_protocol.LEGACY
            )[0]
            self.assertEqual(
                [(s["content"], s["train"]) for s in ex["segments"]],
                [("0", False), ("1", True)],
            )
            self.assertEqual(
                capture(root, "failure", "0", "a" * 64, {"action": "0"}, 1), a
            )
            (root / "originals" / b["source"]["sha256"]).write_bytes(b"x")
            with self.assertRaisesRegex(ValueError, "original source bytes"):
                paired_source.derive(a, b, root / "originals")

    def test_foreign_destination_and_altered_outcomes_refuse(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "failure.artifact").write_bytes(b"0")
            with self.assertRaisesRegex(ValueError, "another write"):
                capture(root, "failure", "0", "a" * 64, {"action": "0"}, 1)
            a = capture(root, "separate", "0", "a" * 64, {"action": "0"}, 1)
            b = capture(root, "correction", "1", "b" * 64, {"action": "1"}, 2)
            for field, val in (("task_id", "other"), ("lineage_id", "wrong")):
                bad = {**b, field: val}
                with self.assertRaisesRegex(ValueError, "different tasks"):
                    paired_source.derive(a, bad, root / "originals")
            wrong = copy.deepcopy(b)
            wrong["trajectory"][0]["receipt_sha256"] = a["trajectory"][0][
                "receipt_sha256"
            ]
            with self.assertRaisesRegex(ValueError, "readback differs"):
                paired_source.derive(a, wrong, root / "originals")
            b["authorization"]["training_allowed"] = False
            with self.assertRaisesRegex(ValueError, "permit training"):
                paired_source.derive(a, b, root / "originals")

    def test_source_identity_uses_issuer_namespace(self):
        with TemporaryDirectory() as d:
            r = draft(Path(d), "first", "0", "a" * 64, {}, 1)
            original = paired_source.known_source_keys(r)
            other = copy.deepcopy(r)
            other["source"]["repository"] = "another-issuer"
            other["source"]["sha256"] = "c" * 64
            self.assertFalse(original & paired_source.known_source_keys(other))
