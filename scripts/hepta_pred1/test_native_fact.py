"""Synthetic native wire fixtures and parser/file-reader boundary tests."""

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest

from .native_fact import _parse_native, read_native_fact

OWNER = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12"


def wire(fact, ordered=False):
    # Independent fixture encoder for both workspace serde_json feature modes.
    def encode(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()

    if not ordered:
        fact = json.loads(json.dumps(fact, sort_keys=True))
    semantic = dict(fact)
    del semantic["caller_time_ms"]
    if ordered:
        last = list(fact)[-1]
        order = [
            last if key == "caller_time_ms" else key for key in fact if key != last
        ]
        semantic = {key: semantic[key] for key in order}
    return encode(
        {
            "schema_version": 1,
            "semantic_sha256": sha256(encode(semantic)).hexdigest(),
            "fact_sha256": sha256(encode(fact)).hexdigest(),
            "fact": fact,
        }
    )


class NativeFactFixture:
    """Shared setup only; no inherited test cases are collected twice."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.identity = {
            "owner_agent_id": OWNER,
            "run_id": "run",
            "step_id": "step",
            "attempt": 1,
            "intent_digest": "1" * 64,
            "payload_digest": "2" * 64,
            "binding_digest": "3" * 64,
            "destination_id": "destination",
        }
        self.fact = {
            "schema": "hepta-native-predispatch-shadow-fact-v1",
            "owner_agent_id": OWNER,
            "intent": {
                "run_id": "run",
                "step_id": "step",
                "attempt": 1,
                "operation_id": "op",
                "subject_id": OWNER,
                "destination_id": "destination",
                "payload_digest": "2" * 64,
                "final_use_scope_digest": "4" * 64,
                "policy_generation": 1,
                "expected_predecessor_digest": None,
                "dependencies": [],
                "compensation_for": None,
            },
            "claimed_step": {
                "owner_agent_id": OWNER,
                "run_id": "run",
                "step_id": "step",
                "attempt": 1,
                "state": "claimed",
                "event_seq": 2,
                "intent_digest": "1" * 64,
                "payload_digest": "2" * 64,
                "fence_sha256": "5" * 64,
            },
            "caller_time_ms": 2**64 - 1,
            "time_scope": "original caller wall-clock milliseconds; not monotonic availability",
            "sequence_scope": "claimed_step.event_seq is per-step; not a shared arrival cursor",
            "read_scope": "verified step read followed by separate dispatch-attempt absence read; not atomic",
            "owner_api_scope": "original step read includes schema assurance; not a strictly read-only database probe",
            "pending_attempt_at_second_read": False,
            "source_provenance_authenticated": False,
            "independent_effect_observed": False,
            "prediction_deployed": False,
            "physical_cost_complete": False,
            "storage_scope": "synchronous fixed-slot scan and file/directory fsync may delay dispatch; no complete cost claim",
            "authority": False,
        }


class NativeFactTests(NativeFactFixture, unittest.TestCase):
    def test_malformed_bytes_hashes_and_mixed_serializer_profiles_are_rejected(self):
        raw = wire(self.fact)
        self.assertEqual(_parse_native(raw, OWNER), (self.fact, ["serde_json_sorted"]))
        variants = [
            raw + b"\n",
            raw[:-1],
            b" " * (65536 + 1),
            raw.replace(
                b'"schema_version":1', b'"schema_version":1,"schema_version":1'
            ),
            raw.replace(b'"event_seq":2', b'"event_seq":3'),
            raw.replace(b'"event_seq":2', b'"event_seq":2.0'),
            raw.replace(
                b'"caller_time_ms":18446744073709551615', b'"caller_time_ms":NaN'
            ),
        ]
        mixed = json.loads(wire(self.fact, ordered=True))
        mixed["semantic_sha256"] = json.loads(raw)["semantic_sha256"]
        variants.append(json.dumps(mixed, separators=(",", ":")).encode())
        # A sorted-map source cannot borrow preserve_order's swap-remove hash.
        variants.append(wire(json.loads(raw)["fact"], ordered=True))
        for encoded in variants:
            with self.subTest(encoded=encoded[:90]), self.assertRaises(ValueError):
                _parse_native(encoded, OWNER)

    def test_rehashed_scope_escalations_and_native_identity_tampering_are_rejected(
        self,
    ):
        for name, value in (
            ("authority", True),
            ("prediction_deployed", True),
            ("pending_attempt_at_second_read", True),
            ("time_scope", "monotonic clock"),
            ("caller_time_ms", -1),
            ("caller_time_ms", True),
        ):
            changed = deepcopy(self.fact)
            changed[name] = value
            with self.subTest(field=name), self.assertRaises(ValueError):
                _parse_native(wire(changed), OWNER)
        for name, value in (
            ("run_id", "other"),
            ("payload_digest", "f" * 64),
            ("attempt", True),
            ("state", "succeeded"),
        ):
            changed = deepcopy(self.fact)
            changed["claimed_step"][name] = value
            with self.subTest(field=name), self.assertRaises(ValueError):
                _parse_native(wire(changed), OWNER)
        changed = deepcopy(self.fact)
        changed["intent"]["subject_id"] = "different-subject"
        with self.assertRaises(ValueError):
            _parse_native(wire(changed), OWNER)

    @unittest.skipUnless(
        hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_NONBLOCK"),
        "Unix live source reader",
    )
    def test_live_source_read_rejects_links_and_special_files_without_rewriting_artifacts(
        self,
    ):
        raw = wire(self.fact)
        original = self.root / "slot-00.json"
        original.write_bytes(raw)
        self.assertEqual(read_native_fact(original), raw)
        link = self.root / "symlink"
        link.symlink_to(original)
        with self.assertRaises(OSError):
            read_native_fact(link)
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            read_native_fact(fifo)
        os.link(original, self.root / "hardlink")
        with self.assertRaises(ValueError):
            read_native_fact(original)
        self.assertEqual(original.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
