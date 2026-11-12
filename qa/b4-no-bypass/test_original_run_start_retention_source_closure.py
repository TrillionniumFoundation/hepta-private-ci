"""Keep a real live RunStart ACK distinct from cold data and execution authority.

These mutations are source checks. Actual Root/store subprocess execution and
the ordinary A/Outcome/learning chain require separate retained native results.
"""

from dataclasses import replace
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_root_historical_capture_source_closure as component
import test_root_data_refusal_source_closure as refusal


ROOT = component.ROOT
PROOF = component.PROOF
A = component.AGENT
STORE = A + "authority_host_run_start_store.rs"
CONTEXT = A + "authority_host_run_start_context.rs"
INPUTS = A + "authority_host_run_start_inputs.rs"
DEPLOYMENT = A + "authority_host_run_start_deployment.rs"
TRANSPORT = A + "authority_host_run_start_transport.rs"
CLIENT = A + "root_generation_initial_run_start.rs"
OBJECTIVE = A + "objective_run_start_retention.rs"
SUBMISSION = A + "objective_submission.rs"
CALLERS = {
    "root_initial_run_start_enable": (A + "bin/hepta-authority-host.rs",),
    "root_initial_run_start_fixed_files": (A + "authority_host_historical_read.rs", A + "authority_host_post_a_provider.rs"),
    "root_initial_run_start_original_files": (INPUTS, CONTEXT),
    "root_initial_run_start_register": (A + "authority_host_generation_initial_runtime.rs",),
    "root_initial_run_start_live_retain": (TRANSPORT,),
    "root_initial_run_start_original_pin": (STORE,),
    "root_initial_run_start_original_observe": (CONTEXT, STORE),
    "root_initial_run_start_cold_data": (A + "authority_host_historical_task.rs",),
    "root_initial_run_start_cold_digest": (),
    "root_initial_run_start_cold_physical": (),
    "root_initial_run_start_client": (A + "neuron_generation_current_initial_run_start.rs",),
    "root_initial_run_start_current": (A + "production_run_start_retention.rs",),
    "ordinary_initial_run_start_select": (A + "production_initial_q24.rs",),
    "ordinary_initial_run_start_original_append": (OBJECTIVE,),
    "ordinary_initial_run_start_config": (A + "production_launcher.rs",),
    "ordinary_initial_run_start_take": (A + "runtime.rs",),
    "ordinary_initial_run_start_objective": (A + "runtime.rs",),
    "ordinary_initial_run_start_before_execution": (SUBMISSION,),
    "root_initial_run_start_original_trust_data": (INPUTS,),
}


def span(code, marker):
    if code.count(marker) != 1:
        raise PROOF.VerificationFailure("one exact RunStart action required")
    start = code.index("{", code.index(marker))
    depth, end = 1, start + 1
    while depth and end < len(code):
        depth += (code[end] == "{") - (code[end] == "}")
        end += 1
    if depth:
        raise PROOF.VerificationFailure("complete RunStart action required")
    return start, end


def require_structure(path, source):
    if path == STORE:
        code = component.function_code(source, "register_initial_run_start_retention")
        arm, arm_end = span(code, "RootDataRefusalV1::create_fresh(")
        context, context_end = span(code, "|proof| {")
        if not arm < context < context_end < arm_end:
            raise PROOF.VerificationFailure("registration context escaped durable arm")
        for match in re.finditer(r"OriginalInputPin::capture\s*\(|RunStartRecordStore::initialize_unchecked\s*\(", code):
            if not context < match.start() < context_end:
                raise PROOF.VerificationFailure("original physical baseline escaped context")
        tail = code[context_end:arm_end]
        if not re.match(r"^\s*,\s*\)\?\s*;", tail) or "require_end(session_end)?" not in tail:
            raise PROOF.VerificationFailure("registration lacks real context/end postchecks")
        cold = component.function_code(source, "open_finalized")
        begin, end = span(cold, "RootDataRefusalV1::inspect(&refusal, || {")
        for marker in ("HostAuthorityFrontierStore::open(", "store.load(&owner)",
                       "expected.phase != RetentionPhase::Finalized"):
            if not begin < cold.index(marker) < end:
                raise PROOF.VerificationFailure("cold primary read escaped independent arm")
        if re.search(r"\b(?:initialize|initialize_unchecked|create_fresh|finalize_unchecked)\s*\(", cold):
            raise PROOF.VerificationFailure("cold data reader cannot create first acknowledgement")
        for name in ("readback_digest", "read_original_publication"):
            code = component.function_code(source, name)
            begin, end = span(code, "RootDataRefusalV1::inspect(&self.refusal, || {")
            for match in re.finditer(r"require_exact_unchecked\s*\(|OriginalInputPin::observe\s*\(|read_original_publication_unchecked\s*\(", code):
                if not begin < match.start() < end:
                    raise PROOF.VerificationFailure("retained data read escaped independent arm")
    if path == CONTEXT:
        code = component.function_code(source, "retain_initial_run_start")
        arm, arm_end = span(code, "RootDataRefusalV1::inspect(&retained.refusal, || {")
        context, context_end = span(code, "|proof| {")
        finalize = code.index("state.finalize_unchecked(")
        if not arm < context < context_end < finalize < arm_end:
            raise PROOF.VerificationFailure("Finalized precedes actual complete Root context")
        if not re.match(r"^\s*,\s*\)\?\s*;", code[context_end:finalize]):
            raise PROOF.VerificationFailure("original context error was not propagated")
        for match in re.finditer(r"OriginalInputPin::observe\s*\(|slot.require_genesis\s*\(", code):
            if not context < match.start() < context_end:
                raise PROOF.VerificationFailure("physical RunStart/genesis escaped original context")
        deadline = code.rindex("require_end(request_end)?")
        receipt = code.index("OriginalRunStartRetentionResponseV1 {")
        if not finalize < receipt < deadline < arm_end:
            raise PROOF.VerificationFailure("Ready preceded real receipt/deadline postcheck")
        if code.index("state.expected = next") < arm_end:
            raise PROOF.VerificationFailure("cached Finalized advanced before durable inspection")
    if path == SUBMISSION:
        code = component.function_code(source, "submit_for<P: ObjectiveExecutionProfile>")
        begin, end = span(code, "let (published, record) = {")
        if not begin < code.index("compile_and_publish_objective_run_v1(") < end:
            raise PROOF.VerificationFailure("original append left its mutex scope")
        retain = code.index("self.retain_original_run_start_before_execution(")
        if not end < code.index("if !authentication_is_current(", end) < retain < code.index("P::execute("):
            raise PROOF.VerificationFailure("first Root acknowledgement left real live seam")


class OriginalRunStartRetentionSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
        paths = {path for identifier, expected in CALLERS.items()
                 for path in (cls.boundaries[identifier].definition_path, *expected)}
        cls.sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in paths}

    def test_original_root_and_daemon_callers_are_exact(self):
        for identifier, expected in CALLERS.items():
            with self.subTest(boundary=identifier):
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, self.sources, ())

    def test_every_actual_live_caller_must_remain_declared(self):
        for identifier, expected in CALLERS.items():
            for missing in expected:
                with self.subTest(boundary=identifier, missing=missing):
                    row = replace(self.boundaries[identifier], product_callers=tuple(
                        path for path in expected if path != missing))
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                        PROOF._verify_boundary(ROOT, row, self.sources, ())

    def test_unregistered_live_and_cold_callers_are_rejected(self):
        for identifier in (
            "root_initial_run_start_enable", "root_initial_run_start_register",
            "root_initial_run_start_live_retain", "root_initial_run_start_cold_data",
            "root_initial_run_start_cold_digest", "root_initial_run_start_cold_physical",
            "ordinary_initial_run_start_select",
        ):
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                method = row.symbol.rsplit("::", 1)[-1]
                call = (f"fn unregistered(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                        if row.receiver_type else f"fn unregistered() {{ {row.symbol}(); }}")
                sources = dict(self.sources)
                sources[A + "unregistered_run_start.rs"] = call
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())

    def test_cold_physical_read_guards_the_real_root_receiver(self):
        row = self.boundaries["root_initial_run_start_cold_physical"]
        self.assertEqual(row.receiver_type, "RootRetainedRunStartDataV1")
        self.assertIsNone(row.call_pattern)
        self.assertEqual(row.product_callers, ())
        path = A + "unregistered_retained_data.rs"
        sources = dict(self.sources)
        sources[path] = (
            "fn read(owner: &UnrelatedArtifactReadView) { owner.read_original_publication(); }"
        )
        PROOF._verify_boundary(ROOT, row, sources, ())
        sources[path] = (
            "fn read(owner: &RootRetainedRunStartDataV1) { owner.read_original_publication(); }"
        )
        with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
            PROOF._verify_boundary(ROOT, row, sources, ())

    def verify_path(self, root, path):
        rows = [r for r in self.manifest["protected_file"] if r["path"] == path]
        self.assertTrue(rows)
        PROOF._verify_protected_files(root, {"protected_file": rows})
        require_structure(path, (root / path).read_text())

    def mutation(self, path, mutate):
        original = (ROOT / path).read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(original)
            self.verify_path(root, path)
            target.write_text(mutate(original))
            with self.assertRaises(PROOF.VerificationFailure):
                self.verify_path(root, path)

    def remove(self, path, name, markers):
        for marker in markers:
            with self.subTest(path=path, marker=marker):
                def mutate(source):
                    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
                    function = "fn " + name + "("
                    self.assertEqual(code.count(function), 1)
                    start = code.index(function)
                    end = PROOF._rust_item_end(code, start)
                    position = source.index(marker, start, end)
                    return source[:position] + source[position + len(marker):]
                self.mutation(path, mutate)

    def test_root_only_prepared_metadata_pins_original_three_files(self):
        self.remove(DEPLOYMENT, "open_original_deployment", (
            "original_root()?", "MetadataFile::open_metadata(path)?",
            "data.schema_version != 1 || data.purpose != DEPLOYMENT_PURPOSE",
            "OriginalFile::open_original(&data.journal)?",
            "OriginalFile::open_original(&data.objective_profile)?",
            "OriginalFile::open_original(&data.authbus_trust)?",
        ))
        self.remove(DEPLOYMENT, "enable_initial_run_start_retention_from_deployment", (
            "initial.phase.load(Ordering::Acquire) != PREPARED || initial.run_start.is_some()",
            "self.service.with_initial_publication_context(", "&self.owner_pidfd",
            "initial.run_start = Some(Arc::new(files))",
        ))

    def test_original_descriptor_custody_is_rechecked_after_every_action(self):
        self.remove(DEPLOYMENT, "with_original_files<T>", (
            "self.metadata.require_metadata_unchanged()?", "self.journal.original_descriptor()?",
            "self.profile.original_descriptor()?", "self.trust.original_descriptor()?",
            "let value = action(&journal, &profile, &trust)?",
            "self.journal.require_original_file()?", "self.profile.require_original_file()?",
            "self.trust.require_original_file()?",
        ))
        self.remove(INPUTS, "read", (
            "libc::fcntl(file.as_raw_fd(), libc::F_GETFL)", "flags < 0", "io::Error::last_os_error()", "flags & libc::O_ACCMODE != libc::O_RDONLY || flags & libc::O_PATH != 0",
            "metadata.nlink() != 1", "metadata.mode() & 0o7777 != 0o600",
            "![(0, 0), (uid, gid)].contains(&(metadata.uid(), metadata.gid()))",
        ))

    def test_complete_baseline_precedes_first_ack_and_never_comes_from_peer(self):
        self.remove(STORE, "register_initial_run_start_retention", (
            "slot.mode != RootGenerationInitialModeV1::Reserve", "RootDataRefusalV1::create_fresh(",
            "self.with_initial_publication_context(", "if held.is_some()",
            "OriginalInputPin::capture(", "state.require_exact_unchecked()?",
        ))
        self.remove(INPUTS, "capture", (
            "observe_original_run_start_prefix_v1(journal, binding, MAX_RECORDS)",
            "prefix_length: prefix.length", "prefix_digest: prefix.digest.to_string()",
            "pin.require_decoded(&decode_inputs(",
        ))

    def test_live_source_matches_same_physical_prefix_frame_and_complete_tuple(self):
        self.remove(INPUTS, "observe", (
            "publication.run_id != target.scope().run_id", "publication.profile_digest != self.profile_digest",
            "ReadOnlyRunStartViewV1::open(", "read_with_frame_at_original_prefix(",
            "self.prefix_length", "digest(&self.prefix_digest)?",
            "observed.frame_start < self.prefix_length", "observed.frame_end > observed.observed_length",
            "actual.publication.sequence != publication.sequence",
            "actual.publication.record_digest != digest(&publication.record_digest)?",
            "actual.publication.chain_digest != digest(&publication.chain_digest)?",
            "record.snapshot.generation != target.generation()",
            "record.admission.observed_at_unix_micros > now_micros",
            "record.admission.deadline_unix_micros <= now_micros",
            "authentication_is_current(", "if read()? != observed",
        ))

    def test_original_root_context_and_actual_deadline_surround_finalization(self):
        self.remove(CONTEXT, "retain_initial_run_start", (
            "retained.consumed.swap(true, Ordering::AcqRel)",
            "session_end.min(Instant::now() + Duration::from_millis(config.timeout_ms))",
            "RootDataRefusalV1::inspect(&retained.refusal, || {",
            "self.with_initial_publication_context(", "slot.require_genesis()?",
            "slot.verify_recorded_use(&signed, &witness)? != revocations",
            "OriginalInputPin::observe(", "if confirmed != observed",
            "state.finalize_unchecked(", "store::record_digest(&next)?.to_string()",
        ))
        def hide_last_deadline(source):
            marker = "require_end(request_end)?"
            position = source.rindex(marker)
            return source[:position] + "Ok::<(), io::Error>(())?" + source[position + len(marker):] + "\n// " + marker
        self.mutation(CONTEXT, hide_last_deadline)

    def test_first_attempt_error_cannot_retry_or_promote_cold_data(self):
        self.remove(TRANSPORT, "exchange", (
            "if self.attempted", "self.attempted = true", "require_end(self.session_end)?",
            "request.purpose != RUN_START_RETENTION_PURPOSE", "request.profile != self.slot.profile.binding",
            "request.request_id != *sequence", ".checked_add(1)",
            "self.service.retain_initial_run_start(", "RootDataRefusalV1::refuse(&retained.refusal)?",
        ))
        self.remove(STORE, "open_finalized", (
            "RootDataRefusalV1::open_existing(", "RootDataRefusalV1::inspect(&refusal, || {",
            "expected.phase != RetentionPhase::Finalized", "expected.observed.is_none()",
        ))

    def test_context_result_cannot_be_discarded_before_clearing_arm(self):
        for path, name in ((STORE, "register_initial_run_start_retention"),
                           (CONTEXT, "retain_initial_run_start")):
            with self.subTest(path=path):
                def discard(source):
                    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
                    start = code.index("fn " + name + "(")
                    end = PROOF._rust_item_end(code, start)
                    body = code[start:end + 1]
                    _, context_end = span(body, "|proof| {")
                    tail = re.match(r"^\s*,\s*\)(\?)\s*;", body[context_end:])
                    self.assertIsNotNone(tail)
                    position = start + context_end + tail.start(1)
                    return source[:position] + source[position + 1:]
                self.mutation(path, discard)

    def test_cross_process_driver_requires_executed_phase_receipt(self):
        source = (ROOT / A / "authority_host_run_start_retention_tests.rs").read_text()
        refusal.require_executed_child(source)
        for marker in ("output.status.success()",
                       "&& String::from_utf8_lossy(&output.stdout).contains(receipt.as_str())",
                       "std::io::stdout().flush()?"):
            with self.subTest(marker=marker):
                self.assertEqual(source.count(marker), 1)
                with self.assertRaises(PROOF.VerificationFailure):
                    refusal.require_executed_child(source.replace(marker, "", 1))

    def test_cold_data_readback_keeps_arm_identity_and_original_physical_cut(self):
        self.remove(STORE, "read_original_publication", (
            "RootDataRefusalV1::inspect(&self.refusal, || {",
            "self.read_original_publication_unchecked(files, original_identity)",
        ))
        self.remove(STORE, "read_original_publication_unchecked", (
            "self.state.require_exact_unchecked()?",
            "neuron_generation_process_identity_digest_v1(original_identity)",
            "original.spawn_generation != original_identity.spawn_generation",
            "OriginalInputPin::observe(", "observed.observed_unix_ms",
            "frame.frame_start != observed.frame_start", "frame.frame_end != observed.frame_end",
            "frame.observed_length < observed.observed_length",
        ))

    def test_daemon_requires_fresh_actual_append_and_never_renews_the_lane(self):
        self.remove(CLIENT, "retain_live_run_start", (
            "self.run_start_attempted.swap(true, Ordering::AcqRel)",
            "published.publication.disposition != RunStartAppendDisposition::Appended",
            "published.run_start != record.snapshot", "self.lane.try_lock()", "held.take()",
            "request_id.checked_add(1)", "lane.stream.exchange(", "require_retained_reply(",
            "self.observe_initial_current()? != before", "self.fence()",
        ))
        self.remove(CLIENT, "require_retained_reply", (
            "response.request_id != request_id", "response.profile != profile", "response.mode != mode",
            "&response.publication != publication", "retained.is_zero()",
            "retained.to_string() != response.retained",
        ))

    def test_actual_live_seam_rechecks_current_authbus_before_execution(self):
        self.remove(SUBMISSION, "submit_for<P: ObjectiveExecutionProfile>", (
            "let (published, record) = {", "compile_and_publish_objective_run_v1(",
            "self.retain_original_run_start_before_execution(agentd, &record, &published)",
            "P::execute(agentd, &record).await?",
        ))
        self.remove(OBJECTIVE, "retain_original_run_start_before_execution", (
            "retained.identity != *agentd.identity() || !agentd.circuit_task_enabled()",
            ".retain_live_append(record.clone(), published.clone())", ".await?",
            "authbus_ingress::require_objective_ready(agentd)?", "agentd.current_generation()?",
            "record.snapshot.generation != generation",
            "record.snapshot.fence_digest != objective_fence(agentd.identity(), generation)",
            "authbus_ingress::attached(agentd)?.trust(agentd)?", "if !authentication_is_current(",
        ))

    def test_actual_ordinary_caller_cannot_be_replaced_by_component_definitions(self):
        rows = {r["id"]: r for r in self.manifest["boundary"]}
        for identifier, caller in (
            ("ordinary_initial_run_start_select", "production_initial_q24.rs"),
            ("ordinary_initial_run_start_before_execution", "objective_submission.rs"),
            ("root_initial_run_start_register", "authority_host_generation_initial_runtime.rs"),
            ("root_initial_run_start_live_retain", "authority_host_run_start_transport.rs"),
        ):
            self.assertEqual(rows[identifier]["product_callers"], [A + caller])
        self.assertEqual(rows["root_initial_run_start_cold_data"]["product_callers"],
                         [A + "authority_host_historical_task.rs"])
        for identifier in ("root_initial_run_start_cold_digest", "root_initial_run_start_cold_physical"):
            self.assertEqual(rows[identifier]["product_callers"], [])
        self.remove(A + "production_initial_q24.rs", "assemble_original_initial_q24", (
            "self.retain_original_initial_run_start(&published)?",
        ))


if __name__ == "__main__":
    unittest.main()
