from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from admission_service import Config, AdmissionError, ReplayError, admit


NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
SUBJECT = {
    "source_commit": "968968046d69d000f1f9fe03683e92aa7903cf99",
    "source_tree": "04ba2fab66dfc41680784e1288e14c2fc54c58d9",
    "promotion_pr_number": 41,
    "promotion_pr_head": "7e1e611e7299391cf3d4edc1ded322da0d023cc6",
}


class AdmissionServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.keys = tempfile.TemporaryDirectory()
        key_root = Path(cls.keys.name)
        cls.private_key = key_root / "private.pem"
        cls.public_key = key_root / "public.pem"
        subprocess.run(
            [
                "/usr/bin/openssl",
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:2048",
                "-out",
                cls.private_key,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                "/usr/bin/openssl",
                "pkey",
                "-in",
                cls.private_key,
                "-pubout",
                "-out",
                cls.public_key,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.keys.cleanup()

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.chmod(self.root, 0o700)
        self.inbox = self.root / "inbox"
        self.etc = self.root / "etc"
        self.state = self.root / "state"
        for path in (self.inbox, self.etc, self.state):
            path.mkdir(mode=0o700)
        self.pub = self.etc / "grant-authority.pem"
        shutil.copyfile(self.public_key, self.pub)
        os.chmod(self.pub, 0o600)
        self.policy_path = self.etc / "policy.json"
        self.config = Config(self.policy_path, self.pub, self.state, os.getuid())
        self.request_path = self.inbox / "request.json"
        self.grant_path = self.inbox / "grant.json"
        self.signature_path = self.inbox / "grant.sig"

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def stamp(value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    @staticmethod
    def fd_count() -> int:
        return len(list(Path("/proc/self/fd").iterdir()))

    def write(self, path: Path, data: bytes) -> None:
        path.write_bytes(data)
        os.chmod(path, 0o600)

    def request(self, kind: str = "installed_root_linux_process_matrix") -> dict:
        policies = {
            "installed_root_linux_process_matrix": (
                "L2",
                "owner-open-r5-l2",
                "TARGET-0001",
            ),
            "destructive_fault_matrix": ("L5", "owner-open-r5-l5", "DESTRUCTIVE-0001"),
        }
        level, lane, ticket = policies[kind]
        return {
            "schema": "org.trillionnium.target-evidence-admission-request.v2",
            "status": "ROUTE_ONLY_PENDING_EXTERNAL_ADMISSION",
            "repository": "TrillionniumFoundation/trillionnium-os",
            "evidence_kind": kind,
            "evidence_level": level,
            **SUBJECT,
            "protected_main_tip_observed": SUBJECT["source_commit"],
            "independent_approvals": ["independent-reviewer"],
            "authorization_ticket": ticket,
            "authorization_expires_at": self.stamp(NOW + timedelta(hours=1)),
            "authorization_nonce": "a" * 32,
            "requested_by": "capture-producer",
            "external_lane": lane,
            "candidate_checkout_performed": False,
            "candidate_code_executed": False,
            "external_runner_allocated": False,
            "capture_scheduled": False,
            "synthetic": False,
            "automatic_redispatch": False,
            "promotion_authorized": False,
            "public_release": False,
        }

    def policy(self) -> dict:
        return {
            "schema": "org.trillionnium.external-evidence-admission-policy.v1",
            "version": "1",
            "status": "ACTIVE",
            "repository": "TrillionniumFoundation/trillionnium-os",
            "required_uid": os.getuid(),
            "grant_public_key_sha256": hashlib.sha256(
                self.pub.read_bytes()
            ).hexdigest(),
            "issuer_allowlist": ["external-admission"],
            "allowed_subjects": [SUBJECT],
            "max_request_future_seconds": 86400,
            "max_grant_lifetime_seconds": 3600,
            "max_clock_skew_seconds": 300,
            "evidence_kinds": {
                "installed_root_linux_process_matrix": {
                    "level": "L2",
                    "lane": "owner-open-r5-l2",
                    "authorization_class": "TARGET_CAPTURE",
                    "required_roles": [
                        "producer",
                        "target_operator",
                        "admission_issuer",
                    ],
                    "minimum_independent_approvals": 1,
                },
                "destructive_fault_matrix": {
                    "level": "L5",
                    "lane": "owner-open-r5-l5",
                    "authorization_class": "DESTRUCTIVE_CAPTURE",
                    "required_roles": [
                        "producer",
                        "fault_operator",
                        "destructive_authorizer",
                        "admission_issuer",
                    ],
                    "minimum_independent_approvals": 2,
                },
            },
        }

    def grant(self, request: dict, request_raw: bytes) -> dict:
        if request["evidence_kind"] == "destructive_fault_matrix":
            roles = {
                "producer": "capture-producer",
                "fault_operator": "fault-operator",
                "destructive_authorizer": "destructive-authorizer",
                "admission_issuer": "external-admission",
            }
            authorization_class = "DESTRUCTIVE_CAPTURE"
        else:
            roles = {
                "producer": "capture-producer",
                "target_operator": "target-operator",
                "admission_issuer": "external-admission",
            }
            authorization_class = "TARGET_CAPTURE"
        mirrored = {
            key: request[key]
            for key in (
                "repository",
                "source_commit",
                "source_tree",
                "promotion_pr_number",
                "promotion_pr_head",
                "evidence_kind",
                "evidence_level",
                "external_lane",
                "authorization_nonce",
                "authorization_ticket",
                "authorization_expires_at",
            )
        }
        return {
            "schema": "org.trillionnium.external-evidence-execution-grant.v1",
            "version": "1",
            "status": "AUTHORIZED",
            "grant_id": "b" * 32,
            "request_sha256": hashlib.sha256(request_raw).hexdigest(),
            **mirrored,
            "requester": request["requested_by"],
            "roles": roles,
            "issuer": "external-admission",
            "key_id": "grant-key-20260907",
            "issued_at": self.stamp(NOW - timedelta(minutes=1)),
            "expires_at": self.stamp(NOW + timedelta(minutes=30)),
            "authorization_class": authorization_class,
            "harness_sha256": "c" * 64,
            "target_attestation_sha256": "d" * 64,
            "automatic_redispatch": False,
            "promotion_authorized": False,
            "public_release": False,
        }

    def prepare(self, request: dict | None = None, mutate_grant=None) -> None:
        request = request or self.request()
        request_raw = (json.dumps(request, sort_keys=True) + "\n").encode()
        grant = self.grant(request, request_raw)
        if mutate_grant:
            mutate_grant(grant)
        grant_raw = (json.dumps(grant, sort_keys=True) + "\n").encode()
        self.write(
            self.policy_path,
            (json.dumps(self.policy(), sort_keys=True) + "\n").encode(),
        )
        self.write(self.request_path, request_raw)
        self.write(self.grant_path, grant_raw)
        subprocess.run(
            [
                "/usr/bin/openssl",
                "dgst",
                "-sha256",
                "-sign",
                self.private_key,
                "-out",
                self.signature_path,
                self.grant_path,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.chmod(self.signature_path, 0o600)

    def test_admits_once_without_target_authority(self) -> None:
        self.prepare()
        result = admit(
            self.request_path,
            self.grant_path,
            self.signature_path,
            config=self.config,
            now=NOW,
        )
        self.assertEqual(result["status"], "ADMITTED_PENDING_FIXED_TARGET_EXECUTION")
        self.assertFalse(result["target_contact_performed"])
        self.assertFalse(result["promotion_authorized"])
        with self.assertRaises(ReplayError):
            admit(
                self.request_path,
                self.grant_path,
                self.signature_path,
                config=self.config,
                now=NOW,
            )

    def test_rejects_invalid_signature(self) -> None:
        self.prepare()
        raw = bytearray(self.signature_path.read_bytes())
        raw[0] ^= 1
        self.write(self.signature_path, bytes(raw))
        with self.assertRaisesRegex(AdmissionError, "signature"):
            admit(
                self.request_path,
                self.grant_path,
                self.signature_path,
                config=self.config,
                now=NOW,
            )

    def test_rejects_signed_cross_splice(self) -> None:
        self.prepare(
            mutate_grant=lambda grant: grant.__setitem__("source_tree", "f" * 40)
        )
        with self.assertRaisesRegex(AdmissionError, "cross-splice"):
            admit(
                self.request_path,
                self.grant_path,
                self.signature_path,
                config=self.config,
                now=NOW,
            )

    def test_rejects_unseparated_external_roles(self) -> None:
        self.prepare(
            mutate_grant=lambda grant: grant["roles"].__setitem__(
                "target_operator", "capture-producer"
            )
        )
        with self.assertRaisesRegex(AdmissionError, "not separated"):
            admit(
                self.request_path,
                self.grant_path,
                self.signature_path,
                config=self.config,
                now=NOW,
            )

    def test_rejects_duplicate_request_member_and_symlink(self) -> None:
        self.prepare()
        raw = self.request_path.read_text().rstrip()[:-1] + ',"schema":"duplicate"}\n'
        self.write(self.request_path, raw.encode())
        with self.assertRaisesRegex(AdmissionError, "duplicate JSON member"):
            admit(
                self.request_path,
                self.grant_path,
                self.signature_path,
                config=self.config,
                now=NOW,
            )
        real = self.inbox / "real-request.json"
        self.write(real, (json.dumps(self.request(), sort_keys=True) + "\n").encode())
        self.request_path.unlink()
        self.request_path.symlink_to(real.name)
        with self.assertRaisesRegex(AdmissionError, "cannot open"):
            admit(
                self.request_path,
                self.grant_path,
                self.signature_path,
                config=self.config,
                now=NOW,
            )

    def test_fifo_input_is_rejected_without_blocking(self) -> None:
        self.prepare()
        self.request_path.unlink()
        os.mkfifo(self.request_path, 0o600)
        service_root = Path(__file__).resolve().parents[1]
        child = f"""import sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,{str(service_root)!r})
from admission_service import AdmissionError,Config,admit
try: admit(Path({str(self.request_path)!r}),Path({str(self.grant_path)!r}),Path({str(self.signature_path)!r}),config=Config(Path({str(self.policy_path)!r}),Path({str(self.pub)!r}),Path({str(self.state)!r}),{os.getuid()}),now=datetime(2026,9,7,12,0,tzinfo=timezone.utc))
except AdmissionError: raise SystemExit(0)
raise SystemExit(3)
"""
        done = subprocess.run(
            [sys.executable, "-I", "-c", child], timeout=2, check=False
        )
        self.assertEqual(done.returncode, 0)

    def test_rejects_invalid_grant_intervals(self) -> None:
        cases = [
            (NOW + timedelta(minutes=4), NOW + timedelta(minutes=1)),
            (NOW + timedelta(minutes=1), NOW + timedelta(minutes=1)),
            (NOW - timedelta(minutes=1), NOW + timedelta(minutes=60, seconds=1)),
        ]
        for issued, expires in cases:
            with self.subTest(issued=issued, expires=expires):
                self.prepare(
                    mutate_grant=lambda g, i=issued, e=expires: g.update(
                        issued_at=self.stamp(i), expires_at=self.stamp(e)
                    )
                )
                with self.assertRaisesRegex(AdmissionError, "time bounds"):
                    admit(
                        self.request_path,
                        self.grant_path,
                        self.signature_path,
                        config=self.config,
                        now=NOW,
                    )
                self.tearDown()
                self.setUp()

    def test_approvals_are_casefold_unique_and_role_disjoint(self) -> None:
        for approvals in (
            ["capture-producer"],
            ["external-admission"],
            ["TARGET-OPERATOR"],
            ["reviewer", "Reviewer"],
        ):
            with self.subTest(approvals=approvals):
                request = self.request()
                request["independent_approvals"] = approvals
                self.prepare(request=request)
                with self.assertRaisesRegex(AdmissionError, "approval"):
                    admit(
                        self.request_path,
                        self.grant_path,
                        self.signature_path,
                        config=self.config,
                        now=NOW,
                    )
                self.tearDown()
                self.setUp()

    def test_destructive_lane_requires_two_approvals(self) -> None:
        request = self.request("destructive_fault_matrix")
        self.prepare(request=request)
        with self.assertRaisesRegex(AdmissionError, "approval"):
            admit(
                self.request_path,
                self.grant_path,
                self.signature_path,
                config=self.config,
                now=NOW,
            )
        self.tearDown()
        self.setUp()
        request = self.request("destructive_fault_matrix")
        request["independent_approvals"] = ["reviewer-one", "reviewer-two"]
        self.prepare(request=request)
        self.assertEqual(
            admit(
                self.request_path,
                self.grant_path,
                self.signature_path,
                config=self.config,
                now=NOW,
            )["evidence_level"],
            "L5",
        )

    def test_partial_acquisition_and_invalid_policy_do_not_leak_fds(self) -> None:
        self.prepare()
        self.grant_path.unlink()
        before = self.fd_count()
        for _ in range(12):
            with self.assertRaises(AdmissionError):
                admit(
                    self.request_path,
                    self.grant_path,
                    self.signature_path,
                    config=self.config,
                    now=NOW,
                )
        self.assertEqual(self.fd_count(), before)
        self.tearDown()
        self.setUp()
        self.prepare()
        self.write(self.policy_path, b'{"schema":')
        before = self.fd_count()
        for _ in range(12):
            with self.assertRaises(AdmissionError):
                admit(
                    self.request_path,
                    self.grant_path,
                    self.signature_path,
                    config=self.config,
                    now=NOW,
                )
        self.assertEqual(self.fd_count(), before)


if __name__ == "__main__":
    unittest.main()
