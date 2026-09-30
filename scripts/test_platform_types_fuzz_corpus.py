#!/usr/bin/env python3
"""Verify real seed materialization without claiming a mocked fuzz run passed."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from platform_types_fuzz_corpus import (
    EXPECTED_WIRE_KINDS,
    ROOT,
    VECTOR_ROOT,
    seed_corpus,
)


class FuzzCorpusTests(unittest.TestCase):
    def test_frozen_inputs_seed_all_admitted_protocols_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            receipt = seed_corpus(output)
            original = (output / "corpus-seeds.json").read_bytes()
            type_vectors = json.loads(
                (ROOT / VECTOR_ROOT / "CANONICAL_V1_CONFORMANCE.json").read_bytes()
            )["vectors"]
            self.assertEqual(
                len([row for row in receipt["seeds"] if row["target"] == "types"]),
                len(type_vectors),
            )
            wire_kinds = set()
            for row in receipt["seeds"]:
                payload = (output / row["seed"]).read_bytes()
                self.assertEqual(len(payload), row["seedBytes"])
                self.assertEqual(hashlib.sha256(payload).hexdigest(), row["seedSha256"])
                if row["target"] == "wire":
                    wire_kinds.add(json.loads(payload)["kind"])
                else:
                    vector = next(v for v in type_vectors if v["id"] == row["vectorId"])
                    self.assertEqual(payload, bytes.fromhex(vector["encodingHex"]))
            self.assertEqual(wire_kinds, EXPECTED_WIRE_KINDS)
            seed_corpus(output)
            self.assertEqual((output / "corpus-seeds.json").read_bytes(), original)
            self.assertNotIn("status", receipt)

    def test_corrupt_canonical_seed_fails_before_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vector_root = root / VECTOR_ROOT
            vector_root.mkdir(parents=True)
            for name in (
                "CANONICAL_V1_CONFORMANCE.json",
                "PLATFORM_TYPES_WIRE_CONFORMANCE_V1.json",
                "MANIFEST_V1_CONFORMANCE.json",
            ):
                shutil.copyfile(ROOT / VECTOR_ROOT / name, vector_root / name)
            path = vector_root / "CANONICAL_V1_CONFORMANCE.json"
            document = json.loads(path.read_bytes())
            document["vectors"][0]["sha256"] = "0" * 64
            path.write_text(json.dumps(document), encoding="utf-8")
            output = root / "output"
            with self.assertRaisesRegex(ValueError, "canonical seed digest mismatch"):
                seed_corpus(output, root=root)
            self.assertFalse(output.exists())

    def test_runner_materializes_seeds_before_toolchain_and_propagates_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "bin"
            tools.mkdir()
            rustup = tools / "rustup"
            rustup.write_text("#!/usr/bin/env bash\nexit 19\n", encoding="utf-8")
            rustup.chmod(0o755)
            output = root / "evidence"
            environment = dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}")
            result = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/run_platform_types_coverage_fuzz.sh"),
                    str(output),
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 19, result.stdout + result.stderr)
            receipt = json.loads((output / "corpus-seeds.json").read_bytes())
            self.assertGreaterEqual(len(receipt["seeds"]), 10)
            self.assertEqual(
                {
                    row["protocol"]
                    for row in receipt["seeds"]
                    if row["target"] == "wire"
                },
                EXPECTED_WIRE_KINDS,
            )
            self.assertTrue(
                all((output / row["seed"]).is_file() for row in receipt["seeds"])
            )
            self.assertFalse((output / "summary.json").exists())

    def test_synthetic_runner_keeps_relative_output_bound_across_cwd_changes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = root / "bin"
            tools.mkdir()
            rustup = tools / "rustup"
            rustup.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            rustup.chmod(0o755)
            cargo = tools / "cargo"
            cargo.write_text(
                """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
if args == ["fuzz", "--version"]:
    print("cargo-fuzz 0.12.0")
    raise SystemExit(0)
target = next(name for name in ("canonical_validate", "platform_types_json") if name in args)
corpus = Path(args[args.index(target) + 1])
artifact = Path(next(arg.split("=", 1)[1] for arg in args if arg.startswith("-artifact_prefix=")))
output = Path(os.environ["SYNTHETIC_FUZZ_OUTPUT"])
lane = "types" if target == "canonical_validate" else "wire"
assert corpus.is_absolute() and corpus == output / lane / "corpus"
assert artifact.is_absolute() and artifact == output / lane / "artifacts"
seeds = sorted(path.name for path in corpus.iterdir() if path.is_file())
assert seeds
with Path(os.environ["SYNTHETIC_FUZZ_CALLS"]).open("a", encoding="utf-8") as record:
    record.write(json.dumps({"target": target, "corpus": str(corpus), "seeds": seeds}) + "\\n")
print("synthetic invocation only; no fuzz execution")
raise SystemExit(23 if lane == "wire" else 0)
""",
                encoding="utf-8",
            )
            cargo.chmod(0o755)
            output = root / "relative-evidence"
            calls = root / "synthetic-calls.jsonl"
            environment = dict(
                os.environ,
                PATH=f"{tools}:{os.environ['PATH']}",
                SYNTHETIC_FUZZ_OUTPUT=str(output),
                SYNTHETIC_FUZZ_CALLS=str(calls),
            )
            result = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/run_platform_types_coverage_fuzz.sh"),
                    "relative-evidence",
                ],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
            invocations = [json.loads(line) for line in calls.read_text().splitlines()]
            self.assertEqual(
                [row["target"] for row in invocations],
                ["canonical_validate", "platform_types_json"],
            )
            receipt = json.loads((output / "corpus-seeds.json").read_bytes())
            for row in invocations:
                target = "types" if row["target"] == "canonical_validate" else "wire"
                self.assertEqual(
                    row["seeds"],
                    sorted(
                        Path(seed["seed"]).name
                        for seed in receipt["seeds"]
                        if seed["target"] == target
                    ),
                )
            self.assertFalse((output / "summary.json").exists())

    def test_output_symlink_target_survives_runner_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "protected"
            target.mkdir()
            sentinel = target / "sentinel"
            sentinel.write_text("preserve target contents", encoding="utf-8")
            output = root / "evidence"
            output.symlink_to(target, target_is_directory=True)
            tools = root / "bin"
            tools.mkdir()
            rustup = tools / "rustup"
            rustup.write_text("#!/usr/bin/env bash\nexit 19\n", encoding="utf-8")
            rustup.chmod(0o755)
            environment = dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}")
            result = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts/run_platform_types_coverage_fuzz.sh"),
                    "evidence",
                ],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 19, result.stdout + result.stderr)
            self.assertEqual(sentinel.read_text(), "preserve target contents")
            self.assertEqual(list(target.iterdir()), [sentinel])
            self.assertFalse(output.is_symlink())
            self.assertTrue((output / "corpus-seeds.json").is_file())
            self.assertFalse((output / "summary.json").exists())


if __name__ == "__main__":
    unittest.main()
