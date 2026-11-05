"""Assemble reviewed B inputs and a read-only native execution specification.

This script runs only Git/Python against its own scratch directory. It never
launches Cargo/Bazel, changes a native checkout, or supplies a final A guard.
"""

import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[1]
FOUNDATION = WORKSPACE / "architecture-audit/b16-b-serial-alignment-20261105"
ADOPTION = WORKSPACE / "architecture-audit/sqlx-adoption-test-entry-20261105"
DRIVER = WORKSPACE / "architecture-audit/sqlx-native-lifetime-token-20261105"
BINDING = WORKSPACE / "architecture-audit/b16-state-native-token-binding-20261105"
CHECKPOINT = WORKSPACE / "research-audit/b16-recovery-checkpoint-custody"
VENDOR = "codex-rs/third_party/sqlx-sqlite-0.9.0"


def identity(data):
    return {"blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def read(path, expected):
    data = path.read_bytes()
    assert identity(data)["blob"] == expected, (str(path), identity(data))
    return json.loads(data)


foundation = read(FOUNDATION / "serial-plan.json", "a46fdc65f78295bfb041732aeb03b1937f85eab9")
adoption = read(ADOPTION / "adoption-manifest-v2.json", "55519677d2d26c24e797eeed0db816331107b0c9")
driver = read(DRIVER / "repair-manifest.json", "9262807373267fe42587a36a50721aa08b60c56b")
binding = read(BINDING / "repair-manifest.json", "781d9153910147841372cf60ab4919033668c5cd")
checkpoint = read(CHECKPOINT / "repair-manifest.json", "8c39e58cacf1303283ca5854d3ba78673b1ebda2")
vendor_inventory = read(ADOPTION / "complete-vendor-static-assembly.json", "2193443e1cbbd2017ba56d036f863f80cc2b187f")
directory = ROOT / "static-final-partial-tree-v3"
directory.mkdir(exist_ok=False)
subprocess.run(["git", "init", "-q"], cwd=directory, check=True)
events = []


def digest_file(path):
    return identity((directory / path).read_bytes())["blob"] if (directory / path).exists() else None


def copy_checked(source, path, expected):
    data = source.read_bytes()
    assert identity(data)["blob"] == expected
    target = directory / path
    assert not target.exists(), path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    target.chmod(0o644)


def apply(path, expected_blob, mapping=None):
    assert identity(path.read_bytes())["blob"] == expected_blob
    options = ["-p2", "--directory=" + VENDOR] if mapping == "driver" else []
    for check in (True, False):
        argv = ["git", "apply"] + (["--check"] if check else []) + options + [str(path)]
        result = subprocess.run(argv, cwd=directory, capture_output=True, text=True)
        events.append({"argv": [x.replace(str(WORKSPACE) + "/", "") for x in argv],
                       "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        assert result.returncode == 0, events[-1]


for path, blob in foundation["final_partial_source_map"].items():
    copy_checked(FOUNDATION / "static-full-patches" / path, path, blob)
vendor_files = vendor_inventory["final_source_map"]
actual_vendor_paths = {str(f.relative_to(ADOPTION / "complete-vendor-static-assembly"))
                       for f in (ADOPTION / "complete-vendor-static-assembly").rglob("*")
                       if f.is_file() and ".git" not in f.parts}
assert actual_vendor_paths == {row["path"] for row in vendor_files}
for row in vendor_files:
    copy_checked(ADOPTION / "complete-vendor-static-assembly" / row["path"], row["path"], row["blob"])

# Negatives on the vendored dependency must strip the upstream prefix exactly.
for negative in driver["negative_controls"]:
    local = negative["exact_negative_postimage"]["path"].removeprefix("sqlx-sqlite/")
    mapped = VENDOR + "/" + local
    before = digest_file(mapped)
    apply(DRIVER / negative["patch"]["path"], negative["patch"]["blob"], "driver")
    assert digest_file(mapped) == negative["exact_negative_postimage"]["blob"]
    apply(DRIVER / negative["restore"]["path"], negative["restore"]["blob"], "driver")
    assert digest_file(mapped) == before

for item in binding["changes"]:
    assert digest_file(item["path"]) == item["before_blob"]
apply(BINDING / binding["patch"]["path"], binding["patch"]["blob"])
for item in binding["changes"]:
    assert digest_file(item["path"]) == item["after_blob"]
before_binding_negative = {x["path"]: digest_file(x["path"]) for x in binding["changes"]}
apply(BINDING / binding["counterfactual"]["patch"]["path"], binding["counterfactual"]["patch"]["blob"])
apply(BINDING / binding["counterfactual"]["restore"]["path"], binding["counterfactual"]["restore"]["blob"])
assert {x: digest_file(x) for x in before_binding_negative} == before_binding_negative

for item in checkpoint["physical_control_cohort"]["files"]:
    if item["before"] and digest_file(item["path"]) is None:
        copy_checked(CHECKPOINT / "source" / item["path"], item["path"], item["before"]["blob"])
for section, filename in [("production_cohort", "production-custody.patch"),
                          ("physical_control_cohort", "memory-physical-control.patch")]:
    for item in checkpoint[section]["files"]:
        assert digest_file(item["path"]) == (item["before"]["blob"] if item["before"] else None)
    apply(CHECKPOINT / filename, checkpoint[section]["patch"]["blob"])
    for item in checkpoint[section]["files"]:
        assert digest_file(item["path"]) == item["after"]["blob"]
physical = checkpoint["physical_control_cohort"]
apply(CHECKPOINT / "negative-checkpoint-native-binding.patch", physical["negative"]["patch"]["blob"])
assert digest_file("codex-rs/state/src/sqlite.rs") == physical["negative"]["source"]["blob"]
apply(CHECKPOINT / "restore-checkpoint-native-binding.patch", physical["restore"]["blob"])
assert digest_file("codex-rs/state/src/sqlite.rs") == checkpoint["production_cohort"]["files"][0]["after"]["blob"]
assert digest_file("codex-rs/state/src/sqlite_commit_gate_tests.rs") == "31b26a78bffe40815aa8a5b55e61b5139e7bca96"

source_map = [{"path": str(p.relative_to(directory)), "mode": "100644", **identity(p.read_bytes())}
              for p in sorted((directory / "codex-rs").rglob("*")) if p.is_file()]
features = ["bundled", "chrono", "json", "migrate", "offline", "serde", "time", "uuid"]
driver_args = ["just", "test", "-p", "sqlx-sqlite", "--lib", "--locked", "--retries", "0",
               "--features", ",".join(features)]


def exact_argv(package, names, extra=()):
    return ["just", "test", "-p", package, "--lib", "--locked", "--retries", "0", *extra,
            "-E", " | ".join("test(=" + name + ")" for name in names)]


phases = []
for authored in foundation["proposed_native_sequence"]:
    phase = dict(authored)
    phase["group"] = "foundation_before_native_options_binding"
    phase["argv"] = shlex.split(authored["command"])
    phase["unmodified_authored_command"] = authored["command"]
    phase["native_state"] = "PENDING"
    phases.append(phase)
phases.append({"id": "B11_driver_adoption_and_first_locks", "group": "driver",
               "source_manifest": "55519677d2d26c24e797eeed0db816331107b0c9",
               "complete_payload": "ed4b2ade11ac009426131347a127419a179fcf73",
               "operations": adoption["adoption_sequence"][:3],
               "guard": "Recheck final A root Cargo preimage and every then-current foundation source; no native binding yet.",
               "native_state": "PENDING"})
for index, negative in enumerate(driver["negative_controls"], 12):
    phases.append({"id": f"B{index}_driver_{negative['name']}", "group": "driver",
                   "argv": driver_args + ["-E", " | ".join("test(=" + n + ")" for n in negative["selected"])],
                   "exact_names": negative["selected"], "expected": "QUALIFIED_PHYSICAL_FAILURE",
                   "counterfactual": negative, "git_apply_extra": ["-p2", "--directory=" + VENDOR],
                   "finally": "Restore exact approved driver source even on setup or causal mismatch; no later phases on mismatch.",
                   "native_state": "PENDING"})
roster = adoption["own_unit_roster"]
phases.append({"id": "B14_driver_twelve", "group": "driver", "argv": driver_args,
               "exact_names": roster["original_names"] + roster["new_parent_names"],
               "expected": "12_SELECTED_PASS_ZERO_RETRIES", "ignored_support": roster["ignored_support"],
               "owning_original_tests": 8, "new_parent_controls": 4, "native_state": "PENDING"})
phases.append({"id": "B15_driver_bazel_registration", "group": "driver",
               "target": "//codex-rs/third_party/sqlx-sqlite-0.9.0:sqlx-sqlite-unit-tests",
               "original_gate": "Use original approved Bazel platform/config and actual generated @crates DEP_DATA; no fabricated registration or output paths.",
               "native_state": "PENDING"})
binding_names = binding["exact_new_parent_tests"]
for suffix, negative in [("negative", True), ("fixed", False)]:
    phases.append({"id": "B16_pool_binding_" + suffix, "group": "pool_binding",
                   "apply_patches": [binding["patch"], binding["counterfactual"]["patch"]] if negative else [],
                   "counterfactual": binding["counterfactual"] if negative else None,
                   "finally_restore": binding["counterfactual"]["restore"] if negative else None,
                   "fixed_stage_precondition": "The negative phase always restores the exact binding postimage before this positive stage; do not apply the restore twice.",
                   "commands": [{"package": pkg, "argv": exact_argv(pkg, [x["name"] for x in binding_names if x["package"] == pkg]),
                                 "exact_names": [x["name"] for x in binding_names if x["package"] == pkg]}
                                for pkg in ["codex-state", "codex-hepta-memory"]],
                   "expected": "3_QUALIFIED_PHYSICAL_FAILURES" if negative else "3_SELECTED_PASS",
                   "ordering": "Only after all 24 foundation controls and driver adoption/12 actual driver cases.",
                   "native_state": "PENDING"})
phases.append({"id": "B17_checkpoint_source_and_second_locks", "group": "checkpoint",
               "production_patch": checkpoint["production_cohort"]["patch"],
               "controls_patch": physical["patch"], "changed_dependency": physical["dependency_change"],
               "commands": [["cargo", "metadata", "--format-version=1"], ["just", "bazel-lock-update"], ["just", "bazel-lock-check"]],
               "required_real_result": "Fresh actual Cargo.lock/MODULE resolution, source map, metadata and generated DEP_DATA after the new Memory dev-edge. Either lock may change or remain equal; preserve actual result.",
               "native_state": "PENDING"})
phases.append({"id": "B18_checkpoint_negative", "group": "checkpoint",
               "counterfactual": physical["negative"], "restore": physical["restore"],
               "argv": exact_argv("codex-hepta-memory", [physical["selected_parent"]]),
               "exact_names": [physical["selected_parent"]],
               "causal_acceptance": physical["counterfactual_endpoint"],
               "invalid_negative": physical["invalid_negative"], "finally": "Restore exact checkpoint binding even on failure; stop if causal endpoint is not met.",
               "native_state": "PENDING"})
phases.append({"id": "B19_checkpoint_and_original_recovery", "group": "checkpoint",
               "argv": ["just", "test", "-p", "codex-hepta-memory", "--lib", "--locked", "--retries", "0", "-E", "test(cognitive_store::recovery::tests::)"],
               "exact_names_on_linux": [x["name"] for x in checkpoint["original_test_gate"]["definitions"]] + [physical["selected_parent"]],
               "ignored_support": physical["support"]["name"], "expected": "15_SELECTED_LINUX_PASS_INCLUDING14_ORIGINAL; actual catalog is mandatory", "native_state": "PENDING"})
phases.append({"id": "B20_owning_and_hygiene", "group": "final", "commands": [
    ["just", "test", "-p", "codex-state", "--lib", "--locked", "--retries", "0"],
    ["just", "test", "-p", "codex-hepta-memory", "--lib", "--locked", "--retries", "0"],
    ["just", "fix", "-p", "sqlx-sqlite", "-p", "codex-state", "-p", "codex-hepta-memory"],
    ["just", "fmt"], ["just", "bazel-lock-check"]],
    "guard": "Authoritative fresh owning catalog, complete raw/JUnit, exact source and helper identities. Review every fix/fmt delta, including upstream vendor files; no assumption that formatting touches only authored lines.",
    "native_state": "PENDING"})

plan = {
    "schema": "hepta-b16-native-adoption-runner-specification-v1",
    "status": "SOURCE_ONLY_PLAN_AND_STATIC_PARTIAL_COMPOSITION_NO_NATIVE_RUN",
    "intended_native_platform": "Linux; exact host/toolchain receipt required. No Windows or macOS qualification is implied by these expected rosters.",
    "original_recipe": {"repository_path": "justfile", "blob": "a215a76cf407ace9715bca39c20497014e7dd4dc", "working_directory": "codex-rs unless recipe explicitly no-cd", "test": "Original just test sets RUST_MIN_STACK=8388608 and NEXTEST_PROFILE=local then scripts/run-nextest.py; do not replace with direct cargo test.", "locks": "Original just bazel-lock-update: bazel mod deps --lockfile_mode=update; original just bazel-lock-check invokes scripts/check-module-bazel-lock.sh on Unix."},
    "execution_owner": "/root/ci_audit after root approves final A source and B guard",
    "initial_guard": {"final_A_tree": None, "required_before_launch": ["Full exact final A tree after final fix/fmt/publication boundary", "All foundation original preimages/absence checks", "Root Cargo471374... and Memory Cargo048e... exact preimages or separately reviewed realignment", "Current complete native workspace metadata and actual target/profile", "No concurrent Cargo/Bazel/source writer"]},
    "source_manifests": {"foundation": "a46fdc65f78295bfb041732aeb03b1937f85eab9", "driver": "9262807373267fe42587a36a50721aa08b60c56b", "adoption": "55519677d2d26c24e797eeed0db816331107b0c9", "pool_binding": "781d9153910147841372cf60ab4919033668c5cd", "checkpoint": "8c39e58cacf1303283ca5854d3ba78673b1ebda2"},
    "strict_order": ["foundation24", "driver_adoption_and_driver12", "pool_binding3", "private_checkpoint1_and_original14", "owning_and_hygiene"],
    "causal_isolation": "Applying native pool options binding before foundation R2e3 would keep real custody even after old hook/collation removal, invalidating that historical counterfactual's expected lock acquisition. Do not reorder or count this as a product failure.",
    "lock_boundaries": ["Driver local-member/root patch/vendor manifest/BUILD adoption", "Later Memory libsqlite3-sys dev-edge for actual private checkpoint control"],
    "phases": phases,
    "metadata_contract": {"driver": {"name": "sqlx-sqlite", "version": "0.9.0", "source": None, "manifest_relative": VENDOR + "/Cargo.toml", "must_be_workspace_member": True, "exact_observed_features": features, "reject_unused_patch_or_second_selected_registry_driver": True}, "core": {"name": "sqlx-core", "version": "0.9.0", "required_test_runtime_feature": "_rt-tokio"}, "sqlite_links": "Exactly the real libsqlite3-sys0.37.0 closure; verify metadata and runtime SELECT sqlite_version from R2c pool, not system Python SQLite."},
    "receipts": {"per_phase": ["Exact full-source before/after, complete changed-file map", "Original argv/env/profile plus full graph/actual package manifest path", "Fresh catalog and exact selected name set; skipped/ignored/filtered separate", "Complete raw and fresh JUnit with run UUID, zero retries", "Controller terminal status and exact negative endpoint, not status vector alone", "Physical child callback/gate/lock evidence and cleanup result", "Finally exact restore proof before a subsequent phase"], "negative_verdict": "Structural failure counts and text markers are only prerequisites. Root must read original case output and confirm the actual physical endpoint; generic failure/timeout is not proof.", "child_stdout_limit": "Several frozen fixtures retain stage markers but discard other child stdout. Do not claim complete child stdout; preserve all output the existing parent actually exposes."},
    "counts": {"foundation_unique_new": 24, "driver_original": 8, "driver_new_parent": 4, "pool_new_parent": 3, "checkpoint_new_parent": 1, "unique_new_controls": 32, "driver_and_new_control_union": 40, "existing_owning_counts": "derive fresh native catalog, not predicted", "ignored_supports": [roster["ignored_support"], binding["state_support"]["exact_name"], physical["support"]["name"]]},
    "static_composition": {"partial_source_files": len(source_map), "exact_files": source_map, "git_commands": events, "not_full_candidate_tree": True, "original_R2c_V3_observation_preserved": True},
    "still_open_after_native_pass": ["Actual independent authority peer and Current three-pool binder", "Normal Root signed producer/lease/revocation/FinalUse acceptance", "Independent non-opt-in opens and any unbound caller not covered by these exact APIs", "All original required CI platform qualification", "No B16 closure merely from a DTO, native token API or selected tests"],
}
(ROOT / "execution-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
print(json.dumps({"status": plan["status"], "phases": len(phases), "partial_source_files": len(source_map), "git_commands": len(events), "counts": plan["counts"], "plan": identity((ROOT / "execution-plan.json").read_bytes())}, indent=2))
