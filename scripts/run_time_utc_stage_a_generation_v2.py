#!/usr/bin/env python3
"""Observe one explicitly local Stage A candidate; never publish or transfer qualification."""

import argparse
from collections import Counter
import hashlib
import importlib.util
from importlib.machinery import ModuleSpec
import json
import os
import re
from pathlib import Path
import stat
import sys
import time
import traceback
from types import ModuleType, SimpleNamespace

MODULE_PINS = {
    "scripts/hepta_time_stage_a_v2/contract.py": "5db38c9a56a0a0c9ee501807fcf0619cd1eb8a119d268d2040a35e8eb2a5dd1f",
    "scripts/hepta_time_stage_a_v2/runtime.py": "324304077cb834631a2d35144c0012d9764abf6d7ae0394dad99fd6f2d59171b",
    "scripts/hepta_time_stage_a_v2/source.py": "ca6aedca19c8b74f361a7e29959f5fa94a3ff7d7133100beb55a5c561052beb4",
    "scripts/hepta_time_stage_a_v2/tools.py": "eef77a58b53568f99184fcc87de0c820a9915c352e71eface7905e3489f64f05",
    "scripts/hepta_time_stage_a_v2/generation.py": "2bfc7746d37b435d5bef954c4a57e98f93e641f73e7d2fd9b366e2da025f8901",
    "scripts/hepta_time_stage_a_v2/native.py": "16c10a28916f914150e9335f9ea2c0d0b2725d37e3f4cb04f7ce9da5abddfa40",
    "scripts/run_chrono_hooks_cli_lock_scope_v1.py": "9f7611b839ebe6518260e40cae81344169e7037a8551b1be00a2f20f28513ac2",
    "scripts/hepta_ci_exec.py": "ccabe2e8066c01a612a378d42cd7580ab183870b59921442a0d208b5ac528cba",
    "scripts/hepta_ci_junit.py": "cdb325f4a9266bc554fa266ee6a42dc1e1390b6b45d4bac47fa50aa9255cdeec",
}


def load_reviewed_modules(root):
    if (
        Path(__file__).resolve(strict=True)
        != root / "scripts/run_time_utc_stage_a_generation_v2.py"
    ):
        raise ValueError("entry point is not the actual generation checkout")
    if os.environ.get("PYTHONDONTWRITEBYTECODE") != "1" or sys.version_info < (3, 11):
        raise ValueError("Python 3.11+ without source bytecode writes is required")
    pinned_sources = {}
    for name, expected in MODULE_PINS.items():
        path = root / name
        if (
            path.resolve(strict=True) != path
            or not stat.S_ISREG(path.lstat().st_mode)
            or path.is_symlink()
        ):
            raise ValueError("module is not a regular pinned source: " + name)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("module differs from independently frozen source: " + name)
        pinned_sources[name] = raw

    package_name = "hepta_time_stage_a_v2"
    original_name = "run_chrono_hooks_cli_lock_scope_v1"
    if any(
        name == original_name
        or name == package_name
        or name.startswith(package_name + ".")
        for name in sys.modules
    ):
        raise ValueError("reviewed source modules must not be preloaded")
    package_dir = root / "scripts" / package_name
    package = ModuleType(package_name)
    package.__package__ = package_name
    package.__path__ = [str(package_dir)]
    package.__spec__ = ModuleSpec(package_name, loader=None, is_package=True)
    package.__spec__.submodule_search_locations = package.__path__
    registered = []

    def load_pinned(module_name, relative_path):
        path = root / relative_path
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None or spec.origin != str(path):
            raise ValueError("reviewed module has no exact source spec: " + module_name)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        registered.append((module_name, module))
        # Execute the already hashed bytes, never a second source read or cached pyc.
        code = compile(
            pinned_sources[relative_path],
            str(path),
            "exec",
            dont_inherit=True,
            optimize=0,
        )
        exec(code, module.__dict__)
        if (
            sys.modules.get(module_name) is not module
            or module.__file__ != str(path)
            or module.__spec__ is not spec
        ):
            raise ValueError(
                "reviewed module changed its source identity: " + module_name
            )
        return module

    try:
        load_pinned(original_name, "scripts/" + original_name + ".py")
        sys.modules[package_name] = package
        registered.append((package_name, package))
        loaded = {}
        for name in ("contract", "runtime", "source", "tools", "generation", "native"):
            module = load_pinned(
                package_name + "." + name,
                "scripts/" + package_name + "/" + name + ".py",
            )
            setattr(package, name, module)
            loaded[name] = module
        return SimpleNamespace(**loaded)
    except BaseException:
        for name, module in reversed(registered):
            if sys.modules.get(name) is module:
                del sys.modules[name]
        raise


def generate(ctx, modules):
    c, r = modules.contract, modules.runtime
    admission = r.read_json(ctx.evidence / "source-admission.json")
    r.require(
        ctx.scope.deadline == admission["commands_deadline_monotonic"],
        "engineering deadline differs from the original source admission",
    )
    r.put(
        ctx.evidence / "engineering-invocation-claim.json",
        {
            "started_at": r.now(),
            "started_monotonic": time.monotonic(),
            "deadline": ctx.scope.deadline,
            "single_invocation": True,
        },
    )
    spec, spec_raw = modules.source.load_inputs(ctx)
    r.require(
        r.sha256(spec_raw) == admission["inputs_sha256"],
        "source inputs changed after acquisition",
    )
    event, event_raw = modules.source.validate_event(ctx, spec)
    r.require(
        event == admission["github_event"]
        and r.stable_read(ctx.evidence / "github-event.original.json")[0] == event_raw,
        "original GitHub event changed after acquisition",
    )
    original_raw = r.stable_read(
        ctx.evidence / "generation-source-before.json", 16 * 1024 * 1024
    )[0]
    r.require(
        r.sha256(original_raw) == admission["source_snapshot"]["sha256"],
        "original physical source snapshot changed",
    )
    original = r.json_value(original_raw)
    generation = admission["source"]
    r.require(
        ctx.git("rev-parse", "HEAD").decode().strip() == generation["head"],
        "generation head changed before work",
    )
    ctx.assert_clean()
    r.require(
        ctx.snapshot(generation["tree"]) == original,
        "tool actions changed original source bytes",
    )
    target_dir = ctx.evidence.parent / "cargo-target"
    r.require(not target_dir.exists(), "cargo target directory is not fresh")
    target_dir.mkdir()
    os.environ["CARGO_TARGET_DIR"] = str(target_dir)
    os.environ["CARGO_TERM_COLOR"] = "never"
    os.environ["CARGO_NET_RETRY"] = "0"
    os.environ["NO_COLOR"] = "1"
    reject_environment = (
        "RUSTFLAGS",
        "CARGO_ENCODED_RUSTFLAGS",
        "RUSTC_WRAPPER",
        "RUSTC_WORKSPACE_WRAPPER",
        "RUSTC",
        "CARGO_BUILD_RUSTC_WRAPPER",
        "HEPTA_NEXTTEST_FULL_METADATA",
        "SOURCE_SHA",
        "TESTED_SHA",
        "HEPTA_CI_LANE",
    )
    r.require(
        all(not os.environ.get(name) for name in reject_environment),
        "unreviewed inherited Rust/nextest/native identity override",
    )
    tool_observations = modules.tools.prepare_tools(ctx, spec)
    ctx.assert_clean()
    cargo_before = r.stable_read(ctx.root / "codex-rs/Cargo.lock")[0]
    bazel_before = r.stable_read(ctx.root / "MODULE.bazel.lock")[0]
    r.put_raw(ctx.evidence / "locks-before/codex-rs/Cargo.lock", cargo_before)
    r.put_raw(ctx.evidence / "locks-before/MODULE.bazel.lock", bazel_before)
    modules.generation.overlay_stage_a(ctx, spec, original)
    ctx.command(
        "cargo-workspace-update",
        ["cargo", "update", "--workspace", "--manifest-path", "codex-rs/Cargo.toml"],
        c.PHASE_CAPS["cargo-workspace-update"],
    )
    cargo_generated = r.stable_read(ctx.root / "codex-rs/Cargo.lock")[0]
    lock_delta = modules.generation.verify_cargo_lock(cargo_before, cargo_generated)
    r.put(ctx.evidence / "cargo-lock-delta.json", lock_delta)
    ctx.command(
        "scoped-fix",
        ["just", "fix", "--locked", "-p", c.PACKAGE, "--lib"],
        c.PHASE_CAPS["scoped-fix"],
    )
    # The actual published generation HEAD is the formatter comparison base:
    # only the real A6 overlay is dirty; co-published unrelated changes are not.
    ctx.command(
        "scoped-format",
        ["just", "fmt", "--base", generation["head"]],
        c.PHASE_CAPS["scoped-format"],
    )
    modules.tools.observe_buildifier(ctx)
    metadata_record, metadata_log = ctx.command(
        "locked-metadata",
        [
            "cargo",
            "metadata",
            "--manifest-path",
            "codex-rs/Cargo.toml",
            "--locked",
            "--all-features",
            "--format-version",
            "1",
        ],
        c.PHASE_CAPS["locked-metadata"],
    )
    metadata, metadata_raw, graph = modules.generation.verify_metadata(
        ctx, metadata_log, cargo_generated, spec
    )
    r.put_raw(ctx.evidence / "metadata.extracted-original.json", metadata_raw)
    r.put(
        ctx.evidence / "metadata-verification.json",
        {
            **graph,
            "original_stdout_sha256": r.sha256(metadata_raw),
            "actual_lock_sha256": r.sha256(cargo_generated),
            "original_execution": metadata_record,
            "scope": "Whole workspace locked/all-features metadata; utility-only native controls.",
        },
    )
    ctx.command(
        "bazel-lock-update",
        ["just", "bazel-lock-update"],
        c.PHASE_CAPS["bazel-lock-update"],
    )
    bazel_generated = r.stable_read(ctx.root / "MODULE.bazel.lock")[0]
    r.require(
        r.stable_read(ctx.root / "codex-rs/Cargo.lock")[0] == cargo_generated,
        "later command rewrote the exact lock used by metadata",
    )
    ctx.command(
        "bazel-lock-error-mode",
        ["bazel", "mod", "deps", "--lockfile_mode=error"],
        c.PHASE_CAPS["bazel-lock-error-mode"],
    )
    labels = (
        "//codex-rs/utils/time:time",
        "//codex-rs/utils/time:time-unit-tests",
        "//codex-rs/utils/time:time-unit-tests-bin",
    )
    _, query_log = ctx.command(
        "bazel-query",
        [
            "bazel",
            "query",
            "--lockfile_mode=error",
            "--output=label",
            "set(" + " ".join(labels) + ")",
        ],
        c.PHASE_CAPS["bazel-query"],
    )
    actual_labels = re.findall(r"(?m)^(//[^\s]+)\s*$", query_log.decode())
    r.require(
        Counter(actual_labels) == Counter(labels),
        "Bazel query omitted/duplicated a utility target",
    )
    ctx.command(
        "bazel-analysis",
        [
            "bazel",
            "build",
            "--nobuild",
            "--lockfile_mode=error",
            "//codex-rs/utils/time:time",
            "//codex-rs/utils/time:time-unit-tests",
        ],
        c.PHASE_CAPS["bazel-analysis"],
    )
    r.require(
        r.stable_read(ctx.root / "codex-rs/Cargo.lock")[0] == cargo_generated
        and r.stable_read(ctx.root / "MODULE.bazel.lock")[0] == bazel_generated,
        "locked verification rewrote a generated lock",
    )
    modules.generation.verify_generation_boundary(
        ctx, generation["tree"], original, spec
    )
    postimages = modules.generation.retain_postimages(ctx, "candidate-postimages")
    r.put(
        ctx.evidence / "generated-locks.json",
        {
            "cargo": r.leaf_pin(cargo_generated, "100644"),
            "bazel": r.leaf_pin(bazel_generated, "100644"),
            "previous_bazel_bytes_reused_if_identical": bazel_generated == bazel_before,
            "cargo_workspace_update_invocations": 1,
            "bazel_lock_update_invocations": 1,
            "extra_old_baseline_lock_generation_invocations": 0,
            "metadata_original_lock_sha256": r.sha256(cargo_generated),
            "candidate_postimages": postimages,
        },
    )
    candidate, candidate_snapshot, envelope = modules.generation.create_local_candidate(
        ctx, generation, original, spec
    )
    _, listed_log = ctx.command(
        "nextest-list", c.native_list_command(), c.PHASE_CAPS["nextest-list"]
    )
    modules.native.verify_list(ctx, listed_log)
    r.require(
        ctx.snapshot(candidate["tree"]) == candidate_snapshot,
        "list step changed the actual candidate source",
    )
    observation = modules.native.native_observation(
        ctx, candidate, candidate_snapshot, event
    )
    return {
        "status": "LOCAL_DERIVED_CANDIDATE_ONLY",
        "actual_native16_observed": True,
        "source_generation_head": generation,
        "local_tested_identity": candidate,
        "github_event": event,
        "generation_and_native_are_different_declared_identities": True,
        "local_candidate_envelope": envelope,
        "actual_tool_observation_count": len(tool_observations["versions"]),
        "metadata_graph": graph,
        "cargo_lock_delta": lock_delta,
        "native_observation": observation,
        "requires_Root_source_postimage_and_generated_lock_review": True,
        "requires_actual_publication_readback_before_any_qualification_transfer": True,
        **c.FALSE_QUALIFICATION,
    }


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("mode", choices=("begin", "generate"))
    mode = args.parse_args().mode
    root = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    modules = load_reviewed_modules(root)
    c, r = modules.contract, modules.runtime
    evidence = Path(os.environ["STAGE_A_EVIDENCE"]).resolve(strict=True)
    r.require(
        not evidence.is_relative_to(root) and not root.is_relative_to(evidence),
        "evidence and checkout must be disjoint",
    )
    os.chdir(root)
    for key in list(os.environ):
        if key.startswith("GIT_"):
            del os.environ[key]
    os.environ.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    clock = r.read_json(
        evidence / ("job-start.json" if mode == "begin" else "source-admission.json")
    )
    started = clock[
        "source_started_monotonic"
        if mode == "begin"
        else "engineering_started_monotonic"
    ]
    cap = c.SOURCE_CAP if mode == "begin" else c.ENGINEERING_CAP - c.FINAL_RESERVE
    ctx = r.Context(root, evidence, mode, started, cap)
    report = {
        "schema": "hepta.time-utc-stage-a-generation-result.v2",
        "mode": mode,
        "status": "FAIL",
        "started_at": r.now(),
        "old_source_acquisition_seconds": c.PRIOR_SOURCE_SECONDS,
        "previous_attempt": c.PREVIOUS_ATTEMPT,
        "old_scopes_reopened": False,
        "automatic_retry": False,
        "phase_timings_are_nested_not_additive": True,
        "github_writes": 0,
        **c.FALSE_QUALIFICATION,
    }
    try:
        report.update(
            modules.source.begin(ctx) if mode == "begin" else generate(ctx, modules)
        )
        ctx.check_time()
    except Exception as error:
        report.update(
            status="FAIL",
            error=f"{type(error).__name__}: {error}",
            traceback=traceback.format_exc(),
        )
    finally:
        if mode == "generate" and report["status"] == "FAIL":
            try:
                report["failed_postimages"] = modules.generation.retain_postimages(
                    ctx, "failed-postimages"
                )
            except Exception as error:
                report["failed_postimage_retention_error"] = (
                    f"{type(error).__name__}: {error}"
                )
        report["finished_at"] = r.now()
        report["phase_observation"] = ctx.scope.receipt()
        report["absolute_command_deadline_monotonic"] = ctx.scope.deadline
        report[
            "final_result_io_and_artifact_transport_require_workflow_terminal_readback"
        ] = True
        r.put(evidence / (mode + ".RESULT.json"), report)
        print(json.dumps(report, sort_keys=True), flush=True)
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
