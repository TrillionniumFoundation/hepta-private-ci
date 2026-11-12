"""Mutate the actual final historical route, never infer a native grant.

Root replies are data under a current recipient context. These checks do not
prove a Dataset/Adopt path or that a client-only error durably refuses Root data.
"""
from dataclasses import replace
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_original_run_start_retention_source_closure as original

ROOT = original.ROOT
PROOF = original.PROOF
A = original.A
PROTOCOL = A + "root_historical_task_read_protocol.rs"
CLIENT = A + "root_historical_task_read_client.rs"
INPUTS = A + "root_historical_task_read_inputs.rs"
HANDOFF = A + "root_historical_task_read_handoff.rs"
CONNECTION = A + "root_historical_task_connection.rs"
PROVIDER = A + "authority_host_historical_read.rs"
PREPARED = A + "authority_host_historical_read_session.rs"
RUNTIME = A + "authority_host_historical_read_runtime.rs"
DEPLOYMENT = A + "authority_host_historical_source_deployment.rs"
LAUNCH = A + "production_launcher.rs"
LATE = A + "production_launcher_late_writer.rs"
CLI = A + "bin/hepta-authority-host.rs"
ROOT_INPUTS = A + "root_production_inputs.rs"
SESSION = A + "authority_host_session.rs"
CALLERS = {
    "connection_capture": (ROOT_INPUTS,), "connection_take": (ROOT_INPUTS,),
    "connection_slot": (LAUNCH, LATE), "original_session": (CLIENT, INPUTS),
    "same_session": (CLIENT,), "send": (CLI,), "receive": (LAUNCH, LATE),
    "connect": (LAUNCH, LATE), "from_stream": (INPUTS,),
    "client_session": (LAUNCH, LATE), "observe": (), "receipt_client": (),
    "receipt_read": (), "enable": (CLI,), "seal": (CLI,), "provider": (PREPARED,),
    "exchange": (RUNTIME,), "cold_source": (PROVIDER,), "cold_cell": (PROVIDER,),
    "reply": (CLIENT,), "profile": (PROVIDER, PREPARED, INPUTS),
    "bind": (SESSION,), "serve": (SESSION,),
}
CALLERS = {"root_historical_task_read_" + key: value for key, value in CALLERS.items()}
CALLERS["ordinary_historical_task_read_take"] = ()


def function(source, marker):
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    if code.count(marker) != 1:
        raise PROOF.VerificationFailure("one exact actual function required")
    begin = code.index(marker)
    end = PROOF._rust_item_end(code, begin)
    if end is None:
        raise PROOF.VerificationFailure("actual historical function body required")
    return code[begin:end + 1], source[begin:end + 1]


def token_pattern(marker):
    return r"\s*".join(map(re.escape, re.findall(
        r"[A-Za-z_]\w*|\d+|::|->|=>|!=|==|&&|\|\||\.\.|[^\s]", marker)))


def require_structure(path, source, rows):
    if path == PROVIDER:
        code, _ = function(source, "fn observe_complete_task(")
        outer = original.span(code, "|read| {")
        context = original.span(code, "|initial, proof| {")
        if not outer[0] < context[0] < context[1] < outer[1]:
            raise PROOF.VerificationFailure("whole recipient context must be inside all data refusals")
        for found in re.finditer(
            r"RootHistoricalSourceInputsV1::open_original_source_deployment\s*\("
            r"|RootInitialRunStartFilesV1::open_original_deployment\s*\("
            r"|HistoricalTaskReadResponseV1\s*\{", code,
        ):
            if not context[0] < found.start() < context[1]:
                raise PROOF.VerificationFailure("original files and reply must stay in actual recipient context")
        tail = code[context[1]:outer[1]]
        if not re.match(r"^\s*,\s*\)\?\s*;", tail):
            raise PROOF.VerificationFailure("actual context postcheck error must propagate")
        if "self.metadata.require_metadata_unchanged()?" not in tail or "require_end(end)?" not in tail:
            raise PROOF.VerificationFailure("post-context metadata and actual end must precede refusal Ready")
    if path == CLI:
        # The binary also has a distinct non-Linux main. Select the unique real
        # Result-returning Linux body, rather than weaken the global fn locator.
        code, raw = function(source, "fn main() -> Result")
        for row in rows:
            if "required_order" in row:
                PROOF._verify_required_order(row, code, path)
        for variable, flag in (
            ("historical_deployment", "--historical-task-deployment"),
            ("historical_handoff", "--root-historical-task-read-handoff-fd"),
        ):
            start = code.index("let " + variable + " = options")
            end = code.index(";", start)
            pattern = re.compile(r'\.remove\s*\(\s*std::ffi::OsStr::new\s*\(\s*"'
                                 + re.escape(flag) + r'"\s*,?\s*\)\s*,?\s*\)')
            matches = [m for m in pattern.finditer(raw[start:end])
                       if PROOF._strip_rust_non_code(m.group())
                       == code[start + m.start():start + m.end()]]
            if len(matches) != 1:
                raise PROOF.VerificationFailure("original CLI literal must bind its actual purpose input")
    if path == PROTOCOL:
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        for name in ("HistoricalTaskReadProfileV1", "HistoricalTaskReadBootstrapV1",
                     "HistoricalTaskReadRequestV1", "HistoricalTaskReadResponseV1"):
            if not re.search(r"#\[serde\(deny_unknown_fields\)\]\s*pub\(crate\) struct "
                             + name + r"\b", code):
                raise PROOF.VerificationFailure("every actual historical wire shape must reject unknown fields")
    if path == CLIENT:
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        start = code.index("struct OriginalHistoricalTaskReadReceiptV1 {")
        end = PROOF._rust_item_end(code, start)
        body = code[start:end + 1]
        if re.search(r"\bpub\b", body):
            raise PROOF.VerificationFailure("raw reply data cannot construct a historical receipt")
    if path == RUNTIME:
        code, _ = function(source, "fn serve_optional(")
        if code.count("bound.listener.accept()") != 1 or code.count("HostAuthorityPeerChannel::from_stream(") != 1:
            raise PROOF.VerificationFailure("one original historical connection required")
        if code.index("bound.listener.accept()") > code.index("let mut sequence"):
            raise PROOF.VerificationFailure("original historical route must not reconnect")


class HistoricalTaskReadSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {r.identifier: r for r in PROOF._boundary_rows(cls.manifest)}
        paths = {r.definition_path for name, r in cls.boundaries.items() if name in CALLERS}
        paths.update(path for values in CALLERS.values() for path in values)
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
                require_structure(path, text, rows)

            verify(source)
            changed = change(source)
            self.assertNotEqual(changed, source)
            with self.assertRaises(PROOF.VerificationFailure):
                verify(changed)

    def reject(self, path, name, marker, occurrence=0):
        def change(source):
            key = "fn main() -> Result" if path == CLI and name == "main" else "fn " + name + "("
            body, raw = function(source, key)
            matches = list(re.finditer(token_pattern(marker), body))
            self.assertGreater(len(matches), occurrence, (path, name, marker))
            match = matches[occurrence]
            full_code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
            start = full_code.index(key)
            lo, hi = start + match.start(), start + match.end()
            return source[:lo] + "/* " + source[lo:hi] + " */" + source[hi:]
        self.mutate(path, change)

    def check(self, path, name, markers):
        for marker in markers:
            with self.subTest(function=name, marker=marker):
                self.reject(path, name, marker)

    def test_actual_callers_and_unconnected_dataset_consumer_stay_explicit(self):
        for identifier, callers in CALLERS.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, self.sources, ())

    def test_unregistered_calls_and_removed_legitimate_callers_fail(self):
        for identifier in CALLERS:
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                method = row.symbol.rsplit("::", 1)[-1]
                call = (f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                        if row.receiver_type else f"fn bypass() {{ {method}(); }}")
                if identifier.endswith("_serve"):
                    call = "fn bypass() { historical_read::serve_optional(); }"
                sources = dict(self.sources)
                sources[A + "unregistered_historical_route.rs"] = call
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())
                if row.product_callers:
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=()), self.sources, ())

    def test_connection_is_captured_by_actual_five_lanes_and_taken_once(self):
        self.check(CONNECTION, "capture_after_original_receive", (
            "original.registered_identity.identity()? != *identity",
            "session.authority().grant_digest != original.writer_proof.sha256()?",
            "Instant::now() >= end", "original: original.clone()", "verifier: session.verifier()",
            "connection.require_same_original_session(session)?",
        ))
        self.reject(CONNECTION, "take_original_connection", "self.connection.take()")
        self.check(CONNECTION, "require_same_original_session", ("Arc::ptr_eq(&self.verifier, &session.verifier())",))
        self.check(CONNECTION, "require_original_session", (
            "uid == 0", "effective_uid == 0", "std::process::id() != self.original.consumer.pid",
            "Instant::now() >= self.end", "verify_sender_process_binding(",
            "self.original.writer.local_lease_generation", "self.identity.spawn_generation",
        ))
        self.reject(CONNECTION, "require_original_session", "Instant::now() >= self.end", 1)

    def test_handoff_owns_exact_rights_before_refusing(self):
        self.check(HANDOFF, "send_root_historical_task_read_handoff", (
            "libc::getuid()", "libc::geteuid()", "peer.pid as u32 != std::process::id()",
            "validate_bootstrap(&offer.bootstrap)?", "require_root_pin(root_pidfd, std::process::id())?",
        ))
        self.check(HANDOFF, "receive_root_historical_task_read_handoff", (
            "crate::notes_bootstrap::received_descriptors(&message)", "!valid",
            "libc::MSG_TRUNC | libc::MSG_CTRUNC", "descriptors.len() != 2",
            "size as usize != HISTORICAL_FRAME.len()", "require_root_pin(&root_pidfd, peer.pid as u32)?",
        ))

    def test_client_connect_preserves_seals_actual_root_and_original_absolute_end(self):
        self.check(INPUTS, "connect_original", (
            "connection.original_end().min(launch_end)", "timeout > Duration::from_millis(500)",
            "bytes.len() as u64 != size", "bundle.root != original.root", "bundle.consumer != original.consumer",
            "bundle.root.pid != self.root_pid", "bundle.root.uid != 0", "bundle.socket != socket",
            "bundle.profile.require_original_context(", "&original.writer_proof.sha256()?",
            "validate_lane_paths(", "timeout.min(remaining(end)?)", "OriginalPublicationStream::from_stream_until(",
            "self.root_pidfd", "process_start_ticks: bundle.root.process_start_ticks",
        ))
        for occurrence in (0, 1):
            self.reject(INPUTS, "connect_original", "validate_sealed(&self.bootstrap, size)?", occurrence)

    def test_every_exchange_is_same_session_bounded_once_and_permanently_fenced_on_error(self):
        self.check(CLIENT, "observe", (
            "self.lane.try_lock()", "held.take().ok_or_else(refused)?",
            "!(1..=MAX_READS).contains(&request_id)", "purpose: PURPOSE.into()",
            "profile: self.profile.clone()", "lane.stream.exchange(&request)?",
            "require_complete_reply(&bytes, request_id, &self.profile)?", "request_id.checked_add(1)",
            "*held = Some(lane)", "held.take()",
        ))
        for occurrence in (0, 1):
            self.reject(CLIENT, "observe", "self.connection.require_original_session()", occurrence)
            self.reject(CLIENT, "observe", "self.fenced.load(Ordering::Acquire)", occurrence)
        self.check(CLIENT, "require_original_client", ("!Arc::ptr_eq(&self.client, client)", "self.client.fence()"))
        self.mutate(CLIENT, lambda s: s.replace("    data: HistoricalTaskReadDataV1,", "    pub(crate) data: HistoricalTaskReadDataV1,", 1))

    def test_consumer_stays_between_two_actual_root_observations(self):
        for occurrence in (0, 1):
            self.reject(CLIENT, "with_current_read<T>", "self.client.observe()? != self.data", occurrence)
        self.check(CLIENT, "with_current_read<T>", ("let value = action(&self.data.ledger)?", "self.client.fence()"))

    def test_reply_is_complete_strict_and_bound_to_current_original_profile(self):
        self.check(PROTOCOL, "require_complete_reply", (
            "bytes.len() > WIRE_BOUND", "!(1..=MAX_READS).contains(&request_id)",
            "response.schema != 1", "response.purpose != PURPOSE", "response.request_id != request_id",
            "response.profile != profile", "response.ledger.validate_data()?", "canonical_digest(&response.data_cut)?",
        ))
        self.check(PROTOCOL, "require_original_context", (
            "initial.schema_version != 1", "initial.update_scope.is_some()", "self.writer != proof",
            "initial.encoded_initial().as_bytes()", "self.digest()? != self.binding", "initial.require_binding(identity, proof)",
        ))
        for occurrence in range(4):
            def remove_attribute(s):
                marker = "#[serde(deny_unknown_fields)]"
                hits = list(re.finditer(re.escape(marker), s)); pos = hits[occurrence].start()
                return s[:pos] + "/* " + marker + " */" + s[pos + len(marker):]
            self.mutate(PROTOCOL, remove_attribute)

    def test_original_source_run_start_and_whole_recipient_context_are_inside_all_arms(self):
        self.check(PROVIDER, "observe_complete_task", (
            "with_original_historical_task(service, end", "service.with_learning_profile(",
            "self.profile.require_original_context(", "self.phase.load(Ordering::Acquire) != SERVING",
            "require_original_target(", "observe_original_task(",
            "RootHistoricalSourceInputsV1::open_original_source_deployment(",
            "RootInitialRunStartFilesV1::open_original_deployment(",
            "ledger: observed.ledger_read_data()?", "reply.is_empty() || reply.len() > WIRE_BOUND",
        ))
        for occurrence in (0, 1):
            self.reject(PROVIDER, "observe_complete_task", "self.metadata.require_metadata_unchanged()?", occurrence)
        self.mutate(PROVIDER, lambda s: s.replace("                require_end(end)?;", "                RootInitialRunStartFilesV1::open_original_deployment(&self.deployment.run_start_deployment)?;\n                require_end(end)?;", 1))

    def test_root_sealing_and_serving_cannot_renew_or_replace_original_inputs(self):
        self.check(PREPARED, "seal_original_historical_task_read", (
            "compare_exchange(PREPARED, SEALED, Ordering::AcqRel, Ordering::Acquire)",
            "self.service.with_learning_profile(", "runtime.profile.require_original_context(",
            "pid: self.registration.peer_pid", "process_start_ticks: self.registration.process_start_ticks",
            "crate::authority_host_bootstrap_seal::seal_bytes(&bytes)?", "runtime.phase.store(STOPPED, Ordering::Release)",
        ))
        self.check(RUNTIME, "serve_optional", (
            "owner_alive(owner, session_end)?", "verify_pinned_process(", "*held = Some(stream.try_clone()?)",
            "request_bound: WIRE_BOUND", "response_bound: WIRE_BOUND", "request.profile != bound.runtime.profile.binding",
            "request.request_id != sequence", "!(1..=MAX_READS).contains(&sequence)", "sequence.checked_add(1)",
            "let request_end = session_end.min(Instant::now() + Duration::from_millis(config.timeout_ms))",
            "require_end(session_end)?", "stopping.store(true, Ordering::Release)", "stream.shutdown(Shutdown::Both)", "worker.join()",
        ))

    def test_cold_loaders_never_create_first_pin_or_use_peer_selected_files(self):
        self.check(DEPLOYMENT, "open_original_source_deployment", (
            "original_root()?", "MetadataFile::open_metadata(path)?",
            "data.schema_version != 1 || data.purpose != DEPLOYMENT_PURPOSE",
            "OriginalFile::open_original(&data.source_journal)?", "OriginalFile::open_original(&data.source_witness)?",
            "journal.require_original_file()?", "witness.require_original_file()?", "descriptor.require_metadata_unchanged()?",
        ))
        self.check(DEPLOYMENT, "open_original_cell_deployment", ("data.cell_files.ok_or_else(", "descriptor.require_metadata_unchanged()?"))

    def test_real_root_cli_and_both_daemon_entries_use_the_original_connection(self):
        self.check(CLI, "main", (
            "historical_deployment.is_some() != historical_handoff.is_some()",
            "historical_deployment.is_some() && root_fd.is_none()",
            "historical_deployment.is_some() && initial_deployment.is_some()",
            "prepared.enable_original_historical_task_read_from_deployment(&path)?",
            "prepared.seal_original_historical_task_read()?", "send_root_historical_task_read_handoff(",
        ))
        self.mutate(CLI, lambda s: s.replace('"--historical-task-deployment"', '"--incorrect-historical-input" /* "--historical-task-deployment" */', 1))
        for path, name in ((LAUNCH, "receive"), (LATE, "receive_original_late_writer")):
            self.check(path, name, ("root.take_historical_task_read_connection()?", "connect_original(", "client.require_same_original_session(&root.session)?"))


if __name__ == "__main__":
    unittest.main()
