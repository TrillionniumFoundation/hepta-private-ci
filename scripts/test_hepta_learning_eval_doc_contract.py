#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest
from unittest import mock


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(filename)
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CONTRACT = load("learning_eval_doc_contract", "hepta-learning-eval-doc-contract.py")
MARKDOWN = load("learning_eval_markdown_links", "hepta-learning-eval-markdown-links.py")


class DocumentationContractTests(unittest.TestCase):
    def trusted_reporter_sources(self):
        workflow = (
            CONTRACT.ROOT / ".github/workflows/hepta-learning-eval-trusted-report.yml"
        ).read_text(encoding="utf-8")
        entry = (
            CONTRACT.ROOT / "scripts/hepta-learning-eval-trusted-entry.py"
        ).read_text(encoding="utf-8")
        return workflow, entry

    def test_repository_reporter_uses_the_hardened_trusted_entry(self):
        CONTRACT.validate_trusted_reporter_call_chain(*self.trusted_reporter_sources())

    def test_comment_cannot_satisfy_the_workflow_entry_call(self):
        workflow, entry = self.trusted_reporter_sources()
        workflow = workflow.replace(
            "python3 scripts/hepta-learning-eval-trusted-entry.py",
            "# python3 scripts/hepta-learning-eval-trusted-entry.py",
        )
        with self.assertRaisesRegex(ValueError, "invoke the hardened entry"):
            CONTRACT.validate_trusted_reporter_call_chain(workflow, entry)

    def test_direct_reporter_call_cannot_bypass_the_hardened_entry(self):
        workflow, entry = self.trusted_reporter_sources()
        for prefix in ("scripts", "./scripts"):
            altered = workflow + (
                "\n      - run: |\n"
                f"          python3 {prefix}/hepta-learning-eval-trusted-report.py\n"
            )
            with (
                self.subTest(prefix=prefix),
                self.assertRaisesRegex(ValueError, "bypasses the hardened entry"),
            ):
                CONTRACT.validate_trusted_reporter_call_chain(altered, entry)

    def test_candidate_checkout_is_rejected_even_when_quoted(self):
        workflow, entry = self.trusted_reporter_sources()
        workflow = workflow.replace(
            "ref: ${{ github.event.repository.default_branch }}",
            'ref: "${{ github.event.workflow_run.head_sha }}"',
        )
        with self.assertRaisesRegex(ValueError, "checkout only the default branch"):
            CONTRACT.validate_trusted_reporter_call_chain(workflow, entry)

    def test_inline_inputs_cannot_hide_a_second_candidate_checkout(self):
        workflow, entry = self.trusted_reporter_sources()
        workflow += (
            "\n      - uses: actions/checkout@trusted-pin\n"
            "        with: {ref: '${{ github.event.workflow_run.head_sha }}', "
            "path: candidate, persist-credentials: false}\n"
        )
        with self.assertRaisesRegex(ValueError, "inputs must use block mappings"):
            CONTRACT.validate_trusted_reporter_call_chain(workflow, entry)

    def test_identity_guard_must_execute_before_entry(self):
        workflow, entry = self.trusted_reporter_sources()
        workflow = workflow.replace(
            "python3 scripts/hepta-learning-eval-control-plane-identity.py",
            "# python3 scripts/hepta-learning-eval-control-plane-identity.py",
        )
        with self.assertRaisesRegex(
            ValueError, "verify control-plane identity before entry"
        ):
            CONTRACT.validate_trusted_reporter_call_chain(workflow, entry)

    def test_entry_must_load_reporter_from_its_trusted_directory(self):
        workflow, entry = self.trusted_reporter_sources()
        for altered in (
            entry.replace(
                'SCRIPT_DIR / "hepta-learning-eval-trusted-report.py"',
                'ROOT / "hepta-learning-eval-trusted-report.py"',
            ),
            entry.replace(
                "SCRIPT_DIR = Path(__file__).resolve().parent",
                'SCRIPT_DIR = Path("candidate/scripts")',
            ),
        ):
            with (
                self.subTest(entry=altered[-80:]),
                self.assertRaisesRegex(ValueError, "trusted.*(directory|path)"),
            ):
                CONTRACT.validate_trusted_reporter_call_chain(workflow, altered)

    def test_entry_reporter_and_shell_hook_must_have_byte_identity_checks(self):
        workflow, entry = self.trusted_reporter_sources()
        for path in (
            "scripts/hepta-learning-eval-trusted-entry.py",
            "scripts/hepta-learning-eval-trusted-report.py",
            "scripts/just-shell.py",
        ):
            altered = entry.replace(f'    "{path}",\n', "")
            with (
                self.subTest(path=path),
                self.assertRaisesRegex(ValueError, "bound by byte identity"),
            ):
                CONTRACT.validate_trusted_reporter_call_chain(workflow, altered)

    def test_convergence_storage_checker_rejects_empty_plans_and_lost_retry(self):
        workflow = (
            CONTRACT.ROOT / ".github/workflows/hepta-learning-eval-convergence.yml"
        ).read_text(encoding="utf-8")
        block = workflow.split("python3 - \"$out/storage-profile.json\" <<'PY'\n", 1)[1]
        code = compile(
            textwrap.dedent(block.split("\n          PY", 1)[0]),
            "storage-check",
            "exec",
        )
        profile = {
            "schema": "hepta.learning-eval.storage-profile.v1",
            "attempts": {"attemptCount": 1024, "eventCount": 7168},
            "holdout": {
                "fenceTransitions": 512,
                "planRecords": 512,
                "retryPreserved": True,
                "anchorPreserved": True,
                "beforeBytes": 4096,
                "afterBytes": 2048,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            with mock.patch.object(sys, "argv", ["storage-check", str(path)]):
                path.write_text(json.dumps(profile), encoding="utf-8")
                exec(code, {})
                for field, value in (
                    ("planRecords", None),
                    ("planRecords", 0),
                    ("retryPreserved", None),
                    ("retryPreserved", False),
                ):
                    changed = json.loads(json.dumps(profile))
                    if value is None:
                        changed["holdout"].pop(field)
                    else:
                        changed["holdout"][field] = value
                    path.write_text(json.dumps(changed), encoding="utf-8")
                    with (
                        self.subTest(field=field, value=value),
                        self.assertRaises((AssertionError, KeyError)),
                    ):
                        exec(code, {})

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
                '# Repeated heading\n\n## Repeated heading\n\n<span id="explicit"></span>\n',
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

    def test_markdown_symlink_target_fails_closed_before_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.md"
            target.write_text("# Real target\n", encoding="utf-8")
            linked = root / "linked.md"
            try:
                linked.symlink_to(target.name)
            except OSError as error:
                self.skipTest(f"symlink fixture is unavailable: {error}")
            source = root / "source.md"
            source.write_text("[linked](linked.md#real-target)\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "contains symlink"):
                MARKDOWN.validate_markdown_links([source, target], root)

    def test_markdown_source_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.md"
            target.write_text("# Target\n", encoding="utf-8")
            linked = root / "linked-source.md"
            try:
                linked.symlink_to(target.name)
            except OSError as error:
                self.skipTest(f"symlink fixture is unavailable: {error}")
            with self.assertRaisesRegex(ValueError, "source is a symlink"):
                MARKDOWN.validate_markdown_links([linked], root)

    def test_repository_learning_eval_markdown_graph_is_closed(self):
        documents = MARKDOWN.markdown_documents()
        self.assertTrue(documents, "repository Markdown inventory must not be empty")
        MARKDOWN.validate_markdown_links(documents, MARKDOWN.ROOT)


if __name__ == "__main__":
    unittest.main()
