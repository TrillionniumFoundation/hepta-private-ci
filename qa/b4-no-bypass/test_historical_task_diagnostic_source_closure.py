"""Keep complete-task diagnostics closed and outside original read authority.

These mutations exercise source guards only; they do not grant native use.
"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_initial_absolute_deadline_source_closure as original

ROOT = original.ROOT
PROOF = original.PROOF
A = original.AGENT
TASK = A + "authority_host_historical_task.rs"
HELPER = A + "authority_host_historical_task_diagnostics.rs"
BOUNDARY = "root_historical_fixed_stage_diagnostic"
SYMBOL = "log_historical_task_diagnostic"
STAGE = "HistoricalTaskDiagnosticStage"

# Reviewed production shape, fixed here rather than obtained from the input.
EXPECTED_HELPER = r"""//! Fixed, value-free error stages for the complete historical task reader.
//! The private parent module is the only caller; no task or error data is accepted.

pub(super) enum HistoricalTaskDiagnosticStage {
    RecipientAction,
    Ledger,
    RunStart,
    SourceCell,
    Handoff,
    SourceObservation,
    RunStartPublisher,
    RunStartDeployment,
    RunStartObservation,
    LedgerObservation,
    RunStartDigest,
    LedgerDigest,
    PublicationProjection,
    PublicationValidation,
}

pub(super) fn log_historical_task_diagnostic(stage: HistoricalTaskDiagnosticStage) {
    let bytes: &[u8] = match stage {
        HistoricalTaskDiagnosticStage::RecipientAction => {
            b"root_stage=historical_task.recipient_action\n"
        }
        HistoricalTaskDiagnosticStage::Ledger => b"root_stage=historical_task.ledger\n",
        HistoricalTaskDiagnosticStage::RunStart => b"root_stage=historical_task.run_start\n",
        HistoricalTaskDiagnosticStage::SourceCell => b"root_stage=historical_task.source_cell\n",
        HistoricalTaskDiagnosticStage::Handoff => b"root_stage=historical_task.handoff\n",
        HistoricalTaskDiagnosticStage::SourceObservation => {
            b"root_stage=historical_task.source_observation\n"
        }
        HistoricalTaskDiagnosticStage::RunStartPublisher => {
            b"root_stage=historical_task.run_start_publisher\n"
        }
        HistoricalTaskDiagnosticStage::RunStartDeployment => {
            b"root_stage=historical_task.run_start_deployment\n"
        }
        HistoricalTaskDiagnosticStage::RunStartObservation => {
            b"root_stage=historical_task.run_start_observation\n"
        }
        HistoricalTaskDiagnosticStage::LedgerObservation => {
            b"root_stage=historical_task.ledger_observation\n"
        }
        HistoricalTaskDiagnosticStage::RunStartDigest => {
            b"root_stage=historical_task.run_start_digest\n"
        }
        HistoricalTaskDiagnosticStage::LedgerDigest => {
            b"root_stage=historical_task.ledger_digest\n"
        }
        HistoricalTaskDiagnosticStage::PublicationProjection => {
            b"root_stage=historical_task.publication_projection\n"
        }
        HistoricalTaskDiagnosticStage::PublicationValidation => {
            b"root_stage=historical_task.publication_validation\n"
        }
    };
    let _ = std::io::Write::write_all(&mut std::io::stderr(), bytes);
}
"""
LABELS = (
    "recipient_action", "ledger", "run_start", "source_cell", "handoff",
    "source_observation", "run_start_publisher", "run_start_deployment",
    "run_start_observation", "ledger_observation", "run_start_digest",
    "ledger_digest", "publication_projection", "publication_validation",
)
CALLS = {
    "fn with_original_historical_task<T>(": (
        "RecipientAction", "Ledger", "RunStart", "SourceCell", "Handoff",
    ),
    "fn observe_original_task(": (
        "SourceObservation", "RunStartPublisher", "RunStartDeployment",
        "RunStartObservation", "LedgerObservation", "RunStartDigest",
        "LedgerDigest", "PublicationProjection", "PublicationValidation",
    ),
}
HEADER = r"""use crate::circuit_task::RootHistoricalTaskPublicationDataV1;

#[path = "authority_host_historical_task_diagnostics.rs"]
mod diagnostics;

use diagnostics::HistoricalTaskDiagnosticStage;
use diagnostics::log_historical_task_diagnostic;

pub(crate) struct RootRetainedHistoricalCompleteTaskV1 {"""
READER_FORBIDDEN = (
    "Option<", "SigningKey", "create_fresh(", "initialize(",
    "compare_and_set(", "write_all(", "OpenOptions", "try_clone(",
    "Duration::", "pub cut:", "pub ledger:", "Deserialize", "Serialize",
)
TOKEN = re.compile(r"[A-Za-z_]\w*|\d+|::|->|=>|!=|==|&&|\|\||\.\.|[^\s]")
OBSERVER = re.compile(
    r"\.\s*inspect_err\s*\(\s*\|\s*_\s*\|\s*\{\s*"
    r"log_historical_task_diagnostic\s*\(\s*"
    r"HistoricalTaskDiagnosticStage\s*::\s*(\w+)\s*,?\s*\)\s*;\s*\}\s*\)"
)


def require(condition, message):
    if not condition:
        raise PROOF.VerificationFailure(message)


def tokens(text):
    return TOKEN.findall(text)


def pattern(text):
    return r"\s*".join(map(re.escape, tokens(text)))


def compact(text):
    return re.sub(r"\s+", "", text)


def require_fixed_helper(source):
    code = PROOF._strip_rust_non_code(source)
    expected_code = PROOF._strip_rust_non_code(EXPECTED_HELPER)
    require(tokens(code) == tokens(expected_code), "diagnostic executable shape changed")
    # This local complete template also disallows extra literals or comment copies.
    require(compact(source) == compact(EXPECTED_HELPER), "diagnostic complete template changed")
    positions = list(re.finditer(r"\bb\b", code))
    require(len(positions) == len(LABELS), "diagnostic literal count changed")
    for position, label in zip(positions, LABELS):
        literal = 'b"root_stage=historical_task.' + label + r'\n"'
        require(source.startswith(literal, position.start()), "diagnostic code literal changed")


def require_fixed_reader(source):
    code = PROOF._strip_rust_non_code(source)
    header = list(re.finditer(pattern(PROOF._strip_rust_non_code(HEADER)), code))
    require(len(header) == 1, "diagnostic private module and imports changed")
    header = header[0]
    raw_header = source[header.start():header.end()]
    require(compact(raw_header) == compact(HEADER), "diagnostic module path changed")
    require('"authority_host_historical_task_diagnostics.rs"' in raw_header,
            "diagnostic literal module path changed")
    residual = list(code)
    for index in range(header.start(), header.end()):
        residual[index] = " "
    observed_count = 0
    for marker, variants in CALLS.items():
        definitions = list(re.finditer(pattern(marker), code))
        require(len(definitions) == 1, "original diagnostic caller function changed")
        start = definitions[0].start()
        end = PROOF._rust_item_end(code, start)
        require(end is not None, "original diagnostic caller body missing")
        matches = list(OBSERVER.finditer(code, start, end + 1))
        require(tuple(match.group(1) for match in matches) == variants,
                "diagnostic original caller order or variant changed")
        observed_count += len(matches)
        for match in matches:
            for index in range(match.start(), match.end()):
                residual[index] = " "
    require(observed_count == 14, "diagnostic original call count changed")
    require(len(re.findall(r"\.\s*inspect_err\s*\(", code)) == 14,
            "diagnostic observer count changed")
    require(not re.search(r"\b(?:diagnostics|HistoricalTaskDiagnosticStage|"
                          r"log_historical_task_diagnostic)\b", "".join(residual)),
            "diagnostic alias, function pointer or extra caller")


class HistoricalTaskDiagnosticSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def setUp(self):
        self.sources = {path: (ROOT / path).read_text() for path in (TASK, HELPER)}
        self.rows = [row for row in self.manifest["protected_file"]
                     if row["path"] in (TASK, HELPER)]
        self.assertTrue(any(row["path"] == HELPER for row in self.rows))
        self.assertTrue(any(row["path"] == TASK
                            and tuple(row.get("forbidden", ())) == READER_FORBIDDEN
                            for row in self.rows))
        self.verify(self.sources)

    def verify(self, sources):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path, source in sources.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": self.rows})
        require_fixed_helper(sources[HELPER])
        require_fixed_reader(sources[TASK])

    def mutate(self, path, change, error=None):
        changed = dict(self.sources)
        changed[path] = change(changed[path])
        self.assertNotEqual(changed[path], self.sources[path])
        if error is None:
            with self.assertRaises(PROOF.VerificationFailure):
                self.verify(changed)
        else:
            with self.assertRaisesRegex(PROOF.VerificationFailure, error):
                self.verify(changed)

    def test_helper_is_the_reviewed_closed_shape(self):
        require_fixed_helper(self.sources[HELPER])
        require_fixed_reader(self.sources[TASK])

    def test_helper_cannot_change_sink_payload_tags_visibility_or_result(self):
        changes = (
            ("std::io::stderr()", "std::io::stdout()"),
            ("    RecipientAction,", "    RecipientAction(&'static [u8]),"),
            ("    RecipientAction,", "    RecipientAction,\n    Other,"),
            ("stage: HistoricalTaskDiagnosticStage)", "stage: HistoricalTaskDiagnosticStage, payload: &[u8])"),
            ('b"root_stage=historical_task.ledger\\n"', 'b"root_stage=historical_task.forged\\n"'),
            ("pub(super)", "pub(crate)"),
            ("let _ = std::io::Write::write_all(&mut std::io::stderr(), bytes);",
             "std::io::Write::write_all(&mut std::io::stderr(), bytes).unwrap();"),
        )
        for old, new in changes:
            with self.subTest(old=old):
                self.mutate(HELPER, lambda source, old=old, new=new: source.replace(old, new, 1))
        self.mutate(HELPER, lambda source: source + "\nfn extra_output() {}\n")

    def test_comment_and_string_copies_cannot_supply_executable_helper(self):
        self.mutate(HELPER, lambda source: "/*" + source + "*/\n")
        self.mutate(HELPER, lambda source: 'const SPOOF: &str = r###"' + source + '"###;\n')
        old = 'b"root_stage=historical_task.ledger\\n"'
        self.mutate(HELPER, lambda source: source.replace(old, 'b"forged" /* ' + old + " */", 1))

    def test_each_original_observer_is_required(self):
        for variants in CALLS.values():
            for variant in variants:
                with self.subTest(variant=variant):
                    def remove(source):
                        code = PROOF._strip_rust_non_code(source)
                        matches = [match for match in OBSERVER.finditer(code)
                                   if match.group(1) == variant]
                        self.assertEqual(len(matches), 1)
                        match = matches[0]
                        return source[:match.start()] + ".inspect_err(|_| {})" + source[match.end():]
                    self.mutate(TASK, remove)

    def test_reader_cannot_export_redirect_alias_or_add_diagnostic_calls(self):
        changes = (
            ("mod diagnostics;", "pub(crate) mod diagnostics;"),
            ('"authority_host_historical_task_diagnostics.rs"', '"different_diagnostics.rs"'),
            ("use diagnostics::log_historical_task_diagnostic;",
             "use diagnostics::log_historical_task_diagnostic as alias;"),
            ("HistoricalTaskDiagnosticStage::RecipientAction",
             "HistoricalTaskDiagnosticStage::Ledger"),
            ("HistoricalTaskDiagnosticStage::RecipientAction",
             'HistoricalTaskDiagnosticStage::RecipientAction, b"payload"'),
            ("HistoricalTaskDiagnosticStage::RecipientAction",
             "(HistoricalTaskDiagnosticStage::RecipientAction,)"),
        )
        for old, new in changes:
            with self.subTest(old=old):
                self.mutate(TASK, lambda source, old=old, new=new: source.replace(old, new, 1))
        extras = (
            "\nfn extra() { log_historical_task_diagnostic(HistoricalTaskDiagnosticStage::Ledger); }\n",
            "\nfn extra_pointer() -> fn(HistoricalTaskDiagnosticStage) { log_historical_task_diagnostic }\n",
        )
        for extra in extras:
            with self.subTest(extra=extra):
                self.mutate(TASK, lambda source, extra=extra: source + extra)
        for as_string in (False, True):
            with self.subTest(as_string=as_string):
                def spoof(source):
                    match = OBSERVER.search(PROOF._strip_rust_non_code(source))
                    self.assertIsNotNone(match)
                    old = source[match.start():match.end()]
                    fake = ('let _ = r###"' + old + '"###;') if as_string else "/*" + old + "*/"
                    return source[:match.start()] + ".inspect_err(|_| { " + fake + " })" + source[match.end():]
                self.mutate(TASK, spoof)

    def test_original_reader_write_ban_remains_effective(self):
        self.mutate(TASK, lambda source: source + (
            "\nfn forbidden_output() { "
            "let _ = std::io::Write::write_all(&mut std::io::stderr(), b\"forbidden\"); }\n"
        ), error="forbidden")

    def test_unique_caller_boundary_and_inventory_reject_all_extra_references(self):
        boundaries = PROOF._boundary_rows(self.manifest)
        row = next(row for row in boundaries if row.identifier == BOUNDARY)
        self.assertEqual(row.definition_path, HELPER)
        self.assertEqual(row.symbol, SYMBOL)
        self.assertEqual(row.call_pattern, r"\blog_historical_task_diagnostic\b")
        self.assertEqual(row.product_callers, (TASK,))
        self.assertFalse(row.receiver_type)
        PROOF._verify_privileged_inventory(self.manifest, boundaries)
        sources = {path: PROOF._strip_rust_non_code(source)
                   for path, source in self.sources.items()}
        PROOF._verify_boundary(ROOT, row, sources, ())
        extras = (
            "fn extra() { log_historical_task_diagnostic(HistoricalTaskDiagnosticStage::Ledger); }",
            "use crate::diagnostics::log_historical_task_diagnostic as hidden;",
            "fn extra() { let pointer = log_historical_task_diagnostic; }",
        )
        for extra in extras:
            with self.subTest(extra=extra):
                bypass = dict(sources)
                bypass[A + "unexpected_historical_diagnostic.rs"] = PROOF._strip_rust_non_code(extra)
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, bypass, ())
        with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
            PROOF._verify_boundary(ROOT, replace(row, product_callers=()), sources, ())
        for fake in ("// log_historical_task_diagnostic\n",
                     'const SPOOF: &str = "log_historical_task_diagnostic";'):
            with self.subTest(fake=fake):
                missing = dict(sources)
                missing[TASK] = PROOF._strip_rust_non_code(fake)
                with self.assertRaisesRegex(PROOF.VerificationFailure, "missing"):
                    PROOF._verify_boundary(ROOT, row, missing, ())
        missing = deepcopy(self.manifest)
        missing["privileged_inventory"]["required_boundary_ids"].remove(BOUNDARY)
        with self.assertRaisesRegex(PROOF.VerificationFailure, "inventory mismatch"):
            PROOF._verify_privileged_inventory(missing, boundaries)


if __name__ == "__main__":
    unittest.main()
