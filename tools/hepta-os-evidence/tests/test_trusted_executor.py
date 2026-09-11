from datetime import datetime, timedelta, timezone
import hashlib, json, multiprocessing, os, shutil, time
from pathlib import Path
import tempfile, unittest
from unittest import mock
import trusted_executor
from trusted_executor import Config, ExecutionError, ReplayError, execute

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
SUBJECT = {
    "source_commit": "968968046d69d000f1f9fe03683e92aa7903cf99",
    "source_tree": "04ba2fab66dfc41680784e1288e14c2fc54c58d9",
    "promotion_pr_number": 41,
    "promotion_pr_head": "7e1e611e7299391cf3d4edc1ded322da0d023cc6",
}
NONCE = "a" * 32
OTHER_NONCE = "e" * 32


def stamp(value):
    return value.isoformat().replace("+00:00", "Z")


def matching_procfs():
    try:
        trusted_executor._require_procfs_namespace()
    except ExecutionError:
        return False
    return True


@unittest.skipUnless(
    matching_procfs(),
    "native executor requires procfs mounted for the current PID namespace",
)
class TrustedExecutorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        os.chmod(self.root, 0o700)
        self.admissions = self.root / "admissions"
        self.harnesses = self.root / "harnesses"
        self.attestations = self.root / "attestations"
        self.etc = self.root / "etc"
        self.state = self.root / "state"
        for p in (
            self.admissions,
            self.harnesses,
            self.attestations,
            self.etc,
            self.state,
        ):
            p.mkdir(mode=0o700)
        self.policy_path = self.etc / "execution-policy.json"
        self.config = Config(
            self.admissions,
            self.harnesses,
            self.attestations,
            self.policy_path,
            self.state,
            os.getuid(),
        )

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, data, mode=0o600):
        path.write_bytes(data)
        os.chmod(path, mode)

    def fd_count(self):
        return len(list(Path("/proc/self/fd").iterdir()))

    def result(self, nonce=NONCE):
        return json.loads((self.state / "results" / f"{nonce}.json").read_text())

    def prepare(
        self,
        *,
        exit_code=0,
        output_bytes=0,
        sleep_seconds=0,
        expiry_seconds=1800,
        manifest_extra=None,
        bundle_fifo=False,
        close_output=False,
        delayed_marker=False,
        escape_descendant=False,
        mutate_admission=None,
        mutate_policy=None,
        symlink_harness=False,
    ):
        kind = "installed_root_linux_process_matrix"
        level = "L2"
        lane = "owner-open-r5-l2"
        target = "desktop-installed-rootlinux"
        manifest = {
            "schema": "org.trillionnium.target-evidence-bundle.v1",
            "repository": "TrillionniumFoundation/trillionnium-os",
            **{k: SUBJECT[k] for k in ("source_commit", "source_tree")},
            "evidence_kind": kind,
            "evidence_level": level,
            "authorization_nonce": NONCE,
            "target_id": target,
            "synthetic": False,
            "automatic_redispatch": False,
            "promotion_authorized": False,
            "public_release": False,
        }
        if manifest_extra:
            manifest.update(manifest_extra)
        harness = self.harnesses / kind
        script = "#!/bin/sh\nset -eu\n"
        if close_output:
            script += "exec 1>&- 2>&-\n"
        if sleep_seconds:
            script += f"sleep {sleep_seconds}\n"
        if delayed_marker:
            script += 'touch "$TMPDIR/delayed-marker"\n'
        if output_bytes:
            script += f"python3 -c 'print(\"x\"*{output_bytes})'\n"
        script += (
            "cat >\"$OWNER_OPEN_R5_OUTPUT_DIR/manifest.json\" <<'EOF'\n"
            + json.dumps(manifest, sort_keys=True)
            + "\nEOF\n"
        )
        if bundle_fifo:
            script += 'mkfifo "$OWNER_OPEN_R5_OUTPUT_DIR/blocked.fifo"\nchmod 600 "$OWNER_OPEN_R5_OUTPUT_DIR/blocked.fifo"\n'
        if escape_descendant:
            script += (
                "python3 - <<'PY' &\n"
                "import os,signal,time\n"
                "from pathlib import Path\n"
                "if os.fork(): os._exit(0)\n"
                "os.setsid()\n"
                "if os.fork(): os._exit(0)\n"
                "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
                "os.close(1); os.close(2)\n"
                "Path(os.environ['TMPDIR'],'escape-ready').write_text('ready')\n"
                "time.sleep(3)\n"
                "Path(os.environ['TMPDIR'],'escaped-marker').write_text('escaped')\n"
                "Path(os.environ['OWNER_OPEN_R5_OUTPUT_DIR'],'escaped-bundle-mutation').write_text('escaped')\n"
                "PY\n"
                'i=0; while [ ! -f "$TMPDIR/escape-ready" ] && [ $i -lt 200 ]; do i=$((i+1)); sleep .01; done\n'
                'test -f "$TMPDIR/escape-ready"\n'
            )
        script += f"exit {exit_code}\n"
        real = self.harnesses / "real-harness" if symlink_harness else harness
        self.write(real, script.encode(), 0o700)
        if symlink_harness:
            harness.symlink_to(real.name)
        harness_digest = hashlib.sha256(real.read_bytes()).hexdigest()
        expiry = NOW + timedelta(seconds=expiry_seconds)
        attestation = {
            "schema": "org.trillionnium.target-evidence-target-attestation.v1",
            "version": "1",
            "status": "READY",
            "repository": "TrillionniumFoundation/trillionnium-os",
            **{k: SUBJECT[k] for k in ("source_commit", "source_tree")},
            "evidence_kind": kind,
            "evidence_level": level,
            "external_lane": lane,
            "authorization_nonce": NONCE,
            "target_id": target,
            "environment_class": "installed_root_linux",
            "custodian": "target-operator",
            "harness_sha256": harness_digest,
            "issued_at": stamp(NOW - timedelta(minutes=2)),
            "expires_at": stamp(expiry),
            "automatic_redispatch": False,
            "promotion_authorized": False,
            "public_release": False,
        }
        attestation_raw = (json.dumps(attestation, sort_keys=True) + "\n").encode()
        self.write(self.attestations / f"{kind}.json", attestation_raw)
        admission = {
            "schema": "org.trillionnium.external-evidence-admission.v1",
            "version": "1",
            "status": "ADMITTED_PENDING_FIXED_TARGET_EXECUTION",
            "repository": "TrillionniumFoundation/trillionnium-os",
            **SUBJECT,
            "evidence_kind": kind,
            "evidence_level": level,
            "external_lane": lane,
            "authorization_nonce": NONCE,
            "authorization_ticket": "TARGET-0001",
            "authorization_expires_at": stamp(expiry),
            "requester": "capture-producer",
            "roles": {
                "producer": "capture-producer",
                "target_operator": "target-operator",
                "admission_issuer": "external-admission",
            },
            "grant_id": "b" * 32,
            "issuer": "external-admission",
            "key_id": "grant-key",
            "request_sha256": "1" * 64,
            "grant_sha256": "2" * 64,
            "grant_signature_sha256": "3" * 64,
            "grant_public_key_sha256": "4" * 64,
            "admission_policy_sha256": "5" * 64,
            "authorization_class": "TARGET_CAPTURE",
            "grant_issued_at": stamp(NOW - timedelta(minutes=3)),
            "grant_expires_at": stamp(expiry),
            "harness_sha256": harness_digest,
            "target_attestation_sha256": hashlib.sha256(attestation_raw).hexdigest(),
            "admitted_at": stamp(NOW - timedelta(minutes=1)),
            "target_contact_performed": False,
            "candidate_code_executed": False,
            "capture_scheduled": False,
            "automatic_redispatch": False,
            "promotion_authorized": False,
            "public_release": False,
        }
        if mutate_admission:
            mutate_admission(admission)
        self.write(
            self.admissions / f"{NONCE}.json",
            (
                json.dumps(admission, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode(),
        )
        policy = {
            "schema": "org.trillionnium.external-evidence-execution-policy.v1",
            "version": "1",
            "status": "ACTIVE",
            "repository": "TrillionniumFoundation/trillionnium-os",
            "required_uid": os.getuid(),
            "admission_policy_sha256_allowlist": ["5" * 64],
            "grant_public_key_sha256_allowlist": ["4" * 64],
            "issuer_allowlist": ["external-admission"],
            "allowed_subjects": [SUBJECT],
            "max_bundle_files": 32,
            "max_bundle_bytes": 1048576,
            "bundle_inspection_timeout_seconds": 5,
            "evidence_kinds": {
                kind: {
                    "level": level,
                    "lane": lane,
                    "authorization_class": "TARGET_CAPTURE",
                    "required_roles": [
                        "producer",
                        "target_operator",
                        "admission_issuer",
                    ],
                    "custodian_role": "target_operator",
                    "environment_class": "installed_root_linux",
                    "timeout_seconds": 5,
                    "stdout_max_bytes": 128,
                    "stderr_max_bytes": 128,
                }
            },
        }
        if mutate_policy:
            mutate_policy(policy)
        self.write(
            self.policy_path, (json.dumps(policy, sort_keys=True) + "\n").encode()
        )

    def test_success_is_one_shot_and_non_promoting(self):
        self.prepare()
        result = execute(NONCE, config=self.config, now=NOW)
        self.assertEqual(
            result["status"], "CAPTURE_COMPLETE_PENDING_INDEPENDENT_REVIEW"
        )
        self.assertFalse(result["promotion_authorized"])
        self.assertTrue(result["cleanup_confirmed"])
        self.assertTrue(result["escaped_descendants_absence_proven"])
        self.assertEqual(result["cleanup_scope"], trusted_executor.CONTAINMENT_SCOPE)
        with self.assertRaises(ReplayError):
            execute(NONCE, config=self.config, now=NOW)

    def test_failure_is_recorded_and_never_retried(self):
        self.prepare(exit_code=7)
        with self.assertRaisesRegex(ExecutionError, "harness_exit_7"):
            execute(NONCE, config=self.config, now=NOW)
        result = json.loads((self.state / "results" / f"{NONCE}.json").read_text())
        self.assertEqual(result["status"], "CAPTURE_FAILED_NO_RETRY")
        with self.assertRaises(ReplayError):
            execute(NONCE, config=self.config, now=NOW)

    def test_rejects_changed_or_symlinked_fixed_harness_before_start(self):
        self.prepare(
            mutate_admission=lambda a: a.__setitem__("harness_sha256", "f" * 64)
        )
        with self.assertRaisesRegex(ExecutionError, "fixed target bytes"):
            execute(NONCE, config=self.config, now=NOW)
        self.assertFalse((self.state / "started").exists())
        self.tearDown()
        self.setUp()
        self.prepare(symlink_harness=True)
        with self.assertRaisesRegex(ExecutionError, "cannot open"):
            execute(NONCE, config=self.config, now=NOW)

    def test_output_limit_consumes_execution_without_retry(self):
        self.prepare(output_bytes=1024)
        with self.assertRaisesRegex(ExecutionError, "stdout_limit_exceeded"):
            execute(NONCE, config=self.config, now=NOW)
        with self.assertRaises(ReplayError):
            execute(NONCE, config=self.config, now=NOW)

    def test_rejects_tampered_admission_roles(self):
        self.prepare(
            mutate_admission=lambda a: a["roles"].__setitem__(
                "target_operator", "capture-producer"
            )
        )
        with self.assertRaisesRegex(ExecutionError, "roles are not separated"):
            execute(NONCE, config=self.config, now=NOW)

    def test_filename_nonce_must_match_before_start(self):
        self.prepare()
        shutil.copyfile(
            self.admissions / f"{NONCE}.json", self.admissions / f"{OTHER_NONCE}.json"
        )
        os.chmod(self.admissions / f"{OTHER_NONCE}.json", 0o600)
        with self.assertRaisesRegex(ExecutionError, "filename nonce"):
            execute(OTHER_NONCE, config=self.config, now=NOW)
        self.assertFalse((self.state / "started").exists())

    def test_same_inode_and_atomic_replacement_execute_sealed_original(self):
        for atomic in (False, True):
            self.tearDown()
            self.setUp()
            with self.subTest(atomic=atomic):
                self.prepare()
                original = trusted_executor.run_harness
                path = self.harnesses / "installed_root_linux_process_matrix"

                def mutate_then_run(*args, **kwargs):
                    replacement = '#!/bin/sh\ntouch "$TMPDIR/replacement-ran"\n'
                    if atomic:
                        path.rename(self.harnesses / "old-harness")
                        self.write(path, replacement.encode(), 0o700)
                    else:
                        with path.open("w") as handle:
                            handle.write(replacement)
                        os.chmod(path, 0o700)
                    return original(*args, **kwargs)

                with mock.patch.object(
                    trusted_executor, "run_harness", mutate_then_run
                ):
                    result = execute(NONCE, config=self.config, now=NOW)
                self.assertEqual(
                    result["status"], "CAPTURE_COMPLETE_PENDING_INDEPENDENT_REVIEW"
                )
                self.assertFalse(
                    (self.state / "work" / NONCE / "cwd" / "replacement-ran").exists()
                )

    def test_fifo_bundle_member_fails_without_hang(self):
        self.prepare(bundle_fifo=True)
        started = time.monotonic()
        with self.assertRaisesRegex(ExecutionError, "bundle_invalid"):
            execute(NONCE, config=self.config, now=NOW)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(self.result()["status"], "CAPTURE_FAILED_NO_RETRY")

    def test_bundle_inspection_timeout_is_killable(self):
        self.prepare(
            mutate_policy=lambda p: p.__setitem__(
                "bundle_inspection_timeout_seconds", 0.001
            )
        )
        started = time.monotonic()
        with self.assertRaisesRegex(ExecutionError, "bundle_inspection_timeout"):
            execute(NONCE, config=self.config, now=NOW)
        self.assertLess(time.monotonic() - started, 2.5)
        self.assertEqual(self.result()["status"], "CAPTURE_FAILED_NO_RETRY")

    def test_authority_expiry_bounds_running_harness(self):
        self.prepare(sleep_seconds=1, expiry_seconds=0.25)
        started = time.monotonic()
        clock = lambda: NOW + timedelta(seconds=time.monotonic() - started)
        with self.assertRaisesRegex(ExecutionError, "authorization_expired"):
            execute(NONCE, config=self.config, now=NOW, clock=clock)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertTrue(self.result()["target_contact_performed"])

    def test_containment_setup_crossing_expiry_never_launches_harness(self):
        self.prepare(expiry_seconds=0.25)
        clock_now = [NOW]
        original_enter = trusted_executor._enter_descendant_containment

        def enter_then_expire():
            state = original_enter()
            clock_now[0] = NOW + timedelta(seconds=0.3)
            return state

        with (
            mock.patch.object(
                trusted_executor,
                "_enter_descendant_containment",
                side_effect=enter_then_expire,
            ),
            mock.patch.object(
                trusted_executor.subprocess,
                "Popen",
                wraps=trusted_executor.subprocess.Popen,
            ) as popen,
        ):
            with self.assertRaisesRegex(
                ExecutionError, "authorization_expired_before_target_contact"
            ):
                execute(NONCE, config=self.config, now=NOW, clock=lambda: clock_now[0])
        popen.assert_not_called()
        result = self.result()
        self.assertFalse(result["target_contact_performed"])
        self.assertEqual(
            result["failure"], "authorization_expired_before_target_contact"
        )
        with self.assertRaises(ReplayError):
            execute(NONCE, config=self.config, now=NOW)

    def test_containment_setup_delay_still_launches_when_authority_is_valid(self):
        self.prepare(expiry_seconds=2)
        clock_now = [NOW]
        original_enter = trusted_executor._enter_descendant_containment

        def enter_with_valid_delay():
            state = original_enter()
            clock_now[0] = NOW + timedelta(seconds=0.1)
            return state

        with (
            mock.patch.object(
                trusted_executor,
                "_enter_descendant_containment",
                side_effect=enter_with_valid_delay,
            ),
            mock.patch.object(
                trusted_executor.subprocess,
                "Popen",
                wraps=trusted_executor.subprocess.Popen,
            ) as popen,
        ):
            result = execute(
                NONCE, config=self.config, now=NOW, clock=lambda: clock_now[0]
            )
        self.assertEqual(popen.call_count, 1)
        self.assertTrue(result["target_contact_performed"])
        self.assertEqual(
            result["status"], "CAPTURE_COMPLETE_PENDING_INDEPENDENT_REVIEW"
        )

    def test_bundle_manifest_is_closed_world(self):
        for extra in (
            {"evidence_reviewed": True},
            {"gap_transition_authorized": True},
            {"release_authorized": True},
        ):
            self.tearDown()
            self.setUp()
            with self.subTest(extra=extra):
                self.prepare(manifest_extra=extra)
                with self.assertRaisesRegex(ExecutionError, "fields differ"):
                    execute(NONCE, config=self.config, now=NOW)
                self.assertEqual(self.result()["status"], "CAPTURE_FAILED_NO_RETRY")

    def test_closed_output_pipes_do_not_bypass_authority_expiry(self):
        self.prepare(
            close_output=True,
            sleep_seconds=0.7,
            expiry_seconds=0.2,
            delayed_marker=True,
        )
        started = time.monotonic()
        clock = lambda: NOW + timedelta(seconds=time.monotonic() - started)
        with self.assertRaisesRegex(
            ExecutionError, "authorization_expired_during_execution"
        ):
            execute(NONCE, config=self.config, now=NOW, clock=clock)
        self.assertLess(time.monotonic() - started, 0.65)
        self.assertFalse(
            (self.state / "work" / NONCE / "cwd" / "delayed-marker").exists()
        )
        self.assertEqual(
            self.result()["failure"], "authorization_expired_during_execution"
        )
        with self.assertRaises(ReplayError):
            execute(NONCE, config=self.config, now=NOW)
        self.tearDown()
        self.setUp()
        self.prepare(
            close_output=True, sleep_seconds=0.05, expiry_seconds=5, delayed_marker=True
        )
        started = time.monotonic()
        clock = lambda: NOW + timedelta(seconds=time.monotonic() - started)
        result = execute(NONCE, config=self.config, now=NOW, clock=clock)
        self.assertEqual(
            result["status"], "CAPTURE_COMPLETE_PENDING_INDEPENDENT_REVIEW"
        )
        self.assertTrue(
            (self.state / "work" / NONCE / "cwd" / "delayed-marker").exists()
        )

    def test_double_fork_setsid_descendant_is_contained_and_terminalized(self):
        self.prepare(escape_descendant=True)
        started = time.monotonic()
        with self.assertRaisesRegex(ExecutionError, "escaped_descendant_detected"):
            execute(NONCE, config=self.config, now=NOW)
        self.assertLess(time.monotonic() - started, 2.0)
        time.sleep(0.15)
        result = self.result()
        self.assertEqual(result["status"], "CAPTURE_FAILED_NO_RETRY")
        self.assertEqual(result["failure"], "escaped_descendant_detected")
        self.assertTrue(result["cleanup_confirmed"])
        self.assertTrue(result["escaped_descendants_absence_proven"])
        self.assertEqual(result["cleanup_scope"], trusted_executor.CONTAINMENT_SCOPE)
        self.assertFalse(
            (self.state / "work" / NONCE / "cwd" / "escaped-marker").exists()
        )
        self.assertFalse(
            (
                self.state / "work" / NONCE / "bundle" / "escaped-bundle-mutation"
            ).exists()
        )
        with self.assertRaises(ReplayError):
            execute(NONCE, config=self.config, now=NOW)

    def test_bundle_walk_errors_fail_closed(self):
        bundle = self.root / "bundle-walk-error"
        bundle.mkdir(mode=0o700)

        def broken_walk(top, topdown=True, onerror=None, followlinks=False):
            self.assertIsNotNone(onerror)
            onerror(PermissionError("blocked subtree"))
            return []

        with mock.patch.object(trusted_executor.os, "walk", broken_walk):
            with self.assertRaisesRegex(ExecutionError, "bundle traversal failed"):
                trusted_executor.inspect_bundle(
                    bundle,
                    os.getuid(),
                    {"max_bundle_files": 32, "max_bundle_bytes": 1024},
                    {},
                    "target",
                )

    def _assert_post_start_fault(self, patcher, expected_failure):
        with patcher:
            with self.assertRaisesRegex(ExecutionError, expected_failure):
                execute(NONCE, config=self.config, now=NOW)
        result = self.result()
        self.assertEqual(result["status"], "CAPTURE_FAILED_NO_RETRY")
        self.assertEqual(result["failure"], expected_failure)
        self.assertTrue((self.state / "started" / f"{NONCE}.json").exists())
        with self.assertRaises(ReplayError):
            execute(NONCE, config=self.config, now=NOW)

    def test_post_start_mkdir_fsync_popen_and_worker_spawn_failures_are_terminalized(
        self,
    ):
        self.prepare()
        original_mkdir = trusted_executor.os.mkdir

        def fail_work_mkdir(path, mode=0o777, *, dir_fd=None):
            if Path(path) == self.state / "work" / NONCE:
                raise OSError("injected work mkdir failure")
            return (
                original_mkdir(path, mode)
                if dir_fd is None
                else original_mkdir(path, mode, dir_fd=dir_fd)
            )

        self._assert_post_start_fault(
            mock.patch.object(trusted_executor.os, "mkdir", fail_work_mkdir),
            "post_start_work_directory_failed",
        )

        self.tearDown()
        self.setUp()
        self.prepare()
        original_fsync = trusted_executor.fsync_dir

        def fail_work_fsync(path):
            if Path(path) == self.state / "work":
                raise OSError("injected work fsync failure")
            return original_fsync(path)

        self._assert_post_start_fault(
            mock.patch.object(trusted_executor, "fsync_dir", fail_work_fsync),
            "post_start_work_directory_failed",
        )

        self.tearDown()
        self.setUp()
        self.prepare()
        self._assert_post_start_fault(
            mock.patch.object(
                trusted_executor.subprocess,
                "Popen",
                side_effect=OSError("injected Popen failure"),
            ),
            "post_start_harness_execution_failed",
        )

        self.tearDown()
        self.setUp()
        self.prepare()
        self._assert_post_start_fault(
            mock.patch.object(
                trusted_executor.selectors,
                "DefaultSelector",
                side_effect=OSError("injected selector failure"),
            ),
            "post_start_harness_execution_failed",
        )

        self.tearDown()
        self.setUp()
        self.prepare()
        original_descendants = trusted_executor._descendant_identities
        calls = 0

        def fail_cleanup_observation(owner):
            nonlocal calls
            calls += 1
            if calls > 2:
                raise ExecutionError("injected procfs failure")
            return original_descendants(owner)

        with mock.patch.object(
            trusted_executor,
            "_descendant_identities",
            side_effect=fail_cleanup_observation,
        ):
            with self.assertRaisesRegex(
                ExecutionError, "descendant_cleanup_unconfirmed"
            ):
                execute(NONCE, config=self.config, now=NOW)
        result = self.result()
        self.assertEqual(result["status"], "CAPTURE_FAILED_NO_RETRY")
        self.assertFalse(result["cleanup_confirmed"])
        self.assertFalse(result["escaped_descendants_absence_proven"])
        with self.assertRaises(ReplayError):
            execute(NONCE, config=self.config, now=NOW)

        self.tearDown()
        self.setUp()
        self.prepare()
        self._assert_post_start_fault(
            mock.patch.object(
                multiprocessing.context.SpawnProcess,
                "start",
                side_effect=OSError("injected worker spawn failure"),
            ),
            "post_start_bundle_inspection_failed",
        )

    def test_result_persistence_uses_fallback_and_never_overwrites(self):
        self.prepare()
        original_raw = trusted_executor.write_raw_once

        def fail_primary(directory, name, raw):
            if Path(directory) == self.state / "results":
                raise OSError("injected result medium failure")
            return original_raw(directory, name, raw)

        with mock.patch.object(trusted_executor, "write_raw_once", fail_primary):
            with self.assertRaisesRegex(
                ExecutionError, "fallback no-retry receipt recorded"
            ):
                execute(NONCE, config=self.config, now=NOW)
        self.assertFalse((self.state / "results" / f"{NONCE}.json").exists())
        fallback = json.loads(
            (self.state / "terminal_failures" / f"{NONCE}.json").read_text()
        )
        self.assertEqual(
            fallback["status"], "TERMINAL_RESULT_PERSISTENCE_FAILED_NO_RETRY"
        )
        self.assertEqual(
            fallback["intended_status"], "CAPTURE_COMPLETE_PENDING_INDEPENDENT_REVIEW"
        )
        with self.assertRaises(ReplayError):
            execute(NONCE, config=self.config, now=NOW)

        self.tearDown()
        self.setUp()
        self.prepare()
        original_raw = trusted_executor.write_raw_once
        original_write = trusted_executor.write_once

        def fail_both_raw(directory, name, raw):
            if Path(directory) == self.state / "results":
                raise OSError("injected result medium failure")
            return original_raw(directory, name, raw)

        def fail_fallback(directory, name, value):
            if Path(directory) == self.state / "terminal_failures":
                raise OSError("injected fallback medium failure")
            return original_write(directory, name, value)

        with (
            mock.patch.object(trusted_executor, "write_raw_once", fail_both_raw),
            mock.patch.object(trusted_executor, "write_once", fail_fallback),
        ):
            with self.assertRaisesRegex(
                ExecutionError,
                "durable STARTED_NO_AUTOMATIC_RETRY remains authoritative",
            ):
                execute(NONCE, config=self.config, now=NOW)
        self.assertTrue((self.state / "started" / f"{NONCE}.json").exists())
        self.assertFalse((self.state / "results" / f"{NONCE}.json").exists())
        self.assertFalse((self.state / "terminal_failures" / f"{NONCE}.json").exists())
        with self.assertRaises(ReplayError):
            execute(NONCE, config=self.config, now=NOW)

    def test_partial_acquisition_and_invalid_policy_do_not_leak_fds(self):
        self.prepare()
        (self.attestations / "installed_root_linux_process_matrix.json").unlink()
        before = self.fd_count()
        for _ in range(12):
            with self.assertRaises(ExecutionError):
                execute(NONCE, config=self.config, now=NOW)
        self.assertEqual(self.fd_count(), before)
        self.tearDown()
        self.setUp()
        self.prepare()
        self.write(self.policy_path, b'{"schema":')
        before = self.fd_count()
        for _ in range(12):
            with self.assertRaises(ExecutionError):
                execute(NONCE, config=self.config, now=NOW)
        self.assertEqual(self.fd_count(), before)


if __name__ == "__main__":
    unittest.main()
