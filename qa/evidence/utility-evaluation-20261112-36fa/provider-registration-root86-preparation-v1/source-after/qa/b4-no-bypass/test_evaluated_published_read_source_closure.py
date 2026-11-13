"""Close explicit evaluated 4/5-cut reads and actual remote S receipts.

Five-cut serving reads an existing C result. It is not a remote C receipt or
command consumer. These source gates grant no ordinary deployment qualification.
"""

from dataclasses import replace
import importlib.util
import hashlib
import json
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
    "learning_original_evaluated_read_selection_context": ('codex-rs/hepta-agentd/src/circuit_retained_version_state.rs',
 'codex-rs/hepta-agentd/src/circuit_learning_local_read.rs',
 'codex-rs/hepta-agentd/src/circuit_retained_version_local_read.rs'),
    "learning_original_evaluated_read_next_use_context": ('codex-rs/hepta-agentd/src/circuit_learning_completion_readiness.rs',
 'codex-rs/hepta-agentd/src/circuit_completion_readiness_local.rs',
 'codex-rs/hepta-agentd/src/circuit_learning_local_read.rs',
 'codex-rs/hepta-agentd/src/circuit_retained_version_local_read.rs',
 'codex-rs/hepta-agentd/src/circuit_retained_version_next_use_readback.rs'),
    "learning_original_evaluated_read_client_create": (),
    "learning_original_evaluated_read_owner_create": ('codex-rs/hepta-agentd/src/circuit_retained_version_state.rs',
 'codex-rs/hepta-agentd/src/circuit_retained_version_next_use_readback.rs'),
    "learning_original_evaluated_read_selection_binding": ('codex-rs/hepta-agentd/src/circuit_evaluated_selection_remote.rs',
 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_command_service.rs',
 'codex-rs/hepta-agentd/src/circuit_learning_local_read.rs'),
    "learning_original_evaluated_selection_remote_attest": ('codex-rs/hepta-agentd/src/circuit_evaluated_selection_command_service.rs',),
    "learning_original_evaluated_selection_remote_readback": ('codex-rs/hepta-agentd/src/circuit_evaluated_selection_command_service.rs',),
    "learning_original_published_read_client_current": ('codex-rs/hepta-agentd/src/circuit_selection_receipt_owner.rs',
 'codex-rs/hepta-agentd/src/circuit_next_use_receipt_owner.rs',
 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_remote.rs',
 'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_remote.rs',
 'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_local.rs'),
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
            marker = {
                "readiness_response": "request.require_profile(&self.context, self.binding, request_id)?",
                "read_original_readiness": "self.context.decision()?",
            }.get(function, "self.context.legacy()?")
            self.rejects(path, function, marker)
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
        readiness_client = AGENT + "circuit_learning_completion_readiness.rs"
        self.rejects(readiness_client, "require_profile",
                     "self.require_context(legacy, binding, request_id)")
        self.rejects(readiness_client, "require_profile",
                     "ReadProfile::TrainingNoUpdate(legacy)", "ReadProfile::Evaluated(legacy)")

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




# Exact prepared root scopes supplement the original verifier's generic
# function/file-level fallback. No source or verdict cache is used.
ORDINARY_SCOPE_GUARDS = {'codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs': [{'masked_sha256': '5c4f0690b07de885b62baf68ed3552c7c4c857b2c5659104ddc8fda6909c6115',
                                                                           'selector': {'kind': 'unique_function',
                                                                                        'name': 'validate_recovery'}},
                                                                          {'masked_sha256': 'b0152caf210d630d637a4dab75cab3fd297c8d839476103ca7df5706399482f9',
                                                                           'selector': {'kind': 'unique_function',
                                                                                        'name': 'execute_stage'}},
                                                                          {'masked_sha256': 'a37ab118906e2d410451198f28430458c21ac50659987619e9883b654d911107',
                                                                           'selector': {'kind': 'unique_function',
                                                                                        'name': 'prepare_proposal'}},
                                                                          {'masked_sha256': '45739f9bc2115dd2686612184943698e5ba517b1bbf04e8e557f10553a97b37a',
                                                                           'selector': {'kind': 'unique_function',
                                                                                        'name': 'receipt_attestation'}}],
 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_owners.rs': [{'masked_sha256': '9c732db93d63435b23c16b2e2583be858a4e28e5d60c1fada72806304c82e3ad',
                                                                   'selector': {'kind': 'unique_function',
                                                                                'name': 'validate_recovery'}},
                                                                  {'masked_sha256': '398afcb156ecdeb28606a628e5924c201353e662c19608aba6074e2d17663b9b',
                                                                   'selector': {'kind': 'unique_function',
                                                                                'name': 'execute_stage'}},
                                                                  {'masked_sha256': 'ebf905ee2f9fdc872b70623ca38fea20823a6fec2cab6776f1857b6c0cc9955e',
                                                                   'selector': {'kind': 'unique_function',
                                                                                'name': 'prepare_proposal'}},
                                                                  {'masked_sha256': 'a6a46f6777c13742c82a9f27643ec1b4b7bf61e9368a753ce539ad038d4b0a82',
                                                                   'selector': {'kind': 'unique_function',
                                                                                'name': 'receipt_attestation'}}],
 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained.rs': [{'masked_sha256': 'ed2c2f4e93a21657c172a0986464261670da55e4d3e2027f8102b3ebecc6030a',
                                                                     'selector': {'item_kind': 'struct',
                                                                                  'kind': 'root_type',
                                                                                  'name': 'OriginalPins'}},
                                                                    {'masked_sha256': '44f23da0ab1b7f9bc94c2a826123249e63f69bbe0f95311c4e22ccbb36e68da5',
                                                                     'selector': {'item_kind': 'struct',
                                                                                  'kind': 'root_type',
                                                                                  'name': 'EvaluatedContinuation'}}],
 'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_command_service.rs': [{'masked_sha256': 'd71f6e091660b680f8e8bb0ccf706f93acc9fa73c83c9d0f9f70d2c32be6afb0',
                                                                              'selector': {'item_kind': 'enum',
                                                                                           'kind': 'root_type',
                                                                                           'name': 'OriginalPredecessors'}}],
 'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_remote.rs': [{'masked_sha256': '4f802db7f3a24f04fccacdc972cffa1d763cbb8fc62f092c2bcdb80cc59585b1',
                                                                     'selector': {'item_kind': 'struct',
                                                                                  'kind': 'root_type',
                                                                                  'name': 'OriginalCircuitEvaluatedNextUseRemoteSourcesV1'}}],
 'codex-rs/hepta-agentd/src/circuit_evaluated_retention_publication.rs': [{'masked_sha256': '60a620d3a4c613a851deb23e34e188f0d8c46d5cbed948bfd2a5783e41adb444',
                                                                           'selector': {'kind': 'unique_function',
                                                                                        'name': 'prepare_original_circuit_evaluated_retention_v1'}}],
 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_command.rs': [{'masked_sha256': '89751a8d86a6e96aa6b017c7b8ecbe8730a356caf33a4451d475ca43b26f4c97',
                                                                       'selector': {'header': 'impl '
                                                                                              'Clone '
                                                                                              'for '
                                                                                              'OriginalCircuitSelectionCommandContextV1',
                                                                                    'kind': 'root_impl_method',
                                                                                    'name': 'clone',
                                                                                    'protect_entire_impl': True}},
                                                                      {'masked_sha256': '1711a059cc6bb97cb6c6c85e05a615368230f1c0dd5859d5a590c5b845b004d6',
                                                                       'selector': {'header': 'impl '
                                                                                              'Clone '
                                                                                              'for '
                                                                                              'OriginalCircuitSelectionCommandReceiptV1',
                                                                                    'kind': 'root_impl_method',
                                                                                    'name': 'clone',
                                                                                    'protect_entire_impl': True}}],
 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_command_service.rs': [{'masked_sha256': 'd71f6e091660b680f8e8bb0ccf706f93acc9fa73c83c9d0f9f70d2c32be6afb0',
                                                                               'selector': {'item_kind': 'enum',
                                                                                            'kind': 'root_type',
                                                                                            'name': 'OriginalPredecessors'}}],
 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_receipt.rs': [{'masked_sha256': '4f47dcd9bf09ca16dc85d6fce041fba16f2bc78e9f418064cb32bc850f8ed262',
                                                                       'selector': {'kind': 'unique_function',
                                                                                    'name': 'into_evaluated_readback_owner'}}],
 'codex-rs/hepta-agentd/src/circuit_feature_current.rs': [{'masked_sha256': 'd2f402c80b3889d07d3c2e79c28097c208287f4c5c3e127e4f54739a46374ae5',
                                                           'selector': {'kind': 'unique_function',
                                                                        'name': 'from_update'}},
                                                          {'masked_sha256': 'a78526865ac63753afe0e601eb72c362f4e2b2168b4703684bdee8d8aa962323',
                                                           'selector': {'kind': 'unique_function',
                                                                        'name': 'from_parts'}},
                                                          {'masked_sha256': '34d7e4d26a8bd4ff8142b5996c7cc575f52af81c25f22e25afe83c53b67a779f',
                                                           'selector': {'kind': 'unique_function',
                                                                        'name': 'open_cell'}},
                                                          {'masked_sha256': '6e92909fb79b3d605d9b5e0c545062460354c9fcdc491289026aa378ed8dc6ba',
                                                           'selector': {'header': 'impl '
                                                                                  'PublishedCircuitFeatureTaskV1',
                                                                        'kind': 'root_impl_method',
                                                                        'name': 'require_current'}}],
 'codex-rs/hepta-agentd/src/circuit_learning_completion_readiness.rs': [{'masked_sha256': '62995fe1482709dbdefcc64d516efe932184bad533d5695c48cf6a99e6b527cb',
                                                                         'selector': {'item_kind': 'struct',
                                                                                      'kind': 'root_type',
                                                                                      'name': 'Request'}},
                                                                        {'masked_sha256': '26814e30e1870e50bde061a103fe31e4520d2e74270fec91ee2e33faee1410ca',
                                                                         'selector': {'item_kind': 'struct',
                                                                                      'kind': 'root_type',
                                                                                      'name': 'OriginalCircuitCompletionReadinessClientV1'}}],
 'codex-rs/hepta-agentd/src/circuit_next_use_command.rs': [{'masked_sha256': '05f8e30f7d579b5e379f476203edc0fe2d9ede4318d81493780f01536c23f81a',
                                                            'selector': {'item_kind': 'struct',
                                                                         'kind': 'root_type',
                                                                         'name': 'OriginalCircuitNextUseCommandContextV1'}},
                                                           {'masked_sha256': '9ba858eec451f73a9d6daab9a6c20c6f13d3b3a05d79d3b5cb87c2c75557ea83',
                                                            'selector': {'item_kind': 'struct',
                                                                         'kind': 'root_type',
                                                                         'name': 'OriginalCircuitNextUseCommandReceiptV1'}}],
 'codex-rs/hepta-agentd/src/circuit_next_use_command_service.rs': [{'masked_sha256': '9b1f5d5de2400e7aeeffb9dbac683e00ebc04272c0ab2063df3d79b3b3de0340',
                                                                    'selector': {'item_kind': 'struct',
                                                                                 'kind': 'root_type',
                                                                                 'name': 'OriginalCircuitNextUseCommandOwnerV1'}}],
 'codex-rs/hepta-agentd/src/circuit_next_use_receipt_owner.rs': [{'masked_sha256': '7d311b26a1a60d2d16ed7dc63500a5a1a2f667ee98df5dabe954a0d87f219284',
                                                                  'selector': {'item_kind': 'trait',
                                                                               'kind': 'root_type',
                                                                               'name': 'NextUseSources'}}],
 'codex-rs/hepta-agentd/src/circuit_retained_version.rs': [{'masked_sha256': 'ca9fd21edcb6b4c7d6809d867a68d306cadbcd732270fdbd20bca349bc4a35bb',
                                                            'selector': {'item_kind': 'enum',
                                                                         'kind': 'root_type',
                                                                         'name': 'RetainedVersionPurposeV1'}}],
 'codex-rs/hepta-agentd/src/circuit_retained_version_context.rs': [{'masked_sha256': 'a3f96cace3c9e7c685dc7ddcab8d5883526f7dfbca4baa7406cdc19fa0c18bfd',
                                                                    'selector': {'item_kind': 'struct',
                                                                                 'kind': 'root_type',
                                                                                 'name': 'OriginalVersionCut'}}],
 'codex-rs/hepta-agentd/src/circuit_retained_version_host.rs': [{'masked_sha256': '4338114fe18ed9ce7f0ce20311feaa386d7e9ee906d88c097ed9d070df7d8577',
                                                                 'selector': {'item_kind': 'enum',
                                                                              'kind': 'root_type',
                                                                              'name': 'InitialVersionEvidence'}}],
 'codex-rs/hepta-agentd/src/circuit_retained_version_prepared.rs': [{'masked_sha256': '2edf7a76bfdbd968d1acb53640c0b9f4f438ac3e21b0a2b480b773028c3519d5',
                                                                     'selector': {'item_kind': 'enum',
                                                                                  'kind': 'root_type',
                                                                                  'name': 'RetainedVersionPreparedV1'}}],
 'codex-rs/hepta-agentd/src/circuit_selection_command.rs': [{'masked_sha256': '14b592219013ea97056221cbb8b57f5ae03963169a88d1b75796a60df8c0d807',
                                                             'selector': {'item_kind': 'struct',
                                                                          'kind': 'root_type',
                                                                          'name': 'OriginalCircuitSelectionCommandContextV1'}},
                                                            {'masked_sha256': '5ab8dd87e739aedc555c5773df7504cfe84ad8837dd9be7b7913dc34851908dd',
                                                             'selector': {'item_kind': 'struct',
                                                                          'kind': 'root_type',
                                                                          'name': 'OriginalCircuitSelectionCommandReceiptV1'}}],
 'codex-rs/hepta-agentd/src/circuit_selection_command_service.rs': [{'masked_sha256': '19ef55dc3b0d0434b4afdf9467e1a062866a759437a10f3405f65d2fada98a93',
                                                                     'selector': {'item_kind': 'struct',
                                                                                  'kind': 'root_type',
                                                                                  'name': 'OriginalCircuitSelectionCommandOwnerV1'}}]}

ORDINARY_LITERAL_SPECS = [{'path': 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_command.rs',
  'scope': {'kind': 'unique_function', 'name': 'operation'},
  'prefix_regex': 'Some\\s*\\(_\\)\\s*=>',
  'expected_rust_literal': '"runtime.learning.original-circuit-evaluated-selection.command.v1"'},
 {'path': 'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_command.rs',
  'scope': {'kind': 'unique_function', 'name': 'operation'},
  'prefix_regex': 'Some\\s*\\(_\\)\\s*=>',
  'expected_rust_literal': '"runtime.learning.original-circuit-evaluated-next-use.command.v1"'},
 {'path': 'codex-rs/hepta-agentd/src/circuit_selection_command.rs',
  'scope': {'kind': 'unique_function', 'name': 'binding'},
  'prefix_regex': '\\breturn\\s+Ok\\(Digest32::of_parts\\(&\\[',
  'expected_rust_literal': 'b"hepta.agentd.original-circuit-evaluated-selection-command.v1\\0"'},
 {'path': 'codex-rs/hepta-agentd/src/circuit_selection_command.rs',
  'scope': {'kind': 'unique_function', 'name': 'binding'},
  'prefix_regex': '(?m)^\\s*Ok\\(Digest32::of_parts\\(&\\[',
  'expected_rust_literal': 'b"hepta.agentd.original-circuit-selection-command.v1\\0"'},
 {'path': 'codex-rs/hepta-agentd/src/circuit_next_use_command.rs',
  'scope': {'kind': 'unique_function', 'name': 'binding'},
  'prefix_regex': '\\breturn\\s+Ok\\(Digest32::of_parts\\(&\\[',
  'expected_rust_literal': 'b"hepta.agentd.original-circuit-evaluated-next-use-command.v1\\0"'},
 {'path': 'codex-rs/hepta-agentd/src/circuit_next_use_command.rs',
  'scope': {'kind': 'unique_function', 'name': 'binding'},
  'prefix_regex': '(?m)^\\s*Ok\\(Digest32::of_parts\\(&\\[',
  'expected_rust_literal': 'b"hepta.agentd.original-circuit-next-use-command.v1\\0"'},
 {'path': 'codex-rs/hepta-agentd/src/circuit_learning_completion_readiness.rs',
  'scope': {'kind': 'module_constant'},
  'prefix_regex': '\\bconst\\s+PURPOSE\\s*:\\s*&str\\s*=',
  'expected_rust_literal': '"runtime.learning.original-circuit.completion-readiness.v1"'},
 {'path': 'codex-rs/hepta-agentd/src/circuit_learning_completion_readiness.rs',
  'scope': {'kind': 'module_constant'},
  'prefix_regex': '\\bconst\\s+EVALUATED_PURPOSE\\s*:\\s*&str\\s*=',
  'expected_rust_literal': '"runtime.learning.original-circuit.evaluated-completion-readiness.v1"'},
 {'path': 'codex-rs/hepta-agentd/src/circuit_retained_version.rs',
  'scope': {'kind': 'unique_function', 'name': 'operation'},
  'prefix_regex': 'Self::EvaluatedNoUpdate\\s*=>\\s*\\{',
  'expected_rust_literal': '"runtime.learning.original-evaluated-retained-version.command.v1"'},
 {'path': 'codex-rs/hepta-agentd/src/circuit_retained_version_context.rs',
  'scope': {'kind': 'unique_function', 'name': 'authenticate'},
  'prefix_regex': 'RetainedVersionPurposeV1::TrainingNoUpdate\\s*=>\\s*\\{',
  'expected_rust_literal': 'b"hepta.agentd.original-retained-version.command.v1\\0"'},
 {'path': 'codex-rs/hepta-agentd/src/circuit_retained_version_context.rs',
  'scope': {'kind': 'unique_function', 'name': 'authenticate'},
  'prefix_regex': 'RetainedVersionPurposeV1::EvaluatedNoUpdate\\s*=>\\s*\\{',
  'expected_rust_literal': 'b"hepta.agentd.original-evaluated-retained-version.command.v1\\0"'},
 {'path': 'codex-rs/hepta-agentd/src/circuit_selection_command_wire.rs',
  'scope': {'kind': 'module_constant'},
  'prefix_regex': '\\bconst\\s+OPERATION\\s*:\\s*&str\\s*=',
  'expected_rust_literal': '"runtime.learning.original-circuit-selection.command.v1"'},
 {'path': 'codex-rs/hepta-agentd/src/circuit_next_use_command_wire.rs',
  'scope': {'kind': 'module_constant'},
  'prefix_regex': '\\bconst\\s+OPERATION\\s*:\\s*&str\\s*=',
  'expected_rust_literal': '"runtime.learning.original-circuit-next-use.command.v1"'},
 {'path': 'codex-rs/hepta-agentd/src/circuit_retained_version_wire.rs',
  'scope': {'kind': 'module_constant'},
  'prefix_regex': '\\bconst\\s+OPERATION\\s*:\\s*&str\\s*=',
  'expected_rust_literal': '"runtime.learning.original-retained-version.command.v1"'},
 {'path': 'codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs',
  'scope': {'kind': 'module_constant'},
  'prefix_regex': '\\bconst\\s+OPERATION\\s*:\\s*&str\\s*=',
  'expected_rust_literal': '"runtime.learning.original-circuit-selection.readback.v1"'},
 {'path': 'codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs',
  'scope': {'kind': 'unique_function', 'name': 'context_binding'},
  'prefix_regex': 'Ok\\(Digest32::of_parts\\(&\\[',
  'expected_rust_literal': 'b"hepta.agentd.original-circuit-selection-readback.v1\\0"'},
 {'path': 'codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs',
  'scope': {'kind': 'unique_function', 'name': 'operation'},
  'prefix_regex': '\\bif\\s+context\\.evaluated\\.is_some\\(\\)\\s*\\{',
  'expected_rust_literal': '"runtime.learning.original-circuit-evaluated-selection.readback.v1"'}]

ORDINARY_MODULE_MOUNTS = [{'parent': 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_owners.rs',
  'child': 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained.rs',
  'module_name': 'retained',
  'path_literal': '"cell_q24_candidate_stage_retained.rs"'},
 {'parent': 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained.rs',
  'child': 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained_execute.rs',
  'module_name': 'execution',
  'path_literal': '"cell_q24_candidate_stage_retained_execute.rs"'},
 {'parent': 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained.rs',
  'child': 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained_readback.rs',
  'module_name': 'readback',
  'path_literal': '"cell_q24_candidate_stage_retained_readback.rs"'},
 {'parent': 'codex-rs/hepta-agentd/src/circuit_selection_command.rs',
  'child': 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_command.rs',
  'module_name': 'evaluated',
  'path_literal': '"circuit_evaluated_selection_command.rs"'},
 {'parent': 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_receipt.rs',
  'child': 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_command_owner_adapter.rs',
  'module_name': 'command_owner_adapter',
  'path_literal': '"circuit_evaluated_selection_command_owner_adapter.rs"'},
 {'parent': 'codex-rs/hepta-agentd/src/circuit_selection_command_service.rs',
  'child': 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_command_service.rs',
  'module_name': 'evaluated',
  'path_literal': '"circuit_evaluated_selection_command_service.rs"'},
 {'parent': 'codex-rs/hepta-agentd/src/circuit_next_use_command.rs',
  'child': 'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_command.rs',
  'module_name': 'evaluated',
  'path_literal': '"circuit_evaluated_next_use_command.rs"'},
 {'parent': 'codex-rs/hepta-agentd/src/circuit_next_use_command_service.rs',
  'child': 'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_command_service.rs',
  'module_name': 'evaluated',
  'path_literal': '"circuit_evaluated_next_use_command_service.rs"'},
 {'parent': 'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_receipt.rs',
  'child': 'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_remote.rs',
  'module_name': 'remote',
  'path_literal': '"circuit_evaluated_next_use_remote.rs"'},
 {'parent': 'codex-rs/hepta-agentd/src/circuit_retained_version_host.rs',
  'child': 'codex-rs/hepta-agentd/src/circuit_retained_version_prepared.rs',
  'module_name': 'prepared_custody',
  'path_literal': '"circuit_retained_version_prepared.rs"'}]

ORDINARY_COMPLETE_BOUNDARY_SHA256 = '5f20073de3b391b196e318a10bb4268c41e26a0f16e0eed6afde8299fe19494c'

ORDINARY_NEW_BOUNDARIES = [{'id': 'learning_original_candidate_retained_stage_route',
  'symbol': 'OriginalCellQ24CandidateStageOwnersV1::require_evaluated_retained_stage',
  'receiver_type': 'OriginalCellQ24CandidateStageOwnersV1',
  'definition_path': 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained.rs',
  'definition_markers': ['fn require_evaluated_retained_stage('],
  'product_callers': ['codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs',
                      'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained_execute.rs'],
  'caller_markers': []},
 {'id': 'learning_original_candidate_retained_stage_execute',
  'symbol': 'OriginalCellQ24CandidateStageOwnersV1::execute_evaluated_retained_stage',
  'receiver_type': 'OriginalCellQ24CandidateStageOwnersV1',
  'definition_path': 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained_execute.rs',
  'definition_markers': ['fn execute_evaluated_retained_stage('],
  'product_callers': ['codex-rs/hepta-agentd/src/cell_q24_candidate_stage_owners.rs'],
  'caller_markers': []},
 {'id': 'learning_original_candidate_retained_stage_readback',
  'symbol': 'OriginalCellQ24CandidateStageOwnersV1::read_evaluated_retained_prefix',
  'receiver_type': 'OriginalCellQ24CandidateStageOwnersV1',
  'definition_path': 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained_readback.rs',
  'definition_markers': ['fn read_evaluated_retained_prefix('],
  'product_callers': ['codex-rs/hepta-agentd/src/cell_q24_candidate_stage_owners.rs'],
  'caller_markers': []},
 {'id': 'learning_original_candidate_retained_stage_attestation',
  'symbol': 'OriginalCellQ24CandidateStageOwnersV1::retained_attestation',
  'receiver_type': 'OriginalCellQ24CandidateStageOwnersV1',
  'definition_path': 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained_readback.rs',
  'definition_markers': ['fn retained_attestation('],
  'product_callers': ['codex-rs/hepta-agentd/src/cell_q24_candidate_stage_owners.rs'],
  'caller_markers': []},
 {'id': 'learning_original_evaluated_read_next_use_binding',
  'symbol': 'OriginalCircuitLearningReadClientV1::require_original_evaluated_next_use',
  'receiver_type': 'OriginalCircuitLearningReadClientV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_evaluated_learning_read.rs',
  'definition_markers': ['fn require_original_evaluated_next_use('],
  'product_callers': ['codex-rs/hepta-agentd/src/circuit_evaluated_next_use_command_service.rs',
                      'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_remote.rs',
                      'codex-rs/hepta-agentd/src/circuit_learning_local_read.rs'],
  'caller_markers': []},
 {'id': 'learning_original_evaluated_selector_command_context',
  'symbol': 'OriginalCircuitSelectionCommandContextV1::from_original_evaluation',
  'receiver_type': 'OriginalCircuitSelectionCommandContextV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_command.rs',
  'definition_markers': ['fn from_original_evaluation('],
  'product_callers': [],
  'caller_markers': []},
 {'id': 'learning_original_evaluated_selector_command_recover',
  'symbol': 'OriginalCircuitSelectionCommandClientV1::recover_from_original_evaluated_stream',
  'receiver_type': 'OriginalCircuitSelectionCommandClientV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_command.rs',
  'definition_markers': ['fn recover_from_original_evaluated_stream('],
  'product_callers': [],
  'caller_markers': []},
 {'id': 'learning_original_evaluated_selector_command_owner_profile',
  'symbol': 'OriginalCircuitSelectionReceiptOwnerV1::original_evaluated_command_context',
  'receiver_type': 'OriginalCircuitSelectionReceiptOwnerV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_command_owner_adapter.rs',
  'definition_markers': ['fn original_evaluated_command_context('],
  'product_callers': ['codex-rs/hepta-agentd/src/circuit_evaluated_selection_command_service.rs',
                      'codex-rs/hepta-agentd/src/circuit_selection_local_predecessor.rs'],
  'caller_markers': []},
 {'id': 'learning_original_evaluated_selector_command_owner_factory',
  'symbol': 'OriginalCircuitSelectionCommandOwnerV1::from_original_evaluated_receipt_owner',
  'receiver_type': 'OriginalCircuitSelectionCommandOwnerV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_command_service.rs',
  'definition_markers': ['fn from_original_evaluated_receipt_owner('],
  'product_callers': ['codex-rs/hepta-agentd/src/circuit_evaluated_selection_command_owner_adapter.rs'],
  'caller_markers': []},
 {'id': 'learning_original_evaluated_selector_command_owner_transfer',
  'symbol': 'OriginalCircuitSelectionReceiptOwnerV1::into_evaluated_command_owner',
  'receiver_type': 'OriginalCircuitSelectionReceiptOwnerV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_command_owner_adapter.rs',
  'definition_markers': ['fn into_evaluated_command_owner('],
  'product_callers': [],
  'caller_markers': []},
 {'id': 'learning_original_evaluated_selector_command_receipt',
  'symbol': 'OriginalCircuitEvaluatedSelectionReceiptV1::from_original_command_response',
  'receiver_type': 'OriginalCircuitEvaluatedSelectionReceiptV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_command_owner_adapter.rs',
  'definition_markers': ['fn from_original_command_response('],
  'product_callers': ['codex-rs/hepta-agentd/src/circuit_evaluated_selection_command.rs',
                      'codex-rs/hepta-agentd/src/circuit_evaluated_selection_command_local_readback.rs'],
  'caller_markers': []},
 {'id': 'learning_original_evaluated_selector_readback_binding',
  'symbol': 'OriginalCircuitSelectionReadbackConnectionV1::bind_original_evaluated_selection',
  'receiver_type': 'OriginalCircuitSelectionReadbackConnectionV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs',
  'definition_markers': ['fn bind_original_evaluated_selection('],
  'product_callers': [],
  'caller_markers': []},
 {'id': 'learning_original_evaluated_selector_stage_binding',
  'symbol': 'OriginalCircuitSelectionCommandClientV1::bind_original_evaluated_stage_channel',
  'receiver_type': 'OriginalCircuitSelectionCommandClientV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_selection_command_stage_binding.rs',
  'definition_markers': ['fn bind_original_evaluated_stage_channel('],
  'product_callers': ['codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained.rs'],
  'caller_markers': []},
 {'id': 'learning_original_evaluated_next_use_command_context',
  'symbol': 'OriginalCircuitNextUseCommandContextV1::from_original_evaluated_selection',
  'receiver_type': 'OriginalCircuitNextUseCommandContextV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_command.rs',
  'definition_markers': ['fn from_original_evaluated_selection('],
  'product_callers': [],
  'caller_markers': []},
 {'id': 'learning_original_evaluated_next_use_command_recover',
  'symbol': 'OriginalCircuitNextUseCommandClientV1::recover_from_original_evaluated_stream',
  'receiver_type': 'OriginalCircuitNextUseCommandClientV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_command.rs',
  'definition_markers': ['fn recover_from_original_evaluated_stream('],
  'product_callers': [],
  'caller_markers': []},
 {'id': 'learning_original_evaluated_next_use_command_owner_profile',
  'symbol': 'OriginalCircuitNextUseReceiptOwnerV1::original_evaluated_command_selection',
  'receiver_type': 'OriginalCircuitNextUseReceiptOwnerV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_remote.rs',
  'definition_markers': ['fn original_evaluated_command_selection('],
  'product_callers': ['codex-rs/hepta-agentd/src/circuit_evaluated_next_use_command_service.rs',
                      'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_local_command.rs'],
  'caller_markers': []},
 {'id': 'learning_original_evaluated_next_use_command_owner_factory',
  'symbol': 'OriginalCircuitNextUseCommandOwnerV1::from_original_evaluated_receipt_owner',
  'receiver_type': 'OriginalCircuitNextUseCommandOwnerV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_command_service.rs',
  'definition_markers': ['fn from_original_evaluated_receipt_owner('],
  'product_callers': ['codex-rs/hepta-agentd/src/circuit_evaluated_next_use_remote.rs'],
  'caller_markers': []},
 {'id': 'learning_original_evaluated_next_use_command_owner_transfer',
  'symbol': 'OriginalCircuitNextUseReceiptOwnerV1::into_evaluated_command_owner',
  'receiver_type': 'OriginalCircuitNextUseReceiptOwnerV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_remote.rs',
  'definition_markers': ['fn into_evaluated_command_owner('],
  'product_callers': [],
  'caller_markers': []},
 {'id': 'learning_original_evaluated_next_use_remote_attest',
  'symbol': 'OriginalCircuitNextUseReceiptOwnerV1::attest_original_evaluated_remote_completion',
  'receiver_type': 'OriginalCircuitNextUseReceiptOwnerV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_remote.rs',
  'definition_markers': ['fn attest_original_evaluated_remote_completion('],
  'product_callers': ['codex-rs/hepta-agentd/src/circuit_evaluated_next_use_command_service.rs'],
  'caller_markers': []},
 {'id': 'learning_original_evaluated_next_use_remote_readback',
  'symbol': 'OriginalCircuitNextUseReceiptOwnerV1::readback_evaluated_remote_completion',
  'receiver_type': 'OriginalCircuitNextUseReceiptOwnerV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_remote.rs',
  'definition_markers': ['fn readback_evaluated_remote_completion('],
  'product_callers': ['codex-rs/hepta-agentd/src/circuit_evaluated_next_use_command_service.rs'],
  'caller_markers': []},
 {'id': 'learning_original_evaluated_next_use_stage_binding',
  'symbol': 'OriginalCircuitNextUseCommandClientV1::bind_original_evaluated_stage_channel',
  'receiver_type': 'OriginalCircuitNextUseCommandClientV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_next_use_command_stage_binding.rs',
  'definition_markers': ['fn bind_original_evaluated_stage_channel('],
  'product_callers': ['codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained.rs'],
  'caller_markers': []},
 {'id': 'learning_original_evaluated_c_readiness_binding',
  'symbol': 'OriginalCircuitCompletionReadinessClientV1::bind_original_evaluated_stage_channel',
  'receiver_type': 'OriginalCircuitCompletionReadinessClientV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_learning_completion_readiness.rs',
  'definition_markers': ['fn bind_original_evaluated_stage_channel('],
  'product_callers': ['codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained.rs'],
  'caller_markers': []},
 {'id': 'learning_original_evaluated_c_readiness_serve',
  'symbol': 'OriginalCircuitLearningReadOwnerV1::serve_evaluated_completion_readiness',
  'receiver_type': 'OriginalCircuitLearningReadOwnerV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_learning_completion_readiness_service.rs',
  'definition_markers': ['fn serve_evaluated_completion_readiness('],
  'product_callers': [],
  'caller_markers': []},
 {'id': 'learning_retained_version_evaluated_selection_channel',
  'symbol': 'OriginalCircuitLearningReadOwnerV1::serve_original_evaluated_retained_channel',
  'receiver_type': 'OriginalCircuitLearningReadOwnerV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_learning_read_service.rs',
  'definition_markers': ['fn serve_original_evaluated_retained_channel('],
  'product_callers': ['codex-rs/hepta-agentd/src/circuit_retained_version_service.rs'],
  'caller_markers': []},
 {'id': 'learning_retained_version_evaluated_client_bind',
  'symbol': 'OriginalCircuitRetainedVersionClientV1::bind_original_evaluated_stage_channel',
  'receiver_type': 'OriginalCircuitRetainedVersionClientV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_retained_version_client.rs',
  'definition_markers': ['fn bind_original_evaluated_stage_channel('],
  'product_callers': ['codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained.rs'],
  'caller_markers': []},
 {'id': 'learning_retained_version_evaluated_client_recover',
  'symbol': 'OriginalCircuitRetainedVersionClientV1::recover_original_evaluated_stage_channel',
  'receiver_type': 'OriginalCircuitRetainedVersionClientV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_retained_version_client.rs',
  'definition_markers': ['fn recover_original_evaluated_stage_channel('],
  'product_callers': ['codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained.rs'],
  'caller_markers': []},
 {'id': 'learning_retained_version_evaluated_host_create',
  'symbol': 'OriginalCircuitRetainedVersionHostV1::from_original_evaluated_owners',
  'receiver_type': 'OriginalCircuitRetainedVersionHostV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_retained_version_host.rs',
  'definition_markers': ['fn from_original_evaluated_owners('],
  'product_callers': [],
  'caller_markers': []},
 {'id': 'learning_retained_version_evaluated_host_recover',
  'symbol': 'OriginalCircuitRetainedVersionHostV1::recover_from_original_evaluated_owners',
  'receiver_type': 'OriginalCircuitRetainedVersionHostV1',
  'definition_path': 'codex-rs/hepta-agentd/src/circuit_retained_version_host.rs',
  'definition_markers': ['fn recover_from_original_evaluated_owners('],
  'product_callers': [],
  'caller_markers': []}]

ORDINARY_NEW_PROTECTED_PATHS = ['codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained.rs',
 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained_execute.rs',
 'codex-rs/hepta-agentd/src/cell_q24_candidate_stage_retained_readback.rs',
 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_command.rs',
 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_command_owner_adapter.rs',
 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_command_service.rs',
 'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_command.rs',
 'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_command_service.rs',
 'codex-rs/hepta-agentd/src/circuit_evaluated_next_use_remote.rs',
 'codex-rs/hepta-agentd/src/circuit_retained_version_prepared.rs']

def ordinary_require(value, reason):
    if not value:
        raise PROOF.VerificationFailure(reason)


def ordinary_depth_at(code, end):
    """Delimiter depths in the original literal/comment-masked code."""
    brace = paren = bracket = 0
    for char in code[:end]:
        if char == "{":
            brace += 1
        elif char == "}":
            brace -= 1
        elif char == "(":
            paren += 1
        elif char == ")":
            paren -= 1
        elif char == "[":
            bracket += 1
        elif char == "]":
            bracket -= 1
        ordinary_require(min(brace, paren, bracket) >= 0, "unbalanced source before scope")
    return brace, paren, bracket


def ordinary_body_open(code, start, end):
    paren = bracket = 0
    for index in range(start, end + 1):
        char = code[index]
        if char == "(":
            paren += 1
        elif char == ")" and paren:
            paren -= 1
        elif char == "[":
            bracket += 1
        elif char == "]" and bracket:
            bracket -= 1
        elif char == "{" and not (paren or bracket):
            return index
    raise PROOF.VerificationFailure("actual body opening required")


def ordinary_item_end(proof, code, start):
    end = proof._rust_item_end(code, start)
    ordinary_require(end is not None and end >= start, "complete actual Rust item")
    return end


def ordinary_root_containers(proof, code):
    found = []
    pattern = (
        r"(?m)^[ \t]*(?:pub(?:\([^)]*\))?\s+)?"
        r"(?:unsafe\s+)?(?:impl|trait)\b"
    )
    for match in re.finditer(pattern, code):
        start = match.start()
        while start < match.end() and code[start].isspace():
            start += 1
        if ordinary_depth_at(code, start) != (0, 0, 0):
            continue
        end = ordinary_item_end(proof, code, start)
        ordinary_require(code[end] == "}", "actual impl/trait body")
        opening = ordinary_body_open(code, start, end)
        header = " ".join(code[start:opening].split())
        found.append({"start": start, "end": end + 1, "opening": opening,
                      "header": header})
    return found


def ordinary_function_location(proof, code, name, lower=0, upper=None):
    upper = len(code) if upper is None else upper
    pattern = r"\bfn\s+" + re.escape(name) + r"\s*(?=[(<])"
    matches = list(re.finditer(pattern, code[lower:upper]))
    ordinary_require(len(matches) == 1, "unique actual function: " + name)
    start = lower + matches[0].start()
    end = ordinary_item_end(proof, code, start)
    ordinary_require(end < upper and code[end] == "}", "bounded function body: " + name)
    return start, end + 1


def ordinary_select_scope(proof, code, selector):
    kind = selector["kind"]
    if kind == "unique_function":
        start, end = ordinary_function_location(proof, code, selector["name"])
        parents = [
            item for item in ordinary_root_containers(proof, code)
            if item["opening"] < start and end <= item["end"]
        ]
        depth = ordinary_depth_at(code, start)
        if not parents:
            ordinary_require(depth == (0, 0, 0), "function hidden in non-owner/nested scope")
            owner = None
        else:
            ordinary_require(len(parents) == 1 and depth == (1, 0, 0),
                    "function must be direct member of one root impl/trait")
            owner = parents[0]["header"]
        return {"start": start, "end": end, "owner": owner, "kind": kind}
    if kind == "root_impl_method":
        parents = [
            item for item in ordinary_root_containers(proof, code)
            if item["header"] == selector["header"]
        ]
        ordinary_require(len(parents) == 1, "unique root impl: " + selector["header"])
        parent = parents[0]
        start, end = ordinary_function_location(
            proof, code, selector["name"], parent["opening"] + 1, parent["end"] - 1
        )
        ordinary_require(ordinary_depth_at(code, start) == (1, 0, 0), "direct actual impl method")
        if selector.get("protect_entire_impl", False):
            start, end = parent["start"], parent["end"]
        return {"start": start, "end": end, "owner": parent["header"], "kind": kind}
    if kind == "root_type":
        pattern = (
            r"(?m)^[ \t]*(?:pub(?:\([^)]*\))?\s+)?"
            + re.escape(selector["item_kind"]) + r"\s+"
            + re.escape(selector["name"]) + r"\b"
        )
        matches = []
        for match in re.finditer(pattern, code):
            start = match.start()
            while start < match.end() and code[start].isspace():
                start += 1
            if ordinary_depth_at(code, start) == (0, 0, 0):
                matches.append(start)
        ordinary_require(len(matches) == 1, "unique actual root type: " + selector["name"])
        start = matches[0]
        end = ordinary_item_end(proof, code, start) + 1
        return {"start": start, "end": end, "owner": None, "kind": kind}
    raise PROOF.VerificationFailure("unknown scope selector")


def ordinary_without_nested_functions(proof, code, scope):
    """The same nested-function exclusion used by original function-order checks."""
    start, end = scope["start"], scope["end"]
    body = code[start:end]
    outer = re.match(r"fn\s+\w+\s*", body)
    ordinary_require(outer is not None, "literal function scope must begin at fn")
    cursor = outer.end()
    while nested := re.search(r"\bfn\s+(?:r#)?\w+", body[cursor:]):
        nested_start = cursor + nested.start()
        nested_end = ordinary_item_end(proof, body, nested_start)
        body = (
            body[:nested_start]
            + "".join("\n" if char == "\n" else " "
                      for char in body[nested_start:nested_end + 1])
            + body[nested_end + 1:]
        )
        cursor = nested_end + 1
    return body


def ordinary_literal_span(proof, code, raw, spec):
    if spec["scope"]["kind"] == "module_constant":
        start, end = 0, len(code)
        scoped_code = code
    else:
        scope = ordinary_select_scope(proof, code, spec["scope"])
        start, end = scope["start"], scope["end"]
        scoped_code = ordinary_without_nested_functions(proof, code, scope)
    matches = list(re.finditer(spec["prefix_regex"], scoped_code))
    ordinary_require(len(matches) == 1, "unique actual protocol expression")
    match = matches[0]
    prefix_start = start + match.start()
    offset = start + match.end()
    if spec["scope"]["kind"] == "module_constant":
        ordinary_require(ordinary_depth_at(code, prefix_start) == (0, 0, 0),
                "protocol constant must be at actual module scope")
    literal = re.match(r'\s*(b?"(?:[^"\\]|\\.)*")', raw[offset:end])
    ordinary_require(literal is not None, "actual literal immediately follows code prefix")
    token_start = offset + literal.start(1)
    token_end = offset + literal.end(1)
    token = literal.group(1)
    ordinary_require(token == spec["expected_rust_literal"], "actual protocol literal differs")
    ordinary_require(code[token_start:token_end] == proof._strip_rust_non_code(token),
            "literal must occupy this real masked code expression")
    return {"prefix_start": prefix_start, "start": token_start, "end": token_end,
            "literal": token, "scope": spec["scope"],
            "prefix_regex": spec["prefix_regex"]}


def ordinary_mount_span(proof, code, raw, spec):
    matches = []
    for prefix in re.finditer(r"#\[\s*path\s*=", code):
        if ordinary_depth_at(code, prefix.start()) != (0, 0, 0):
            continue
        literal = re.match(r'\s*("(?:[^"\\]|\\.)*")', raw[prefix.end():])
        if literal is None or literal.group(1) != spec["path_literal"]:
            continue
        start_literal = prefix.end() + literal.start(1)
        end_literal = prefix.end() + literal.end(1)
        if code[start_literal:end_literal] != proof._strip_rust_non_code(literal.group(1)):
            continue
        suffix = re.match(
            r"\s*\]\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+"
            + re.escape(spec["module_name"]) + r"\s*;", code[end_literal:]
        )
        if suffix is not None:
            matches.append((prefix.start(), end_literal + suffix.end()))
    ordinary_require(len(matches) == 1, "actual production module mount: " + spec["child"])
    return {"start": matches[0][0], "end": matches[0][1],
            "child": spec["child"], "module_name": spec["module_name"]}


class EvaluatedOrdinaryRetainedClosureTests(unittest.TestCase):
    """Source mechanisms only; these tests create no authorized A/B/C run."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def original_verifies(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows, path)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def actual_scopes(self, path, source):
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        for guard in ORDINARY_SCOPE_GUARDS.get(path, ()):
            span = ordinary_select_scope(PROOF, code, guard["selector"])
            actual = hashlib.sha256(code[span["start"]:span["end"]].encode()).hexdigest()
            ordinary_require(actual == guard["masked_sha256"], "actual root scope changed: " + path)

    def actual_literals(self, path, source):
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        for spec in ORDINARY_LITERAL_SPECS:
            if spec["path"] == path:
                ordinary_literal_span(PROOF, code, source, spec)

    def actual_mounts(self, path, source):
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        for spec in ORDINARY_MODULE_MOUNTS:
            if spec["parent"] == path:
                ordinary_mount_span(PROOF, code, source, spec)

    def verifies(self, path, source):
        self.original_verifies(path, source)
        self.actual_scopes(path, source)
        self.actual_literals(path, source)
        self.actual_mounts(path, source)

    def attack(self, filename, function, marker, replacement="", selector=None):
        path = AGENT + filename
        source = (ROOT / path).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        selector = selector or {"kind": "unique_function", "name": function}
        span = ordinary_select_scope(PROOF, code, selector)
        pattern = r"\s*".join(re.escape(token) for token in re.findall(r"\w+|[^\w\s]", marker))
        if marker[0].isalnum() or marker[0] == "_":
            pattern = r"(?<!\w)" + pattern
        if marker[-1].isalnum() or marker[-1] == "_":
            pattern += r"(?!\w)"
        matches = list(re.finditer(pattern, code[span["start"]:span["end"]]))
        self.assertTrue(matches, (path, function, marker))
        self.verifies(path, source)
        # Repeated real checks are each attacked in a separate fresh source.
        # No changed source, authority field, or verification verdict is cached.
        for occurrence, found in enumerate(matches):
            start = span["start"] + found.start()
            end = span["start"] + found.end()
            self.assertEqual(re.sub(r"\s+", "", source[start:end]), re.sub(r"\s+", "", marker))
            changed = source[:start] + replacement + source[end:]
            self.assertNotEqual(source, changed)
            with self.subTest(path=path, function=function, marker=marker, occurrence=occurrence):
                with self.assertRaises(PROOF.VerificationFailure):
                    self.original_verifies(path, changed)

    def test_new_typed_edges_and_old_boundary_inventory_are_exact(self):
        boundaries = PROOF._boundary_rows(self.manifest)
        PROOF._verify_privileged_inventory(self.manifest, boundaries)
        self.assertEqual(len(boundaries), 621)
        self.assertEqual(PROOF._string_tuple(self.manifest, "source_roots"), ("codex-rs",))
        self.assertEqual(PROOF._string_tuple(self.manifest, "ignored_path_fragments"),
                         ("/tests/", "/examples/", "_tests.rs"))
        checked = {key: self.manifest[key] for key in (
            "boundary", "privileged_inventory", "authority", "source_roots", "ignored_path_fragments")}
        observed = hashlib.sha256(json.dumps(checked, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(observed, ORDINARY_COMPLETE_BOUNDARY_SHA256)
        self.assertEqual(self.manifest["boundary"][541:569], ORDINARY_NEW_BOUNDARIES)
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))
        for path in ORDINARY_SCOPE_GUARDS:
            with self.subTest(actual_root_scopes=path):
                self.actual_scopes(path, (ROOT / path).read_text())

    def test_complete_evaluated_prefix_cannot_admit_legacy_adopt_or_wrong_owner(self):
        path = "cell_q24_candidate_stage_retained.rs"
        for marker in (
            "LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?",
            "!is_evaluated_no_update(snapshot)", "!(4..=6).contains(&snapshot.receipts.len())",
            "snapshot.training_no_update_v2().is_some()", "for receipt in &snapshot.receipts[..4]",
            "original.record(receipt.clone(), receipt.observed_unix_seconds)?",
            "original.next_stage() != Some(Stage::Selection)",
            "original.candidate() != complete.candidate()",
            "original.next_task_bundle() != Some(&snapshot.request.selected_bundle)",
            ".is_none_or(|candidate| candidate == &snapshot.request.selected_bundle)",
            "complete.next_stage() != expected",
            "complete.next_task_bundle() != Some(&snapshot.request.selected_bundle)",
        ):
            self.attack(path, "evaluated_prefix", marker)
        self.attack(path, "is_evaluated_no_update", "LearningEvaluationDispositionV1::NoUpdate", "LearningEvaluationDispositionV1::Adopt")
        self.attack(path, "evaluated_prefix", "4 => Some(Stage::Selection)", "3 => Some(Stage::Selection)")
        self.attack(path, "evaluated_prefix", "5 => Some(Stage::NextUse)", "4 => Some(Stage::NextUse)")
        self.attack(path, "require_evaluated_retained_stage", "evaluated_prefix(snapshot)?")
        self.attack(path, "require_evaluated_retained_stage", "!matches!(stage, Stage::Selection | Stage::NextUse)", "false")
        self.attack(path, "require_evaluated_retained_stage", "!= Some(stage)", "== Some(stage)")

    def test_original_continuation_channels_are_consumed_once(self):
        path = "cell_q24_no_update_stage_state.rs"
        for marker in (
            ".original_receipt_predecessors(auth::now()?)", "self.records.len() != 3",
            "self.records[2].1 != training_signature", "snapshot.request != owners.material.initial.request",
            "snapshot.owners != owners.material.initial.owners", "scope != owners.material.scope",
            "verifier.trust_digest() != owners.material.verifier.trust_digest()",
            "verifier.scope_digest() != owners.material.verifier.scope_digest()",
            "verifier.objective_digest() != owners.material.verifier.objective_digest()",
            "self.version.is_some()", "self.selector.is_some()", "self.next_use.is_some()", "self.readiness.is_some()",
            "self.version_initial.take()", "self.selector_initial.take()", "self.next_use_initial.take()",
            "self.readiness_initial.take()",
        ):
            self.attack(path, "take_evaluated_retained_channels", marker)
        for function, marker in (
            ("refresh", ".take_evaluated_retained_channels(&owners.common, &context)?"),
            ("bind_selector", "self.selector_initial.take()"),
            ("bind_next_use", "self.next_use_initial.take()"),
            ("bind_next_use", "self.readiness_initial.take()"),
        ):
            self.attack("cell_q24_candidate_stage_retained.rs", function, marker)

    def test_root_current_checks_surround_actual_retained_effects(self):
        path = "cell_q24_candidate_stage_retained_execute.rs"
        for function in ("execute_evaluated_retained_stage", "prepare_retained_version", "await_completed_c"):
            self.attack(path, function, "RootResidentLearningEffectGateV3::require_current(")
        for marker in (
            "OriginalCellQ24CandidateStageOwnersV1::require_evaluated_retained_stage(snapshot, stage)?",
            "self.common.origin != Origin::Fresh", "self.common.root.as_ref().ok_or(",
            "if lane.failed", "lane.failed = true", ".require_new_original_receipt(auth::now()?)",
            "auth::require_clock(started, fresh)?", "auth::verify_receipt(",
            "self.require_live_deadline()?", "lane.require_published().await?",
        ):
            self.attack(path, "execute_evaluated_retained_stage", marker)
        self.attack(path, "execute_evaluated_retained_stage", "lane.failed = false", "lane.failed = true")

    def test_version_prepare_is_once_and_completion_requires_actual_readiness(self):
        path = "cell_q24_candidate_stage_retained_execute.rs"
        for marker in (
            "RootResidentLearningEffectGateV3::training_cancellation(gate)",
            "OriginalCircuitRetainedVersionClientV1::prepare_original_version(client, cancellation)",
            "for _ in 0..128", "OriginalCircuitRetainedVersionClientV1::readback(",
            ".is_some_and(|read| read.publication().is_some())",
        ):
            self.attack(path, "prepare_retained_version", marker)
        for marker in ("OriginalCircuitCompletionReadinessClientV1::read_current(",
                       "if let Some(ready) = current", "self.read_selection(owners, snapshot).await?",
                       "self.refresh(owners, snapshot).await?", "for _ in 0..128"):
            self.attack(path, "await_completed_c", marker)
        for marker in ("lane.prepare_retained_version(self, snapshot, gate).await?",
                       "lane.await_completed_c(self, snapshot, gate).await?",
                       "OriginalCircuitSelectionCommandClientV1::execute_selection(",
                       "OriginalCircuitNextUseCommandClientV1::attest_completed_task(",
                       "ready.as_ref() != Some(&original.receipt().observation)"):
            self.attack(path, "execute_evaluated_retained_stage", marker)

    def test_four_five_six_pins_keep_full_signed_predecessors(self):
        path = "cell_q24_candidate_stage_retained_readback.rs"
        for function, length, index in (("pin_selection", 5, 4), ("pin_completion", 6, 5)):
            self.attack(path, function, f"original.snapshot().receipts.len() != {length}", f"original.snapshot().receipts.len() != {length - 1}")
            self.attack(path, function, f".get({index})", f".get({index - 1})")
            self.attack(path, function, ".starts_with(")
            self.attack(path, function, ".is_some_and(|previous| previous != original)")
            self.attack(path, function, ".validate_snapshot(original.snapshot())?")
        self.attack(path, "pin_selection", ".original_receipt_predecessors(auth::now()?)")
        self.attack(path, "pin_completion", "original.selection_attestation() != selection.attestation()")
        self.attack(path, "pin_completion", "auth::verify_receipt(")
        self.attack(path, "read_evaluated_retained_prefix", "4 => {}", "4 => { lane.read_selection(self, snapshot).await?; }")
        for function in ("read_evaluated_retained_prefix", "retained_attestation"):
            for marker in ("evaluated_prefix(snapshot)?", "lane.failed = true", "lane.refresh(self, snapshot).await?", "self.require_live_deadline()?"):
                self.attack(path, function, marker)
        self.attack(path, "retained_attestation", "if actual != *receipt", "if actual == *receipt")

    def test_each_selector_clone_is_bound_to_its_actual_root_impl(self):
        filename = "circuit_evaluated_selection_command.rs"
        path = AGENT + filename
        source = (ROOT / path).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        for owner in ("OriginalCircuitSelectionCommandContextV1", "OriginalCircuitSelectionCommandReceiptV1"):
            selector = {"kind": "root_impl_method", "header": "impl Clone for " + owner,
                        "name": "clone", "protect_entire_impl": True}
            self.attack(filename, "clone", ".map(OriginalCircuitEvaluatedRetentionContextV1::clone_for_original_receipt)", selector=selector)
            span = ordinary_select_scope(PROOF, code, selector)
            hidden = source[:span["start"]] + "fn never_called_clone_decoy() {\n" + source[span["start"]:span["end"]] + "\n}\n" + source[span["end"]:]
            self.actual_scopes(path, source)
            with self.assertRaises(PROOF.VerificationFailure):
                self.actual_scopes(path, hidden)

    def test_clone_and_cold_recovery_cannot_promote_original_origin(self):
        self.attack("circuit_evaluated_retention_context.rs", "clone_for_original_receipt", "origin: self.origin", "origin: Origin::Fresh")
        self.attack("circuit_evaluated_retention_context.rs", "into_original_receipt_readback", "self.origin = Origin::Readback", "self.origin = Origin::Fresh")
        for filename in ("circuit_evaluated_selection_command.rs", "circuit_evaluated_next_use_command.rs"):
            self.attack(filename, "recover_from_original_evaluated_stream", "&original.into_original_receipt_readback()")
            self.attack(filename, "recover_from_original_evaluated_stream", "wire::authenticate_completed(&context, snapshot, signed, now()?)")
            self.attack(filename, "recover_from_original_evaluated_stream", "true, retained", "false, retained")
        for filename, method in (("circuit_evaluated_selection_command_service.rs", "from_original_evaluated_receipt_owner"),
                                 ("circuit_evaluated_next_use_command_service.rs", "from_original_evaluated_receipt_owner")):
            self.attack(filename, method, "owner.original_command_profile()")
            self.attack(filename, method, "AtomicBool::new(readback_only)", "AtomicBool::new(false)")

    def test_original_command_helpers_keep_distinct_legacy_and_evaluated_reads(self):
        for filename, owner, old_attest, new_attest, new_readback in (
            ("circuit_evaluated_selection_command_service.rs", "OriginalCircuitSelectionReceiptOwnerV1", "attest_original_remote_selection", "attest_original_evaluated_remote_selection", "readback_evaluated_remote_selection"),
            ("circuit_evaluated_next_use_command_service.rs", "OriginalCircuitNextUseReceiptOwnerV1", "attest_original_remote_completion", "attest_original_evaluated_remote_completion", "readback_evaluated_remote_completion"),
        ):
            for marker in ("OriginalPredecessors::Legacy(trainer)", "OriginalPredecessors::Evaluated { trainer, evaluator }",
                           owner + "::" + old_attest + "(", owner + "::readback_remote(",
                           owner + "::" + new_attest + "(", owner + "::" + new_readback + "("):
                self.attack(filename, "observe_original", marker)
        for filename in ("circuit_selection_command_evidence.rs", "circuit_next_use_command_evidence.rs"):
            self.attack(filename, "evidence_response", "wire::Action::Readback", "wire::Action::Execute")
        self.attack("circuit_selection_command_readback_service.rs", "original_selection_readback_response", "wire::Action::Readback", "wire::Action::Execute")

    def test_evaluated_remote_c_finishes_with_actual_source_cell_after_predecessors(self):
        path = "circuit_evaluated_next_use_remote.rs"
        for marker in ("let Profile::Evaluated(original) = profile else", "self.selection.snapshot() != original.snapshot()",
                       "self.selection.original_receipt_binding() != original.original_receipt_binding()",
                       "self.live.require_original_evaluated_next_use(original)?"):
            self.attack(path, "require_profile", marker)
        self.attack(path, "evaluated_owners", "Some((self.trainer, self.evaluator))", "None")
        self.attack(path, "location", "ObservationLocation::EvaluatedOwner", "ObservationLocation::RemoteOwner")
        self.attack(path, "observe", "OriginalCircuitLearningReadClientV1::read_current(self.live).await?")
        self.attack("circuit_next_use_receipt_owner.rs", "prepare", "source.require_profile(&self.profile)?")
        filename = "circuit_next_use_receipt_owner.rs"
        for marker in ("let evidence = self.predecessors(source).await?;", "if self.prepare(source).await? != *observed", "self.journal.read(&self.saved)? != bytes"):
            self.attack(filename, "finish_original_readback", marker)
        source = (ROOT / (AGENT + filename)).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        span = ordinary_select_scope(PROOF, code, {"kind": "unique_function", "name": "finish_original_readback"})
        branch = code.index("ObservationLocation::LocalOwner | ObservationLocation::EvaluatedOwner => {", span["start"], span["end"])
        evidence = "let evidence = self.predecessors(source).await?;"
        first = code.index(evidence, branch, span["end"])
        second = code.index("if self.prepare(source).await? != *observed {", first, span["end"])
        guard_end = PROOF._rust_item_end(code, second) + 1
        changed = source[:first] + source[second:guard_end] + "\n                " + evidence + source[guard_end:]
        with self.assertRaises(PROOF.VerificationFailure):
            self.original_verifies(AGENT + filename, changed)

    def test_version_requires_actual_preheld_e_and_distinct_purpose(self):
        for function in ("from_original_evaluated_owners", "recover_from_original_evaluated_owners"):
            self.attack("circuit_retained_version_host.rs", function, "evaluator: OriginalCellEvaluationCommandConnectionV1")
            self.attack("circuit_retained_version_host.rs", function, "InitialVersionEvidence::EvaluatedNoUpdate(evaluator)")
        for marker in ("state.initial_evaluator.take()", "OriginalCellEvaluationCommandConnectionV1::bind_original_training(",
                       "OriginalCellEvaluationCommandClientV1::readback(&evaluator)", "state.evaluator = evaluator"):
            self.attack("circuit_retained_version_state.rs", "bind_original_predecessor", marker)
        self.attack("circuit_retained_version_state.rs", "require_cut_current", "self.original_evaluator()?")
        self.attack("circuit_retained_version_context.rs", "from_original_evaluated", "OriginalCircuitEvaluatedRetentionContextV1::recover_original_evaluation(")
        self.attack("circuit_retained_version_context.rs", "purpose", "Some(_) => RetainedVersionPurposeV1::EvaluatedNoUpdate", "Some(_) => RetainedVersionPurposeV1::TrainingNoUpdate")

    def test_cold_reader_is_installed_only_after_two_complete_current_reads(self):
        filename = "circuit_retained_version_state.rs"
        for marker in ("self.origin != RetainedVersionOriginV1::Recovered", "state.selection_reader.take()",
                       "let before = self.read_original(state)?;", "let after = self.read_original(state)?;",
                       ".build_original_selection_reader()?", "before != after || after.publication().is_none()",
                       ".require_fresh(super::super::now()?, PublicationAccess::Readback)?", "self.require_lifetime()?",
                       "state.selection_reader = Some(reader)"):
            self.attack(filename, "read_original_recovery", marker)
        path = AGENT + filename
        source = (ROOT / path).read_text()
        install = "state.selection_reader = Some(reader);"
        self.assertEqual(source.count(install), 1)
        changed = source.replace(install, "", 1).replace("let after = self.read_original(state)?;", install + "\n        let after = self.read_original(state)?;", 1)
        with self.assertRaises(PROOF.VerificationFailure):
            self.original_verifies(path, changed)

    def test_later_cold_bind_failure_and_invalid_wire_have_separate_effects(self):
        path = "circuit_retained_version_service.rs"
        for marker in ("request.purpose != self.purpose.operation()", "request.request_id != request_id",
                       "request.initial_binding != self.initial_binding.to_string()",
                       "self.bind_original_predecessor(&mut state).is_err()",
                       "self.origin == RetainedVersionOriginV1::Recovered", "state.selection_reader = None",
                       "(wire::OriginalResult::Uncertain, None)",
                       "request.require_cut(state.cut.as_ref().ok_or(Error::Unavailable)?, request_id)?",
                       "self.read_original_recovery(&mut state)"):
            self.attack(path, "command_response", marker)
        source = (ROOT / (AGENT + path)).read_text()
        anchor = "wire::digest(&request.binding)?;"
        self.assertEqual(source.count(anchor), 1)
        changed = source.replace(anchor, "self.state.try_lock()?.selection_reader = None;\n        " + anchor, 1)
        with self.assertRaises(PROOF.VerificationFailure):
            self.original_verifies(AGENT + path, changed)

    def test_only_published_and_fresh_version_can_serve_s_or_start_c(self):
        for marker in ("self.original_final_use_outcome()", "== RetainedVersionFinalUseOutcomeV1::Published",
                       ".require_fresh(super::super::now()?, PublicationAccess::Readback)?", "Some(Arc::clone(reader))"):
            self.attack("circuit_retained_version_service.rs", "serve_original_selection_channel", marker)
        for marker in ("owner.read_original(&state)?", "owner.original_final_use_outcome() != RetainedVersionFinalUseOutcomeV1::Published", "config.take()"):
            self.attack("circuit_retained_version_effect.rs", "run_original_c", marker)
        for marker in ("self.require_lifetime()?", "state.require_cut_current(&self.runtime)?", "artifact::require_same(&before, &after)?"):
            self.attack("circuit_retained_version_state.rs", "read_original", marker)

    def test_final_use_and_prepared_custody_are_consumed_by_original_owners(self):
        for marker in ("self.origin != RetainedVersionOriginV1::Fresh", "state.final_use_issuer.is_some()",
                       "self.publication_requested.swap(true, Ordering::AcqRel)", "state.phase.take()",
                       ".block_on((*original).publish(signed))", ".install_original(published, cut, intent)",
                       "state.trainer = Some(trainer)", "state.evaluator = evaluator",
                       ".install_original_selection_reader()", ".read_original(&state)"):
            self.attack("circuit_retained_version_effect.rs", "publish_original_final_use", marker)
        for marker in ("self,", "PreparedOriginalCircuitRetainedPublicationV1::publish_and_retain_original_trainer(",
                       "PreparedOriginalCircuitEvaluatedRetentionV1::publish_and_retain_original_evidence(",
                       "Ok((task, trainer, None))", "Ok((task, trainer, Some(evaluator)))"):
            self.attack("circuit_retained_version_prepared.rs", "publish", marker)

    def test_readiness_has_exact_typed_purposes_and_monotone_channel_state(self):
        path = "circuit_learning_completion_readiness.rs"
        self.attack(path, "require_profile", "self.require_context(legacy, binding, request_id)")
        self.attack(path, "require_profile", "self.purpose != EVALUATED_PURPOSE", "self.purpose == EVALUATED_PURPOSE")
        self.attack(path, "require_profile", "context.mode()? != original::Mode::NextUse")
        self.attack(path, "require_profile", "context.require_request(&self.original, binding, request_id)")
        self.attack(path, "bind_original_stage_channel", "ReadProfile::TrainingNoUpdate(context)")
        for marker in (".take()", "!(1..=128).contains(&channel.next_request_id)",
                       ".require_profile(&self.context, self.binding, request_id)?",
                       "Readiness::NotReady => None", "Some(self.context.decode(read)?)",
                       "fresh < started_at || self.context.binding(fresh)? != self.binding",
                       ".is_some_and(|prior| current.as_ref() != Some(prior))", "*retained = Some(ready.clone())",
                       "*self.channel.try_lock().map_err(|_| Error::Unavailable)? = Some(channel)"):
            self.attack(path, "read_current", marker)
        # Returning the same Ready is permitted; readiness is not invalidated
        # merely because a previous Ready exists. A changed/absent Ready rejects.
        self.attack(path, "read_current", ".is_some_and(|prior| current.as_ref() != Some(prior))", ".is_some_and(|_| true)")

    def test_actual_protocol_literals_reject_same_length_comment_and_dead_code_decoys(self):
        for spec in ORDINARY_LITERAL_SPECS:
            path = spec["path"]
            source = (ROOT / path).read_text()
            code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
            span = ordinary_literal_span(PROOF, code, source, spec)
            literal = span["literal"]
            at = literal.index('"') + 1
            bad = literal[:at] + ("x" if literal[at] != "x" else "y") + literal[at + 1:]
            changed = source[:span["start"]] + bad + source[span["end"]:]
            self.assertEqual(len(changed), len(source))
            for decoy in ("\n// " + literal + "\n", "\nfn unrelated_protocol_decoy() { let _ = " + literal + "; }\n"):
                with self.subTest(path=path, scope=spec["scope"], decoy=decoy):
                    with self.assertRaises(PROOF.VerificationFailure):
                        self.actual_literals(path, changed + decoy)
            if spec["scope"]["kind"] != "module_constant":
                scope = ordinary_select_scope(PROOF, code, spec["scope"])
                opening = ordinary_body_open(code, scope["start"], scope["end"] - 1)
                nested = changed[:opening + 1] + "\nfn nested_protocol_decoy() { let _ = " + literal + "; }\n" + changed[opening + 1:]
                with self.assertRaises(PROOF.VerificationFailure):
                    self.actual_literals(path, nested)

    def test_new_production_modules_are_real_and_cannot_gain_authority_factories(self):
        for spec in ORDINARY_MODULE_MOUNTS:
            path = spec["parent"]
            source = (ROOT / path).read_text()
            code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
            span = ordinary_mount_span(PROOF, code, source, spec)
            self.assertTrue((ROOT / spec["child"]).is_file())
            declaration = source[span["start"]:span["end"]]
            self.actual_mounts(path, source)
            for replacement in ("// " + declaration.replace("\n", "\n// "), "#[cfg(test)]\n" + declaration,
                                "fn unused_module_decoy() {\n" + declaration + "\n}"):
                changed = source[:span["start"]] + replacement + source[span["end"]:]
                with self.assertRaises(PROOF.VerificationFailure):
                    self.actual_mounts(path, changed)
        for path in ORDINARY_NEW_PROTECTED_PATHS:
            source = (ROOT / path).read_text()
            self.verifies(path, source)
            for marker in ("SigningKey", "File::create", "UnixStream::connect", "with_root_learning_stage_owners("):
                with self.subTest(path=path, forbidden=marker):
                    with self.assertRaises(PROOF.VerificationFailure):
                        self.original_verifies(path, source + "\nfn forbidden_factory() { " + marker + "; }\n")


if __name__ == "__main__":
    unittest.main()
