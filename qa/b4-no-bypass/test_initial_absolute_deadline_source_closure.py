"""Protect the original absolute deadline through Initial file/peer checks."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "initial_deadline_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"


class InitialAbsoluteDeadlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def reject(self, filename, function, marker, occurrence=0, replacement=None):
        path = AGENT + filename
        source = (ROOT / path).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offset = start
        for _ in range(occurrence + 1):
            offset = source.index(marker, offset, end + 1) + len(marker)
        offset -= len(marker)
        replacement = replacement if replacement is not None else "/* " + marker + " */"
        changed = source[:offset] + replacement + source[offset + len(marker):]
        rows = [r for r in self.manifest["protected_file"] if r["path"] == path]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_duration_entry_converts_once_before_any_original_io(self):
        self.reject("root_generation_initial_inputs.rs", "fn connect(",
                    ".checked_add(lifetime)")
        self.reject("root_generation_initial_inputs.rs", "fn connect(",
                    "self.connect_until(connection, timeout, end).await")
        self.reject("root_generation_publication_stream.rs", "fn from_stream(",
                    "Self::from_stream_until(stream, root, peer, timeout, end)")

    def test_initial_file_connect_and_worker_keep_same_absolute_end(self):
        filename = "root_generation_initial_inputs.rs"
        function = "fn connect_original_until("
        for occurrence in (0, 1, 2, 3):
            self.reject(filename, function, "remaining_until(end)?", occurrence)
        self.reject(filename, function, "OriginalPublicationStream::from_stream_until(")
        self.reject(filename, function, "timeout,\n            end,")

    def test_peer_checks_consume_budget_without_rebasing_the_stream(self):
        filename = "root_generation_publication_stream.rs"
        function = "fn from_stream_until("
        for marker in (".checked_duration_since(Instant::now())",
                       "remaining > Duration::from_secs(300)", "libc::SO_PEERCRED",
                       "actual.uid != 0", "check_lifetime(&root)", "Instant::now() >= end"):
            self.reject(filename, function, marker)
        self.reject(filename, function, "            end,",
                    replacement="            end: Instant::now() + remaining,")

    def test_generic_framing_keeps_original_hup_and_frame_rejection(self):
        filename = "root_generation_publication_stream.rs"
        self.reject(filename, "fn wait(",
                    "libc::POLLERR | libc::POLLHUP | libc::POLLNVAL")
        self.reject(filename, "fn wait(", "fds[0].revents != 0")
        self.reject(filename, "fn exchange(", "size > 16_384")

    def test_new_constructors_have_exact_actual_callers(self):
        boundaries = {r["id"]: r for r in self.manifest["boundary"]}
        self.assertEqual(boundaries["root_initial_original_connection_until"]["product_callers"], [])
        self.assertEqual(boundaries["root_initial_ready_connection"]["product_callers"],
                         [AGENT + "production_initial_q24.rs"])
        self.assertEqual(boundaries["root_original_publication_stream_until"]["product_callers"],
                         [AGENT + "root_generation_initial_inputs.rs",
                          AGENT + "root_historical_task_read_inputs.rs",
                          AGENT + "root_generation_publication_inputs.rs"])


if __name__ == "__main__":
    unittest.main()
