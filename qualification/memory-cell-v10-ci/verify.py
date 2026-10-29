"""Ordinary Rust regressions, then exactly one new trained native owner lifecycle."""

import os
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET

from common import HERE, ROOT, actual_command, git, git_text, identity, load, ordinary_command, require, save, source_inventory
from inputs import prepare


REQUIRED = (
    "NATIVE_ACTUAL.json", "owner-before.json", "owner-corrected.json", "owner-deleted.json",
    "original-checkpoint/LEGACY_TORCH.json", "original-checkpoint/PARITY.json",
    "original-checkpoint/RUST_NATIVE_PARITY.json",
    "original-checkpoint/semantic.json", "original-checkpoint/procedure.json",
    "corrected-training/TRAINING.json", "corrected-training/PARITY.json",
    "corrected-training/RUST_NATIVE_PARITY.json",
    "corrected-training/semantic.json", "corrected-training/procedure.json",
    "deleted-rebuild/TRAINING.json", "deleted-rebuild/PARITY.json",
    "deleted-rebuild/RUST_NATIVE_PARITY.json",
    "deleted-rebuild/semantic.json", "deleted-rebuild/procedure.json",
    "deleted-rebuild/inventory-router/manifest.json", "inventory-migration/MIGRATION.json",
)


def retain_junit(target, output, name):
    source = target / "nextest/local/junit.xml"
    require(source.is_file(), "nextest JUnit report is missing")
    destination = output / (name + "-junit.xml")
    shutil.copyfile(source, destination)
    root = ET.parse(destination).getroot()
    cases = root.findall(".//testcase")
    require(bool(cases) and any(case.find("skipped") is None for case in cases), "nextest selected no running tests")
    require(not root.findall(".//failure") and not root.findall(".//error"), "nextest JUnit has a failed case")
    if name == "actual":
        from common import ACTUAL_TEST
        require(len(cases) == 1 and ACTUAL_TEST.rsplit("::", 1)[1] in cases[0].get("name", ""),
                "actual JUnit must contain the exact selected parent test")
    return {"path": destination.name, "cases": len(cases), **identity(destination)}


def numeric_receipts(actual):
    result = {}
    for stage, counts in (("original-checkpoint", (8, 8)), ("corrected-training", (8, 8)), ("deleted-rebuild", (7, 8))):
        path = actual / stage / "RUST_NATIVE_PARITY.json"
        parity = load(path, 8_000_000)
        require(parity.get("schema") == "hepta.memory.inventory-native-numeric-actual.v1"
                and parity.get("status") == "passed" and parity.get("absolute_tolerance") == 1e-4
                and parity.get("relative_tolerance") == 1e-5, "native numeric parity contract differs")
        models = parity.get("models")
        require(isinstance(models, list) and len(models) == 2
                and {model["kind"] for model in models} == {"semantic", "procedure"}, "native numeric model inventory differs")
        by_kind = {model["kind"]: model for model in models}
        for kind, count in zip(("semantic", "procedure"), counts, strict=True):
            rows = by_kind[kind]["rows"]
            require(len(rows) == count and all(row.get("within_declared_tolerance") is True for row in rows),
                    "native numeric parity has incomplete or failed rows")
        result[stage] = {"rows": sum(counts), **identity(path)}
    return result


def run(runner, runtime, receipt):
    sources = source_inventory()
    save(runner.output / "SOURCE_FILES.json", sources)
    receipt["source_inventory"] = identity(runner.output / "SOURCE_FILES.json")
    receipt["tests_executed"] = True
    save(runner.output / "receipt.json", receipt)
    runner.execute("driver-evidence-boundaries", [sys.executable, "-I", "-B", "-m", "unittest", "discover",
                   "-s", str(HERE), "-p", "ci_tests.py"])
    inputs = prepare(runner, runtime)
    # The frozen script hashes its entire research directory and the two legacy
    # model/encoder implementations. It does not run any old or new holdout.
    runner.execute("research-source-freeze", [inputs["python"], "-B",
                   str(ROOT / "qualification/memory-cell-v10/freeze_source.py")])
    target = Path(os.environ["CARGO_TARGET_DIR"])
    require(target.is_absolute(), "absolute Cargo target directory required")
    environment = {**os.environ, "HEPTA_TEST_CODEX_EXECUTABLE": str(target / "debug/codex-app-server"),
                   "MEMORY_CELL_NETWORK_PROCESS_RECEIPT_PATH": str(runner.output / "ordinary-network-process.json"),
                   "HEPTA_MEMORY_V10_PYTHON": inputs["python"],
                   "HEPTA_MEMORY_V10_RESEARCH_ROOT": inputs["research"],
                   "HEPTA_MEMORY_V10_ENCODER": inputs["encoder"],
                   "HEPTA_MEMORY_V10_LEGACY_ROOT": inputs["legacy"],
                   "HEPTA_MEMORY_V10_EVIDENCE": str(runner.output / "native-actual")}
    require(not any(name.startswith(("MEMORY_CELL_V7_", "MEMORY_CELL_V8_", "MEMORY_CELL_V9_"))
                    for name in os.environ), "old qualification environment must not be supplied")
    runner.execute("same-source-app-server", ["cargo", "build", "--locked", "--manifest-path", "codex-rs/Cargo.toml",
                   "-p", "codex-app-server", "--bin", "codex-app-server"], env=environment)
    runner.execute("ordinary-scoped-rust", ordinary_command(), env=environment)
    receipt["ordinary_junit"] = retain_junit(target, runner.output, "ordinary")
    receipt["ordinary_scoped_tests_passed"] = True
    save(runner.output / "receipt.json", receipt)
    runner.execute("actual-trained-owner-lifecycle", actual_command(), env=environment)
    receipt["actual_junit"] = retain_junit(target, runner.output, "actual")
    actual = runner.output / "native-actual"
    missing = [name for name in REQUIRED if not (actual / name).is_file()]
    receipt["missing_required_receipts"] = missing
    require(not missing, "native actual evidence incomplete: " + repr(missing))
    report = load(actual / "NATIVE_ACTUAL.json", 32_000_000)
    require(report.get("schema") == "hepta.memory.inventory-native-actual.v1"
            and report.get("status") == "passed" and report.get("old_holdout_run") is False
            and report.get("separate_owner_processes") == 5, "actual lifecycle completion contract differs")
    receipt["native_actual_identity"] = identity(actual / "NATIVE_ACTUAL.json")
    receipt["native_numeric_parity"] = numeric_receipts(actual)
    receipt["required_native_artifacts"] = {name: identity(actual / name) for name in REQUIRED}
    receipt["actual_trained_owner_lifecycle_passed"] = True
    require(source_inventory() == sources, "tests changed a protected source or source inventory")
    require(git_text("status", "--porcelain", "--untracked-files=no") == "", "tests modified tracked source")
    (runner.output / "generated.patch").write_bytes(git("diff", "--binary"))
    receipt.update(passed=True, tests_executed=True, tests_before_final_fix_and_format=True,
                   final_fix_executed=False, formatter_executed=False,
                   full_research_matrix_executed=False, scientific_superiority_claimed=False,
                   complete_workspace_test=False, old_holdout_run=False)
