import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from . import verify_source


class CurrentSourceFreezeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repository = Path(self.temporary.name)
        self.root = self.repository / verify_source.PREFIX
        shutil.copytree(
            verify_source.ROOT,
            self.root,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        self.workflow = self.repository / verify_source.WORKFLOW
        self.workflow.parent.mkdir(parents=True)
        shutil.copyfile(
            verify_source.ROOT.parents[1] / verify_source.WORKFLOW,
            self.workflow,
        )

    def rewrite_current(self, change):
        path = self.root / "CURRENT_SOURCE_FREEZE.json"
        current = json.loads(path.read_bytes())
        change(current)
        path.write_text(json.dumps(current), encoding="utf-8")

    def rebind_path(self, relative):
        digest = hashlib.sha256((self.repository / relative).read_bytes()).hexdigest()
        self.rewrite_current(lambda current: current["files"].update({relative: digest}))

    def test_successor_runs_original_checks(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            verify_source.verify_current(self.root)
        self.assertEqual(
            output.getvalue().splitlines(),
            [
                "PASS_N256_EXACT_RATIONAL_BINARY64_ROUNDING_SOURCE_ONLY",
                "PASS_N256_FP64_ROUNDING_CURRENT_SOURCE_V2",
            ],
        )

    def test_rebinding_cannot_replace_frozen_primitive_request_or_tests(self):
        for filename in ("fp64_round.py", "REQUEST.json", "test_fp64_round.py"):
            with self.subTest(filename=filename):
                path = self.root / filename
                original = path.read_bytes()
                path.write_bytes(original + b"\n")
                relative = verify_source.PREFIX + filename
                self.rebind_path(relative)
                with self.assertRaisesRegex(SystemExit, "original source pin changed"):
                    verify_source.verify_current(self.root)
                path.write_bytes(original)
                self.rebind_path(relative)

    def test_rebinding_cannot_rewrite_predecessor_evidence(self):
        cases = (
            ("SOURCE_FREEZE.json", "historical source freeze changed"),
            ("history/verify_source_v1.py", "historical verifier pin changed"),
        )
        for filename, message in cases:
            with self.subTest(filename=filename):
                path = self.root / filename
                original = path.read_bytes()
                path.write_bytes(original + b"\n")
                relative = verify_source.PREFIX + filename
                self.rebind_path(relative)
                with self.assertRaisesRegex(SystemExit, message):
                    verify_source.verify_current(self.root)
                path.write_bytes(original)
                self.rebind_path(relative)

    def test_rebinding_cannot_remove_workflow_verification(self):
        self.workflow.write_bytes(
            self.workflow.read_bytes().replace(b"/verify_source.py", b"/ignored.py")
        )
        self.rebind_path(verify_source.WORKFLOW)
        with self.assertRaisesRegex(SystemExit, "approved source-freeze successor"):
            verify_source.verify_current(self.root)

    def test_current_binding_cannot_weaken_inventory_or_boundary(self):
        changes = (
            lambda current: current["files"].pop(verify_source.PREFIX + "fp64_round.py"),
            lambda current: current.update(forbidden_source_tokens=[]),
            lambda current: current.update(scope="provider qualified"),
            lambda current: current["predecessor"].update(sha256="0" * 64),
        )
        path = self.root / "CURRENT_SOURCE_FREEZE.json"
        original = path.read_bytes()
        for index, change in enumerate(changes):
            with self.subTest(change=index):
                self.rewrite_current(change)
                with self.assertRaisesRegex(SystemExit, "current source freeze"):
                    verify_source.verify_current(self.root)
                path.write_bytes(original)

    def test_rebinding_cannot_change_historical_workflow(self):
        relative = verify_source.HISTORICAL_WORKFLOW
        path = self.repository / relative
        path.write_bytes(path.read_bytes() + b"\n")
        self.rebind_path(relative)
        with self.assertRaisesRegex(SystemExit, "exact newline predecessor"):
            verify_source.verify_current(self.root)


if __name__ == "__main__":
    unittest.main()
