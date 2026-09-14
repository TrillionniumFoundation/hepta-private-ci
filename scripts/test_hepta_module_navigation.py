"""Prose-only changes remain cheap without weakening machine ownership or links."""
import contextlib
import copy
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location(
    "module_docs_navigation", Path(__file__).with_name("hepta-module-docs.py")
)
DOCS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOCS)


class ModuleNavigationTests(unittest.TestCase):
    def setUp(self):
        self.guide = DOCS.ROOT / "docs/modules/platform.types/TECHNICAL.md"
        self.original_read = Path.read_text
        self.original_load = DOCS.load

    def verify(self, *, prose=None, transform=None):
        guide = self.guide
        original_read = self.original_read

        def read(path, *args, **kwargs):
            if prose is not None and path == guide:
                return prose
            return original_read(path, *args, **kwargs)

        def load(path):
            document = copy.deepcopy(self.original_load(path))
            if transform:
                transform(path, document)
            return document

        # Implementation-map behavior has its own regression suite. This suite
        # exercises the complete module verifier, without running its child again.
        with mock.patch.object(DOCS, "load", side_effect=load), mock.patch.object(
            Path, "read_text", read
        ), mock.patch.object(
            DOCS.subprocess, "run", return_value=SimpleNamespace(returncode=0, stderr="", stdout="")
        ), contextlib.redirect_stdout(io.StringIO()):
            return DOCS.verify()

    def test_prose_layout_and_cached_metrics_are_not_acceptance_evidence(self):
        self.assertEqual(self.verify(prose="# Types\n\nOwnership is retained in the registry.\n"), 0)

    def test_empty_guide_and_broken_or_escaping_links_still_fail(self):
        for prose in (" ", "[missing](not-present.md)", "[escape](../../../../outside.md)"):
            with self.subTest(prose=prose), self.assertRaises(SystemExit):
                self.verify(prose=prose)

    def test_positive_authority_cannot_be_hidden_by_a_prose_change(self):
        def change(path, document):
            if path == "docs/modules/MODULE_DOCS.json":
                document["authorityFlags"]["runtimeAuthority"] = True
        with self.assertRaisesRegex(SystemExit, "positive authority"):
            self.verify(prose="# Types\n\nNo production authority.\n", transform=change)

    def test_machine_contract_inventory_remains_enforced(self):
        def change(path, document):
            if path == "docs/modules/MODULE_DOCS.json":
                document["modules"][0]["producedContracts"] = ["invented.contract"]
        with self.assertRaisesRegex(SystemExit, "index producedContracts"):
            self.verify(transform=change)

    def test_production_status_disagreement_still_rejects(self):
        def change(path, document):
            if path == "docs/modules/MODULE_DOCS.json":
                row = document["modules"][0]
                row["production_implementation"] = not row["production_implementation"]
        with self.assertRaises(SystemExit):
            self.verify(transform=change)

    def test_guide_link_anchors_are_still_verified(self):
        with self.assertRaisesRegex(SystemExit, "missing anchor"):
            self.verify(prose="# Types\n\n[missing anchor](#does-not-exist)\n")


if __name__ == "__main__":
    unittest.main()
