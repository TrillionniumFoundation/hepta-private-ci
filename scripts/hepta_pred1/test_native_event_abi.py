"""Native event joins retain UNKNOWN without promoting fixture evidence."""

from hashlib import sha256
import unittest

from .native_event_abi import import_native_events, validate_native_events
from .native_ledger import Artifact, _snapshot
from .owner_bridge import model_row
from .test_native_fact import OWNER, NativeFactFixture, wire


class NativeEventAbiTests(NativeFactFixture, unittest.TestCase):
    def collection(self, observation=None, reconciliation=None):
        attempt = {
            **self.identity,
            "authority_epoch": 1,
            "grant_id": "grant",
            "grant_nonce_digest": "6" * 64,
            "record_command_id": "record",
            "started_at_ms": 50,
        }
        key = {
            name: self.identity[name]
            for name in ("owner_agent_id", "run_id", "step_id", "attempt")
        }
        rows = {"attempts": [attempt], "observations": [], "reconciliations": []}
        for table, value in (
            ("observations", observation),
            ("reconciliations", reconciliation),
        ):
            if value is not None:
                rows[table] = [
                    {
                        **key,
                        "observation": value,
                        "evidence_digest": "7" * 64,
                        "observed_at_ms": 60,
                    }
                ]
        return Artifact.make(
            {
                "schema": "pred1-native-collection-v1",
                "identity": self.identity,
                "clock_id": "collector-declared-boot",
                "cursor": 7,
                "available_at": 1.5,
                "rows": rows,
            }
        )

    def test_native_bytes_survive_both_serializers_without_clock_or_label_promotion(
        self,
    ):
        for ordered, profile in (
            (False, "serde_json_sorted"),
            (True, "serde_json_preserve_order_swap_remove"),
        ):
            with self.subTest(profile=profile):
                raw = wire(self.fact, ordered=ordered)
                result = import_native_events(
                    raw, expected_owner=OWNER, source="fixture"
                )
                p = result.payload
                self.assertEqual(p["native_source_utf8"].encode(), raw)
                self.assertEqual(p["native_source_sha256"], sha256(raw).hexdigest())
                self.assertEqual(p["native_serialization_profiles"], [profile])
                self.assertEqual(p["events"][0]["native_wall_time_ms"], 2**64 - 1)
                self.assertEqual(p["events"][0]["per_step_sequence"], 2)
                self.assertIsNone(p["shared_arrival_cursor"])
                self.assertIsNone(p["shared_clock_id"])
                self.assertIsNone(p["collector_arrival_declaration"])
                self.assertEqual(
                    p["phase_status"],
                    {
                        "intention": "claimed_intent_record",
                        "authorization": "unknown",
                        "dispatch": "unknown",
                        "execution": "unknown",
                        "independent_effect": "unknown",
                        "censoring": "unobserved",
                    },
                )
                with self.assertRaises(ValueError):
                    _snapshot(result)
                with self.assertRaises(ValueError):
                    model_row(result)
                output = self.root / f"{profile}-abi.json"
                result.save(output)
                with self.assertRaises(FileExistsError):
                    result.save(output)
                self.assertEqual(Artifact.read(output).encoded, result.encoded)

    def test_settlements_and_reconciliation_preserve_unknown_effect_and_censoring(self):
        for observation in ("succeeded", "failed", "proven_absent", "indeterminate"):
            with self.subTest(observation=observation):
                reconciliation = "succeeded" if observation == "indeterminate" else None
                collection = self.collection(observation, reconciliation)
                raw = wire(self.fact)
                result = import_native_events(
                    raw,
                    expected_owner=OWNER,
                    source="declared_native",
                    collection=collection,
                )
                p = result.payload
                self.assertEqual(p["collection_utf8"].encode(), collection.encoded)
                self.assertEqual(p["events"][2]["detail"]["observation"], observation)
                if reconciliation:
                    self.assertEqual(
                        p["events"][3]["detail"]["observation"], reconciliation
                    )
                self.assertEqual(
                    p["phase_status"]["authorization"], "owner_attempt_record_only"
                )
                self.assertEqual(p["phase_status"]["dispatch"], "may_have_contacted")
                self.assertEqual(p["phase_status"]["execution"], "unknown")
                self.assertEqual(p["phase_status"]["independent_effect"], "unknown")
                self.assertEqual(p["phase_status"]["censoring"], "unobserved")
                self.assertEqual(
                    p["effect_labels"],
                    dict.fromkeys(
                        (
                            "outcome",
                            "duration",
                            "final_cost",
                            "time_lower",
                            "time_upper",
                            "nonoccurrence_witness",
                        )
                    ),
                )
                self.assertFalse(p["authorization_verified"])
                self.assertFalse(p["source_provenance_authenticated"])
                self.assertIsNone(p["shared_arrival_cursor"])

    def test_absent_attempt_never_proves_absent_contact_or_censored_outcome(self):
        c = self.collection().payload
        c["rows"]["attempts"] = []
        p = import_native_events(
            wire(self.fact),
            expected_owner=OWNER,
            source="fixture",
            collection=Artifact.make(c),
        ).payload
        self.assertEqual(len(p["events"]), 1)
        self.assertEqual(p["phase_status"]["dispatch"], "unknown")
        self.assertEqual(
            p["collector_arrival_declaration"],
            {"clock_id": "collector-declared-boot", "cursor": 7, "available_at": 1.5},
        )
        self.assertIsNone(p["effect_labels"]["outcome"])

    def test_same_attempt_keys_do_not_join_different_intent_payload_or_destination(
        self,
    ):
        for name, value in (
            ("owner_agent_id", "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13"),
            ("run_id", "other"),
            ("step_id", "other"),
            ("attempt", 2),
            ("intent_digest", "f" * 64),
            ("payload_digest", "f" * 64),
            ("destination_id", "other"),
        ):
            c = self.collection().payload
            c["identity"][name] = value
            c["rows"]["attempts"][0][name] = value
            with self.subTest(field=name), self.assertRaises(ValueError):
                import_native_events(
                    wire(self.fact),
                    expected_owner=OWNER,
                    source="fixture",
                    collection=Artifact.make(c),
                )
        for table in ("attempts", "observations", "reconciliations"):
            c = self.collection("indeterminate", "succeeded").payload
            c["rows"][table][0]["attempt"] = True
            with self.subTest(table=table), self.assertRaises(ValueError):
                import_native_events(
                    wire(self.fact),
                    expected_owner=OWNER,
                    source="fixture",
                    collection=Artifact.make(c),
                )

    def test_replay_rejects_rehashed_labels_arrival_and_source_reclassification(self):
        artifact = import_native_events(
            wire(self.fact),
            expected_owner=OWNER,
            source="fixture",
            collection=self.collection("succeeded"),
        )
        self.assertEqual(
            validate_native_events(
                artifact, expected_owner=OWNER, expected_source="fixture"
            ),
            artifact.payload,
        )
        for field, value in (
            ("shared_arrival_cursor", 2),
            ("source", "declared_native"),
            ("effect_labels", {"outcome": 1}),
            ("authorization_verified", True),
        ):
            p = artifact.payload
            p[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_native_events(
                    Artifact.make(p), expected_owner=OWNER, expected_source="fixture"
                )


if __name__ == "__main__":
    unittest.main()
