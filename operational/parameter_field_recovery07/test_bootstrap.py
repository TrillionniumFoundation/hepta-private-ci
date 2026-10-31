"""Lifecycle ordering/failure fixtures; no registered scientific entrypoint runs."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import bootstrap, common as c


class BootstrapTests(unittest.TestCase):
    def exercise(self, root, fail=False, semantic_fail=False):
        calls = []
        closure = {"synthetic_source": "a" * 64}
        config_path = root / "ops/registrations/initial/PIPELINE_CONFIG.json"
        config = {
            "source_files": closure,
            "python": "/synthetic/python",
            "empty_cwd": str(root / "empty"),
        }
        (root / "pipeline_measurement").mkdir()

        def initialize(commit):
            calls.append("initialize")
            config_path.parent.mkdir(parents=True)
            c.write_new(config_path, config)

        def measured(name, argv, directory, log, cwd, health, binding):
            calls.append(name)
            if name == "original-semantic-preflight":
                if semantic_fail:
                    raise ValueError("synthetic semantic failure")
                c.write_new(
                    config_path.parent / "SEMANTIC_PREFLIGHT.json",
                    {"synthetic_fixture": True},
                )
            else:
                self.assertEqual(name, "postseal-review")
                self.assertIn("--execute-post-seal", argv)
                (root / "postseal").mkdir()
                c.write_new(
                    root / "postseal/COMPLETE.json",
                    {
                        "schema": "hepta.execution07.postseal-review.1",
                        "complete": True,
                        "execution_episode": c.EPISODE,
                        "pipeline_config": c.descriptor(config_path),
                        "terminal_closure": c.descriptor(
                            root / "ops/TERMINAL_CLOSURE.json"
                        ),
                        "status": "COST_COVERAGE_INCOMPLETE",
                    },
                )
            return {"synthetic_measurement": name}

        def run(config, item):
            calls.append("supervisor")
            if fail:
                raise ValueError("synthetic supervisor failure")
            c.write_new(root / "ops/COMPLETE.json", {"synthetic_fixture": True})
            return {"synthetic_measurement": "supervisor"}

        def publish(config, item):
            calls.append("publish")
            c.write_new(root / "ops/TERMINAL_CLOSURE.json", {"synthetic_fixture": True})

        with (
            patch.object(bootstrap, "RUN", root),
            patch.object(bootstrap, "CONFIG", config_path),
            patch.object(bootstrap, "source_guard", return_value=closure),
            patch.object(bootstrap.terminal, "initialize", side_effect=initialize),
            patch.object(bootstrap.terminal, "run", side_effect=run),
            patch.object(bootstrap.terminal, "publish", side_effect=publish),
            patch.object(bootstrap.terminal, "measured", side_effect=measured),
            patch.object(
                bootstrap.terminal, "health_callback", return_value=lambda: None
            ),
            patch.object(
                c,
                "load_config",
                side_effect=lambda path, digest: (config, c.descriptor(path)),
            ),
            patch.object(c, "committed_sources"),
        ):
            if fail or semantic_fail:
                with self.assertRaisesRegex(ValueError, "synthetic .* failure"):
                    bootstrap.child("a" * 40)
            else:
                bootstrap.child("a" * 40)
        return calls

    def test_closed_negative_review_is_preserved_without_promoting_adoption(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.assertEqual(
                self.exercise(root),
                [
                    "initialize",
                    "original-semantic-preflight",
                    "supervisor",
                    "publish",
                    "postseal-review",
                ],
            )
            result = c.read(root / "pipeline_measurement/CHILD_COMPLETE.json")
            self.assertEqual(
                result["scientific_review_disposition"], "COST_COVERAGE_INCOMPLETE"
            )
            self.assertEqual(result["scientific_efficacy_adoption"], "not_assessed")
            self.assertTrue(result["this_child_final_wait4_pending"])

    def test_failed_science_has_no_publication_review_or_retry(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.assertEqual(
                self.exercise(root, fail=True),
                ["initialize", "original-semantic-preflight", "supervisor"],
            )
            self.assertFalse(
                (root / "pipeline_measurement/CHILD_COMPLETE.json").exists()
            )
            self.assertFalse((root / "postseal").exists())

    def test_original_semantic_failure_prevents_first_scientific_worker(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.assertEqual(
                self.exercise(root, semantic_fail=True),
                ["initialize", "original-semantic-preflight"],
            )
            self.assertFalse((root / "ops/COMPLETE.json").exists())


if __name__ == "__main__":
    unittest.main()
