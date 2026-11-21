"""Synthetic static controls; never start Git, Python packages, or models."""

from pathlib import Path
import unittest
from unittest.mock import patch

import acquire_fresh as acquisition
import assemble_fresh
import fresh_contract as c
import test_fresh as fixtures


class AcquisitionTests(unittest.TestCase):
    setUp = fixtures.FreshTests.setUp

    def test_unsupported_original_configuration_and_test_scope_are_refused(self):
        tree = {"module.py": {}, "tests/test_module.py": {}}
        self.assertEqual(acquisition.compatibility(tree, ["tests/test_module.py"], {}), "tests")
        for changed, extra, configs in [
            ([], {}, {"pytest.ini": b"[pytest]\n"}),
            ([], {}, {"pyproject.toml": b"[tool.pytest.ini_options]\naddopts = '-q'\n"}),
            (["tests/deleted_test.py"], {}, {}),
            ([], {"tests/module_test.py": {}}, {}),
            (["outside/test_module.py"], {"outside/test_module.py": {}}, {}),
        ]:
            with self.subTest(changed=changed, configs=configs), self.assertRaises(ValueError):
                acquisition.compatibility({**tree, **extra}, changed, configs)

    def test_later_source_waits_for_prior_terminal_and_stops_after_four(self):
        owner = Path(self.selection["owner_root"])
        with self.assertRaises(FileNotFoundError):
            acquisition.preceding_sources(self.selection, self.excluded, 1)
        for index, project in enumerate(c.REPOSITORIES[:4]):
            scan = owner / "scans" / f"{index:02d}-{project.replace('/', '--')}"
            scan.mkdir(parents=True)
            c.write_new(scan / "RESULT.json", {"schema": "hepta.current-student-fresh-history.v1",
                "status": "ORDERED_STATIC_SCAN_COMPLETE", "canonical_repository": project,
                "commits": [{"source_candidates": [{"status": "REQUIRES_QUALIFICATION"}]}]})
            material = owner / "materials" / f"{index:02d}" / "0"
            material.mkdir(parents=True)
            c.write_new(material / "FINAL.json", {"status": "QUALIFIED"})
        with self.assertRaisesRegex(ValueError, "four sources already selected"):
            acquisition.preceding_sources(self.selection, self.excluded, 4)

    def test_exhausted_panel_refuses_without_new_sources_or_model_calls(self):
        owner = Path(self.selection["owner_root"])
        for index, project in enumerate(c.REPOSITORIES):
            if project.split("/")[0].casefold() in self.excluded["owners"]:
                continue
            scan = owner / "scans" / f"{index:02d}-{project.replace('/', '--')}"
            scan.mkdir(parents=True)
            c.write_new(scan / "RESULT.json", {"schema": "hepta.current-student-fresh-history.v1",
                "status": "ORDERED_STATIC_SCAN_COMPLETE", "canonical_repository": project, "commits": []})
        admissions = c.validate_selection(self.selection, self.weights, self.excluded, self.publication)
        with patch.object(acquisition, "release", return_value=(self.selection, self.excluded, self.publication, admissions, None)):
            result = assemble_fresh.assemble({})
        self.assertEqual((result["status"], result["qualified_sources"], result["replacement_sources"]), ("PANEL_REFUSED", 0, 0))
        self.assertTrue((owner / "PANEL_REFUSED.json").is_file())
        self.assertFalse((owner / "PANEL_FROZEN.json").exists())


if __name__ == "__main__":
    unittest.main()
