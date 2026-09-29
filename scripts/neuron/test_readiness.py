from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("readiness.py")
SPEC = (
    Path(__file__).resolve().parents[2]
    / "docs/modules/neuron.runtime/MODULE_SPEC.json"
)
MODULE_SPEC = importlib.util.spec_from_file_location("neuron_readiness", SCRIPT)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
readiness = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(readiness)


class ReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.spec = json.loads(SPEC.read_text())
        spec_path = self.root / "docs/modules/neuron.runtime/MODULE_SPEC.json"
        spec_path.parent.mkdir(parents=True)
        spec_path.write_text(json.dumps(self.spec, indent=2) + "\n")
        for item in self.spec["documents"]:
            path = self.root / item["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {path.name}\n")
        cargo_lock = self.root / "codex-rs/Cargo.lock"
        cargo_lock.parent.mkdir(parents=True)
        cargo_lock.write_text("# locked\n")
        self.spec_path = spec_path
        self.patch = mock.patch.object(readiness, "ROOT", self.root)
        self.patch.start()
        readiness.render(self.spec_path, check=False)

    def tearDown(self) -> None:
        self.patch.stop()
        self.temp.cleanup()

    def capture(self, gate_id: str, source_sha: str = "a" * 40) -> Path:
        gate = readiness.gate_by_id(self.spec, gate_id)
        output = self.root / "evidence" / f"{gate_id}.provenance.json"
        args = argparse.Namespace(
            spec=self.spec_path,
            gate=gate_id,
            source_sha=source_sha,
            base_sha="b" * 40,
            tested_sha="c" * 40,
            tree_sha="d" * 40,
            lane=gate["lane"],
            toolchain=gate["toolchain"],
            target_triple="x86_64-unknown-linux-gnu",
            workflow="test",
            run_id="42",
            run_attempt="1",
            job=gate_id,
            repository="example/repo",
            runner_name="test-runner",
            runner_os="Linux",
            runner_arch="X64",
            runner_image="test-image",
            result="success",
            output=output,
        )
        readiness.capture(args)
        return output

    def test_rendered_projections_are_current_and_activation_is_false(self) -> None:
        readiness.render(self.spec_path, check=True)
        activation = json.loads(
            (self.root / self.spec["paths"]["productionActivation"]).read_text()
        )
        self.assertFalse(activation["productionActivation"])
        implementation = json.loads(
            (self.root / self.spec["paths"]["implementationMap"]).read_text()
        )
        self.assertEqual(
            implementation["generatedFrom"],
            self.spec_path.relative_to(self.root).as_posix(),
        )

    def test_capture_contains_required_bindings(self) -> None:
        path = self.capture("linux-stable-source-head")
        evidence = json.loads(path.read_text())
        self.assertEqual(
            set(evidence["bindings"]),
            {
                "specSha256",
                "testSetSha256",
                "cargoLockSha256",
                "documentationSha256",
                "implementationMapSha256",
            },
        )
        self.assertEqual(evidence["workflow"]["runId"], "42")
        self.assertEqual(
            evidence["runner"]["targetTriple"], "x86_64-unknown-linux-gnu"
        )
        self.assertRegex(
            evidence["runner"]["fingerprintSha256"], r"^[0-9a-f]{64}$"
        )
        self.assertFalse(evidence["claimBoundary"]["productionActivation"])

    def test_aggregate_accepts_one_complete_same_candidate_set(self) -> None:
        for gate in self.spec["qualification"]["requiredGates"]:
            self.capture(gate["id"])
        output = self.root / "READINESS_MANIFEST.json"
        args = argparse.Namespace(
            spec=self.spec_path,
            evidence_dir=self.root / "evidence",
            source_sha="a" * 40,
            base_sha="b" * 40,
            output=output,
            allow_incomplete=False,
        )
        readiness.aggregate(args)
        manifest = json.loads(output.read_text())
        self.assertTrue(manifest["qualificationReady"])
        self.assertFalse(manifest["productionActivation"])
        self.assertEqual(manifest["blockers"], [])

    def test_aggregate_rejects_mixed_source_sha(self) -> None:
        gates = self.spec["qualification"]["requiredGates"]
        for index, gate in enumerate(gates):
            self.capture(gate["id"], source_sha=("e" if index == 0 else "a") * 40)
        output = self.root / "READINESS_MANIFEST.json"
        args = argparse.Namespace(
            spec=self.spec_path,
            evidence_dir=self.root / "evidence",
            source_sha=None,
            base_sha=None,
            output=output,
            allow_incomplete=False,
        )
        with self.assertRaises(readiness.ReadinessError):
            readiness.aggregate(args)
        manifest = json.loads(output.read_text())
        self.assertFalse(manifest["qualificationReady"])
        self.assertIn(
            "mixed source SHAs in readiness evidence", manifest["blockers"]
        )

    def test_aggregate_rejects_failed_or_missing_gate(self) -> None:
        self.capture("linux-stable-source-head")
        output = self.root / "READINESS_MANIFEST.json"
        args = argparse.Namespace(
            spec=self.spec_path,
            evidence_dir=self.root / "evidence",
            source_sha=None,
            base_sha=None,
            output=output,
            allow_incomplete=True,
        )
        readiness.aggregate(args)
        manifest = json.loads(output.read_text())
        self.assertFalse(manifest["qualificationReady"])
        self.assertTrue(
            any(
                item.startswith("missing evidence for gate")
                for item in manifest["blockers"]
            )
        )


if __name__ == "__main__":
    unittest.main()
