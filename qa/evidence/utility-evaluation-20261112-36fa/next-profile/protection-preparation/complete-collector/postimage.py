"""Close explicit evaluated 4/5-cut reads and actual remote S receipts.

Five-cut serving reads an existing C result. It is not a remote C receipt or
command consumer. These source gates grant no ordinary deployment qualification.
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
    "evaluated_published_read_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
CUT = AGENT + "circuit_evaluated_learning_read.rs"
PROFILE = AGENT + "circuit_learning_read_profile.rs"
REMOTE = AGENT + "circuit_evaluated_selection_remote.rs"
CLIENT = AGENT + "circuit_learning_read_capability.rs"
SERVICE = AGENT + "circuit_learning_read_service.rs"
WIRE = AGENT + "circuit_learning_read_wire.rs"
READINESS = AGENT + "circuit_learning_completion_readiness_service.rs"
SELECTOR = AGENT + "circuit_selection_receipt_owner.rs"
EVALUATED_S = AGENT + "circuit_evaluated_selection_receipt.rs"
EXPECTED = {
    "learning_original_evaluated_read_selection_context": ('codex-rs/hepta-agentd/src/circuit_retained_version_state.rs',),
    "learning_original_evaluated_read_next_use_context": ('codex-rs/hepta-agentd/src/circuit_learning_completion_readiness.rs',),
    "learning_original_evaluated_read_client_create": (),
    "learning_original_evaluated_read_owner_create": ('codex-rs/hepta-agentd/src/circuit_retained_version_state.rs',),
    "learning_original_evaluated_read_selection_binding": ('codex-rs/hepta-agentd/src/circuit_evaluated_selection_remote.rs', 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_command_service.rs'),
    "learning_original_evaluated_selection_remote_attest": ('codex-rs/hepta-agentd/src/circuit_evaluated_selection_command_service.rs',),
    "learning_original_evaluated_selection_remote_readback": ('codex-rs/hepta-agentd/src/circuit_evaluated_selection_command_service.rs',),
    "learning_original_published_read_client_current": ('codex-rs/hepta-agentd/src/circuit_selection_receipt_owner.rs', 'codex-rs/hepta-agentd/src/circuit_next_use_receipt_owner.rs', 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_remote.rs', 'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_remote.rs'),
}
DOMAINS = {
    PROFILE: [(None, r"const EVALUATED_OPERATION: &str =", '"runtime.learning.original-circuit.evaluated-current-read.v1"')],
    WIRE: [
        (None, r"pub\(super\) const OPERATION: &str =", '"runtime.learning.original-circuit.current-read.v1"'),
        ("context_binding", r"Ok\(Digest32::of_parts\(&\[", 'b"hepta.agentd.original-circuit-current-read.v1\\0"'),
    ],
    CUT: [
        ("binding", r"Ok\(Digest32::of_parts\(&\[", 'b"hepta.agentd.original-circuit-evaluated-current-read.v1\\0"'),
        ("binding", r"\(\s*4,\s*LearningIterationStageV1::Selection,", 'b"selection"'),
        ("binding", r"\(\s*5,\s*LearningIterationStageV1::NextUse,", 'b"next_use"'),
    ],
}


def function_span(source, name):
    code = PROOF._strip_rust_non_code(source)
    marker = "fn " + name + "("
    if code.count(marker) != 1:
        raise PROOF.VerificationFailure("unique actual function: " + marker)
    start = code.index(marker)
    end = PROOF._rust_item_end(code, start)
    if end is None:
        raise PROOF.VerificationFailure("complete actual function: " + marker)
    return code, start, end + 1


def require_actual_domains(path, source):
    """Check literals at real code spans; a comment cannot supply the domain."""
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    for function, prefix, literal in DOMAINS.get(path, ()):
        start, end = 0, len(code)
        if function is not None:
            _, start, end = function_span(source, function)
        found = list(re.finditer(prefix, code[start:end]))
        if len(found) != 1:
            raise PROOF.VerificationFailure("unique actual protocol-domain expression")
        offset = start + found[0].end()
        actual = re.match(r'\s*(b?"(?:[^"\\]|\\.)*")', source[offset:end])
        if actual is None or actual.group(1) != literal:
            raise PROOF.VerificationFailure("actual protocol domain differs: " + path)
        if function is None and code[:start + found[0].start()].count("{") != code[:start + found[0].start()].count("}"):
            raise PROOF.VerificationFailure("protocol operation must be a module constant")


class EvaluatedPublishedReadClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def verifies(self, path, source, domains=True):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), 1, path)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
        if domains:
            require_actual_domains(path, source)

    def rejects(self, path, function, marker, replacement=""):
        source = (ROOT / path).read_text()
        code, start, end = function_span(source, function)
        pattern = r"\s*".join(re.escape(token) for token in re.findall(r"\w+|[^\w\s]", marker))
        found = re.search(pattern, code[start:end])
        self.assertIsNotNone(found, (path, function, marker))
        offset = start + found.start()
        actual = source[offset:start + found.end()]
        self.assertEqual(re.sub(r"\s+", "", actual), re.sub(r"\s+", "", marker))
        self.verifies(path, source)
        changed = source[:offset] + replacement + source[offset + len(actual):]
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(path, changed)

    def rejects_unused_body(self, path, function):
        source = (ROOT / path).read_text()
        code, start, end = function_span(source, function)
        opening = code.index("{", start, end)
        changed = source[:opening + 1] + "\nlet _never_called = || async {" + source[opening + 1:end - 1] + "\n}; panic!();\n" + source[end - 1:]
        self.verifies(path, source)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(path, changed)

    def test_registered_calls_are_exact_and_extra_callers_are_rejected(self):
        source_roots = PROOF._string_tuple(self.manifest, "source_roots")
        ignored = PROOF._string_tuple(self.manifest, "ignored_path_fragments")
        self.assertEqual(source_roots, ("codex-rs",))
        self.assertEqual(ignored, ("/tests/", "/examples/", "_tests.rs"))
        sources = {
            path.relative_to(ROOT).as_posix(): PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code(path.read_text(encoding="utf-8"))
            )
            for path in PROOF._source_files(ROOT, source_roots)
        }
        for attack_path in (
            AGENT + "unregistered_evaluated_read.rs",
            AGENT + "unregistered_real_remote_s.rs",
        ):
            self.assertFalse(PROOF._is_ignored(attack_path, ignored))
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, sources, ignored)
                method = row.symbol.rsplit("::", 1)[-1]
                changed = dict(sources)
                changed[AGENT + "unregistered_evaluated_read.rs"] = f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, changed, ignored)
                if expected:
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=()), sources, ignored)
        for identifier in ("learning_original_published_read_client_current", "learning_original_evaluated_read_selection_binding"):
            changed = dict(sources)
            changed[AGENT + "unregistered_real_remote_s.rs"] = sources[REMOTE]
            with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                PROOF._verify_boundary(ROOT, self.boundaries[identifier], changed, ignored)
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_all_actual_product_functions_have_guards(self):
        for path in (CUT, PROFILE, REMOTE, CLIENT, SERVICE, WIRE, READINESS, SELECTOR, EVALUATED_S):
            self.verifies(path, (ROOT / path).read_text())
        for path in (CUT, PROFILE, REMOTE):
            source = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text()))
            actual = set(re.findall(r"\bfn ([A-Za-z_]\w*)\(", source))
            row = next(item for item in self.manifest["protected_file"] if item["path"] == path)
            protected = {item["function"][3:-1] for item in row["required_function_order"]}
            self.assertEqual(actual, protected, path)

    def test_opaque_cut_client_and_actual_owner_fields_cannot_be_made_writable(self):
        for path, fields in (
            (CUT, ("original: OriginalCut", "scope: FrozenLearningScopeV2")),
            (CLIENT, ("context: ReadProfile", "binding: Digest32", "channel: Mutex<Option<Channel>>", "retained: Mutex<Option<OriginalCircuitLearningReadbackV1>>")),
            (SERVICE, ("cell: PublishedCircuitCellOwnerV1<C>", "source: CircuitTaskSourceReadbackV1<S>", "identity: AgentdIdentity", "context: ReadProfile", "binding: Digest32", "connections: Semaphore")),
        ):
            source = (ROOT / path).read_text()
            self.verifies(path, source)
            for field in fields:
                for visibility in ("pub ", "pub(crate) ", "pub(super) "):
                    with self.subTest(path=path, field=field, visibility=visibility):
                        changed = source.replace("    " + field + ",", "    " + visibility + field + ",", 1)
                        self.assertNotEqual(source, changed)
                        with self.assertRaises(PROOF.VerificationFailure):
                            self.verifies(path, changed)
        self.rejects(REMOTE, "evaluated_owners", "Some((self.trainer, self.evaluator))", "None")
        for field in ("snapshot", "live", "trainer", "evaluator"):
            source = (ROOT / REMOTE).read_text()
            changed = source.replace("pub " + field + ": &'a ", "pub " + field + ": &'a mut ", 1)
            self.assertNotEqual(source, changed)
            with self.assertRaises(PROOF.VerificationFailure):
                self.verifies(REMOTE, changed)

    def test_only_original_opaque_inputs_can_construct_readback_profiles(self):
        for function, source, cut in (
            ("for_original_selection", "context", "Selection"),
            ("for_original_next_use", "selection", "NextUse"),
        ):
            for marker in (source + ".into_original_receipt_readback()", "OriginalCut::" + cut + "(" + source + ")", "profile.binding(now()?)?"):
                self.rejects(CUT, function, marker)
            self.rejects_unused_body(CUT, function)
        for marker in ("context.clone_for_original_receipt()", "selection.clone()", "self.scope.clone()"):
            self.rejects(CUT, "clone", marker)
        for path, function, marker in (
            (CLIENT, "from_original_stream", "ReadProfile::TrainingNoUpdate(context)"),
            (SERVICE, "from_original_owners", "ReadProfile::TrainingNoUpdate(context)"),
            (CUT, "from_original_evaluated_stream", "ReadProfile::Evaluated(context)"),
            (CUT, "from_original_evaluated_owners", "ReadProfile::Evaluated(context)"),
        ):
            self.rejects(path, function, marker)

    def test_complete_signed_context_exact_cuts_and_baseline_are_mandatory(self):
        for marker, changed in (
            ("prefix.receipts.len() != length", "prefix.receipts.len() == length"),
            ("coordinator.next_stage() != Some(stage)", "coordinator.next_stage() == Some(stage)"),
            ("prefix.training_no_update_v2().is_some()", "prefix.training_no_update_v2().is_none()"),
            ("coordinator.candidate().is_none()", "coordinator.candidate().is_some()"),
            ("coordinator.next_task_bundle() != Some(&prefix.request.selected_bundle)", "coordinator.next_task_bundle() == Some(&prefix.request.selected_bundle)"),
        ):
            for replacement in ("", changed):
                self.rejects(CUT, "binding", marker, replacement)
        for marker in (
            "context.original_receipt_predecessors(at)", "selection.original_receipt_predecessors(at)",
            "context.receipt_context_binding()", "selection.original_receipt_binding()",
            "LearningIterationCoordinatorV1::from_snapshot(prefix.clone())?", "self.scope.validate_snapshot(prefix)?",
            "&encode_original_owner_snapshot_v1(prefix)?", "self.scope.binding().as_array()", "original.as_array()",
        ):
            self.rejects(CUT, "binding", marker)
        self.rejects_unused_body(CUT, "binding")
        for marker in ("original.snapshot() != expected.snapshot()", "original.receipt_context_binding() != expected.receipt_context_binding()"):
            self.rejects(CUT, "require_original_selection", marker)
            self.rejects(CUT, "require_original_selection", marker, marker.replace("!=", "=="))

    def test_actual_domain_literals_cannot_be_spoofed_by_comments(self):
        for path, guards in DOMAINS.items():
            original = (ROOT / path).read_text()
            self.verifies(path, original)
            for _, _, literal in guards:
                with self.subTest(path=path, literal=literal):
                    offset = literal.index('"') + 1
                    changed_literal = literal[:offset] + "x" + literal[offset + 1:]
                    changed = original.replace(literal, changed_literal, 1)
                    original_line = next(line for line in original.splitlines() if literal in line)
                    changed += "\n// preserved old text is not a live domain: " + original_line + "\n"
                    self.verifies(path, changed, domains=False)
                    with self.assertRaises(PROOF.VerificationFailure):
                        self.verifies(path, changed)

    def test_fixed_evaluated_request_checks_every_echo_and_original_prefix(self):
        for field in ("schema", "operation", "request_id", "binding", "prefix_head", "operation_id", "mode"):
            marker = "request." + field + " != expected." + field
            self.rejects(PROFILE, "require_request", marker)
            self.rejects(PROFILE, "require_request", marker, marker.replace("!=", "=="))
        for marker in ("schema: 1", "operation: EVALUATED_OPERATION.into()", "binding: binding.to_string()", "context.prefix().head_digest", "context.prefix().request.operation_id", "mode: context.mode()"):
            self.rejects(PROFILE, "request", marker)
        self.rejects_unused_body(PROFILE, "require_request")
        for path, function, index in ((WIRE, "decode", "get(3)"), (WIRE, "decode_evaluated", "get(4)")):
            self.rejects(path, function, index, "get(2)")
        for marker in ("let expected = expected_selection", "source_publication.is_none()", "scope.validate_observation(&observation)?"):
            self.rejects(WIRE, "decode_original", marker)

    def test_legacy_tnu_version_and_readiness_reject_evaluated_contexts(self):
        for marker in ("Self::TrainingNoUpdate(context) => Ok(context)", "Self::Evaluated(_) => Err("):
            self.rejects(PROFILE, "legacy", marker)
        for path, function in (
            (CLIENT, "require_original_context"), (SERVICE, "serve_original_retained_channel"),
            (READINESS, "serve_completion_readiness"), (READINESS, "readiness_response"),
            (READINESS, "read_original_readiness"),
        ):
            self.rejects(path, function, "self.context.legacy()?")
            self.rejects_unused_body(path, function)
        for marker in ("LearningIterationObservationV1::TrainingNoUpdateV2(_)", "(3, Some(LearningIterationStageV1::Selection), None)", "(4, Some(LearningIterationStageV1::NextUse), Some(_))"):
            self.rejects(WIRE, "mode", marker)
        for function, marker in (
            ("mode", "wire::mode(context)"), ("binding", "wire::context_binding(context, at)"),
            ("decision", "wire::decision(context)"), ("decode", "read.decode(context)"),
            ("request", "wire::Request::new(context, binding, request_id)"),
            ("require_request", "return request.require_context(context, binding, request_id);"),
        ):
            self.rejects(PROFILE, function, marker)

    def test_actual_source_and_cell_surround_each_read_and_five_cut_c_result(self):
        for function, markers in (
            ("from_original_profile", ("owner.require_task_input_current()?", "cell.read_learning_selection(&coordinator)?", "owner.require_original_selection(&observed)?", "owner.context.binding(fresh)? != binding")),
            ("require_task_input_current", ("self.cell.task.require_current()?", "let request = &self.context.prefix().request;", "source.require_original_input(&self.identity, input)?")),
            ("read_original", ("self.require_task_input_current()?", "cell.read_learning_selection(&coordinator)?", "circuit_feature_task_digest_v1(", "wire::Mode::Selection => (selection.clone(), None)", "cell.read_learning_next_use(", "before.publication_digest()", "cell.read_learning_selection(&coordinator)? != selection")),
            ("response", ("self.context.require_request(&request, self.binding, request_id)?", "self.read_original()?", "self.context.binding(fresh)? != self.binding")),
        ):
            for marker in markers:
                self.rejects(SERVICE, function, marker)
        self.rejects(SERVICE, "require_original_selection", "&& self.context.selection()? != observed", "|| self.context.selection()? != observed")
        self.rejects_unused_body(SERVICE, "read_original")
        self.rejects_unused_body(SERVICE, "response")

    def test_remote_s_uses_actual_same_context_and_predecessor_owners(self):
        for path, function, marker in (
            (REMOTE, "require_profile", "let Profile::Evaluated(context) = profile else"),
            (REMOTE, "require_profile", "self.live.require_original_evaluated_selection(context)?"),
            (CUT, "require_original_evaluated_selection", "let ReadProfile::Evaluated(original) = &self.context else"),
            (CUT, "require_original_evaluated_selection", "original.require_original_selection(expected)"),
            (SELECTOR, "prepare", "source.require_profile(&self.profile)?"),
            (SELECTOR, "training_evidence", ".require_original_receipt_owners(trainer, evaluator)"),
            (REMOTE, "observe", "OriginalCircuitLearningReadClientV1::read_current(self.live).await?"),
        ):
            self.rejects(path, function, marker)
        for function in ("require_profile", "observe"):
            self.rejects_unused_body(REMOTE, function)
        self.rejects_unused_body(SELECTOR, "prepare")
        for location in ("ObservationLocation::RemoteOwner", "ObservationLocation::LocalOwner"):
            self.rejects(REMOTE, "location", "ObservationLocation::EvaluatedOwner", location)

    def test_last_live_tb_then_remote_source_cell_then_journal_order_cannot_move(self):
        source = (ROOT / SELECTOR).read_text()
        code, start, end = function_span(source, "finish_original_readback")
        evidence = "let evidence = self.training_evidence(source).await?;"
        branch = source.index("ObservationLocation::LocalOwner | ObservationLocation::EvaluatedOwner => {", start, end)
        first = source.index(evidence, branch, end)
        second = source.index("if self.prepare(source).await? != *observed {", first, end)
        guard_end = PROOF._rust_item_end(code, second) + 1
        changed = source[:first] + source[second:guard_end] + "\n                " + evidence + source[guard_end:]
        self.verifies(SELECTOR, source)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(SELECTOR, changed)
        for marker in (
            "let evidence = self.training_evidence(source).await?;", "if self.prepare(source).await? != *observed",
            "if self.journal.read(&self.saved)? != bytes", "self.authenticate_completed(completed, &evidence, started_at, current, new_attestation)",
        ):
            self.rejects(SELECTOR, "finish_original_readback", marker)
        self.rejects_unused_body(SELECTOR, "finish_original_readback")

    def test_active_signature_final_owner_and_actual_c_arms_reject_unused_closures(self):
        for path, function, arm, fallback in (
            (CUT, "binding", "OriginalCut::Selection(context) => {", '(4, LearningIterationStageV1::Selection, b"selection".as_slice(), context.receipt_context_binding())'),
            (CUT, "binding", "OriginalCut::NextUse(selection) => {", '(5, LearningIterationStageV1::NextUse, b"next_use".as_slice(), selection.original_receipt_binding())'),
            (SELECTOR, "finish_original_readback", "ObservationLocation::LocalOwner | ObservationLocation::EvaluatedOwner => {", "self.config.training_evidence.clone()"),
            (SERVICE, "read_original", "wire::Mode::NextUse => {", "(selection.clone(), None)"),
        ):
            with self.subTest(path=path, function=function, arm=arm):
                source = (ROOT / path).read_text()
                code, start, end = function_span(source, function)
                branch = code.index(arm, start, end)
                opening = code.index("{", branch, end)
                closing = PROOF._rust_item_end(code, branch)
                changed = source[:opening + 1] + "\nlet _unused = || async { Ok::<_, Error>({" + source[opening + 1:closing] + "}) };\n" + fallback + "\n" + source[closing:]
                self.verifies(path, source)
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(path, changed)

    def test_recovery_never_claims_and_unknown_completion_stays_fenced(self):
        self.rejects(REMOTE, "attest_original_evaluated_remote_selection", "CommandOrigin::Recovered => self.readback_source(source).await?", "CommandOrigin::Recovered => self.attest_source(source).await?")
        self.rejects(REMOTE, "readback_evaluated_remote_selection", "self.readback_source(source).await?", "self.attest_source(source).await?")
        for function in ("attest_original_evaluated_remote_selection", "readback_evaluated_remote_selection"):
            self.rejects(REMOTE, function, "self.completed_evaluated_selection(completed)")
            self.rejects_unused_body(REMOTE, function)
        for function in ("attest_source", "readback_source"):
            for marker in ("if self.completion_fenced", "self.completion_fenced = true"):
                self.rejects(SELECTOR, function, marker)

    def test_consumed_connection_and_original_bounds_survive_dispatch(self):
        for marker in (".take()", "channel.next_request_id > 128", "channel.peer.request(&bytes)?", "response.require_request(&request)?", "self.context.decode(response.read)?", "channel.peer.check_peer_lifetime()?", "self.context.binding(fresh)? != self.binding", "retained.as_ref().is_some_and(|prior| prior != &current)"):
            self.rejects(CLIENT, "read_current", marker)
        self.rejects_unused_body(CLIENT, "read_current")
        for marker in ("timeout.is_zero()", "timeout > Duration::from_millis(500)", "lifetime.is_zero()", "lifetime > Duration::from_secs(300)"):
            self.rejects(CLIENT, "require_timing", marker)
        for path, function, marker in (
            (CLIENT, "from_original_profile", "original_task_pidfd"),
            (SERVICE, "serve_readback", "original_consumer_pidfd"),
            (SERVICE, "from_original_profile", "Semaphore::new(4)"),
            (SERVICE, "serve_channel", "for request_id in 1..=128"),
            (SERVICE, "response", "bytes.is_empty() || bytes.len() > 16_384"),
        ):
            self.rejects(path, function, marker)

    def test_new_read_modules_cannot_gain_writer_or_signer_factories(self):
        for path in (CUT, PROFILE, REMOTE):
            source = (ROOT / path).read_text()
            self.verifies(path, source)
            for marker in ("SigningKey", "File::open", "UnixStream::connect", "Deserialize", ".claim(", ".publish(", ".commit_once(", "LearningEvidenceVerifierV1::new", "with_root_learning_stage_owners("):
                with self.subTest(path=path, marker=marker):
                    with self.assertRaises(PROOF.VerificationFailure):
                        self.verifies(path, source + "\n" + marker + "\n")

    def test_real_modules_exports_and_six_native_cases_are_mounted(self):
        mounts = (
            (CLIENT, "circuit_evaluated_learning_read.rs", "evaluated"),
            (CLIENT, "circuit_learning_read_profile.rs", "profile"),
            (EVALUATED_S, "circuit_evaluated_selection_remote.rs", "remote"),
            (AGENT + "circuit_evaluated_retention_receipt_tests.rs", "circuit_evaluated_selection_remote_tests.rs", "remote_tests"),
        )
        for path, child, module in mounts:
            source = (ROOT / path).read_text()
            self.assertIn(f'#[path = "{child}"]\nmod {module};', source)
            self.assertTrue((ROOT / AGENT / child).is_file())
        lib = (ROOT / AGENT / "lib.rs").read_text()
        for module, name in (
            ("circuit_selection_receipt_owner", "OriginalCircuitEvaluatedSelectionRemoteSourcesV1"),
            ("circuit_feature_current", "OriginalCircuitEvaluatedLearningReadContextV1"),
        ):
            self.assertIn(f'#[cfg(target_os = "linux")]\npub use {module}::{name};', lib)
        tests = (ROOT / AGENT / "circuit_evaluated_selection_remote_tests.rs").read_text()
        self.assertEqual(set(re.findall(r"async fn (evaluated_\w+)\(", tests)), {
            "evaluated_remote_s_reads_original_task_and_recovers_exact_five_cut",
            "evaluated_remote_s_cold_missing_cannot_claim_or_reinterpret_legacy",
            "evaluated_remote_s_refuses_withdrawn_original_training",
            "evaluated_remote_s_refuses_withdrawn_original_evaluation",
            "evaluated_remote_s_fences_committed_journal_if_final_source_read_fails",
            "evaluated_read_corruption_and_cancellation_consume_original_connections",
        })


if __name__ == "__main__":
    unittest.main()
