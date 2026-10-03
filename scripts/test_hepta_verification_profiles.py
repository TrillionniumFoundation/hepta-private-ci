"""Development checks retain authority validation and delegate source profiles."""

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))


def verifier(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), SCRIPTS / name
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DOCS = verifier("hepta-docs.py")
MODULES = verifier("hepta-module-docs.py")
GAP = verifier("hepta-gap-closure.py")
REGISTRY = verifier("hepta_source_registry_closure.py")


class VerificationProfileTests(unittest.TestCase):
    def test_real_development_tree_reports_a_shared_path_touch_without_activating_the_lease(
        self,
    ):
        lease = DOCS.load(DOCS.FILES["paths"])["activeLeases"][0]
        changed = {lease["normalizedExactPaths"][0]}
        output = io.StringIO()
        with (
            patch.object(DOCS, "pull_request_changed_paths", return_value=changed),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(DOCS.verify("development"), 0)
        report = json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual(report["touchedLeaseCount"], 1)
        self.assertEqual(report["externallyAttestedLeaseCount"], 0)
        self.assertFalse(report["leaseActivationEvaluated"])
        self.assertFalse(report["historicalEvidenceRevalidated"])

    def test_gap_owner_development_checks_the_real_tree_without_renewing_stale_maps(
        self,
    ):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(GAP.verify("development"), [])

    def test_gap_profiles_are_forwarded_to_the_document_child(self):
        for profile in ("development", "qualification"):
            with (
                self.subTest(profile=profile),
                patch.object(GAP.subprocess, "run") as run,
            ):
                run.return_value.returncode = 0
                self.assertEqual(GAP.verify(profile), [])
                self.assertEqual(
                    run.call_args.args[0],
                    [
                        sys.executable,
                        str(GAP.ROOT / "scripts/hepta-module-docs.py"),
                        "verify",
                        "--profile",
                        profile,
                    ],
                )

    def test_gap_unknown_profile_is_rejected_before_reading_source(self):
        with patch.object(GAP.CARGO_MANIFEST.__class__, "read_text") as read:
            self.assertEqual(GAP.verify("permissive"), ["unknown verification profile"])
        read.assert_not_called()

    def test_unknown_profile_is_rejected_before_reading_source(self):
        for module in (DOCS, MODULES):
            with (
                self.subTest(module=module.__name__),
                self.assertRaisesRegex(SystemExit, "profile"),
            ):
                module.verify("permissive")

    def test_authority_types_and_permissions_remain_mandatory_in_both_profiles(self):
        for module in (DOCS, MODULES):
            original_load = module.load
            for profile in ("development", "qualification"):
                for value in (True, 0, "", None):

                    def altered(path):
                        document = copy.deepcopy(original_load(path))
                        if path == "docs/modules/MODULES.json":
                            document["authorityFlags"]["merge"] = value
                        return document

                    with self.subTest(
                        module=module.__name__, profile=profile, value=value
                    ):
                        with (
                            patch.object(module, "load", altered),
                            self.assertRaisesRegex(SystemExit, "authority"),
                        ):
                            module.verify(profile)

    def test_module_profile_reaches_the_real_map_verifier(self):
        # All registry/path/navigation checks run against actual repository inputs.
        # The source-map subprocess is observed separately from execution evidence.
        for profile in ("development", "qualification"):
            with (
                self.subTest(profile=profile),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                with patch.object(MODULES.subprocess, "run") as run:
                    run.return_value.returncode = 0
                    MODULES.verify(profile)
                    self.assertEqual(
                        run.call_args.args[0],
                        [
                            "python3",
                            "scripts/hepta-implementation-maps.py",
                            "verify",
                            "--profile",
                            profile,
                        ],
                    )


class SourceEvidenceNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.module_id = "objective.compiler"
        self.roots = REGISTRY.SOURCE_ROOTS[self.module_id]
        self.bootstrap = "OBJ-0-OBJECTIVE-CONTRACTS"
        self.relative_path = "docs/modules/objective.compiler/TECHNICAL.md"
        self.original = (REGISTRY.ROOT / self.relative_path).read_text(encoding="utf-8")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / self.relative_path
        self.path.parent.mkdir(parents=True)
        self.path.write_text(self.original, encoding="utf-8")

    def normalize(self):
        with patch.object(REGISTRY, "ROOT", self.root):
            return REGISTRY._normalize_technical_document(
                self.module_id, self.path, self.roots, self.bootstrap
            )

    def _guide_reader(self, replacement):
        original_read = Path.read_text
        target = REGISTRY.ROOT / self.relative_path

        def read(path, *args, **kwargs):
            if path == target:
                return replacement
            return original_read(path, *args, **kwargs)

        return read

    def verify(self):
        # Exercise the real registry verifier, replacing only this guide's bytes.
        replacement = self.path.read_text(encoding="utf-8")
        with patch.object(Path, "read_text", self._guide_reader(replacement)):
            return REGISTRY.verify()

    def test_real_objective_requirements_and_contract_tail_survive_normalization(self):
        for heading in (
            REGISTRY.SOURCE_REQUIREMENTS_HEADING,
            REGISTRY.SOURCE_RECEIPT_HEADING,
        ):
            with self.subTest(heading=heading):
                original = self.original.replace(
                    REGISTRY.SOURCE_REQUIREMENTS_HEADING, heading
                )
                self.path.write_text(original, encoding="utf-8")
                tail = original[original.index(heading) :]
                self.assertIn("### RunStart rotation writer fence", tail)
                self.assertIn(
                    "## Admission-proof persistence and recovery contract", tail
                )
                self.assertEqual(self.verify(), [])
                self.assertTrue(self.normalize())
                normalized = self.path.read_text(encoding="utf-8")
                self.assertEqual(normalized[normalized.index(heading) :], tail)
                self.assertEqual(self.verify(), [])
                self.assertFalse(self.normalize())
                self.assertEqual(self.path.read_text(encoding="utf-8"), normalized)

    def test_duplicate_supported_sections_are_rejected_without_writing(self):
        for first in (
            REGISTRY.SOURCE_REQUIREMENTS_HEADING,
            REGISTRY.SOURCE_RECEIPT_HEADING,
        ):
            for second in (
                REGISTRY.SOURCE_REQUIREMENTS_HEADING,
                REGISTRY.SOURCE_RECEIPT_HEADING,
            ):
                for body in ("", "\n\nDuplicate binding.\n"):
                    with self.subTest(first=first, second=second, body=body):
                        original = (
                            self.original.replace(
                                REGISTRY.SOURCE_REQUIREMENTS_HEADING, first
                            )
                            + "\n"
                            + second
                            + body
                        )
                        self.path.write_text(original, encoding="utf-8")
                        self.assertTrue(
                            any(
                                "duplicate technical source evidence" in failure
                                for failure in self.verify()
                            )
                        )
                        with self.assertRaisesRegex(
                            REGISTRY.RegistryClosureError,
                            "duplicate technical source evidence",
                        ):
                            self.normalize()
                        self.assertEqual(
                            self.path.read_text(encoding="utf-8"), original
                        )

    def test_mismatched_requirements_are_rejected_without_writing(self):
        prefix, section = self.original.split(REGISTRY.SOURCE_REQUIREMENTS_HEADING, 1)
        for expected, substituted in (
            (self.module_id, "other.module"),
            (self.bootstrap, "OTHER-BOOTSTRAP"),
            (self.roots[0], "codex-rs/other-root"),
        ):
            with self.subTest(binding=expected):
                original = (
                    prefix
                    + REGISTRY.SOURCE_REQUIREMENTS_HEADING
                    + section.replace(expected, substituted, 1)
                )
                self.path.write_text(original, encoding="utf-8")
                self.assertTrue(
                    any(
                        "requirements binding mismatch" in failure
                        for failure in self.verify()
                    )
                )
                with self.assertRaisesRegex(
                    REGISTRY.RegistryClosureError, "requirements binding mismatch"
                ):
                    self.normalize()
                self.assertEqual(self.path.read_text(encoding="utf-8"), original)

    def test_stale_legacy_receipt_replacement_stops_at_next_contract(self):
        original = self.original.replace(
            REGISTRY.SOURCE_REQUIREMENTS_HEADING, REGISTRY.SOURCE_RECEIPT_HEADING
        )
        prefix, section = original.split(REGISTRY.SOURCE_RECEIPT_HEADING, 1)
        original = (
            prefix
            + REGISTRY.SOURCE_RECEIPT_HEADING
            + section.replace(self.bootstrap, "OLD-BOOTSTRAP", 1)
        )
        self.path.write_text(original, encoding="utf-8")
        tail_heading = "## Admission-proof persistence and recovery contract"
        tail = original[original.index(tail_heading) :]
        self.assertTrue(
            any("receipt binding mismatch" in failure for failure in self.verify())
        )
        self.assertTrue(self.normalize())
        normalized = self.path.read_text(encoding="utf-8")
        self.assertEqual(normalized[normalized.index(tail_heading) :], tail)
        self.assertEqual(self.verify(), [])
        self.assertFalse(self.normalize())


if __name__ == "__main__":
    unittest.main()
