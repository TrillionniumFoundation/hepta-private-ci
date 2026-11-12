"""CLI accepts a real fitted head artifact and preserves strict request limits.

The retained visual vectors and paired utility labels are synthetic fixtures;
the optimizer, CLI processes, source artifacts and durable owner actually run.
"""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import perc1
import test_perc1_source_feature_profile as fixture_support
from PIL import Image

from perc1.capture_entry import model_sha256
from perc1.owner import Owner
from perc1.schema import canonical, sha
from perc1.source_entry import make_config


@unittest.skipUnless(os.name == "posix", "existing POSIX source owner")
class ProfiledSourceEntryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_support.SourceFeatureProfileTests()
        self.fixture.setUp()
        self.root = self.fixture.root
        image_path = self.root / "catalog.png"
        Image.new("RGB", (16, 16), "white").save(image_path)
        projection_path = self.root / "projection.json"
        projection_path.write_bytes(canonical(self.fixture.projection))
        model = {
            "weights": str(self.root / "unavailable-weights.pth"),
            "weights_sha256": self.fixture.weights,
            "projection": str(projection_path),
            "projection_sha256": sha(projection_path.read_bytes()),
            "device": "cpu",
        }
        sources = {
            "document": {
                "schema": "perc1.source-capture.v1",
                "kind": "screenshot",
                "image": {
                    "path": str(image_path),
                    "sha256": sha(image_path.read_bytes()),
                },
                "source_uri": "fixture://profile-cli",
                "source_group": "profile-cli",
                "document": None,
                "text": None,
                "ocr": None,
            }
        }
        self.config = make_config(
            self.root / "cli-owner",
            "profile-cli",
            1,
            64,
            sources,
            model,
            self.fixture.task_sha,
        )
        self.fixture.owner.close()
        self.fixture.grant = self.config["grant"]
        self.fixture.binding = {
            **{
                key: self.fixture.grant[key]
                for key in ("owner_id", "generation", "source_frontier")
            },
            "grant_sha256": sha(self.fixture.grant),
            "encoder_sha256": model_sha256(
                self.fixture.weights, self.fixture.projection
            ),
        }
        self.fixture.owner = Owner(self.root / "cli-owner", self.fixture.binding, 64)
        self.fixture.producer = self.fixture.make_producer()
        self.head = self.fixture.fitted_head()
        self.fixture.source("negative", -1.0)
        self.candidate = self.fixture.candidate(["negative"])
        self.before = self.fixture.owner.status()
        self.fixture.owner.close()
        self.head_path = self.root / "head.json"
        self.head_path.write_bytes(canonical(self.head) + b"\n")
        self.config_path = self.root / "config.json"
        self.config_path.write_bytes(canonical(self.config))
        self.request = {
            "schema": "perc1.profiled-source-active.v1",
            "feature_profile": self.fixture.profile,
            "head_artifact": {
                "path": str(self.head_path),
                "sha256": sha(self.head_path.read_bytes()),
            },
            "head_sha256": sha(self.head),
            "task_sha256": self.fixture.task_sha,
            "observed_operations": ["negative"],
            "candidates": [self.candidate],
        }
        self.env = dict(
            os.environ, PYTHONPATH=str(Path(perc1.__file__).resolve().parent.parent)
        )

    def tearDown(self):
        self.fixture.tearDown()

    def cli(self, operation, *, request=None, command="source-active"):
        args = [
            sys.executable,
            "-m",
            "perc1",
            command,
            "--config",
            str(self.config_path),
            "--operation",
            operation,
        ]
        if request is not None:
            path = self.root / (operation + ".json")
            path.write_bytes(canonical(request))
            args.extend(["--request", str(path)])
        return subprocess.run(
            args, env=self.env, capture_output=True, text=True, timeout=30
        )

    def test_large_fitted_artifact_runs_cli_and_cold_reads_retained_head(self):
        self.assertGreater(self.head_path.stat().st_size, 65536)
        self.assertLess(len(canonical(self.request)), 65536)
        first = self.cli("stopped", request=self.request)
        self.assertEqual(first.returncode, 0, first.stderr)
        result = json.loads(first.stdout)
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(
            result["active"]["decision"]["schema"], "perc1.active-capture-decision.v3"
        )
        self.assertEqual(
            result["this_entry"],
            {
                "source_callback_invocations": 0,
                "encoder_loaded": False,
                "encoder_completed_calls": 0,
            },
        )
        self.assertEqual(result["owner_status"], self.before)
        self.head_path.unlink()
        cold = self.cli("stopped", command="source-decision-read")
        self.assertEqual(cold.returncode, 0, cold.stderr)
        readback = json.loads(cold.stdout)
        self.assertEqual(readback["decision"], result["active"]["decision"])
        self.assertEqual(readback["owner_status"], self.before)

    def test_strict_schema_and_both_head_identities_refuse_without_effect(self):
        cases = []
        for key, value in (
            ("schema", "perc1.profiled-source-active.v999"),
            ("head_sha256", sha("changed head")),
            (
                "head_artifact",
                {
                    "path": "head.json",
                    "sha256": self.request["head_artifact"]["sha256"],
                },
            ),
            ("head_artifact", self.request["head_artifact"] | {"unrecognized": 0}),
            (
                "head_artifact",
                self.request["head_artifact"] | {"sha256": sha("changed bytes")},
            ),
            ("feature_profile", None),
        ):
            cases.append(self.request | {key: value})
        cases.append(self.request | {"head": {}})
        missing = copy.deepcopy(self.request)
        del missing["feature_profile"]
        cases.append(missing)
        changed = copy.deepcopy(self.request)
        changed["feature_profile"]["observation"] = "last"
        cases.append(changed)
        for index, request in enumerate(cases):
            with self.subTest(index=index):
                self.assertLess(len(canonical(request)), 65536)
                result = self.cli("bad-" + str(index), request=request)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                with Owner(self.root / "cli-owner", self.fixture.binding, 64) as owner:
                    self.assertEqual(owner.status(), self.before)
                self.assertFalse(
                    (
                        self.root
                        / "cli-owner/active-decisions"
                        / (sha(("bad-" + str(index)).encode()) + ".json")
                    ).exists()
                )
        self.assertFalse((self.root / "unavailable-weights.pth").exists())


if __name__ == "__main__":
    unittest.main()
