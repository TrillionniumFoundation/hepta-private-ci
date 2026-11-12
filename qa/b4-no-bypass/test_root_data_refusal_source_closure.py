"""Guard durable refusal of Root Source data across primary failure and restart.

These mutations check executable structure and closed callers. They neither
execute the UID0 subprocess tests nor attest an A/learning/cold-recovery chain.
"""

from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_root_historical_capture_source_closure as component


ROOT = component.ROOT
PROOF = component.PROOF
PIN = component.PIN
RECORD = component.RECORD
HANDOFF = component.HANDOFF
REFUSAL = component.REFUSAL
TRANSPORT = component.TRANSPORT
PRIMARY = re.compile(
    r"HostAuthorityFrontierStore::(?:open|initialize)\s*\("
    r"|\b(?:(?:self|retained)\s*\.\s*)?store\s*\.\s*(?:load|compare_and_set)\s*\("
)


def closure_span(code, marker):
    if code.count(marker) != 1:
        raise PROOF.VerificationFailure("one exact armed action required")
    brace = code.index("{", code.index(marker))
    depth = 1
    end = brace + 1
    while depth and end < len(code):
        depth += (code[end] == "{") - (code[end] == "}")
        end += 1
    if depth:
        raise PROOF.VerificationFailure("complete armed action required")
    return brace, end


def inside(code, marker, positions):
    begin, end = closure_span(code, marker)
    if any(not begin < position < end for position in positions):
        raise PROOF.VerificationFailure("primary operation escaped its durable arm")


def require_armed_io(path, source):
    functions = {
        RECORD: (
            ("open_existing", "refusal.inspect(|| {"),
            ("inspect_exact<T>", "self.refusal.inspect(|| {"),
        ),
        HANDOFF: (
            ("create_pending", "|| {"),
            ("open_record", "refusal.inspect(|| {"),
            ("open_finalized", "RootDataRefusalV1::inspect(&retained.refusal, || {"),
            ("require_exact", "self.refusal.inspect(|| {"),
            ("replace", "self.refusal.inspect(|| {"),
        ),
    }
    for name, marker in functions.get(path, ()):
        code = component.function_code(source, name)
        positions = [match.start() for match in PRIMARY.finditer(code)]
        if not positions:
            raise PROOF.VerificationFailure("actual protected primary IO required")
        inside(code, marker, positions)
        if name == "replace":
            if code.count("postcheck()") != 1:
                raise PROOF.VerificationFailure("one real final postcheck required")
            inside(code, marker, [code.index("postcheck()")])
    if path in (RECORD, HANDOFF):
        code = component.function_code(source, "fence")
        refused = code.index("self.refusal.refuse()?")
        if any(match.start() < refused for match in PRIMARY.finditer(code)):
            raise PROOF.VerificationFailure("primary decoded before independent refusal")
    if path == PIN:
        code = component.function_code(source, "capture_initial_source_pin")
        outer, outer_end = closure_span(code, "|access| {")
        proof, proof_end = closure_span(code, "|proof| {")
        if not code.index("RootHistoricalSourcePinV1::capture(") < outer < proof < proof_end < outer_end:
            raise PROOF.VerificationFailure("original context must finish within the arm")
        physical = re.compile(
            r"FilePin::readonly\s*\(|FileAnchorWitnessStore::open\s*\("
            r"|HistoricalCircuitTaskSourceV1::open\s*\(|\.observe_run_publication\s*\("
        )
        positions = [match.start() for match in physical.finditer(code)]
        inside(code, "|proof| {", positions)
        tail = code[proof_end:outer_end]
        if not re.match(r"^\s*,\s*\)\?\s*;", tail) or re.search(
            r"\bretained\s*\.\s*ok_or_else\s*\(", tail
        ) is None:
            raise PROOF.VerificationFailure("original context postcheck was not propagated")
    if path == TRANSPORT:
        code = component.function_code(source, "exchange")
        marker = "RootHistoricalSourceHandoffV1::finalize_after_verified_context("
        start = code.index(marker)
        action = code[start:code.index("self.acknowledged = true", start)]
        for guard in (
            "RootHistoricalSourcePinV1::open_existing(",
            "pin.readback_digest()? != receipt.pin_digest()",
            "receipt.require_original_capture_session()",
        ):
            if action.count(guard) != 1:
                raise PROOF.VerificationFailure("real final pin/receipt postcheck required")
            inside(action, "|| {", [action.index(guard)])
    if path == REFUSAL:
        cold = component.function_code(source, "open_existing")
        if re.search(r"\b(?:initialize|complete_armed|compare_and_set)\s*\(", cold):
            raise PROOF.VerificationFailure("cold refusal open cannot initialize or finish")
        for name in ("inspect<T>", "complete_armed<T>"):
            code = component.function_code(source, name)
            if code.count("compare_and_set(") != 1:
                raise PROOF.VerificationFailure("one exact arm transition required")
        masked = PROOF._strip_rust_non_code(source)
        start = masked.index("fn binding(")
        end = PROOF._rust_item_end(masked, start)
        raw = source[start:end + 1]
        code = masked[start:end + 1]
        literal = 'let owner = format!("initial-data-refusal/{name}/{scope}");'
        if raw.count(literal) != 1:
            raise PROOF.VerificationFailure("same primary scope refusal namespace required")
        position = raw.index(literal)
        if code[position:position + len(literal)] != PROOF._strip_rust_non_code(literal):
            raise PROOF.VerificationFailure("a comment cannot supply the refusal namespace")


def require_executed_child(source):
    # Test functions are intentionally retained here: this checks the real
    # subprocess driver, not a production caller or an executed native result.
    code = PROOF._strip_rust_non_code(source)
    markers = (
        ".split_once(", "let output = std::process::Command::new(",
        ".output()?", "output.status.success()",
        "&& String::from_utf8_lossy(&output.stdout).contains(receipt.as_str())",
    )
    offset = 0
    for marker in markers:
        found = code.find(marker, offset)
        if found < 0:
            raise PROOF.VerificationFailure("zero-tests exit cannot supply a child receipt")
        offset = found + len(marker)
    if "std::io::stdout().flush()?" not in code:
        raise PROOF.VerificationFailure("child must flush its real execution receipt")


class RootDataRefusalClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    rejects_removal = component.RootHistoricalSourceCaptureClosureTests.rejects_removal

    def check_mutation(self, path, mutate):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        original = (ROOT / path).read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)

            def verify(source):
                target.write_text(source)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                require_armed_io(path, source)

            verify(original)
            changed = mutate(original)
            self.assertNotEqual(changed, original)
            with self.assertRaises(PROOF.VerificationFailure):
                verify(changed)

    def test_arm_precedes_action_and_keeps_exact_attempt_and_shared_gate(self):
        self.rejects_removal(REFUSAL, "create_fresh<T>", (
            "original_root()?", "armed.attempt = 1", "armed.phase = Phase::Armed",
            "HostAuthorityFrontierStore::initialize(root, owner.clone(), armed.clone())",
            "retained.complete_armed(&armed, initialize)?",
        ))
        self.rejects_removal(REFUSAL, "inspect<T>", (
            ".try_lock()", "if self.poisoned.load(Ordering::Acquire)",
            "let before = self.load_matching()?", "before.phase != Phase::Ready",
            "before.attempt.checked_add(1)", "armed.attempt = attempt",
            "armed.phase = Phase::Armed", "compare_and_set(&self.owner, &before, &armed)",
            "self.complete_armed(&armed, action)",
        ))
        self.rejects_removal(REFUSAL, "complete_armed<T>", (
            "action().and_then(|value| {", "if self.poisoned.load(Ordering::Acquire)",
            "ready.phase = Phase::Ready", "compare_and_set(&self.owner, armed, &ready)",
            "if result.is_err()", "self.poisoned.store(true, Ordering::Release)",
        ))

    def test_same_scope_full_target_and_no_cold_initialization_are_required(self):
        self.rejects_removal(REFUSAL, "binding", (
            "scope_digest(target.scope())", "RootDataKind::SourcePin",
            "RootDataKind::SourceHandoff", "target: target.clone()",
        ))
        self.rejects_removal(REFUSAL, "load_matching", (
            "same_binding.phase = self.binding.phase", "same_binding.attempt = self.binding.attempt",
            "observed.attempt == 0 || same_binding != self.binding",
        ))
        self.rejects_removal(REFUSAL, "open_existing", (
            "original_root()?", "HostAuthorityFrontierStore::open(root, owner.clone())",
            "retained.load_matching()?.phase != Phase::Ready",
        ))
        self.check_mutation(REFUSAL, lambda source: source.replace(
            '"initial-data-refusal/{name}/{scope}"', '"another-marker/{name}/{scope}"', 1
        ) + '\n// let owner = format!("initial-data-refusal/{name}/{scope}");\n')
        self.check_mutation(REFUSAL, lambda source: source.replace(
            "if retained.load_matching()?.phase != Phase::Ready",
            "retained.complete_armed(&fake, || Ok(()))?;\n"
            "        if retained.load_matching()?.phase != Phase::Ready", 1
        ))

    def test_refusal_does_not_need_to_decode_the_primary(self):
        self.rejects_removal(REFUSAL, "refuse", (
            "original_root()?", ".try_lock()", "self.poisoned.store(true, Ordering::Release)",
            "let observed = self.load_matching()?", "observed.phase == Phase::Refused",
            "refused.phase = Phase::Refused", "compare_and_set(&self.owner, &observed, &refused)",
            "self.store.load(&self.owner).map_err(io::Error::other)? != refused",
        ))
        for path in (RECORD, HANDOFF):
            self.rejects_removal(path, "fence", ("self.refusal.refuse()?",))
            self.check_mutation(path, lambda source: source.replace(
                "self.refusal.refuse()?;", "self.store.load(&self.owner)?;\n"
                "        self.refusal.refuse()?;", 1
            ))

    def test_existing_marker_fallback_cannot_replay_a_started_capture(self):
        self.rejects_removal(RECORD, "capture", (
            "RootDataRefusalV1::create_fresh(", "action(PinRecordAccess::Fresh)",
            "capture.is_some() && error.kind() == io::ErrorKind::AlreadyExists",
            "RootDataRefusalV1::open_existing(root, RootDataKind::SourcePin, target)?",
            "refusal.inspect(|| action(PinRecordAccess::Existing))?",
        ))

    def test_extra_primary_read_outside_arm_is_rejected(self):
        for path, name in ((RECORD, "open_existing"), (HANDOFF, "open_record")):
            def escape(source):
                start = source.index("fn " + name + "(")
                offset = source.index("{", start) + 1
                return source[:offset] + "\nHostAuthorityFrontierStore::open(root, owner);\n" + source[offset:]
            self.check_mutation(path, escape)
        self.check_mutation(PIN, lambda source: source.replace(
            "        RootHistoricalSourcePinV1::capture(",
            "        HistoricalCircuitTaskSourceV1::open(unregistered);\n"
            "        RootHistoricalSourcePinV1::capture(", 1
        ))

    def test_final_primary_readback_and_actual_receipt_stay_inside_arm(self):
        self.check_mutation(HANDOFF, lambda source: source.replace(
            "            postcheck()\n        });",
            "            Ok(())\n        });\n        postcheck()?;", 1
        ))
        self.check_mutation(TRANSPORT, lambda source: source.replace(
            "                        receipt.require_original_capture_session()\n"
            "                    },\n                )?;",
            "                        Ok(())\n                    },\n                )?;\n"
            "                receipt.require_original_capture_session()?;", 1
        ))

    def test_context_failure_cannot_leave_a_successful_pin_arm(self):
        def discard_original_context_error(source):
            code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
            start = code.index("fn capture_initial_source_pin(")
            end = PROOF._rust_item_end(code, start)
            body = code[start:end + 1]
            _, proof_end = closure_span(body, "|proof| {")
            close = re.match(r"\s*,\s*\)(\?)\s*;", body[proof_end:])
            self.assertIsNotNone(close)
            offset = start + proof_end + close.start(1)
            return source[:offset] + source[offset + 1:]
        self.check_mutation(PIN, discard_original_context_error)

    def test_subprocess_success_requires_an_actual_child_execution_receipt(self):
        for filename in (
            "authority_host_data_refusal_tests.rs",
            "authority_host_historical_source_pin_cold_tests.rs",
            "authority_host_historical_source_handoff_cold_tests.rs",
        ):
            original = (ROOT / component.AGENT / filename).read_text()
            require_executed_child(original)
            for marker in (
                ".split_once(",
                "&& String::from_utf8_lossy(&output.stdout).contains(receipt.as_str())",
                "std::io::stdout().flush()?",
            ):
                # The crash helper has two flush sites: removal must cover both.
                changed = original.replace(marker, "/* " + marker + " */")
                with self.subTest(file=filename, marker=marker):
                    self.assertNotEqual(changed, original)
                    with self.assertRaises(PROOF.VerificationFailure):
                        require_executed_child(changed)


if __name__ == "__main__":
    unittest.main()
