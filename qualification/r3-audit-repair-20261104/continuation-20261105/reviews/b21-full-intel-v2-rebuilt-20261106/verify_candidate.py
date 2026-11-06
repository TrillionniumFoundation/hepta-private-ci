#!/usr/bin/env python3
"""Read-only portable source and evidence verification; no Bazel/native calls."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import yaml
sys.dont_write_bytecode = True

MAIN = "67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed"
PARENT = "cc65856cc0b20d03db506c19495d53d61162102d"
MAIN_TREE = "3982ba56dc5a3f1da0c1de7ea57992f88125c359"
PARENT_TREE = "eaded1870d080eaa55efae6208354729140e784c"
WORKFLOW = ".github/workflows/b21-intel-original-pty.yml"
V1_BLOB = "77387b7a3e8a15efe11cca02bf4185377ff0a86f"
OLD_UNRECOVERED = "863a36de822ea127bf9aa8a0e5d131626952cfe2"


def identity(body):
    return {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()}


def load(path):
    return json.loads(path.read_text())


def unwrapped(value):
    assert value.get("isError") is not True
    if isinstance(value.get("structuredContent"), dict):
        return value["structuredContent"]
    return json.loads(next(x["text"] for x in value["content"] if x["type"] == "text"))


def rebuild_tree(leaves):
    directories = {"": {}}
    for entry in leaves:
        assert entry["type"] in ("blob", "commit")
        path, mode, sha = entry["path"], entry["mode"], entry["sha"]
        assert path and not path.startswith("/") and ".." not in path.split("/")
        parts = path.split("/")
        for index in range(1, len(parts)):
            parent = "/".join(parts[:index - 1])
            directory = "/".join(parts[:index])
            directories.setdefault(directory, {})
            if parts[index - 1] in directories[parent]:
                assert directories[parent][parts[index - 1]][0] == "tree"
            directories[parent][parts[index - 1]] = ("tree", directory)
        parent = "/".join(parts[:-1])
        assert parts[-1] not in directories[parent]
        directories[parent][parts[-1]] = (entry["type"], (mode, sha))
    hashes = {}

    def visit(directory):
        body = b""
        entries = sorted(directories[directory].items(),
                         key=lambda pair: (pair[0] + ("/" if pair[1][0] == "tree" else "")).encode("utf-8"))
        for name, (kind, data) in entries:
            mode, sha = ("40000", visit(data)) if kind == "tree" else data
            body += mode.encode("ascii") + b" " + name.encode("utf-8") + b"\0" + bytes.fromhex(sha)
        sha = hashlib.sha1(b"tree " + str(len(body)).encode() + b"\0" + body).hexdigest()
        hashes[directory] = sha
        return sha
    sha = visit("")
    result = [copy.deepcopy(x) for x in leaves]
    result += [{"path": path, "mode": "040000", "type": "tree", "sha": value}
               for path, value in hashes.items() if path]
    result.sort(key=lambda x: x["path"])
    return {"sha": sha, "truncated": False, "tree": result}, hashes


def verify_actual_tree(path, raw_path, expected):
    tree, raw = load(path), load(raw_path)
    assert tree["sha"] == raw["sha"] == expected
    assert tree["truncated"] is False and raw["truncated"] is False

    def normalize(rows):
        return sorted(({key: row[key] for key in ("path", "mode", "type", "sha")} for row in rows),
                      key=lambda x: x["path"])

    assert normalize(tree["tree"]) == normalize(raw["tree"])
    leaves = [x for x in tree["tree"] if x["type"] != "tree"]
    rebuilt, hashes = rebuild_tree(leaves)
    assert rebuilt["sha"] == expected
    assert rebuilt["tree"] == normalize(tree["tree"])
    return {x["path"]: x for x in leaves}, hashes


def array(body, name):
    match = re.search(r"(?ms)^" + re.escape(name) + r"=\(\n(.*?)^\)", body)
    assert match, name
    return shlex.split(match[1], comments=True)


def prove(root):
    root = Path(root).resolve()
    main, main_nodes = verify_actual_tree(
        root / "authority/main67-full-tree.json",
        root / "authority/main67-complete-recursive-API.original.json", MAIN_TREE)
    parent, parent_nodes = verify_actual_tree(
        root / "authority/cc-v1-full-tree.json",
        root / "authority/cc-v1-complete-recursive-API.original.json", PARENT_TREE)
    assert len(main) == 10582 and len(parent) == 10583
    assert set(parent) - set(main) == {WORKFLOW}
    assert all(main[name] == parent[name] for name in main)
    assert parent[WORKFLOW] == {"path": WORKFLOW, "mode": "100644", "type": "blob", "sha": V1_BLOB}
    for name, sha, tree in (("main67", MAIN, MAIN_TREE), ("cc", PARENT, PARENT_TREE)):
        commit = load(root / "authority" / (name + "-commit.json"))
        original = json.loads(unwrapped(load(root / "authority" / (name + "-commit.GET.original.json")))["content"])
        assert commit == original
        assert commit["sha"] == sha and commit["tree"]["sha"] == tree
        if name == "cc":
            assert [x["sha"] for x in commit["parents"]] == [MAIN]
    source_map = load(root / "source-map.json")
    assert len(source_map) == 15
    for row in source_map:
        data = (root / "source" / row["path"]).read_bytes()
        assert identity(data) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
        assert main[row["path"]]["sha"] == row["git_blob"]
        original = unwrapped(load(root / "source-GET" / (row["git_blob"] + ".json")))
        assert original["content"].encode("utf-8") == data
    original_v1 = (root / "source/v1-workflow.yml").read_bytes()
    assert identity(original_v1)["git_blob"] == V1_BLOB
    assert unwrapped(load(root / "source/v1-workflow.GET.original.json"))["content"].encode() == original_v1

    primary_proof = []
    for path in sorted((root / "primary").iterdir()):
        if path.suffix not in (".java", ".proto"):
            continue
        original = unwrapped(load(path.with_name(path.name + ".GET.original.json")))
        assert original["content"].encode("utf-8") == path.read_bytes()
        assert "/blob/9.3.0/" in original["url"] and "github.com/bazelbuild/bazel/" in original["url"]
        primary_proof.append({"path": path.name, "url": original["url"], **identity(path.read_bytes())})
    assert len(primary_proof) == 14
    assert (root / "source/.bazelversion").read_text() == "9.3.0\n"
    execution = (root / "primary/ExecutionOptions.java").read_text()
    assert 'name = "flaky_test_attempts"' in execution and 'defaultValue = "default"' in execution
    assert "single test attempt" in execution and "three for tests marked explicitly as flaky" in execution
    transport = (root / "primary/BuildEventServiceModule.java").read_text()
    start = transport.index("if (!Strings.isNullOrEmpty(besStreamOptions.buildEventJsonFile))")
    json_block = transport[start:transport.index("BuildEventServiceTransport besTransport =", start)]
    assert "besStreamOptions.buildEventJsonFilePathConversion" in json_block
    assert ": new LocalFilesArtifactUploader()" in json_block
    assert "new JsonFormatFileTransport" in json_block
    assert "createBesTransport(cmdEnv, uploaderSupplier, artifactGroupNamer)" in transport
    local = (root / "primary/LocalFilesArtifactUploader.java").read_text()
    assert "FileUriPathConverter" in local and "OUTPUT_DIRECTORY" in local and "OUTPUT_SYMLINK" in local
    rc = (root / "source/.bazelrc").read_text()
    for clause in ("common:ci-macos --jobs=128", "common:ci-macos --loading_phase_threads=4",
                   "common:ci-macos --local_test_jobs=2",
                   "common:ci-macos --strategy=TestRunner=darwin-sandbox,local"):
        assert clause in rc
    attributes = [name for name in main if Path(name).name == ".gitattributes"]
    assert sorted(attributes) == sorted([".gitattributes", "codex-rs/apply-patch/tests/fixtures/scenarios/.gitattributes"])
    for name in attributes:
        assert re.search(r"\bexport-(ignore|subst)\b", (root / "source" / name).read_text()) is None

    workflow_bytes = (root / "candidate" / WORKFLOW).read_bytes()
    workflow_identity = identity(workflow_bytes)
    assert workflow_identity["git_blob"] != OLD_UNRECOVERED
    workflow = yaml.safe_load(workflow_bytes)
    original = yaml.safe_load((root / "source/.github/workflows/bazel.yml").read_text())
    v1 = yaml.safe_load(original_v1)
    trigger = workflow.get("on", workflow.get(True))
    assert trigger == {"pull_request": {"paths": [WORKFLOW]}}
    assert workflow["permissions"] == original["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == v1["concurrency"]
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert set(workflow["jobs"]) == {"test"}
    job, original_job = workflow["jobs"]["test"], original["jobs"]["test"]
    assert job["if"] == v1["jobs"]["original-pty"]["if"]
    assert job["timeout-minutes"] == original_job["timeout-minutes"] == 120
    assert job["environment"] == original_job["environment"] == {"name": "bazel", "deployment": False}
    assert job["runs-on"] == original_job["runs-on"]
    assert job["strategy"] == {"fail-fast": False, "matrix": {"include": [
        {"os": "macos-15-intel", "target": "x86_64-apple-darwin"}]}}
    assert job["strategy"]["matrix"]["include"][0] in original_job["strategy"]["matrix"]["include"]
    steps, old_steps = job["steps"], original_job["steps"]
    assert len(steps) == 9
    find_old = lambda name: next(x for x in old_steps if x.get("name") == name)
    assert steps[2] == find_old("Prepare Bazel CI")
    assert steps[2]["id"] == "prepare_bazel"
    assert steps[2]["with"]["cache-scope"] == "bazel-${{ github.job }}"
    assert steps[7] == find_old("Save bazel repository cache")
    assert steps[8] == find_old("Check for a clean worktree")
    assert steps[0]["uses"] == old_steps[0]["uses"]
    assert steps[0]["with"] == {"persist-credentials": False,
                                "ref": "${{ github.event.pull_request.head.sha }}", "fetch-depth": 3}
    preflight = steps[1]["run"]
    for clause in (
        'test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"',
        'test "$(git show -s --format=%P HEAD)" = ' + PARENT,
        'test "$(git show -s --format=%P HEAD^)" = ' + MAIN,
        'test "$(git rev-parse \'HEAD^1^{tree}\')" = ' + PARENT_TREE,
        'test "$(git rev-parse \'HEAD~2^{tree}\')" = ' + MAIN_TREE,
        "git diff --name-only --no-renames " + MAIN + " HEAD",
        "git diff --name-only --no-renames HEAD^ HEAD",
        'test ! -s "$evidence_dir/source-status-before.txt"',
        "git -c core.attributesFile=/dev/null archive",
        "assert len(expected) == 10583", "assert seen == expected",
        'test "$(uname -s)" = Darwin', 'test "$(uname -m)" = x86_64',
        'test "$RUNNER_ARCH" = X64',
    ):
        assert clause in preflight, clause
    assert "HEAD^2" not in preflight
    assert steps[4]["name"] == "Preserve final source identity before artifact privacy checks"
    assert 'git diff --quiet' in steps[4]["run"] and 'git diff --cached --quiet' in steps[4]["run"]
    for step in (steps[1], steps[4]):
        assert step["env"]["EXPECTED_HEAD"] == "${{ github.event.pull_request.head.sha }}"
    original_test = find_old("bazel test //...")
    run, old_run = steps[3]["run"], original_test["run"]
    assert array(run, "bazel_targets") == array(old_run, "bazel_targets") == [
        "//...", "-//third_party/v8:all", "-//codex-rs/v8-poc:v8-poc-unit-tests"]
    assert array(run, "bazel_wrapper_args") == array(old_run, "bazel_wrapper_args") == [
        "--print-failed-action-summary", "--print-failed-test-logs"]
    expected_args = [x.replace("${GITHUB_SHA}", "${TESTED_SHA}") for x in array(old_run, "bazel_test_args")]
    additions = ["--nocache_test_results", "--build_event_json_file=${private_bep_dir}/build-events.jsonl",
                 "--nobuild_event_json_file_path_conversion"]
    assert array(run, "bazel_test_args") == expected_args + additions
    assert steps[3]["env"] == {**original_test["env"], "TESTED_SHA": "${{ github.event.pull_request.head.sha }}"}
    assert "continue-on-error" not in steps[3]
    assert run.count('"${args[@]}" 2>&1 | tee "$evidence_dir/console.log"') == 1
    assert '"${args[@]}" 2>&1 | tee "$evidence_dir/console.log"\nstatuses=("${PIPESTATUS[@]}")' in run
    assert run.endswith('exit "${statuses[0]}"\n')

    collector_bytes = (root / "collect_attempts.py").read_bytes()
    ast.parse(collector_bytes)
    registration = load(root / "candidate-postimages.actual.json")
    assert registration["publication"] is False and registration["native_execution"] is False
    assert len(registration["items"]) == 2
    get_pairs = (("candidate/" + WORKFLOW, "workflow.full-GET.original.json"),
                 ("collect_attempts.py", "collector.full-GET.original.json"))
    for local_path, get_name in get_pairs:
        data = (root / local_path).read_bytes()
        row = next(item for item in registration["items"] if item["local"] == local_path)
        assert {k: row[k] for k in ("bytes", "sha256", "git_blob")} == identity(data)
        assert row["full_GET_equal"] is True
        assert unwrapped(load(root / "source-registration" / get_name))["content"].encode("utf-8") == data
    created = unwrapped(load(root / "source-registration/create-tree.original.json"))
    assert created["sha"] == registration["materialization_tree"]
    collect_run = steps[5]["run"]
    embedded = collect_run.split("<<'BEP_COLLECTOR_PY'\n", 1)[1].split("\nBEP_COLLECTOR_PY\n", 1)[0] + "\n"
    assert embedded.encode() == collector_bytes
    assert steps[5]["id"] == "evidence" and steps[5]["if"] == "always() && !cancelled()"
    assert steps[5]["env"] == original_test["env"]
    assert 'printf \'safe-for-upload=false\\n\' >> "$GITHUB_OUTPUT"' in collect_run
    assert '"${RUNNER_TEMP}/b21-intel-full-bep-private/build-events.jsonl"' in collect_run
    assert '"//codex-rs/utils/pty:pty-unit-tests"' in collect_run
    assert 'printf \'%s\\n\' "$collector_exit" > "$evidence_dir/collector-exit-code.txt"' in collect_run
    assert steps[6]["if"] == "always() && !cancelled() && steps.evidence.outputs.safe-for-upload == 'true'"
    assert steps[6]["uses"] == "actions/upload-artifact@bbbca2ddaa5d8feaa63e36b76fdaad77386f024f"
    assert steps[6]["with"]["path"].splitlines() == [
        "${{ runner.temp }}/b21-original-intel-full-context",
        "${{ runner.temp }}/bazel-execution-logs"]
    assert steps[6]["with"]["include-hidden-files"] is True
    assert steps[6]["with"]["if-no-files-found"] == "error"
    bash_checks = 0
    for step in steps:
        if "run" in step:
            subprocess.run(["bash", "--noprofile", "--norc", "-n"], input=step["run"].encode(),
                           check=True, capture_output=True)
            bash_checks += 1
    mocks = []
    for code in (0, 7):
        with tempfile.TemporaryDirectory(prefix="b21-shell-stub-") as directory:
            base = Path(directory)
            temporary = base / "runner-temp"
            (temporary / "b21-original-intel-full-context").mkdir(parents=True)
            (temporary / "b21-intel-full-bep-private").mkdir()
            stub = base / ".github/scripts/run-bazel-ci.sh"
            stub.parent.mkdir(parents=True)
            stub.write_text('#!/bin/bash\nprintf \'%s\\0\' "$@" > "$RUNNER_TEMP/stub.argv0"\n'
                            'printf \'synthetic wrapper exit %s\\n\' "$SYNTHETIC_BAZEL_EXIT"\n'
                            'exit "$SYNTHETIC_BAZEL_EXIT"\n')
            stub.chmod(0o755)
            env = {"PATH": os.defpath, "RUNNER_TEMP": str(temporary),
                   "TESTED_SHA": "SYNTHETIC_SOURCE_HEAD", "GITHUB_SHA": "SYNTHETIC_EVENT_MERGE",
                   "SYNTHETIC_BAZEL_EXIT": str(code)}
            result = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", run],
                                    cwd=base, env=env, capture_output=True)
            assert result.returncode == code, result.stderr
            public = temporary / "b21-original-intel-full-context"
            assert (public / "original-bazel-exit-code.txt").read_text() == str(code) + "\n"
            assert (public / "console-copy-exit-code.txt").read_text() == "0\n"
            args = (public / "command.argv0").read_bytes().split(b"\0")[:-1]
            captured = (temporary / "stub.argv0").read_bytes().split(b"\0")[:-1]
            assert args[1:] == captured
            assert [x.decode() for x in args[-3:]] == array(run, "bazel_targets")
            assert b"--build_metadata=COMMIT_SHA=SYNTHETIC_SOURCE_HEAD" in args
            assert b"--flaky_test_attempts=1" not in args
            mocks.append({"synthetic_original_exit": code, "wrapper_calls": 1,
                          "preserved_original_exit": True, "console_copy_exit": 0,
                          "exact_targets_and_argument_vector": True})
    fixture_result = subprocess.run(
        [sys.executable, str(root / "verify_collection_fixtures.py")],
        cwd=root, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, check=True)
    assert fixture_result.stderr == b""
    fixture_output = json.loads(fixture_result.stdout)
    assert fixture_output["case_count"] == fixture_output["passed"] == 36
    expected_fixture_output = root / "fixtures-final.stdout.json"
    if expected_fixture_output.exists():
        assert fixture_result.stdout == expected_fixture_output.read_bytes()

    intended_leaves = [copy.deepcopy(x) for x in parent.values()]
    next(x for x in intended_leaves if x["path"] == WORKFLOW)["sha"] = workflow_identity["git_blob"]
    intended, new_nodes = rebuild_tree(intended_leaves)
    assert len(intended_leaves) == 10583
    leaf_map = {x["path"]: x for x in intended_leaves}
    assert all(leaf_map[name] == main[name] for name in main)
    if (root / "intended-full-tree.json").exists():
        assert intended == load(root / "intended-full-tree.json")
    report = {
        "schema": "b21-rebuilt-full-intel-static-proof-v1", "result": "STATIC_VERIFIED",
        "main_commit": MAIN, "main_tree": MAIN_TREE, "parent_commit": PARENT, "parent_tree": PARENT_TREE,
        "candidate_workflow": {"path": WORKFLOW, **workflow_identity},
        "collector": identity(collector_bytes), "candidate_tree": intended["sha"],
        "source_proof": {"main_leaves_unchanged": len(main), "candidate_leaves": len(intended_leaves),
                         "main_merkle_nodes": len(main_nodes), "parent_merkle_nodes": len(parent_nodes),
                         "candidate_merkle_nodes": len(new_nodes), "only_changed_path": WORKFLOW,
                         "repository_dependency_full_GET_matches": len(source_map),
                         "fixed_primary_full_GET_matches": len(primary_proof),
                         "candidate_postimages_actual_full_GET": len(registration["items"])},
        "original_context": {"runner": "macos-15-intel", "target": "x86_64-apple-darwin",
                             "job_id": "test", "outer_minutes": 120, "cache_scope": "bazel-test",
                             "all_targets": array(run, "bazel_targets"),
                             "default_retry_unchanged": True, "parallelism_and_test_timeouts_unchanged": True},
        "evidence_flags_added": additions,
        "metadata_identity_substitution": "COMMIT_SHA uses actual checked-out source HEAD instead of PR event merge",
        "bash_syntax_blocks": bash_checks, "synthetic_wrapper_exit_checks": mocks,
        "required_synthetic_cases": fixture_output["passed"],
        "raw_bep_uploaded": False, "opaque_payloads_omitted": True,
        "qualification_scope": "static_source_and_synthetic_evidence_only",
        "native_run": False, "ref_or_PR_mutation": False,
        "B21": "OPEN", "historical_2_023_second_failure_cause": "UNKNOWN",
        "old_863a_full_bytes_recovered_or_equivalence_claimed": False,
        "primary_sources": primary_proof,
    }
    return report, intended


if __name__ == "__main__":
    report, _intended = prove(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
