"""Preserve original publication custody while retaining the late absolute end."""

from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_historical_task_read_source_closure as route

ROOT, PROOF, A = route.ROOT, route.PROOF, route.A
CAPTURE = A + "authority_host_original_publication_route.rs"
SESSION = A + "authority_host_generation_publication_session.rs"
DEPLOYMENT = A + "authority_host_publication_deployment.rs"


class OriginalPublicationRouteSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def reject(self, path, function, marker, occurrence=0):
        source = (ROOT / path).read_text()
        body, _ = route.function(source, function)
        matches = list(re.finditer(route.token_pattern(marker), body))
        self.assertGreater(len(matches), occurrence)
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        offset = code.index(function)
        match = matches[occurrence]
        left, right = offset + match.start(), offset + match.end()
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(source[:left] + "/* " + source[left:right] + " */" + source[right:])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_real_learning_scope_and_checkpoint_surround_the_original_seal(self):
        for marker in ("service.with_learning_profile(",
                       "learning.profile.require_cell_scope(&initial)?",
                       "learning.backend.frozen_scope_binding() != Some(scope.binding())",
                       "scope.validate_snapshot(snapshot)", "seal_bytes(", "!= before"):
            with self.subTest(marker=marker):
                self.reject(CAPTURE, "fn prepare_original_publication_route(", marker)
        for occurrence in (0, 1):
            self.reject(CAPTURE, "fn prepare_original_publication_route(",
                        "learning.backend.restore(&initial.request)", occurrence)

    def test_sealed_route_keeps_actual_root_recipient_and_writer_identity(self):
        for marker in ("original_root()?", "uid: 0", "pid: std::process::id()",
                       "uid: config.peer_uid", "pid: registration.peer_pid",
                       "registration.process_start_ticks", "root_start()?",
                       "identity: registration.registered_identity.clone()",
                       "initial: initial.head_digest.to_string()", "scope: scope.binding().to_string()",
                       "writer: proof", "original_end,"):
            with self.subTest(marker=marker):
                self.reject(CAPTURE, "fn prepare_original_publication_route(", marker)

    def test_late_capture_and_acknowledgement_cannot_renew_the_original_end(self):
        for occurrence in (0, 1):
            self.reject(CAPTURE, "fn prepare_original_publication_route(",
                        "owner_alive(owner_pidfd, end)?", occurrence)
        for marker in ("Some(end) => end", "Instant::now() >= end"):
            self.reject(SESSION, "fn operation_end(", marker)
        for marker in ("let end = self.operation_end()?", "checked_duration_since(Instant::now())",
                       "!remaining.is_zero()", "recv_timeout(remaining)", "Instant::now() >= end"):
            self.reject(SESSION, "fn register(", marker)
        self.reject(DEPLOYMENT, "fn wait_and_register(", "self.capability.operation_end()?")

    def test_existing_session_retains_original_owner_and_one_shot_registration(self):
        for marker in ("self.publication.is_some()", "self.learning.as_ref()",
                       "prepare_original_publication_route(", "&self.service,", "&self.owner_pidfd,",
                       "self.publication = Some(runtime)"):
            self.reject(SESSION, "fn enable_generation_publication(", marker)
        for marker in ("std::process::id() != self.root_pid", "compare_exchange(ACTIVE, CONSUMED",
                       "self.sender.try_send(", "self.phase.load(Ordering::Acquire) != CONSUMED"):
            self.reject(SESSION, "fn register(", marker)


if __name__ == "__main__":
    unittest.main()
