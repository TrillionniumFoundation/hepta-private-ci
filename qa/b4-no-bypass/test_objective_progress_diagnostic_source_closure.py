"""Keep phase diagnostics outside the original admission, time and error decisions."""

from copy import deepcopy
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
AGENT = "codex-rs/hepta-agentd/src/"
CIRCUIT = AGENT + "state_circuit_task.rs"
PROGRESS = AGENT + "state_q24_outcome.rs"
CONTROL = AGENT + "control.rs"
SPEC = importlib.util.spec_from_file_location("objective_progress_diagnostic_proof", ROOT / "scripts/verify_hepta_callers.py")
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)


class ObjectiveProgressDiagnosticSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        self.rows = [r for r in manifest["protected_file"] if r["path"] in (CIRCUIT, PROGRESS, CONTROL)]
        self.assertEqual(len(self.rows), 6)
        self.original = {p: (ROOT / p).read_text() for p in (CIRCUIT, PROGRESS, CONTROL)}
        for p, source in self.original.items():
            target = self.root / p
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source)
        self.verify()

    def code(self, source):
        return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))

    def function(self, source, marker):
        code = self.code(source)
        self.assertEqual(code.count(marker), 1)
        start = code.index(marker)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        return start, end + 1, code[start:end + 1]

    def compact(self, text):
        return re.sub(r"\s+", "", text)

    def remove_one(self, source, pattern, replacement=""):
        matches = list(re.finditer(pattern, source))
        self.assertEqual(len(matches), 1, pattern)
        m = matches[0]
        return source[:m.start()] + replacement + source[m.end():]

    def normalize_diagnostics(self, path, source):
        suffix = {CIRCUIT: "circuit", PROGRESS: "progress", CONTROL: "control"}[path]
        marker = "fn trace_original_" + suffix + "_phase("
        start, end, helper = self.function(source, marker)
        line = self.code(source).rfind("\n", 0, start) + 1
        self.assertEqual(self.code(source)[line:start].strip(), "", "diagnostics remain private")
        arguments = {
            CIRCUIT: "started:std::time::Instant,phase:&'staticstr",
            PROGRESS: "started:std::time::Instant,phase:&'staticstr,pending:Option<usize>,",
            CONTROL: "started:std::time::Instant,method:Option<&'staticstr>,request_id:u64,phase:&'staticstr,",
        }[path]
        prefix = "fntrace_original_" + suffix + "_phase(" + arguments + "){usestd::io::Write;"
        if path == CONTROL:
            prefix += "letSome(method)=methodelse{return;};"
        expected = prefix + "let_=writeln!(std::io::stderr().lock(),,started.elapsed().as_micros(),);}"
        self.assertEqual(self.compact(helper), expected)
        source = source[:line] + source[end:]
        if path == CIRCUIT:
            call = r'trace_original_circuit_phase\(\s*original_started,\s*"[a-z-]+"\s*\);'
        elif path == PROGRESS:
            call = r'trace_original_progress_phase\(\s*original_started,\s*"[a-z-]+",\s*(?:None|Some\(original_pending\))\s*\);'
        else:
            call = r'trace_original_control_phase\(\s*original_started,\s*original_method,\s*original_request_id,\s*(?:"[a-z-]+"|phase)\s*,?\s*\);'
        self.assertGreater(len(re.findall(call, source)), 0)
        source = re.sub(call, "", source)
        self.assertNotRegex(self.code(source), r"\btrace_original_(?:circuit|progress|control)_phase\b")
        source = self.remove_one(source, r"let\s+original_started\s*=\s*std::time::Instant::now\(\);", "")
        self.assertNotRegex(self.code(source), r"\boriginal_started\b")
        if path == PROGRESS:
            source = self.remove_one(source, r"let\s+original_pending\s*=\s*self.circuit_task_pending_count\(\);", "")
            source = self.remove_one(source, r"let\s+observed\s*=\s*if\s+original_pending\s*!=\s*0", "let observed = if self.circuit_task_pending_count() != 0")
            self.assertNotRegex(self.code(source), r"\boriginal_pending\b|\bInstant\b|\bSystemTime\b")
        if path == CONTROL:
            code = self.code(source)
            start = code.index("let original_request_id = request.request_id;")
            end = code.index("let circuit_admission =", start)
            classification = source[start:end]
            expected_classification = '''let original_request_id = request.request_id;
                let original_method = match &request.method {
                    crate::AgentdMethod::ObjectiveStart { .. } => Some("objective_start"),
                    crate::AgentdMethod::Q24OriginalInitialTaskProgress { .. } => { Some("initial_task_progress") }
                    _ => None,
                };'''
            self.assertEqual(self.compact(classification), self.compact(expected_classification))
            source = source[:start] + source[end:]
            pattern = r'result\s*=>\s*\{\s*let\s+phase\s*=\s*if\s+result.is_ok\(\)\s*\{\s*"write-completed"\s*\}\s*else\s*\{\s*"write-failed"\s*\};\s*result\s*\}'
            source = self.remove_one(source, pattern, "result => result")
            self.assertNotRegex(self.code(source), r"\boriginal_method\b|\boriginal_request_id\b")
        return source

    def legacy_rows(self):
        rows = deepcopy(self.rows)
        for row in rows:
            if row["path"] == PROGRESS and "SystemTime::now" in row.get("forbidden", []):
                self.assertNotIn("Instant::now", row["forbidden"])
                row["forbidden"].append("Instant::now")
            for order in row.get("required_function_order", []):
                if row["path"] == CONTROL and order["function"] == "fn serve_connection(":
                    tail = ["result => {", "let phase = if result.is_ok()", "trace_original_control_phase(", "result\n"]
                    self.assertEqual(order["sequence"][-4:], tail)
                    order["sequence"][-4:] = ["result => result"]
                if row["path"] == PROGRESS and order["function"] == "fn read_original_q24_initial_task_progress(":
                    self.assertEqual(order["sequence"][0], "let original_started = std::time::Instant::now();")
                    order["sequence"].pop(0)
                    at = order["sequence"].index("let original_pending = self.circuit_task_pending_count();")
                    self.assertEqual(order["sequence"][at+1], "let observed = if original_pending != 0")
                    order["sequence"][at:at+2] = ["let observed = if self.circuit_task_pending_count() != 0"]
                    order["top_level"] = [
                        "self.require_original_q24_outcome_current()?;\n        let producer:",
                        "let (admission, record) =", "let observed = if self.circuit_task_pending_count() != 0",
                        "let after = crate::objective_runtime::ObjectiveRuntimeHost::read_original_initial_request(",
                        "self.require_original_q24_outcome_current()?;\n        if after",
                        "if after != (admission, record)", "\n        observed\n",
                    ]
        return rows

    def verify(self):
        PROOF._verify_protected_files(self.root, {"protected_file": self.rows})
        clean = {}
        for path in self.original:
            source = (self.root / path).read_text()
            clean[path] = self.normalize_diagnostics(path, source)
        progress = self.code((self.root / PROGRESS).read_text())
        _, _, body = self.function(progress, "fn read_original_q24_initial_task_progress(")
        checks = list(re.finditer(re.escape("self.require_original_q24_outcome_current()?;"), body))
        self.assertEqual(len(checks), 2)
        for check in checks:
            prefix = body[:check.start()]
            self.assertEqual(prefix.count("{")-prefix.count("}"), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path, source in clean.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                # Removing logging leaves blank lines, not new business tokens.
                source = re.sub(r"\n(?:[ \t]*\n)+", "\n", source)
                target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": self.legacy_rows()})

    def reject(self, path, old, new, occurrence=0):
        source = self.original[path]
        start = -1
        for _ in range(occurrence+1):
            start = source.index(old, start+1)
        changed = source[:start] + new + source[start+len(old):]
        self.assertNotEqual(changed, source)
        target = self.root / path
        try:
            target.write_text(changed)
            with self.assertRaises((PROOF.VerificationFailure, AssertionError, ValueError)):
                self.verify()
        finally:
            target.write_text(source)

    def test_diagnostic_clock_cannot_supply_business_time_or_authority(self):
        self.reject(PROGRESS, "fn trace_original_progress_phase(", "pub(crate) fn trace_original_progress_phase(")
        self.reject(PROGRESS, "let original_started = std::time::Instant::now();", "let original_started = std::time::Instant::now(); let deadline = original_started;")
        self.reject(PROGRESS, "let observed = if original_pending != 0", "let forged = std::time::Instant::now(); let observed = if original_pending != 0")
        self.reject(PROGRESS, "started.elapsed().as_micros()", "0")

    def test_original_pending_sample_and_both_current_checks_remain(self):
        self.reject(PROGRESS, "let original_pending = self.circuit_task_pending_count();", "let original_pending = 0;")
        self.reject(PROGRESS, "|| self.circuit_task_pending_count() != 0", "")
        for occurrence in (0, 1):
            old = "self.require_original_q24_outcome_current()?;"
            self.reject(PROGRESS, old, "if true { " + old + " }", occurrence)
            self.reject(PROGRESS, old, "", occurrence)

    def test_control_uses_real_request_id_and_returns_original_write_result(self):
        self.reject(CONTROL, "let original_request_id = request.request_id;", "let original_request_id = 0;")
        self.reject(CONTROL, "let phase = if result.is_ok()", "let phase = if true")
        self.reject(CONTROL, "                result\n", "                Ok(())\n")
        self.reject(CONTROL, "if completed_circuit", "if true")


if __name__ == "__main__":
    unittest.main()
