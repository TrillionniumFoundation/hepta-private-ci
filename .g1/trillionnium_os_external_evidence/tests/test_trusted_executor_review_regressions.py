from __future__ import annotations

from datetime import timedelta
import hashlib
import json
import os
import time
import unittest
from unittest import mock

import trusted_executor
from trusted_executor import ExecutionError, execute
from test_trusted_executor import NONCE, NOW, TrustedExecutorTest


class TrustedExecutorReviewRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = TrustedExecutorTest(
            methodName="test_success_is_one_shot_and_non_promoting"
        )
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def rewrite_harness(self, transform) -> None:
        fixture = self.fixture
        kind = "installed_root_linux_process_matrix"
        harness = fixture.harnesses / kind
        fixture.write(harness, transform(harness.read_bytes()), 0o700)
        digest = hashlib.sha256(harness.read_bytes()).hexdigest()

        attestation_path = fixture.attestations / f"{kind}.json"
        attestation = json.loads(attestation_path.read_text())
        attestation["harness_sha256"] = digest
        attestation_raw = (json.dumps(attestation, sort_keys=True) + "\n").encode()
        fixture.write(attestation_path, attestation_raw)

        admission_path = fixture.admissions / f"{NONCE}.json"
        admission = json.loads(admission_path.read_text())
        admission["harness_sha256"] = digest
        admission["target_attestation_sha256"] = hashlib.sha256(
            attestation_raw
        ).hexdigest()
        fixture.write(
            admission_path,
            (json.dumps(admission, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        )

    def test_closed_output_pipes_do_not_bypass_authority_expiry(self) -> None:
        fixture = self.fixture
        fixture.prepare(sleep_seconds=1, expiry_seconds=0.25)
        self.rewrite_harness(
            lambda raw: raw.replace(
                b"set -eu\n",
                b"set -eu\nexec 1>&- 2>&-\n",
                1,
            )
        )
        started = time.monotonic()
        clock = lambda: NOW + timedelta(seconds=time.monotonic() - started)
        with self.assertRaisesRegex(ExecutionError, "authorization_expired"):
            execute(NONCE, config=fixture.config, now=NOW, clock=clock)
        self.assertLess(time.monotonic() - started, 0.9)
        self.assertEqual(fixture.result()["status"], "CAPTURE_FAILED_NO_RETRY")

    def test_bundle_walk_errors_fail_closed(self) -> None:
        fixture = self.fixture
        fixture.prepare()
        bundle = fixture.root / "bundle"
        bundle.mkdir(mode=0o700)
        policy = json.loads(fixture.policy_path.read_text())
        admission = json.loads((fixture.admissions / f"{NONCE}.json").read_text())

        def failed_walk(*args, **kwargs):
            kwargs["onerror"](PermissionError("unreadable subtree"))
            return iter(())

        with mock.patch.object(trusted_executor.os, "walk", failed_walk):
            with self.assertRaisesRegex(ExecutionError, "bundle traversal failed"):
                trusted_executor.inspect_bundle(
                    bundle,
                    os.getuid(),
                    policy,
                    admission,
                    "desktop-installed-rootlinux",
                )

    def test_post_start_exception_persists_one_terminal_failure(self) -> None:
        fixture = self.fixture
        fixture.prepare()
        with mock.patch.object(
            trusted_executor,
            "write_raw_once",
            side_effect=ExecutionError("injected-after-start"),
        ):
            with self.assertRaisesRegex(ExecutionError, "injected-after-start"):
                execute(NONCE, config=fixture.config, now=NOW)

        results = list((fixture.state / "results").glob("*.json"))
        self.assertEqual(len(results), 1)
        result = fixture.result()
        self.assertEqual(result["status"], "CAPTURE_FAILED_NO_RETRY")
        self.assertIn("injected-after-start", result["failure"])
        self.assertFalse(result["target_contact_performed"])

    def test_failure_receipt_error_retains_original_exception(self) -> None:
        fixture = self.fixture
        fixture.prepare()
        original_write_once = trusted_executor.write_once
        calls = 0

        def fail_second_write(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return original_write_once(*args, **kwargs)
            raise OSError("receipt-store-failure")

        with (
            mock.patch.object(
                trusted_executor,
                "write_raw_once",
                side_effect=ExecutionError("original-post-start-error"),
            ),
            mock.patch.object(
                trusted_executor,
                "write_once",
                side_effect=fail_second_write,
            ),
        ):
            with self.assertRaisesRegex(
                ExecutionError,
                "original-post-start-error.*terminal failure receipt persistence failed.*receipt-store-failure",
            ):
                execute(NONCE, config=fixture.config, now=NOW)

    def test_pre_contact_expiry_is_recorded_without_claiming_contact(self) -> None:
        fixture = self.fixture
        fixture.prepare(expiry_seconds=1)
        calls = 0

        def clock():
            nonlocal calls
            calls += 1
            return NOW if calls == 1 else NOW + timedelta(seconds=2)

        with self.assertRaisesRegex(ExecutionError, "authorization_expired"):
            execute(NONCE, config=fixture.config, now=NOW, clock=clock)
        result = fixture.result()
        self.assertEqual(result["status"], "CAPTURE_FAILED_NO_RETRY")
        self.assertFalse(result["target_contact_performed"])
        self.assertFalse(result["capture_performed"])

    def test_invalid_preexisting_failure_receipt_is_not_accepted(self) -> None:
        fixture = self.fixture
        fixture.prepare()

        def fail_after_creating_invalid_result(*args, **kwargs):
            results = fixture.state / "results"
            results.mkdir(mode=0o700, exist_ok=True)
            fixture.write(results / f"{NONCE}.json", b"{}\n")
            raise ExecutionError("original-after-start-error")

        with mock.patch.object(
            trusted_executor,
            "write_raw_once",
            side_effect=fail_after_creating_invalid_result,
        ):
            with self.assertRaisesRegex(
                ExecutionError,
                "original-after-start-error.*terminal failure receipt persistence failed.*incomplete",
            ):
                execute(NONCE, config=fixture.config, now=NOW)


if __name__ == "__main__":
    unittest.main()
