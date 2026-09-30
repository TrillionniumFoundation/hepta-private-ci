#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CONTRACT = load("learning_eval_doc_contract", "hepta-learning-eval-doc-contract.py")
MARKDOWN = load("learning_eval_markdown_links", "hepta-learning-eval-markdown-links.py")


class DocumentationContractTests(unittest.TestCase):
    def test_bare_verified_is_rejected_at_any_depth(self):
        with self.assertRaises(ValueError):
            CONTRACT.reject_bare_verified({"nested": {"verified": True}})

    def test_scoped_verified_name_is_allowed(self):
        CONTRACT.reject_bare_verified({"sourceInventoryVerified": True})

    def test_external_claims_must_remain_false(self):
        CONTRACT.require_external_false(
            {"claims": {"targetHostQualified": False, "releaseAuthorized": False}},
            "fixture",
        )
        with self.assertRaises(ValueError):
            CONTRACT.require_external_false(
                {"claims": {"independentAcceptanceIssued": True}}, "fixture"
            )

    def test_markdown_links_validate_files_and_duplicate_heading_anchors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.md"
            target.write_text(
                "# Repeated heading\n\n## Repeated heading\n\n<span id=\"explicit\"></span>\n",
                encoding="utf-8",
            )
            source = root / "source.md"
            source.write_text(
                "[first](target.md#repeated-heading)\n"
                "[second](target.md#repeated-heading-1)\n"
                "[explicit](target.md#explicit)\n",
                encoding="utf-8",
            )
            MARKDOWN.validate_markdown_links([source, target], root)

    def test_markdown_missing_file_and_anchor_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.md"
            target.write_text("# Existing\n", encoding="utf-8")
            missing_file = root / "missing-file.md"
            missing_file.write_text("[missing](absent.md)\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing target"):
                MARKDOWN.validate_markdown_links([missing_file, target], root)

            missing_anchor = root / "missing-anchor.md"
            missing_anchor.write_text(
                "[missing](target.md#does-not-exist)\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "missing anchor"):
                MARKDOWN.validate_markdown_links([missing_anchor, target], root)

    def test_markdown_links_may_not_escape_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.md"
            source.write_text("[escape](../outside.md)\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "outside the repository"):
                MARKDOWN.validate_markdown_links([source], root)

    def test_repository_learning_eval_markdown_graph_is_closed(self):
        documents = MARKDOWN.markdown_documents()
        self.assertTrue(documents, "repository Markdown inventory must not be empty")
        MARKDOWN.validate_markdown_links(documents, MARKDOWN.ROOT)


if __name__ == "__main__":
    unittest.main()
