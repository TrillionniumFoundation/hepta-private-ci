"""The ordinary ready frame can start only Root's original fixed enrollment.

These are source mutations, not a native Initial or ordinary A acceptance.
No ready data is an execution, Decision, completed Outcome, or recovery grant.
"""
from dataclasses import replace
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_historical_task_read_source_closure as route

ROOT, PROOF, A = route.ROOT, route.PROOF, route.A
DEPLOYMENT = A + "authority_host_initial_peer_deployment.rs"
ROOT_RUNTIME = A + "authority_host_generation_initial_runtime.rs"
ENROLLMENT = A + "authority_host_initial_enrollment_runtime.rs"
PEER = A + "authority_host_initial_peer_runtime.rs"
SESSION = A + "authority_host_generation_initial_session.rs"
WIRE = A + "root_generation_initial_ready_data.rs"
CLIENT = A + "root_generation_initial_peer_ready.rs"
INPUTS = A + "root_generation_initial_inputs.rs"
CLI = A + "bin/hepta-authority-host.rs"
FILES = A + "authority_host_initial_deployment.rs"
CALLERS = {
    "peer_deployment_attach": (CLI,), "peer_fixed_enrollment": (PEER,),
    "peer_runtime_register": (ROOT_RUNTIME,),
    "runtime_enrollment": (ROOT_RUNTIME, PEER), "runtime_context": (PEER,),
    "runtime_accept": (ROOT_RUNTIME,), "runtime_peer_policy": (ROOT_RUNTIME, PEER),
    "bound_listener": (A + "authority_host_session.rs",),
    "ready_connection": (A + "production_initial_q24.rs",),
    "connection_selected": (), "ready_client": (INPUTS,),
    "ready_bootstrap_binding": (SESSION, CLIENT), "ready_request": (CLIENT,),
    "ready_require_request": (PEER,), "ready_response": (PEER,),
    "ready_require_response": (CLIENT,), "historical_same_root": (CLI,),
}
CALLERS = {"root_initial_" + name: callers for name, callers in CALLERS.items()}
CALLERS["root_initial_profile_check"] = (ENROLLMENT, PEER)
CALLERS["root_initial_profile_refusal"] = (ROOT_RUNTIME, ENROLLMENT, PEER)



def structure(path, source):
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    if path == WIRE:
        for name in ("ReadyRequest", "ReadyResponse"):
            if not re.search(r"#\[serde\(deny_unknown_fields\)\]\s*struct " + name, code):
                raise PROOF.VerificationFailure("strict original ready shape required")
        enum = code[code.index("enum ReadyCommand {"):]
        if not re.match(r"enum ReadyCommand\s*\{\s*Ready\s*\{\s*\}\s*,\s*\}", enum):
            raise PROOF.VerificationFailure("zero-payload struct variant required")
        if not re.search(r"#\[serde\([^]]*deny_unknown_fields\)\]\s*enum ReadyCommand", code):
            raise PROOF.VerificationFailure("command unknown fields must be rejected")
    if path == CLI:
        body, raw = route.function(source, "fn main() -> Result")
        pattern = r'if\s+option\s*==\s*"--initial-peer-ready"\s*\{'
        matches = [m for m in re.finditer(pattern, raw)
                   if PROOF._strip_rust_non_code(m.group()) == body[m.start():m.end()]]
        if len(matches) != 1:
            raise PROOF.VerificationFailure("real explicit ready CLI flag required")
        begin = body.index("if source_deployment.is_some()", body.index(
            "RootGenerationInitialDeploymentFilesV1::open_original_initial_deployment"))
        end = PROOF._rust_item_end(body, begin)
        if end is None or "require_original_historical_root(&files, &config.state_dir)?" not in body[begin:end]:
            raise PROOF.VerificationFailure("same Root check must stay in historical opt-in")


class InitialPeerReadySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.rows = {b.identifier: b for b in PROOF._boundary_rows(cls.manifest)}
        names = set(CALLERS) | {"root_initial_profile_check", "root_initial_profile_refusal"}
        paths = {cls.rows[name].definition_path for name in names}
        paths.update(p for name in names for p in cls.rows[name].product_callers)
        cls.sources = {p: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / p).read_text()))
                       for p in paths}

    def mutate(self, path, change):
        rows = [r for r in self.manifest["protected_file"] if r["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)

            def verify(text):
                target.write_text(text)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                structure(path, text)

            verify(source)
            changed = change(source)
            self.assertNotEqual(source, changed)
            with self.assertRaises(PROOF.VerificationFailure):
                verify(changed)

    def reject(self, path, function, marker, occurrence=0):
        def change(source):
            marker_function = "fn main() -> Result" if function == "main" else "fn " + function + "("
            body, _ = route.function(source, marker_function)
            matches = list(re.finditer(route.token_pattern(marker), body))
            self.assertGreater(len(matches), occurrence, (path, function, marker))
            code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
            offset = code.index(marker_function)
            lo, hi = offset + matches[occurrence].start(), offset + matches[occurrence].end()
            return source[:lo] + "/* " + source[lo:hi] + " */" + source[hi:]
        self.mutate(path, change)

    def check(self, path, function, markers):
        for marker in markers:
            with self.subTest(function=function, marker=marker):
                self.reject(path, function, marker)

    def test_exact_actual_callers_and_scope_inventory(self):
        for name, callers in CALLERS.items():
            with self.subTest(boundary=name):
                row = self.rows[name]
                self.assertEqual(row.product_callers, callers)
                self.assertIn(name, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, self.sources, ())

    def test_removed_and_unregistered_callers_are_detected(self):
        for name in CALLERS:
            with self.subTest(boundary=name):
                row = self.rows[name]
                method = row.symbol.rsplit("::", 1)[-1]
                if row.receiver_type:
                    call = f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                elif name == "root_initial_peer_runtime_register":
                    call = "fn bypass() { peer_ready::register_original_peer(); }"
                elif name == "root_initial_ready_client":
                    call = "fn bypass() { RootGenerationInitialClient::from_original_ready_stream(); }"
                else:
                    call = f"fn bypass() {{ ready::{method}(); }}"
                sources = {**self.sources, A + "unregistered_initial_ready.rs": call}
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())
                if row.product_callers:
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=()), self.sources, ())

    def test_root_attachment_requires_same_private_cap_and_context(self):
        self.check(DEPLOYMENT, "enable_original_initial_peer_ready", (
            "original_root()?", "initial.peer_deployment.is_some()",
            "Arc::ptr_eq(&initial.phase, &deployment.capability.phase)",
            "Arc::ptr_eq(&initial.original_end, &deployment.capability.original_end)",
            "initial.phase.load(Ordering::Acquire) != PREPARED",
            "initial.deployment != deployment.files.deployment", "self.service.with_initial_publication_context(",
            "proof != initial.writer", "deployment.files.require_original_initial_files()",
        ))

    def test_one_attempt_checks_held_files_even_when_enrollment_fails(self):
        self.check(DEPLOYMENT, "with_original_peer_enrollment<T>", (
            "end > *original", "Instant::now() >= end", "std::process::id() != cap.root_pid",
            "root_start()? != cap.process_start_ticks", "trim() != cap.boot_id",
            "compare_exchange(ACTIVE, CONSUMED", "initial_enrollment_inputs(", "&self.files.data",
            "cap.consumer_uid", "let result = action(inputs)", "let post =",
            "file.require_original_file()?", "cap.phase.load(Ordering::Acquire) != CONSUMED",
            "let value = result?", "post?",
        ))
        self.reject(DEPLOYMENT, "with_original_peer_enrollment<T>", "self.files.require_original_initial_files()?", 1)
        self.reject(DEPLOYMENT, "with_original_peer_enrollment<T>", "Instant::now() >= end", 1)
        self.mutate(DEPLOYMENT, lambda s: s.replace(
            "let result = action(inputs);", "let result = action(inputs)?;", 1))

    def test_actual_context_has_original_writer_pidfd_and_absolute_end(self):
        self.check(ENROLLMENT, "require_original_context", (
            "end > self.end", "self.stopping.load(Ordering::Acquire)",
            "owner_alive(self.owner, end)?", "self.service.with_initial_publication_context(",
            "proof != self.initial.runtime.writer",
        ))
        self.reject(ENROLLMENT, "require_original_context", "owner_alive(self.owner, end)", 2)

    def test_same_enrollment_registers_actual_baselines_before_profile_ack(self):
        self.check(ENROLLMENT, "enroll_original", (
            "self.require_original_context(end)?", "self.service.enroll_generation_initial(",
            "let enrollment_post = self.require_original_context(end)", "enrolled?",
            "self.service.register_initial_run_start_retention(",
            "source.register_original_source_cell(context)?", "source.register_original_source_ledger(context)?",
            "RegisteredGenerationInitial::require_original_enrollment_profile(&slot)?",
            "let post = self.require_original_context(end)", "post.map(|()| run_start)",
        ))
        self.reject(ENROLLMENT, "enroll_original", "RegisteredGenerationInitial::refuse_original_enrollment(&slot)?", 1)

    def test_ready_transport_is_one_original_socket_and_uncertainty_fences(self):
        self.check(PEER, "register_original_peer", (
            "stream.try_clone()?", "context.peer_policy()?", "context.owner.try_clone()?",
            "HostAuthorityPeerChannel::limit_original_end(&mut channel, context.end)",
            "channel.exchange_with_original_deadline(|bytes, request_end|",
            "ready::require_request(bytes, &context.initial.runtime.ready_binding)?",
            "context.require_original_context(request_end)?", "deployment.with_original_peer_enrollment(request_end, |inputs|",
            "context.enroll_original(inputs, request_end)?", "let post = context.require_original_context(request_end)",
            "registration?", "post?", "RegisteredGenerationInitial::require_original_enrollment_profile(slot)?",
            "if !matches!(result, Ok(true))", "RegisteredGenerationInitial::refuse_original_enrollment(slot)?", "drop(channel)",
        ))

    def test_listener_and_pending_enrollment_cannot_renew_the_deadline(self):
        self.check(ROOT_RUNTIME, "bind", ("Instant::now() >= end", "runtime.original_end.set(end)", "UnixListener::bind("))
        self.check(ROOT_RUNTIME, "serve_optional", (
            "original_end.get()", "compare_exchange(PREPARED, ACTIVE", "context.accept_original(&active)?",
            "peer_ready::register_original_peer(&context, deployment, &stream)?", "Some(stream) => stream",
            "context.accept_original(&active)?", "serve_generation_initial(",
            "stopping.store(true, Ordering::Release)", "worker.join()",
        ))
        self.check(SESSION, "register", ("self.original_end.get()", "checked_duration_since(Instant::now())", "Instant::now() >= end"))

    def test_peer_and_framing_keep_original_custody_and_bounds(self):
        self.check(ENROLLMENT, "accept_original", ("owner_alive(self.owner, self.end)?", "verify_pinned_process(", "self.owner, self.end,", "stream.try_clone()?"))
        self.check(ENROLLMENT, "peer_policy", ("uid: self.config.peer_uid", "pid: self.registration.peer_pid", ".checked_duration_since(Instant::now())", "request_bound: 16 * 1024", "response_bound: 16 * 1024"))

    def test_ready_client_returns_only_after_real_observe_of_same_profile(self):
        self.check(CLIENT, "from_original_ready_stream", (
            "ready::bootstrap_binding(bootstrap)?", "stream.exchange(&ready::request(&binding)?)?",
            "ready::require_response(&response, &binding)?", "Self::from_original_initial_stream(stream, bootstrap, connection)?",
            "client.profile.binding != acknowledged", "client.connection.require_original_publication_session()?",
        ))
        for occurrence in (0, 1):
            self.reject(CLIENT, "from_original_ready_stream", "connection.require_original_publication_session()?", occurrence)

    def test_strict_ready_data_carries_no_peer_selected_business_input(self):
        self.mutate(WIRE, lambda s: s.replace("Ready {},", "Ready { path: String },", 1))
        self.mutate(WIRE, lambda s: s.replace("Ready {},", "Ready,", 1))
        self.mutate(WIRE, lambda s: s.replace("#[serde(deny_unknown_fields)]", "", 1))
        self.check(WIRE, "require_request", ("request.schema != 1", "request.purpose != PURPOSE", "request.request_id != 1", "request.bootstrap != binding"))
        self.check(WIRE, "require_response", ("require_digest(&response.profile)?", "response.schema != 1", "response.purpose != PURPOSE", "response.request_id != 1", "response.bootstrap != binding"))
        self.reject(WIRE, "require_digest", "!digest.is_zero() && digest.to_string() == value")
        self.reject(WIRE, "bootstrap_binding", "serde_json::to_vec(bootstrap)")

    def test_cli_is_explicit_and_normal_root_trigger_remains(self):
        self.mutate(CLI, lambda s: s.replace('option == "--initial-peer-ready"', 'option == "--not-the-ready-option"', 1))
        self.check(CLI, "main", ("initial_peer_ready && initial_deployment.is_none()", "if initial_peer_ready", "PreparedHostAuthoritySession::enable_original_initial_peer_ready(", "deployment.wait_and_register_initial(stop_ref)?",))
        self.check(A + "production_initial_q24.rs", "assemble_original_initial_q24", (".connect_ready_until(",))
        self.check(INPUTS, "connect_ready_until", ("OriginalEnrollment::ReadyPeer", "self.connect_original_until("))

    def test_historical_opt_in_checks_same_root_before_enrollment(self):
        self.check(FILES, "require_original_historical_root", ("original_root()?", "self.data.current_directory == state_dir", "if !same_directory"))
        for occurrence in (0, 1):
            self.reject(FILES, "require_original_historical_root", "self.require_original_initial_files()?", occurrence)
        self.reject(CLI, "main", "RootGenerationInitialDeploymentFilesV1::require_original_historical_root(&files, &config.state_dir)?")


if __name__ == "__main__":
    unittest.main()
