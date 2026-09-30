"""Development checks retain authority validation and delegate source profiles."""

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
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
                patch.object(
                    GAP,
                    "cargo_workspace_member_roots",
                    return_value=set(GAP.RUST_PACKAGES),
                ),
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


if __name__ == "__main__":
    unittest.main()
