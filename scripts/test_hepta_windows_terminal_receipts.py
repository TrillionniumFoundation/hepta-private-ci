"""Synthetic controls for the actual workflow reader; never Windows qualification."""

import ast
import hashlib
import re
import unittest

from hepta_ci_exec import observed_test_counts
import test_hepta_windows_boundary_receipts as original


class TerminalReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = original.reader()
        tree = ast.parse(cls.source)
        assignments = {
            target.id: node
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        functions = {
            node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
        }
        selected = [
            assignments[name]
            for name in (
                "probes",
                "store_selectors",
                "required",
                "query_existing_selectors",
                "terminal_selectors",
            )
        ]
        selected += [
            functions[name]
            for name in ("extended_query_result", "terminal_receipt", "terminal_result")
        ]
        cls.namespace = {
            "re": re,
            "hashlib": hashlib,
            "observed_test_counts": observed_test_counts,
        }
        exec(
            compile(
                ast.Module(body=selected, type_ignores=[]),
                "workflow-terminal-reader",
                "exec",
            ),
            cls.namespace,
        )
        cls.cases = cls.namespace["terminal_selectors"]

    def fixture(self):
        raw = original.log(self.cases, skipped=200).encode()
        terminal = self.namespace["terminal_receipt"](raw, 3, 0, 0)
        logs = {
            name: ("actual retained log " + name).encode()
            for name in self.namespace["required"]
        }
        rows = {
            name: {
                "status": "passed",
                "returncode": 0,
                "logging_returncode": 0,
                "minimum_tests": 1,
                "observed_passed_tests": 1,
                "observed_failed_tests": 0,
                "log_sha256": hashlib.sha256(value).hexdigest(),
            }
            for name, value in logs.items()
        }
        old = {
            "status": "passed",
            "tests": rows,
            "source": {"scope": "synthetic parser only"},
        }
        query_raw = original.log(
            self.namespace["query_existing_selectors"], skipped=200
        ).encode()
        logs["query-existing-readback"] = query_raw
        query = {
            "schema": "hepta-windows-query-existing-receipt-v1",
            "status": "passed",
            "returncode": 0,
            "logging_returncode": 0,
            "minimum_tests": 6,
            "observed_passed_tests": 6,
            "observed_failed_tests": 0,
            "required_test_names": list(self.namespace["query_existing_selectors"]),
            "observed_passed_test_names": list(
                self.namespace["query_existing_selectors"]
            ),
            "log_sha256": hashlib.sha256(query_raw).hexdigest(),
        }
        v2 = self.namespace["extended_query_result"](old, query)
        v2["query_log_sha256_matches_receipt"] = True
        return [old, query, v2, terminal, raw, logs]

    def combine(self, values):
        return self.namespace["terminal_result"](*values)["status"]

    def test_three_names_match_actual_binary_source_and_original_command(self):
        path = (
            original.ROOT
            / "codex-rs/windows-sandbox-rs/src/bin/command_runner/win/process_observation_tests.rs"
        )
        names = re.findall(
            r"^#\[test\]\nfn ([a-z0-9_]+)\(", path.read_text(), re.MULTILINE
        )
        self.assertEqual(
            tuple("win::process_observation::tests::" + name for name in names),
            self.cases,
        )
        self.assertEqual(len(names), 3)
        workflow = original.WORKFLOW.read_text()
        command = "just test --locked -p codex-windows-sandbox --bin codex-command-runner -E 'test(/^win::process_observation::tests::/)' --test-threads 1 --no-capture"
        self.assertEqual(workflow.count(command), 1)
        self.assertLess(
            workflow.index("tests query-existing-readback 6"), workflow.index(command)
        )
        self.assertLess(
            workflow.index('save("result-v3.json", combined)'),
            workflow.index('assert extended["status"] != "failed"'),
        )
        self.assertIn(
            '("command-runner-terminal.json", "command-runner-terminal.log", "result-v3.json")',
            workflow,
        )
        self.assertEqual(self.combine(self.fixture()), "passed")

    def test_actual_nextest_ansi_indented_summary_passes_and_indented_duplicate_refuses(
        self,
    ):
        # Same horizontal prefix/ANSI layout as retained Windows witness.log, not a native run.
        for prefix in ("     ", "\t"):
            text = original.log(self.cases, skipped=200).replace(
                "Summary", "\x1b[32;1m" + prefix + "Summary\x1b[0m"
            )
            values = self.fixture()
            values[4] = text.encode()
            values[3] = self.namespace["terminal_receipt"](values[4], 3, 0, 0)
            self.assertEqual(self.combine(values), "passed")
            values[4] += text[text.index("\x1b[32;1m") :].encode()
            values[3] = self.namespace["terminal_receipt"](values[4], 3, 0, 0)
            self.assertEqual(self.combine(values), "failed")

    def test_terminal_missing_duplicate_unknown_failed_empty_and_multiple_summary_refuse(
        self,
    ):
        complete = original.log(self.cases, skipped=200)
        invalid = [
            original.log(self.cases[:-1], passed=3),
            original.log(("wrong::case",) + self.cases[1:]),
            complete + "test " + self.cases[0] + " ... ok\n",
            complete + complete,
            complete + "Summary broken\n",
            complete.replace("Summary", "Incomplete"),
            original.log(self.cases, failed=1),
            original.log(self.cases, passed=2),
            original.log(()),
        ]
        for raw in invalid:
            with self.subTest(raw=raw):
                value = self.fixture()
                value[4] = raw.encode()
                value[3] = self.namespace["terminal_receipt"](value[4], 3, 0, 0)
                self.assertEqual(self.combine(value), "failed")

    def test_terminal_codes_counts_types_schema_names_and_current_bytes_are_strict(
        self,
    ):
        for key, bad in (
            ("returncode", 1),
            ("logging_returncode", 1),
            ("returncode", False),
            ("logging_returncode", False),
            ("minimum_tests", 3.0),
            ("minimum_tests", True),
            ("observed_passed_tests", 0),
            ("observed_failed_tests", False),
            ("schema", "future"),
            ("log_sha256", "0" * 64),
            ("required_test_names", list(self.cases[:-1])),
            ("observed_passed_test_names", [self.cases[0]] * 3),
        ):
            with self.subTest(key=key, bad=bad):
                values = self.fixture()
                values[3][key] = bad
                self.assertEqual(self.combine(values), "failed")
        for index, bad in ((3, None), (3, []), (4, None), (4, b"changed")):
            values = self.fixture()
            values[index] = bad
            self.assertEqual(self.combine(values), "failed")
        for minimum, code, log_code in ((2, 0, 0), (3, 1, 0), (3, 0, 1), (3, False, 0)):
            values = self.fixture()
            values[3] = self.namespace["terminal_receipt"](
                values[4], minimum, code, log_code
            )
            self.assertEqual(self.combine(values), "failed")

    def test_every_original_twenty_and_query_receipt_remains_independently_required(
        self,
    ):
        self.assertEqual(len(self.namespace["required"]), 20)
        for name in self.namespace["required"]:
            for mode in ("missing", "failed", "code", "bool", "raw"):
                with self.subTest(name=name, mode=mode):
                    values = self.fixture()
                    if mode == "missing":
                        del values[0]["tests"][name]
                    elif mode == "failed":
                        values[0]["tests"][name]["status"] = "failed"
                    elif mode == "code":
                        values[0]["tests"][name]["returncode"] = 1
                    elif mode == "bool":
                        values[0]["tests"][name]["logging_returncode"] = False
                    else:
                        del values[5][name]
                    self.assertEqual(self.combine(values), "failed")
        for index, bad in (
            (0, {"status": "passed"}),
            (1, {}),
            (1, None),
            (2, {"status": "passed"}),
            (2, {"schema": "future", "status": "passed"}),
        ):
            values = self.fixture()
            values[index] = bad
            self.assertEqual(self.combine(values), "failed")
        for key, bad in (
            ("status", "failed"),
            ("returncode", 1),
            ("logging_returncode", False),
            ("observed_passed_tests", 5),
            ("observed_passed_test_names", []),
        ):
            values = self.fixture()
            values[1][key] = bad
            self.assertEqual(self.combine(values), "failed")
        for index in range(6):
            values = self.fixture()
            del values[1]["observed_passed_test_names"][index]
            self.assertEqual(self.combine(values), "failed")
        values = self.fixture()
        values[5]["query-existing-readback"] = b"changed"
        self.assertEqual(self.combine(values), "failed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
