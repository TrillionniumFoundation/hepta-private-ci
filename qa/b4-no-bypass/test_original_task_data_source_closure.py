"""Canonical data remains data; only an actual same-Root receipt holds a Task.

These are source mutations, not Root/session or native execution positives.
Trace/dispatch bytes remain whole-publication commitments; these tests do not
pretend to reconstruct their typed authority or grant a Dataset from raw JSON.
"""

from dataclasses import replace
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_historical_task_read_source_closure as route

ROOT = route.ROOT
PROOF = route.PROOF
A = route.A
DATA = A + "circuit_task_source_data.rs"
DECISION = A + "circuit_task_source_data_decision.rs"
TASK = A + "cell_q24_dataset_historical_task.rs"
MATERIALIZER = A + "cell_q24_dataset_materializer.rs"
CLIENT = route.CLIENT
ROOT_TASK = A + "authority_host_historical_task.rs"
DERIVE = A + "authority_host_post_a_derive.rs"
CALLERS = {
    "original_task_data_observation": (ROOT_TASK,),
    "original_task_data_validate": (ROOT_TASK, route.PROTOCOL, CLIENT, DERIVE),
    "original_task_data_decode": (),
    "original_task_data_decision": (DATA,),
    "root_historical_task_publication_data": (route.PROVIDER, DERIVE),
    "root_historical_task_publication_read": (TASK,),
    "cell_q24_historical_dataset_task_capture": (),
    "cell_q24_historical_dataset_task_receipt": (),
}


def require_structure(path, source):
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    if path == DATA:
        purpose = re.search(r'const PURPOSE: &str = "runtime\.learning\.'
                            r'historical-task-publication-data\.v1";', source)
        if (purpose is None or code[purpose.start():purpose.end()]
                != PROOF._strip_rust_non_code(purpose.group())
                or "const DATA_BOUND: usize = 16_384;" not in code):
            raise PROOF.VerificationFailure("original data purpose and bound must be actual code")
        if not re.search(r"#\[serde\(deny_unknown_fields\)\]\s*pub\(crate\) struct "
                         r"RootHistoricalTaskPublicationDataV1\b", code):
            raise PROOF.VerificationFailure("actual raw data must reject unknown fields")
        start = code.index("struct RootHistoricalTaskPublicationDataV1 {")
        end = PROOF._rust_item_end(code, start)
        if re.search(r"\bpub\b", code[start:end + 1]):
            raise PROOF.VerificationFailure("raw data fields must remain private")
        if re.search(r"\bpub(?:\([^)]*\))?\s+fn decode_data\(", code):
            raise PROOF.VerificationFailure("raw decoder is not a capability constructor")
        # Keep exact purpose/domain/prefix literals at the actual code spans.
        for name, literal in (
            ("decode_data", 'b"HCSTREQ1"'),
            ("decode_data", 'b"HCSTRES1"'),
            ("decode_data", 'b"hepta.circuit.original-source-publication.v1\\0"'),
            ("validate_against", 'b"hepta.root.original-ledger-cell-decision.v1\\0"'),
        ):
            body, raw = route.function(source, "fn " + name + "(")
            matches = list(re.finditer(re.escape(literal), raw))
            if len(matches) != 1:
                raise PROOF.VerificationFailure("one original commitment domain required")
            match = matches[0]
            # A quoted marker inside a comment is not an actual literal.
            prefix = re.search(r"(?:Reader::new\(\s*&(?:request|result)_bytes,|"
                               r"Digest32::of_parts\(\s*&\[)\s*$", raw[:match.start()])
            if (body[match.start():match.end()] != PROOF._strip_rust_non_code(literal)
                    or prefix is None
                    or body[prefix.start():prefix.end()] != prefix.group()):
                raise PROOF.VerificationFailure("original domain must bind the actual decoder/hash")
    if path == DECISION:
        body, raw = route.function(source, "fn decode_original_decision(")
        marker = '.strip_prefix(b"hepta.circuit.committed-cell-decision.v1\\0")'
        matches = list(re.finditer(re.escape(marker), raw))
        if len(matches) != 1 or body[matches[0].start():matches[0].end()] != PROOF._strip_rust_non_code(marker):
            raise PROOF.VerificationFailure("only the original committed decision codec is data")
    if path == MATERIALIZER:
        body, _ = route.function(source, "fn read_for_historical_receipt(")
        if re.search(r"\bOk\s*\(|\bself\s*\.\s*read\s*\(", body):
            raise PROOF.VerificationFailure("ordinary Task cannot impersonate a historical receipt")
    if path == TASK:
        start = code.index("struct HistoricalTaskSource {")
        end = PROOF._rust_item_end(code, start)
        if re.search(r"\bpub\b", code[start:end + 1]):
            raise PROOF.VerificationFailure("historical Task must retain its private actual receipt")
        body, _ = route.function(source, "fn capture_historical(")
        signature = body[:body.index("{")]
        for forbidden in ("RootHistoricalTaskPublicationDataV1", "CellDecisionReceiptV1",
                          "CircuitTaskSourcePublicationV1", "Digest32", "bool"):
            if forbidden in signature:
                raise PROOF.VerificationFailure("caller-authored task data cannot form this capability")


class OriginalTaskDataSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {r.identifier: r for r in PROOF._boundary_rows(cls.manifest)}
        paths = {DATA, DECISION, TASK, MATERIALIZER, CLIENT, ROOT_TASK,
                 route.PROTOCOL, route.PROVIDER, DERIVE}
        cls.sources = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text()))
            for path in paths
        }

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
                require_structure(path, text)

            verify(source)
            changed = change(source)
            self.assertNotEqual(changed, source)
            with self.assertRaises(PROOF.VerificationFailure):
                verify(changed)

    def reject(self, path, name, marker, occurrence=0):
        def change(source):
            key = "fn " + name + "("
            body, _ = route.function(source, key)
            matches = list(re.finditer(route.token_pattern(marker), body))
            self.assertGreater(len(matches), occurrence, (name, marker))
            match = matches[occurrence]
            full = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
            start = full.index(key)
            lo, hi = start + match.start(), start + match.end()
            return source[:lo] + "/* " + source[lo:hi] + " */" + source[hi:]
        self.mutate(path, change)

    def check(self, path, name, markers):
        for marker in markers:
            with self.subTest(function=name, marker=marker):
                self.reject(path, name, marker)

    def test_real_projection_read_and_unconnected_constructors_have_exact_callers(self):
        for identifier, callers in CALLERS.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, self.sources, ())

    def test_a_raw_decoder_or_publication_cannot_supply_an_unregistered_capability(self):
        for identifier in CALLERS:
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                method = row.symbol.rsplit("::", 1)[-1]
                call = (f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                        if row.receiver_type else f"fn bypass() {{ {method}(); }}")
                sources = dict(self.sources)
                sources[A + "unregistered_raw_task_cap.rs"] = call
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())
                if row.product_callers:
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=()), self.sources, ())

    def test_root_projection_requires_actual_source_full_cell_and_exact_roundtrip(self):
        self.check(DATA, "from_original_observation", (
            "publication.require_decision(cell)?", "publication.original_record()",
            "observed.original_source()", "request.validate_record(record, observed.original_fence().generation)?",
            "source_configuration: observed.binding_digest().to_string()",
            "request: STANDARD.encode(super::request(&request, record)?)",
            "result: STANDARD.encode(publication.result_bytes())",
            "publication: publication.publication_digest().to_string()",
            "data.decode_data()?", "decoded != (publication.clone(), cell.clone())",
        ))
        self.reject(ROOT_TASK, "publication_read_data", "self.publication.clone()")

    def test_request_and_input_canonical_checks_precede_data_construction(self):
        self.check(DATA, "decode_data", (
            "self.schema != 1", "self.purpose != PURPOSE", "json(self)?.len() > DATA_BOUND",
            "binding.is_zero()", "binding.to_string() != self.source_configuration",
            "bounded(&request_bytes)?", "bounded(&result_bytes)?",
            "STANDARD.encode(&request_bytes) != self.request", "STANDARD.encode(&result_bytes) != self.result",
            "original_record(&request_bytes)?", "request.validate_record(&record, record.snapshot.generation)?",
            "super::request(&request, &record)? != request_bytes", "decode_input(saved_input)?",
            "publication(&result_bytes, saved_input)?", "result.end()?",
            "input.scope != cell.scope", "input.operation_id != cell.operation_id",
            "input.source_frontier != cell.source_frontier", "input.scope.run_id != record.snapshot.run_id",
            "input.objective_digest != request.objective_digest",
            "request.start.scope_digest != circuit_cell_scope_digest_v1(&input.scope)?",
            "request.start.input_digest != Sha256Digest::for_bytes(&input.observation)",
            "output != crate::circuit_cell_output::encode_output(&cell)?",
            "publication_digest.to_string() != self.publication", "publication.require_decision(&cell)?",
        ))

    def test_commitment_includes_exact_original_result_and_uses_actual_domains(self):
        for marker in ("binding.as_array()", "&request_bytes,", "saved_input,", "&result_bytes,"):
            self.reject(DATA, "decode_data", marker)
        for literal in ('b"HCSTREQ1"', 'b"HCSTRES1"',
                        'b"hepta.circuit.original-source-publication.v1\\0"',
                        'b"hepta.root.original-ledger-cell-decision.v1\\0"'):
            with self.subTest(literal=literal):
                self.mutate(DATA, lambda source: source.replace(literal, 'b"wrong" /* ' + literal + ' */', 1))

    def test_complete_ledger_scope_source_and_cell_cut_must_all_match(self):
        self.check(DATA, "validate_against", (
            "ledger.validate_data()", "self.decode_data()?",
            "crate::circuit_cell_output::encode_receipt(&cell)?",
            "&cell.representation.drive_q24", "&cell.representation.prediction_q24",
            "self.source_configuration != ledger.source.configuration",
            "self.publication != ledger.source.publication", "self.publication != ledger.cut.source_publication",
            "publication.history_digest().as_str() != ledger.source.completed_task",
            "decision.to_string() != ledger.cut.cell_decision", "input.scope.agent_id.as_str() != scope.agent_id",
            "input.scope.cell_id.as_str() != scope.cell_id", "input.scope.run_id.as_str() != scope.run_id",
            "input.scope.principal_digest.into_array() != scope.principal_digest",
            "input.source_frontier.into_array() != ledger.target.source_frontier()",
            "input.objective_digest.to_string() != ledger.trust.objective",
        ))

    def test_cell_decoder_refuses_unknown_bits_trailing_data_and_authority(self):
        self.check(DECISION, "decode_original_decision", (
            "bounded(bytes)?", "bounded(representation)?", "if !(1..=256).contains(&count)",
            "consumed_input_bytes: u64::from_be_bytes(r.take()?).try_into()",
            "truncated_input_bytes: u64::from_be_bytes(r.take()?).try_into()",
            "if r.take::<1>()? != [0]", "r.end()?",
            "json(&(&drive_q24, &prediction_q24))? != representation", "channels.validate()",
            "authority: AuthorityPosture::DENY_ALL",
            "crate::circuit_cell_output::encode_receipt(&receipt)? != bytes",
        ))
        for occurrence in (0, 1):
            self.reject(DECISION, "decode_original_decision", "_ => return Err(Error::InvalidBinding)", occurrence)

    def test_task_capture_holds_same_opaque_receipt_and_queries_current_root(self):
        self.check(TASK, "capture_historical", (
            "receipt: Arc<OriginalHistoricalTaskReadReceiptV1>",
            "client: &Arc<RootHistoricalTaskReadClientV1>", "session: &AgentdRootAuthoritySession",
            "receipt.require_original_client(client, session)", "receipt.read_original_publication()",
            "Arc::new(HistoricalTaskSource { receipt })", "source.read()? != publication",
            "source.receipt.require_original_client(client, session)",
        ))
        self.reject(TASK, "read", "self.receipt.read_original_publication()")
        self.reject(TASK, "read_for_historical_receipt", "!Arc::ptr_eq(&self.receipt, receipt)")
        self.reject(TASK, "read_for_historical_receipt", "self.read()")
        self.reject(TASK, "require_historical_receipt", "self.source.read_for_historical_receipt(receipt)? != self.publication")
        self.mutate(TASK, lambda source: source.replace(
            "    receipt: Arc<OriginalHistoricalTaskReadReceiptV1>,",
            "    pub(crate) receipt: Arc<OriginalHistoricalTaskReadReceiptV1>,", 1))
        self.mutate(TASK, lambda source: source.replace(
            "        session: &AgentdRootAuthoritySession,",
            "        session: &AgentdRootAuthoritySession,\n        raw: Digest32,", 1))

    def test_original_task_default_and_same_root_publication_reader_cannot_fall_back(self):
        self.reject(MATERIALIZER, "read_for_historical_receipt", "Err(Error::Binding(")
        self.mutate(MATERIALIZER, lambda source: source.replace(
            '        Err(Error::Binding(\n            "task is not held',
            '        return self.read();\n        Err(Error::Binding(\n            "task is not held', 1))
        self.check(CLIENT, "read_original_publication", (
            "self.client.observe()?", "observed != self.data",
            "observed.publication.validate_against(&observed.ledger)", "self.client.fence()",
        ))

    def test_data_and_consumer_modules_cannot_open_files_or_construct_authority(self):
        for path in (DATA, DECISION, TASK):
            for forbidden in ("File::open(path)", "OpenOptions::new()", "std::fs::read(path)",
                              "RootAuthorityDirectory::open(path)", "CellGenerationCurrentV1::new()",
                              "SigningKey::from_bytes(bytes)", "ActivatedLearningTrustV1::new()",
                              "CircuitCommittedTraceV2 {}", "CircuitReceiptV2 {}"):
                with self.subTest(path=path, forbidden=forbidden):
                    self.mutate(path, lambda source: source + "\nfn forbidden_consumer() { " + forbidden + "; }\n")

    def test_raw_data_visibility_and_comment_nested_or_test_surrogates_do_not_supply_guards(self):
        self.mutate(DATA, lambda source: source.replace(
            '"runtime.learning.historical-task-publication-data.v1"',
            '"wrong" /* "runtime.learning.historical-task-publication-data.v1" */', 1))
        self.mutate(DATA, lambda source: source.replace(
            "const DATA_BOUND: usize = 16_384;",
            "const DATA_BOUND: usize = 32_768; /* DATA_BOUND: usize = 16_384 */", 1))
        self.mutate(DECISION, lambda source: source.replace(
            'b"hepta.circuit.committed-cell-decision.v1\\0"',
            'b"wrong" /* .strip_prefix(b"hepta.circuit.committed-cell-decision.v1\\0") */', 1))
        self.mutate(DATA, lambda source: source.replace(
            "#[serde(deny_unknown_fields)]", "/* #[serde(deny_unknown_fields)] */", 1))
        self.mutate(DATA, lambda source: source.replace("    request: String,", "    pub request: String,", 1))
        self.mutate(DATA, lambda source: source.replace("    fn decode_data(", "    pub(crate) fn decode_data(", 1))
        for template in ("/* {marker} */", "fn false_guard() {{ {marker}; }}",
                         "#[cfg(test)] fn false_guard() {{ {marker}; }}"):
            with self.subTest(template=template):
                marker = "publication.require_decision(&cell)?"
                self.mutate(DATA, lambda source: source.replace(marker, template.format(marker=marker), 1))


if __name__ == "__main__":
    unittest.main()
