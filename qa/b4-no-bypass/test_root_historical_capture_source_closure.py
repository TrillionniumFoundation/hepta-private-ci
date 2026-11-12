"""Protect the Root data pin and the exact registered terminal Root callers.

These are source mutation checks. They do not establish an A execution,
authenticated experience, retirement, historical grant or native receipt.
"""

from dataclasses import replace
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "root_historical_source_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
PIN = AGENT + "authority_host_historical_source_pin.rs"
RECORD = AGENT + "authority_host_historical_source_record.rs"
REFUSAL = AGENT + "authority_host_data_refusal.rs"
INPUTS = AGENT + "authority_host_historical_source_inputs.rs"
SESSION = AGENT + "authority_host_historical_source_session.rs"
RUNTIME = AGENT + "authority_host_generation_initial_runtime.rs"
TRANSPORT = AGENT + "authority_host_historical_source_transport.rs"
HANDOFF = AGENT + "authority_host_historical_source_handoff.rs"
DEPLOYMENT = AGENT + "authority_host_historical_source_deployment.rs"
CALLERS = {
    "root_initial_original_writer_context": (
        AGENT + "authority_host_generation_initial_session.rs",
        AGENT + "authority_host_generation_initial_enrollment.rs",
        AGENT + "authority_host_generation_initial_transport.rs",
        PIN, SESSION, TRANSPORT,
    ),
    "root_historical_source_fixed_inputs": (SESSION,),
    "root_historical_source_registered_inputs": (PIN,),
    "root_historical_source_original_capture": (SESSION,),
    "root_historical_source_enable_unconnected": (DEPLOYMENT,),
    "root_historical_source_request_unconnected": (TRANSPORT,),
    "root_historical_source_deployment_enable": (AGENT + "bin/hepta-authority-host.rs",),
    "root_historical_source_handoff_begin": (TRANSPORT,),
    "root_historical_source_handoff_ack": (TRANSPORT,),
    "root_historical_source_handoff_finalize": (TRANSPORT,),
    "root_historical_source_handoff_existing": (),
    "root_historical_source_handoff_fence": (TRANSPORT,),
    "root_historical_source_pin_publisher": (HANDOFF,),
    "root_initial_data_refusal_fresh": (RECORD, HANDOFF),
    "root_initial_data_refusal_existing": (RECORD, HANDOFF),
    "root_initial_data_refusal_inspect": (RECORD, HANDOFF),
    "root_initial_data_refusal_refuse": (RECORD, HANDOFF),
    "root_historical_source_armed_capture": (PIN,),
    "root_historical_source_armed_record": (PIN,),
    "root_generation_current_original_broker_head": (
        AGENT + "authority_host_generation_publication_enrollment.rs",
        AGENT + "authority_host_generation_publication_transport.rs",
        AGENT + "authority_host_generation_initial_enrollment.rs",
        AGENT + "authority_host_generation_initial_transport.rs", PIN,
    ),
    "root_initial_exact_retained_record": (
        AGENT + "authority_host_generation_initial_enrollment.rs",
        AGENT + "authority_host_generation_initial_transport.rs",
        AGENT + "root_generation_initial_client.rs", PIN, TRANSPORT,
    ),
}


def function_code(source, name):
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    marker = "fn " + name + "("
    if code.count(marker) != 1:
        raise PROOF.VerificationFailure("unique original function required")
    start = code.index(marker)
    end = PROOF._rust_item_end(code, start)
    if end is None:
        raise PROOF.VerificationFailure("complete original function required")
    return code[start:end + 1]


def require_read_only_recovery(source):
    # Recovery never creates or overwrites the primary data. Its independent
    # durable refusal arm is allowed; a sibling fresh initializer is not.
    for name in ("open_existing", "readback_digest"):
        code = function_code(source, name)
        if re.search(
            r"\b(?:initialize|initialize_bounded|retain|capture_initial_source_pin|"
            r"compare_and_set|write_all|set_len)\s*\(", code
        ):
            raise PROOF.VerificationFailure("historical pin recovery must only read")


class RootHistoricalSourceCaptureClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def check_mutation(self, path, mutate):
        rows = [r for r in self.manifest["protected_file"] if r["path"] == path]
        self.assertTrue(rows)
        original = (ROOT / path).read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)

            def verify(source):
                target.write_text(source)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                if path == RECORD:
                    require_read_only_recovery(source)

            verify(original)
            changed = mutate(original)
            self.assertNotEqual(changed, original)
            with self.assertRaises(PROOF.VerificationFailure):
                verify(changed)

    def rejects_removal(self, path, function, markers):
        for marker in markers:
            with self.subTest(path=path, function=function, marker=marker):
                def remove(source):
                    start = source.index("fn " + function + "(")
                    end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
                    self.assertIsNotNone(end)
                    offset = source.index(marker, start, end + 1)
                    # Keeping the removed spelling in a comment must not supply
                    # the guard in the original function's executable sequence.
                    return source[:offset] + "/* " + marker + " */" + source[offset + len(marker):]
                self.check_mutation(path, remove)

    def test_capture_requires_reserve_original_process_writer_and_target(self):
        self.rejects_removal(PIN, "capture_initial_source_pin", (
            "original_root()?", "self.with_initial_publication_context(",
            "inputs.into_registered(", "slot.mode != RootGenerationInitialModeV1::Reserve",
            "slot.profile.writer != proof", "slot.profile.identity",
            "Some(inputs.fence.generation)",
            "inputs.fence.owner_agent_id != self.identity.agent_id",
            "registration.checkpoint_owner_agent_id != self.identity.agent_id",
            "registration.publisher_epoch == 0", ".validate_peer(", "require_target(",
            "original_initial_record(",
            "slot.verify_recorded_use(&signed, &witness)? != revocations",
        ))

    def test_source_cut_must_be_read_physically_before_and_after_root_retention(self):
        self.rejects_removal(PIN, "capture_initial_source_pin", (
            "FilePin::readonly(&inputs.journal", "FilePin::readonly(&inputs.witness",
            "witness_file.metadata()?.len() == 0", "FileAnchorWitnessStore::open(",
            "HistoricalCircuitTaskSourceV1::open(",
            "observe_run_publication(&inputs.source.scope.run_id)",
            "observed.original_identity() != &self.identity",
            "observed.original_fence() != &inputs.fence",
            "observed.original_source() != &inputs.source",
            "observed.publication().bundle_digest()", "!= inputs.definition.bundle_digest",
            "RootHistoricalSourcePinV1::retain_unchecked(", "!= observed",
            "slot.target.observe().map_err(io::Error::other)? != target",
            "current.original_broker_head().map_err(io::Error::other)? != head",
            "FilePin::read(&inputs.journal", "FilePin::read(&inputs.witness",
            "RootHistoricalSourcePinV1::capture(", "retained.ok_or_else(",
        ))

    def test_descriptor_custody_does_not_borrow_the_writer_lock(self):
        self.rejects_removal(PIN, "read", (
            "!metadata.is_file()", "metadata.nlink() != 1",
            "![(0, 0), (uid, gid)].contains(&(metadata.uid(), metadata.gid()))",
            "metadata.mode() & 0o7777 != 0o600",
        ))
        self.rejects_removal(PIN, "readonly", (
            "Self::read(file, uid, gid)?", "File::open(format!(",
            "Self::read(&readonly, uid, gid)? != pin",
            "Self::read(file, uid, gid)? != pin",
        ))
        for marker in ("OpenOptions", "try_clone(", "DurableCircuitTaskSourceV1::"):
            self.check_mutation(PIN, lambda source: source + "\n" + marker)

    def test_original_inputs_are_fixed_before_serving_and_rechecked_at_capture(self):
        self.rejects_removal(INPUTS, "retain_original", (
            "original_root()?", "require_target(target, &self.definition, &self.source)?",
            "self.fence.owner_agent_id != identity.agent_id",
            "identity.spawn_generation.checked_add(1) != Some(self.fence.generation)",
            "FilePin::readonly(&self.journal, uid, gid)?",
            "FilePin::readonly(&self.witness, uid, gid)?",
            "(journal_pin.device, journal_pin.inode) == (witness_pin.device, witness_pin.inode)",
            "self.journal = journal", "self.witness = witness",
        ))
        self.rejects_removal(INPUTS, "into_registered", (
            "original_root()?", "&self.target != target", "self.identity",
            "FilePin::read(&self.inputs.journal, uid, gid)?",
            "FilePin::read(&self.inputs.witness, uid, gid)?",
        ))
        for marker in ("Deserialize", "pub inputs:", "pub target:", "pub identity:"):
            self.check_mutation(INPUTS, lambda source: source + "\n" + marker)

    def test_pin_recovery_does_not_initialize_and_refuses_fenced_or_different_records(self):
        self.rejects_removal(RECORD, "open_existing", (
            "original_root()?", "RootDataRefusalV1::open_existing(",
            "refusal.inspect(|| {", "HostAuthorityFrontierStore::open(root, owner.clone())",
            "expected.fenced", "expected.pin.schema != 1",
            "expected.pin.purpose != PIN_PURPOSE", "&expected.pin.target != target",
        ))
        self.rejects_removal(RECORD, "readback_digest", ("self.inspect_exact(|| {",))
        self.rejects_removal(RECORD, "inspect_exact<T>", (
            "original_root()?", "if *poisoned", "self.refusal.inspect(|| {",
            "self.store.load(&self.owner).map_err(io::Error::other)? != self.expected",
            "action()", "if result.is_err()", "*poisoned = true",
        ))
        self.rejects_removal(RECORD, "fence", (
            "original_root()?", "self.refusal.refuse()?", "next.fenced = true",
            "self.store.load(&self.owner).map_err(io::Error::other)? == next",
            "compare_and_set(&self.owner, &self.expected, &next)",
        ))
        self.rejects_removal(RECORD, "retain_unchecked", (
            "original_root()?", "PinRecordAccess::Fresh", "PinRecordAccess::Existing",
            "store.load(&owner).map_err(io::Error::other)? != expected",
        ))
        for name in ("open_existing", "readback_digest"):
            def insert_write(source):
                start = source.index("fn " + name + "(")
                offset = source.index("{", start) + 1
                return source[:offset] + "\nHostAuthorityFrontierStore::initialize(root, owner, fake);" + source[offset:]
            self.check_mutation(RECORD, insert_write)

    def test_root_lifetime_is_the_actual_process_and_boot(self):
        self.rejects_removal(SESSION, "require_current", (
            "original_root()?", "std::process::id() != self.pid",
            "super::root_start()? != self.start",
            'std::fs::read_to_string("/proc/sys/kernel/random/boot_id")',
            "!= self.boot",
        ))
        self.rejects_removal(SESSION, "enable_initial_source_capture", (
            "original_root()?", "initial.source_capture.is_some()",
            "initial.phase.load(Ordering::Acquire) != PREPARED",
            "self.service.with_initial_publication_context(", "inputs.retain_original(",
            "self.registration.registered_identity.identity()?",
            "&initial.deployment.target", "root.require_current()?",
        ))

    def test_capability_shares_the_session_deadline_and_requires_one_shot_ack_consumption(self):
        self.rejects_removal(SESSION, "capture", (
            "self.root.require_current()?", ".end\n            .get()",
            "compare_exchange(ACTIVE, CONSUMED", ".checked_duration_since(Instant::now())",
            ".filter(|remaining| !remaining.is_zero())", ".recv_timeout(remaining)",
            "if Instant::now() >= end", "compare_exchange(CONSUMED, ACKNOWLEDGED",
            "self.phase.store(CLOSED",
        ))
        self.rejects_removal(SESSION, "serve", (
            ".set(context.end)", "compare_exchange(PREPARED, ACTIVE",
            "owner_alive(context.owner, context.end)?",
            "self.phase.load(Ordering::Acquire) != CONSUMED", ".take()",
            "context.service.capture_initial_source_pin(", "pin.readback_digest()?",
            "verify_pinned_process(", ".try_send(Ok(digest))",
            "ACKNOWLEDGED => return Ok(())", "== Err(ACKNOWLEDGED)",
            "if delivered.is_err()", "pin.fence()?", "self.close()",
        ))

    def test_capture_request_cannot_choose_payload_or_clone_a_capability(self):
        for field in ("path: String,", "run: String,", "observation: Vec<u8>,"):
            self.check_mutation(SESSION, lambda source: source.replace(
                "struct Submission {", "struct Submission {\n    " + field, 1
            ))
        for marker in ("Deserialize", "impl Clone for RootHistoricalSourceCaptureCapabilityV1",
                       "recv_timeout(self.lifetime)", "UnixStream::connect", "Command::Observe"):
            self.check_mutation(SESSION, lambda source: source + "\n" + marker)

    def test_original_session_exit_closes_pending_capture_without_a_new_wait_window(self):
        self.rejects_removal(SESSION, "serve_optional", (
            "scope.spawn(|| source.serve(context))", "source.close()", "join()",
        ))
        self.rejects_removal(SESSION, "close", ("(phase != ACKNOWLEDGED).then_some(CLOSED)",))
        self.rejects_removal(RUNTIME, "serve_optional", (
            "source_capture::serve_optional(", "slot: &slot", "stopping: &stopping",
            "initial.runtime.source_capture.as_ref()", "source.close()",
        ))



    def test_shared_source_preimage_preserves_original_inputs_and_registry(self):
        data = AGENT + "authority_host_historical_source_deployment_data.rs"
        self.rejects_removal(data, "into_inputs", (
            "self.into_configuration(identity)?", "original.registry().map_err(io::Error::other)?",
            "journal,\n            witness,",
        ))
        self.rejects_removal(data, "into_configuration", (
            "self.schema_version != 1", "TaskFlowFence::new(", "identity.agent_id.clone()",
            "agent_id: StableId::new(identity.agent_id.as_str())",
            "lease_duration_ms: source.lease_duration_ms",
        ))
        self.rejects_removal(AGENT + "circuit_q24_source_configuration.rs", "registry", (
            "program.program_id == self.circuit.entry_program", "CircuitCellBindingV1 {",
            "cell: self.definition.clone()", "routes: self.routes.clone()",
            "CircuitCellRegistryV1::new(self.circuit.clone(), vec![binding])",
        ))

    def test_shared_initial_decoder_cannot_open_root_authorities(self):
        data = AGENT + "authority_host_initial_deployment_data.rs"
        self.rejects_removal(data, "from_original_deployment_value", (
            "data.schema_version != 1", "data.owner_trust.original_owner_trust()?",
            "data.selector_trust.original_selector(&trust)?",
            "data.target.original_observer_config()?",
            "data.retained_current.original_current()?",
            "data.selection.original_selection()?",
        ))
        self.check_mutation(data, lambda source: source + "\nRootAuthorityDirectory::open(path);\n")


class RootHistoricalSourceCallerClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {b.identifier: b for b in PROOF._boundary_rows(cls.manifest)}
        paths = {path for identifier, expected in CALLERS.items()
                 for path in (cls.boundaries[identifier].definition_path, *expected)}
        cls.sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in paths}

    def test_component_and_terminal_root_callers_are_exact(self):
        for identifier, expected in CALLERS.items():
            with self.subTest(identifier=identifier):
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, self.sources, ())

    def test_each_real_internal_caller_must_be_declared(self):
        for identifier, callers in CALLERS.items():
            row = self.boundaries[identifier]
            for missing in callers:
                with self.subTest(identifier=identifier, missing=missing):
                    altered = replace(row, product_callers=tuple(p for p in callers if p != missing))
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                        PROOF._verify_boundary(ROOT, altered, self.sources, ())

    def test_new_public_entrypoint_callers_cannot_hide_outside_the_closed_set(self):
        for identifier, call in (
            ("root_historical_source_enable_unconnected",
             "fn unregistered(host: &mut PreparedHostAuthoritySession) { host.enable_initial_source_capture(inputs); }"),
            ("root_historical_source_request_unconnected",
             "fn unregistered(cap: RootHistoricalSourceCaptureCapabilityV1) { cap.capture(); }"),
            ("root_historical_source_deployment_enable",
             "fn unregistered(host: &mut PreparedHostAuthoritySession) { host.enable_initial_source_capture_from_deployment(path); }"),
            ("root_initial_data_refusal_fresh",
             "fn unregistered() { RootDataRefusalV1::create_fresh(root, kind, target, action); }"),
            ("root_initial_data_refusal_existing",
             "fn unregistered() { RootDataRefusalV1::open_existing(root, kind, target); }"),
            ("root_initial_data_refusal_inspect",
             "fn unregistered(refusal: &RootDataRefusalV1) { refusal.inspect(action); }"),
            ("root_initial_data_refusal_refuse",
             "fn unregistered(refusal: &RootDataRefusalV1) { refusal.refuse(); }"),
            ("root_historical_source_armed_capture",
             "fn unregistered() { RootHistoricalSourcePinV1::capture(root, target, action); }"),
            ("root_historical_source_armed_record",
             "fn unregistered() { RootHistoricalSourcePinV1::retain_unchecked(root, pin, access); }"),
            ("root_historical_source_handoff_existing",
             "fn unregistered() { RootHistoricalSourceHandoffV1::open_finalized(root, target); }"),
        ):
            sources = dict(self.sources)
            sources[AGENT + "unregistered_source_capture.rs"] = call
            with self.subTest(identifier=identifier):
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, self.boundaries[identifier], sources, ())


if __name__ == "__main__":
    unittest.main()
