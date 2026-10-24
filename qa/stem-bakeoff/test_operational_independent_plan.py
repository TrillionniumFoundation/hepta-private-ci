"""Metadata-only regressions; no upstream benchmark commands are executed."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from operational_independent_plan import build, exposure, normalize_commands, repository


class IndependentSourcePlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        counts = {"youtube-dl": 43, "scrapy": 40, "luigi": 33, "thefuck": 32,
                  "tqdm": 9, "PySnooper": 3, "black": 23, "tornado": 16}
        projects = {name: {"url": "https://github.com/example/" + name} for name in counts}
        bugs = [{"group_id": "bugsinpy/" + name + "/" + str(i), "project": name,
                 "revisions": {role: hashlib.sha1((name + role + str(i)).encode()).hexdigest()
                               for role in ("base", "candidate")}}
                for name, count in counts.items() for i in range(1, count + 1)]
        self.old = self.write("old.json", {"schema": "hepta.operational-cohort-protocol.v1",
                                         "projects": projects, "bugs": bugs})
        self.dataset = self.write("data.json", {"rows": [{"group_id": "external/1", "repo": "ansible",
            "split": "train", "labels": {"irrelevant": 1}, "text": "not inspected"}]})
        self.registry = self.write("registry.json", {"all_registered_main_studies_complete": True,
            "main_studies": [{"dataset": str(self.dataset),
                              "dataset_sha256": hashlib.sha256(self.dataset.read_bytes()).hexdigest()}]})

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value))
        return path

    def test_tox_adapter_retains_original_and_rejects_other_shell_contracts(self):
        raw = "tox tests/test_hooks.py::TestHooks::test_hook\npytest tests/test_other.py::test_other\n"
        commands = normalize_commands("cookiecutter", raw)
        self.assertEqual([c["runner"] for c in commands], ["pytest", "pytest"])
        self.assertEqual(commands[0]["upstream_original"], raw.splitlines()[0])
        self.assertEqual(commands[0]["original"], "pytest tests/test_hooks.py::TestHooks::test_hook")
        self.assertIsNotNone(commands[0]["source_adapter"])
        for project, command in (("httpie", "tox tests/t.py::test_a"),
                                 ("cookiecutter", "tox -e py38"),
                                 ("cookiecutter", "tox tests/t.py::test_a; echo injected")):
            with self.assertRaises(ValueError):
                normalize_commands(project, command)

    def test_unknown_prior_project_name_is_exposed_and_blocks_selection(self):
        audit = exposure(self.old, [], self.registry)
        self.assertIn("ansible", audit["project_names"])
        self.assertEqual({k: len(v) for k, v in audit["development_groups"].items()},
                         {"train": 83, "tuning": 33, "calibration": 44})
        directory = self.root / "upstream/projects/ansible"
        directory.mkdir(parents=True)
        (directory / "project.info").write_text('github_url="https://github.com/ansible/ansible"\n')
        with patch("operational_independent_plan.subprocess.check_output", side_effect=["a" * 40, ""]):
            with self.assertRaisesRegex(ValueError, "already experimentally exposed"):
                build(self.root / "upstream", self.old, [], self.registry)

    def test_changed_prior_dataset_fails_its_experimental_pin(self):
        self.dataset.write_text('{"rows": []}')
        with self.assertRaisesRegex(ValueError, "dataset changed"):
            exposure(self.old, [], self.registry)

    def test_original_url_trailing_slash_normalizes_without_shell_text(self):
        self.assertEqual(repository("https://github.com/Jakubroztocil/Httpie/"), "jakubroztocil/httpie")
        with self.assertRaises(ValueError):
            repository("https://github.com/owner/repo;command")


if __name__ == "__main__":
    unittest.main()
