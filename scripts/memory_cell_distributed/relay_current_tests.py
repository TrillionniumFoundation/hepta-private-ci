"""Local signatures and real source transitions; no model or hosted-run claim.

Artifact delivery/runner identities and prior callback counts are fixtures.
SourceEvidence, MemoryService, signatures, epoch changes and revocation are real.
"""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import relay_current as trial
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from memory_service import MemoryService
from relay_current_contract import acknowledgment_binding, digest, evidence_request
from relay_current_contract import verify_ack, verify_evidence, verify_ready
from relay_protocol import SCOPE, artifact_name, provenance, read, retain, seal
from source_evidence import SourceEvidence


class CurrentRelayTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(
            os.environ, SOURCE_SHA="a" * 40, GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="1"
        )
        environment.start()
        self.addCleanup(environment.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "source"
        self.source = MemoryService(self.root / "source-owner", SCOPE)
        self.record = self.source.write("remote/source_00", "remote_00", "color", "red")
        self.source_key, self.target_key = (
            Ed25519PrivateKey.generate(),
            Ed25519PrivateKey.generate(),
        )
        self.secret = Path(directory.name) / "source.key"
        self.secret.write_bytes(self.source_key.private_bytes_raw())
        self.secret.chmod(0o600)
        shared = dict(source_sha="a" * 40, run_id="123", run_attempt="1")
        self.source_actor = dict(
            shared, job="source-owner", boot_id_sha256="b" * 64, runner_name="source"
        )
        self.target_actor = dict(
            shared, job="target-worker", boot_id_sha256="c" * 64, runner_name="target"
        )
        frontier = asdict(self.source.authority_view())
        frontier["revoked"] = list(frontier["revoked"])
        self.offer = dict(
            **provenance("offer"),
            public_key=self.source_key.public_key().public_bytes_raw().hex(),
            source_identity=self.source_actor,
            package=dict(manifest_sha256="d" * 64),
            target_snapshot=dict(
                frontier=frontier,
                placement=dict(
                    scope=SCOPE,
                    cell_id="memory",
                    node_id="worker-b",
                    generation=1,
                    manifest_sha256="d" * 64,
                    roots=[self.record.source_digest],
                ),
            ),
            evidence_grant_root=self.record.source_digest,
        )
        retain(self.root / "out-offer/offer.json", seal(self.offer, self.source_key))
        self.ready = seal(
            dict(
                **provenance("ready"),
                public_key=self.target_key.public_key().public_bytes_raw().hex(),
                identity=self.target_actor,
                manifest_sha256="d" * 64,
                evidence_request=evidence_request(self.offer),
                source_database_present=False,
            ),
            self.target_key,
        )
        with (
            patch.object(trial, "await_artifact", side_effect=self.deliver),
            patch.object(trial, "identity", return_value=self.source_actor),
        ):
            trial.source_evidence(
                self.root, Path(directory.name) / "unused-model", self.secret
            )
        self.evidence = read(self.root / "out-current-evidence/current-evidence.json")
        self.ack = seal(
            dict(
                **provenance("current-ack"),
                **acknowledgment_binding(self.offer, self.ready, self.evidence),
                target_actor=self.target_actor,
                accepted_under_delivered_cut=True,
                source_database_present=False,
                callbacks_before=33,
                callbacks_after=33,
            ),
            self.target_key,
        )

    def deliver(self, stage, output):
        value = {"ready": self.ready, "current-ack": getattr(self, "ack", None)}[stage]
        path = output / (stage + ".json")
        retain(path, value)
        return path

    def test_exact_current_root_bytes_and_epoch_are_required_even_with_valid_signature(
        self,
    ):
        verify_evidence(self.evidence, self.offer, self.ready)
        for field, replacement in (
            ("source_root", "e" * 64),
            ("source_epoch", 9),
            ("scope", "other"),
            ("payload_base64", "AAAA"),
            ("parameter_output", True),
        ):
            with self.subTest(field=field):
                value = deepcopy(self.evidence["payload"])
                value["evidence"][field] = replacement
                with self.assertRaises(ValueError):
                    verify_evidence(
                        seal(value, self.source_key), self.offer, self.ready
                    )
        value = dict(
            self.evidence["payload"],
            source_actor=dict(self.source_actor, job="target-worker"),
        )
        with self.assertRaises(ValueError):
            verify_evidence(seal(value, self.source_key), self.offer, self.ready)

    def test_ack_exact_envelope_identity_and_run_are_required(self):
        verify_ack(self.ack, self.offer, self.ready, self.evidence)
        for field, replacement in (
            ("evidence_sha256", "f" * 64),
            ("source_epoch", 9),
            ("source_root", "e" * 64),
            ("callbacks_after", 34),
            ("target_actor", dict(self.target_actor, boot_id_sha256="e" * 64)),
        ):
            with self.subTest(field=field):
                value = dict(self.ack["payload"], **{field: replacement})
                with self.assertRaises(ValueError):
                    verify_ack(
                        seal(value, self.target_key),
                        self.offer,
                        self.ready,
                        self.evidence,
                    )
        with self.assertRaises(ValueError):
            verify_ack(
                seal(self.ack["payload"], self.source_key),
                self.offer,
                self.ready,
                self.evidence,
            )
        with patch.dict(os.environ, GITHUB_RUN_ID="124"), self.assertRaises(ValueError):
            verify_ack(self.ack, self.offer, self.ready, self.evidence)

    def test_ready_identity_and_exact_root_request_are_required(self):
        for field, replacement in (
            ("identity", dict(self.target_actor, job="source-owner")),
            ("identity", dict(self.target_actor, run_attempt="2")),
            (
                "evidence_request",
                dict(evidence_request(self.offer), source_root="e" * 64),
            ),
            ("source_database_present", True),
        ):
            with self.subTest(field=field, replacement=replacement):
                value = dict(self.ready["payload"], **{field: replacement})
                with self.assertRaises(ValueError):
                    verify_ready(seal(value, self.target_key), self.offer)

    def test_unbound_ack_cannot_advance_the_actual_source(self):
        before = self.source.snapshot()
        self.ack = seal(
            dict(self.ack["payload"], evidence_sha256="e" * 64), self.target_key
        )
        with patch.object(trial, "await_artifact", side_effect=self.deliver):
            with self.assertRaises(ValueError):
                trial.source_ack_withdraw(
                    self.root, self.root / "unused-model", self.secret
                )
        self.assertEqual(self.source.snapshot(), before)
        self.assertFalse((self.root / "source-ack-current.json").exists())
        self.assertFalse((self.root / "out-withdrawal/withdrawal.json").exists())

    def test_ack_cannot_move_source_confirmation_to_another_owner(self):
        before = self.source.snapshot()
        other = dict(self.source_actor, boot_id_sha256="e" * 64)
        with (
            patch.object(trial, "await_artifact", side_effect=self.deliver),
            patch.object(trial, "identity", return_value=other),
        ):
            with self.assertRaises(ValueError):
                trial.source_ack_withdraw(
                    self.root, self.root / "unused-model", self.secret
                )
        self.assertEqual(self.source.snapshot(), before)
        self.assertFalse((self.root / "source-ack-current.json").exists())

    def test_new_artifact_stages_keep_exact_digest_and_member_admission(self):
        for stage in ("current-evidence", "current-ack"):
            for member in (stage + ".json", "../" + stage + ".json"):
                with (
                    self.subTest(stage=stage, member=member),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    buffer = io.BytesIO()
                    with zipfile.ZipFile(buffer, "w") as archive:
                        archive.writestr(member, b'{"metadata":"only"}')
                    raw = buffer.getvalue()
                    item = dict(
                        id=12,
                        name=artifact_name(stage),
                        expired=False,
                        digest="sha256:" + hashlib.sha256(raw).hexdigest(),
                    )
                    responses = [
                        dict(head_sha="a" * 40, run_attempt=1),
                        dict(total_count=1, artifacts=[item]),
                        raw,
                    ]
                    with patch("artifact_relay.api", side_effect=responses):
                        if member.startswith("../"):
                            with self.assertRaises(ValueError):
                                trial.await_artifact(
                                    stage, Path(directory) / "download"
                                )
                        else:
                            path = trial.await_artifact(
                                stage, Path(directory) / "download"
                            )
                            self.assertEqual(path.read_bytes(), b'{"metadata":"only"}')

    def test_actual_source_observes_exact_ack_current_then_revokes(self):
        with (
            patch.object(trial, "await_artifact", side_effect=self.deliver),
            patch.object(trial, "identity", return_value=self.source_actor),
        ):
            trial.source_ack_withdraw(
                self.root, self.root / "unused-model", self.secret
            )
        confirmation = read(self.root / "source-ack-current.json")
        transition = read(self.root / "source-withdraw-transition.json")
        self.assertEqual(confirmation["ack_sha256"], digest(self.ack))
        self.assertEqual(
            confirmation["snapshot"]["digest"],
            self.evidence["payload"]["source_snapshot_sha256"],
        )
        self.assertEqual(
            transition["frontier"]["epoch"], confirmation["snapshot"]["epoch"] + 1
        )
        self.assertEqual(transition["frontier"]["revoked"], [self.record.source_digest])
        self.assertEqual(transition["confirmed_current_sha256"], digest(confirmation))
        with self.assertRaises(ValueError):
            SourceEvidence(self.source.store).dispatch(evidence_request(self.offer))

    def test_intervening_source_change_prevents_ack_confirmation_and_revoke(self):
        self.source.correct("remote/source_00", "blue", 0)
        with (
            patch.object(trial, "await_artifact", side_effect=self.deliver),
            patch.object(trial, "identity", return_value=self.source_actor),
        ):
            with self.assertRaises(ValueError):
                trial.source_ack_withdraw(
                    self.root, self.root / "unused-model", self.secret
                )
        self.assertFalse((self.root / "source-ack-current.json").exists())
        self.assertFalse((self.root / "out-withdrawal/withdrawal.json").exists())


if __name__ == "__main__":
    unittest.main()
