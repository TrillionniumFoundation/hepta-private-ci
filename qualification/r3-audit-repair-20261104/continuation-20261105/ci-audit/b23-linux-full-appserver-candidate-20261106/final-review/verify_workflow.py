from pathlib import Path
import argparse
import copy
import difflib
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import yaml

ROOT = Path(__file__).resolve().parent
TARGET = "//codex-rs/app-server:app-server-unit-tests"
WORKFLOW_PATH = ".github/workflows/hepta-b23-linux-app-server-original-gate.yml"


def identity(data):
    return {
        "bytes": len(data),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def api_tree(path):
    raw = json.loads(path.read_text())
    value = raw.get("structuredContent")
    if value is None:
        value = json.loads(next(item["text"] for item in raw["content"] if item["type"] == "text"))
    return json.loads(value["content"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", type=Path)
    parser.add_argument("--collector", type=Path)
    args = parser.parse_args()
    path = args.workflow or ROOT / "draft" / (WORKFLOW_PATH + ".template")
    proof_dir = ROOT / ("verification-final" if args.collector else "verification-draft")
    proof_dir.mkdir(parents=True, exist_ok=True)
    data = path.read_bytes()
    text = data.decode()
    workflow = yaml.safe_load(text)
    baseline = yaml.safe_load((ROOT / "source/.github/workflows/bazel.yml").read_text())
    job, original = workflow["jobs"]["test"], baseline["jobs"]["test"]
    assert set(workflow["on"]) == {"pull_request"}
    assert "workflow_dispatch" not in workflow["on"]
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert job["timeout-minutes"] == original["timeout-minutes"] == 120
    assert job["runs-on"] == original["runs-on"]
    assert job["strategy"]["fail-fast"] is False
    assert job["strategy"]["matrix"]["include"] == [
        {"os": "ubuntu-24.04", "target": "x86_64-unknown-linux-gnu"}
    ]
    assert job["environment"] == original["environment"]
    old_steps = original["steps"]
    steps = job["steps"]
    by_name = {step.get("name"): step for step in steps}
    old_by_name = {step.get("name"): step for step in old_steps}
    assert steps[0] == old_steps[0]
    unchanged_steps = [
        "Prepare Bazel CI", "Check rusty_v8 MODULE.bazel checksums",
        "Check MODULE.bazel.lock is up to date", "Save bazel repository cache",
        "Check for a clean worktree",
    ]
    for name in unchanged_steps:
        assert by_name[name] == old_by_name[name], name
    syntax = []
    embedded = {}
    for step in steps:
        if "run" not in step:
            continue
        command = step["run"]
        parsed = subprocess.run(["bash", "-n"], input=command, text=True, capture_output=True)
        assert parsed.returncode == 0, (step.get("name"), parsed.stderr)
        python_blocks = re.findall(r"<<'PY'\n(.*?)\nPY(?:\n|$)", command, re.S)
        for index, code in enumerate(python_blocks):
            compile(code, step.get("name", "step") + str(index), "exec")
        embedded[step.get("id", step["name"])] = python_blocks
        syntax.append({"name": step["name"], "bash_syntax": "passed",
                       "python_blocks_compiled": len(python_blocks)})
    guard_text = (ROOT / "source_identity.py").read_text()
    assert embedded["source_before"] == [guard_text.rstrip()]
    if args.collector:
        collector = args.collector.read_text()
        assert len(embedded["evidence"]) == 1
        assert (embedded["evidence"][0] + "\n").encode() == args.collector.read_bytes()
        assert identity(args.collector.read_bytes()) == {
            "bytes": 34905,
            "git_blob": "00dc37697adde6154a347963ab19e8a6edebac07",
            "sha256": "7d8962de05fae508b259c1e16efa1be78a760c4a6a0da8ec239e796f3d1cdd1c",
        }
        before = next(step for step in steps if step.get("id") == "source_before")["run"]
        assert 'command -v zstd >"${RUNNER_TEMP}/b23-app-server-evidence/zstd-path.txt"' in before
        assert 'zstd --version >"${RUNNER_TEMP}/b23-app-server-evidence/zstd-version.txt"' in before
        ids_before = [step.get("id") for step in steps]
        assert ids_before.index("source_before") < ids_before.index("bazel")
        collector_scope = "exact accepted collector bytes embedded"
    else:
        assert "collector pending independent acceptance; draft only" in embedded["evidence"][0]
        collector_scope = "explicit unaccepted placeholder; not publishable"
    run_step = next(step for step in steps if step.get("id") == "bazel")
    run = run_step["run"]
    assert run_step["env"] == old_by_name["bazel test //..."]["env"]
    assert run_step["continue-on-error"] is True
    for forbidden in (
        "--test_filter", "--test_arg", "--test_timeout", "--flaky_test_attempts",
        "--runs_per_test", "--test_sharding_strategy", "--jobs", "RUST_TEST_THREADS",
    ):
        assert forbidden not in run, forbidden
    assert TARGET in run and "//..." not in run
    uploads = [step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@")]
    assert len(uploads) == 2
    for step in uploads:
        assert step["uses"] == "actions/upload-artifact@bbbca2ddaa5d8feaa63e36b76fdaad77386f024f"
        assert "steps.evidence.outputs.safe-for-upload == 'true'" in step["if"]
        assert step["with"]["if-no-files-found"] == "error"
        assert "private" not in step["with"]["path"]
    ids = [step.get("id") for step in steps]
    assert ids.index("source_after") < ids.index("evidence") < ids.index("upload_evidence")
    final_script = by_name["Preserve the original result and require complete evidence"]["run"]
    wrapper_fixtures = []
    for label, native_exit, tee_failure in (("pass", 0, False), ("original-failure", 3, False), ("copy-failure", 0, True)):
        with tempfile.TemporaryDirectory(prefix="b23-static-exit-") as temporary:
            fixture = Path(temporary)
            wrapper = fixture / ".github/scripts/run-bazel-ci.sh"
            wrapper.parent.mkdir(parents=True)
            wrapper.write_text(
                "#!/bin/bash\n"
                "printf '%s\\0' \"$@\" >\"$STUB_ARGS\"\n"
                "printf '%s\\n' 'STATIC STAND-IN ONLY; NO BAZEL OR PRODUCT TEST EXECUTED'\n"
                "exit \"$STUB_EXIT\"\n"
            )
            wrapper.chmod(0o755)
            runner = fixture / "runner"
            public = runner / "b23-app-server-evidence"
            public.mkdir(parents=True)
            if tee_failure:
                (public / "console.log").symlink_to("/dev/full")
            env = {
                "PATH": os.environ["PATH"], "RUNNER_TEMP": str(runner),
                "GITHUB_SHA": "0" * 40, "STUB_ARGS": str(fixture / "argv.bin"),
                "STUB_EXIT": str(native_exit),
            }
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-c", run],
                cwd=fixture, env=env, capture_output=True, text=True,
            )
            observed = [entry.decode() for entry in (fixture / "argv.bin").read_bytes().split(b"\0")[:-1]]
            expected = [
                "--print-failed-action-summary", "--print-failed-test-logs", "--",
                "test", "--test_tag_filters=-argument-comment-lint",
                "--test_verbose_timeout_warnings", "--build_metadata=COMMIT_SHA=" + "0" * 40,
                "--nocache_test_results",
                "--build_event_json_file=" + str(runner / "b23-app-server-private/build-events.jsonl"),
                "--nobuild_event_json_file_path_conversion", "--", TARGET,
            ]
            assert observed == expected, observed
            assert result.returncode == native_exit, (label, result.returncode)
            native_text = (public / "original-bazel-exit-code.txt").read_bytes()
            copy_text = (public / "console-copy-exit-code.txt").read_bytes()
            assert native_text == str(native_exit).encode() + b"\n"
            assert int(copy_text) == (1 if tee_failure else 0), (label, copy_text)
            for phase in ("before", "after"):
                (public / ("source-" + phase + ".json")).write_text('{"status":"passed"}\n')
            # Deliberately optimistic synthetic outcomes exercise the independent
            # final exit-file gate. This is not a source guard or native run.
            final_env = dict(env)
            for key in (
                "ORIGINAL_OUTCOME", "SOURCE_BEFORE_OUTCOME", "SOURCE_AFTER_OUTCOME",
                "EVIDENCE_OUTCOME", "EVIDENCE_UPLOAD_OUTCOME", "COMPACT_UPLOAD_OUTCOME",
                "JOB_STATUS",
            ):
                final_env[key] = "success"
            final_env["ARTIFACT_SAFE"] = "true"
            final = subprocess.run(
                ["bash", "--noprofile", "--norc", "-c", final_script],
                cwd=fixture, env=final_env, capture_output=True, text=True,
            )
            should_pass = native_exit == 0 and not tee_failure
            assert (final.returncode == 0) == should_pass, (label, final.stderr)
            (proof_dir / (label + ".stdout.log")).write_text(result.stdout + final.stdout)
            (proof_dir / (label + ".stderr.log")).write_text(result.stderr + final.stderr)
            wrapper_fixtures.append({
                "case": label, "synthetic_wrapper_exit": result.returncode,
                "saved_original_exit": int(native_text), "saved_console_copy_exit": int(copy_text),
                "final_gate_exit": final.returncode, "exact_argument_sequence": True,
                "actual_bazel_or_product_execution": False,
            })
    spec = importlib.util.spec_from_file_location("b23_source_identity", ROOT / "source_identity.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    trees = {name: api_tree(ROOT / "source-api" / ("base-" + name + "-tree.original.json"))
             for name in ("root", "github", "workflows")}
    for tree in trees.values():
        assert not tree["truncated"]
        entries = [{**entry, "name": entry["path"]} for entry in tree["tree"]]
        assert guard.tree_sha(entries) == tree["sha"]
    assert trees["root"]["sha"] == guard.BASE_TREE
    assert next(entry["sha"] for entry in trees["root"]["tree"] if entry["path"] == ".github") == trees["github"]["sha"]
    assert next(entry["sha"] for entry in trees["github"]["tree"] if entry["path"] == "workflows") == trees["workflows"]["sha"]
    assert all(entry["path"] != Path(WORKFLOW_PATH).name for entry in trees["workflows"]["tree"])
    expanded = [entry for entry in trees["root"]["tree"] if entry["path"] != ".github"]
    expanded += [{**entry, "path": ".github/" + entry["path"]}
                 for entry in trees["github"]["tree"] if entry["path"] != "workflows"]
    expanded += [{**entry, "path": ".github/workflows/" + entry["path"]}
                 for entry in trees["workflows"]["tree"]]
    assert guard.flat_tree_sha(expanded) == guard.BASE_TREE
    workflow_identity = identity(data)
    addition = {"path": WORKFLOW_PATH, "mode": "100644", "type": "blob",
                "sha": workflow_identity["git_blob"]}
    new_root = guard.flat_tree_sha(expanded + [addition])
    assert new_root != guard.BASE_TREE
    assert guard.flat_tree_sha([entry for entry in expanded + [addition]
                                if entry["path"] != WORKFLOW_PATH]) == guard.BASE_TREE
    contamination = {"path": "unexpected-original-source", "mode": "100644", "type": "blob",
                     "sha": "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"}
    assert guard.flat_tree_sha(expanded + [contamination]) != guard.BASE_TREE
    forward = "".join(difflib.unified_diff([], text.splitlines(keepends=True),
                                         fromfile="/dev/null", tofile="b/" + WORKFLOW_PATH))
    reverse = "".join(difflib.unified_diff(text.splitlines(keepends=True), [],
                                         fromfile="a/" + WORKFLOW_PATH, tofile="/dev/null"))
    (proof_dir / "full.patch").write_text(forward)
    (proof_dir / "reverse.patch").write_text(reverse)
    with tempfile.TemporaryDirectory(prefix="b23-static-patch-") as temporary:
        scratch = Path(temporary)
        subprocess.run(["git", "apply", "--check", str(proof_dir / "full.patch")],
                       cwd=scratch, check=True, capture_output=True)
        subprocess.run(["git", "apply", str(proof_dir / "full.patch")],
                       cwd=scratch, check=True, capture_output=True)
        assert (scratch / WORKFLOW_PATH).read_bytes() == data
        subprocess.run(["git", "apply", "--check", str(proof_dir / "reverse.patch")],
                       cwd=scratch, check=True, capture_output=True)
        subprocess.run(["git", "apply", str(proof_dir / "reverse.patch")],
                       cwd=scratch, check=True, capture_output=True)
        assert not (scratch / WORKFLOW_PATH).exists()
    restoration = json.loads((ROOT / "recovery-source-receipt.json").read_text())
    for item in restoration["records"]:
        relative = item["path"].split("/source/", 1)[1]
        assert not Path(relative).is_absolute() and ".." not in Path(relative).parts
        actual = identity((ROOT / "source" / relative).read_bytes())
        assert all(actual[key] == item[key] for key in ("bytes", "git_blob", "sha256"))
    result = {
        "scope": "offline workflow/static integrity checks plus controlled shell stand-ins; no native target execution",
        "draft": not bool(args.collector),
        "workflow_identity": workflow_identity,
        "workflow_lines": len(text.splitlines()),
        "original_base_commit": "67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed",
        "original_base_tree": guard.BASE_TREE,
        "actual_preimage_tree_objects_recomputed": {name: tree["sha"] for name, tree in trees.items()},
        "computed_candidate_root_tree": new_root,
        "candidate_root_actual_created": False,
        "reverse_projection_restores_actual_base": True,
        "extra_original_leaf_is_rejected": True,
        "forward_reverse_git_apply": "passed",
        "fixed_original_source_bodies_unchanged": len(restoration["records"]),
        "original_steps_semantically_identical": ["checkout", *unchanged_steps],
        "original_full_target": TARGET,
        "job_timeout_minutes": 120,
        "runtime_cases_filtered": False,
        "retry_threads_or_test_budget_overrides": False,
        "syntax": syntax,
        "collector_scope": collector_scope,
        "controlled_exit_fixtures": wrapper_fixtures,
        "actual_source_guard_on_github_checkout": "NOT_RUN",
        "native_run": "NOT_RUN",
        "independent_B23_acceptance": "PENDING",
    }
    (proof_dir / "static-verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
