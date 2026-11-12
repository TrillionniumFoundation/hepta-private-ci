"""Mutate actual Cell data/custody checks; no native or Root qualification."""
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_root_data_refusal_source_closure as armed

ROOT = armed.ROOT
PROOF = armed.PROOF
A = "codex-rs/hepta-agentd/src/"
N = "codex-rs/hepta-neuron/src/"

def token_pattern(marker):
    return r"\s*".join(map(re.escape, re.findall(
        r"[A-Za-z_]\w*|\d+|::|->|=>|!=|==|&&|\|\||\.\.|[^\s]", marker)))

def cell_armed_io(path, source):
    functions = {
        A + "authority_host_historical_cell_pin.rs": (
            "with_original_cell_capture<T>", "RootDataRefusalV1::inspect(&original.refusal, || {"),
        A + "authority_host_historical_cell_registration.rs": (
            "register_original_initial_cell", "|| {"),
    }
    if path not in functions:
        return
    name, arm = functions[path]
    code = armed.component.function_code(source, name)
    pattern = re.compile(
        r"HostAuthorityFrontierStore::(?:initialize|open)\s*\("
        r"|\b(?:original\s*\.\s*)?store\s*\.\s*(?:load|compare_and_set)\s*\("
        r"|\bfiles\s*\.\s*require_original_cell_baseline\s*\("
    )
    positions = [m.start() for m in pattern.finditer(code)]
    if not positions:
        raise PROOF.VerificationFailure("actual original Cell IO required")
    armed.inside(code, arm, positions)
    if name == "with_original_cell_capture<T>":
        armed.inside(code, arm, [code.index("action(Some(&mut pending))?")])
    else:
        armed.inside(code, arm, [code.index("self.with_initial_publication_context(")])

class OriginalCellSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

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
                cell_armed_io(path, text)
            verify(source)
            changed = change(source)
            self.assertNotEqual(changed, source)
            with self.assertRaises(PROOF.VerificationFailure):
                verify(changed)

    def reject(self, path, function, marker, occurrence=0):
        def change(source):
            code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
            self.assertEqual(code.count(function), 1)
            start = code.index(function)
            end = PROOF._rust_item_end(code, start)
            matches = list(re.finditer(token_pattern(marker), code[start:end + 1]))
            self.assertGreater(len(matches), occurrence, (path, function, marker))
            m = matches[occurrence]
            lo, hi = start + m.start(), start + m.end()
            return source[:lo] + "/* " + source[lo:hi] + " */" + source[hi:]
        self.mutate(path, change)

    def test_physical_reader_keeps_full_binding_locks_and_complete_ack(self):
        path = N + "cell_journal_observer.rs"
        for marker in (
            "semantic_request_digest.is_zero()",
            "partition.scope.principal_digest.into_array() != scope.principal_digest",
            "partition.source_frontier.into_array() != binding.source_frontier()",
            "partition.writer_epoch != binding.writer_epoch()",
            "original_readonly(&files.journal)?", "original_readonly(&files.witness)?",
            "parsed.head != expected", "parsed.offset != bytes.len()",
            "parsed.owner.pending_inference(scope)?.is_some()",
        ):
            with self.subTest(marker=marker):
                self.reject(path, "fn observe_original_guarded_cell_v1(", marker)
        for marker in ("read_witness()? != expected", "original_image(&journal)? != bytes"):
            for occurrence in range(3):
                self.reject(path, "fn observe_original_guarded_cell_v1(", marker, occurrence)
        for marker in (".read(true)", "LockedFile::acquire(readonly)"):
            self.reject(path, "fn original_readonly(", marker)

    def test_shared_decoder_keeps_original_frame_checksum_and_full_witness(self):
        for marker in (
            "bytes[..HEADER_BYTES] != *header", "size == 0 || size > MAX_FRAME_BYTES",
            "count > max_records", "next_anchor(header, head, payload)?",
            "anchor.checkpoint_digest.as_array() != &bytes[end - 32..end]",
            "apply_record(payload, specs, &mut owner)?", "expected == Some(anchor)",
        ):
            self.reject(N + "cell_journal_image.rs", "fn parse_original_cell_image(", marker)

    def test_root_baseline_and_cell_decision_require_actual_physical_files(self):
        path = A + "authority_host_historical_cell_files.rs"
        for marker in ("self.inputs.journal.metadata()?.len() != 0",
                       "observe_original_file_anchor_v1(", "observed.is_some()"):
            self.reject(path, "fn require_original_cell_baseline(", marker)
        for marker in ("require_target(target, definition, source)?",
                       "observe_original_guarded_cell_v1(", ".require_decision(&observed.decision)",
                       "observed.snapshot.revision != 1",
                       "observed.decision.checkpoint_after != publication.checkpoint_digest()"):
            self.reject(path, "fn read_original_cell_data(", marker)
        self.reject(path, "fn observe_original_cell(", "before != after || physical != after")

    def test_cell_capture_retains_actual_original_identity_and_entire_context(self):
        path = A + "authority_host_historical_cell_pin.rs"
        for marker in ("original_root()?", "RootDataRefusalV1::inspect(&original.refusal, || {",
                       "original.baseline.phase != CellPhase::Enrolled",
                       "action(Some(&mut pending))?", "!= captured"):
            self.reject(path, "fn with_original_cell_capture<T>(", marker)
        for marker in ("baseline.identity != slot.profile.identity",
                       "retained.expected.pin.publisher != baseline.publisher",
                       "NeuronGenerationCurrentOwnerV1::open(",
                       "original.files.observe_original_cell(",
                       ".compare_and_set(&original.owner, baseline, &next)",
                       "self.captured = Some(next)"):
            self.reject(path, "fn observe_and_retain_original_cell(", marker)

    def test_cell_registration_keeps_durable_arm_and_original_deadline(self):
        path = A + "authority_host_historical_cell_registration.rs"
        for marker in ("RootDataRefusalV1::create_fresh(", "RootDataKind::CellSnapshot",
                       "self.with_initial_publication_context(",
                       "slot.mode != RootGenerationInitialModeV1::Reserve",
                       "slot.profile.writer != proof"):
            self.reject(path, "fn register_original_initial_cell(", marker)
        for occurrence in (0, 1):
            self.reject(path, "fn register_original_initial_cell(",
                        "std::time::Instant::now() >= end", occurrence)
            self.reject(path, "fn register_original_initial_cell(",
                        "files.require_original_cell_baseline()?", occurrence)

    def test_initial_ack_and_post_drain_consume_keep_original_custody(self):
        self.reject(A + "authority_host_generation_initial_runtime.rs", "fn serve_optional(",
                    ".register_original_source_cell(context)")
        self.reject(A + "authority_host_historical_cell_session.rs",
                    "fn take_original_source_cell(", "self.close()")
        self.reject(A + "authority_host_historical_source_deployment.rs",
                    "fn enable_initial_source_capture_from_deployment(",
                    "self.install_initial_source_cell(cell)?")

    def test_primary_io_cannot_escape_the_cell_refusal_arm(self):
        self.mutate(A + "authority_host_historical_cell_pin.rs", lambda s: s.replace(
            "        RootDataRefusalV1::inspect(&original.refusal, || {",
            "        original.store.load(&original.owner)?;\n"
            "        RootDataRefusalV1::inspect(&original.refusal, || {", 1))
        self.mutate(A + "authority_host_historical_cell_registration.rs", lambda s: s.replace(
            "        let (refusal, ()) = RootDataRefusalV1::create_fresh(",
            "        files.require_original_cell_baseline()?;\n"
            "        let (refusal, ()) = RootDataRefusalV1::create_fresh(", 1))

    def test_unknown_product_caller_cannot_borrow_the_physical_reader(self):
        boundary = next(b for b in PROOF._boundary_rows(self.manifest)
                        if b.identifier == "cell_original_physical_cut")
        index = {p: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / p).read_text())) for p in boundary.product_callers}
        ignored = tuple(self.manifest["ignored_path_fragments"])
        PROOF._verify_boundary(ROOT, boundary, index, ignored)
        index["codex-rs/hepta-agentd/src/unregistered_physical_reader.rs"] = (
            "fn product() { observe_original_guarded_cell_v1(peer_files); }")
        with self.assertRaises(PROOF.VerificationFailure):
            PROOF._verify_boundary(ROOT, boundary, index, ignored)

if __name__ == "__main__":
    unittest.main()

