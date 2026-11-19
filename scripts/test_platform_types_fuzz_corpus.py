#!/usr/bin/env python3
"""Verify fuzz seed/evidence behavior with explicitly synthetic runner transcripts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from platform_types_fuzz_corpus import (
    EXPECTED_WIRE_KINDS,
    ROOT,
    VECTOR_ROOT,
    seed_corpus,
)
from platform_types_fuzz_evidence import MAX_RUNS, validate_fuzz_summary


class FuzzCorpusTests(unittest.TestCase):
    def _synthetic_tools(self, root: Path) -> dict[str, str]:
        tools = root / "synthetic-bin"
        tools.mkdir()
        rustup = tools / "rustup"
        rustup.write_text(
            '#!/usr/bin/env bash\nprintf "called\\n" >> "$SYNTHETIC_TOOLCHAIN_CALLS"\n',
            encoding="utf-8",
        )
        rustup.chmod(0o755)
        cargo = tools / "cargo"
        cargo.write_text(
            """#!/usr/bin/env python3
import os
import sys
from pathlib import Path

args = sys.argv[1:]
if args == ["fuzz", "--version"]:
    print(os.environ.get("SYNTHETIC_CARGO_FUZZ_VERSION", "cargo-fuzz 0.12.0"))
    raise SystemExit(0)
if args and args[0] == "install":
    print("synthetic installation only")
    raise SystemExit(0)
target = next(name for name in ("canonical_validate", "platform_types_json") if name in args)
corpus = Path(args[args.index(target) + 1])
requested = int(next(arg.split("=", 1)[1] for arg in args if arg.startswith("-runs=")))
seeds = len([path for path in corpus.iterdir() if path.is_file()])
print(f"INFO: seed corpus: files: {seeds} min: 1B max: 1B total: {seeds}B rss: 1Mb")
mode = os.environ.get("SYNTHETIC_FUZZ_MODE", "complete")
initialized = requested + 3 if mode == "initializer_extra_replay" else seeds + 4 if mode == "lsan_complete" else seeds + 1
if mode == "out_of_order":
    print(f"#{requested} DONE cov: 42 ft: 51 corp: 1/1B exec/s: 0 rss: 1Mb")
print(f"#{initialized} INITED cov: 42 ft: 51 corp: 1/1B")
if mode == "duplicate_init":
    print(f"#{initialized} INITED cov: 42 ft: 51 corp: 1/1B")
if mode == "coverage_only":
    pass
else:
    executed = initialized if mode in ("seed_replay", "initializer_extra_replay") else requested - 1 if mode == "shortfall" else requested
    print(f"#{executed} DONE cov: 42 ft: 51 corp: 1/1B exec/s: 0 rss: 1Mb")
print("synthetic transcript only; no fuzz execution")
""",
            encoding="utf-8",
        )
        cargo.chmod(0o755)
        return dict(
            os.environ,
            PATH=f"{tools}:{os.environ['PATH']}",
            SYNTHETIC_TOOLCHAIN_CALLS=str(root / "toolchain-calls"),
        )

    def _synthetic_runner(
        self, root: Path, environment: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "bash",
                str(ROOT / "scripts/run_platform_types_coverage_fuzz.sh"),
                str(root / "evidence"),
            ],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_invalid_run_budgets_fail_before_cleanup_or_toolchain(self) -> None:
        for lane in ("TYPE", "WIRE"):
            for budget in ("0", "-1", "invalid", str(MAX_RUNS + 1)):
                with (
                    self.subTest(lane=lane, budget=budget),
                    tempfile.TemporaryDirectory() as directory,
                ):
                    root = Path(directory)
                    environment = self._synthetic_tools(root)
                    environment[f"PLATFORM_TYPES_{lane}_FUZZ_RUNS"] = budget
                    output = root / "evidence"
                    output.mkdir()
                    sentinel = output / "sentinel"
                    sentinel.write_text("keep existing output", encoding="utf-8")
                    result = self._synthetic_runner(root, environment)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("positive integer", result.stderr)
                    self.assertEqual(sentinel.read_text(), "keep existing output")
                    self.assertFalse((root / "toolchain-calls").exists())

    def test_replay_only_budget_fails_before_cargo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = self._synthetic_tools(root)
            environment["PLATFORM_TYPES_TYPE_FUZZ_RUNS"] = "1"
            result = self._synthetic_runner(root, environment)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not exceed initial seed replay", result.stderr)
            self.assertFalse((root / "toolchain-calls").exists())
            self.assertFalse((root / "evidence/summary.json").exists())

    def test_synthetic_transcripts_cannot_pass_without_budgeted_new_execution(
        self,
    ) -> None:
        for mode in (
            "seed_replay",
            "shortfall",
            "coverage_only",
            "initializer_extra_replay",
            "out_of_order",
            "duplicate_init",
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                environment = self._synthetic_tools(root)
                environment["SYNTHETIC_FUZZ_MODE"] = mode
                result = self._synthetic_runner(root, environment)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse((root / "evidence/summary.json").exists())

    def test_runner_and_final_receipt_share_execution_and_log_binding(self) -> None:
        from platform_types_candidate_evidence import _validate_coverage_fuzz
        from platform_types_candidate_support import CandidateBundleError

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self._synthetic_runner(root, self._synthetic_tools(root))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            output = root / "evidence"
            summary_path = output / "summary.json"
            summary = json.loads(summary_path.read_bytes())
            for record in summary["targets"]:
                self.assertEqual(record["executedRuns"], 4096)
                self.assertGreater(record["postInitializationExecutionRuns"], 0)
            validate_fuzz_summary(summary, output)
            with patch(
                "platform_types_candidate_evidence.resolve_record_path",
                return_value=summary_path,
            ):
                _validate_coverage_fuzz(summary, {})
                for key in ("canonicalValidate", "platformTypesJson"):
                    for value in (0, -1, "invalid", MAX_RUNS + 1):
                        changed = json.loads(json.dumps(summary))
                        changed["runs"][key] = value
                        with (
                            self.subTest(key=key, value=value),
                            self.assertRaises(CandidateBundleError),
                        ):
                            _validate_coverage_fuzz(changed, {})
                for key, value in (
                    ("toolchain", "nightly"),
                    ("cargoFuzzVersion", "0.12.1"),
                ):
                    changed = json.loads(json.dumps(summary))
                    changed[key] = value
                    with self.subTest(key=key), self.assertRaises(CandidateBundleError):
                        _validate_coverage_fuzz(changed, {})
                raw = (
                    (output / "types.log")
                    .read_bytes()
                    .replace(b"#4096 DONE", b"#4097 DONE")
                )
                (output / "types.log").write_bytes(raw)
                summary["targets"][0]["logSha256"] = hashlib.sha256(raw).hexdigest()
                summary["targets"][0]["logBytes"] = len(raw)
                with self.assertRaisesRegex(
                    CandidateBundleError, "differs from its bound log"
                ):
                    _validate_coverage_fuzz(summary, {})
                raw = raw.replace(b"#4097 DONE", b"#6 DONE")
                (output / "types.log").write_bytes(raw)
                summary["targets"][0]["logSha256"] = hashlib.sha256(raw).hexdigest()
                summary["targets"][0]["logBytes"] = len(raw)
                with self.assertRaisesRegex(CandidateBundleError, "execution count"):
                    _validate_coverage_fuzz(summary, {})

    def test_synthetic_lsan_replays_are_counted_as_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = self._synthetic_tools(root)
            environment["SYNTHETIC_FUZZ_MODE"] = "lsan_complete"
            result = self._synthetic_runner(root, environment)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = json.loads((root / "evidence/summary.json").read_bytes())
            for record in summary["targets"]:
                initialized = record["initialCorpusFiles"] + 4
                self.assertEqual(record["initializationExecutions"], initialized)
                self.assertEqual(
                    record["postInitializationExecutionRuns"], 4096 - initialized
                )
                self.assertNotIn("mutatedRunsLowerBound", record)

    def test_required_seed_and_log_files_reject_symlinks_and_wrong_seed_version(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self._synthetic_runner(root, self._synthetic_tools(root))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            output = root / "evidence"
            summary = json.loads((output / "summary.json").read_bytes())
            for name in ("corpus-seeds.json", "types.log", "wire.log"):
                with self.subTest(name=name):
                    path = output / name
                    raw = path.read_bytes()
                    outside = root / ("outside-" + name)
                    outside.write_bytes(raw)
                    path.unlink()
                    path.symlink_to(outside)
                    with self.assertRaisesRegex(ValueError, "non-symlink"):
                        validate_fuzz_summary(summary, output)
                    path.unlink()
                    path.write_bytes(raw)
            receipt_path = output / "corpus-seeds.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["schemaVersion"] = 2
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported fuzz seed receipt"):
                validate_fuzz_summary(summary, output)

    def test_runner_rejects_unpinned_fuzz_toolchain_before_toolchain_work(self) -> None:
        for key, value in (
            ("PLATFORM_TYPES_FUZZ_TOOLCHAIN", "nightly"),
            ("PLATFORM_TYPES_CARGO_FUZZ_VERSION", "0.12.1"),
        ):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                environment = self._synthetic_tools(root)
                environment[key] = value
                result = self._synthetic_runner(root, environment)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("pinned toolchain", result.stderr)
                self.assertFalse((root / "toolchain-calls").exists())

    def test_runner_rechecks_actual_cargo_fuzz_version_after_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = self._synthetic_tools(root)
            environment["SYNTHETIC_CARGO_FUZZ_VERSION"] = "cargo-fuzz 0.12.0-unpinned"
            result = self._synthetic_runner(root, environment)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("installed cargo-fuzz differs", result.stderr)
            self.assertFalse((root / "evidence/types.log").exists())
            self.assertFalse((root / "evidence/summary.json").exists())

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
