"""Prepare a fresh local Git shadow and run the unchanged full E6 PR blob gate.

This controller accepts explicit source-only stages, followed by one new
evidence-only commit. It creates no remote objects, fetches nothing, changes
no ref, and never touches the measured host. The checker and seven tests are
the original exact blobs. The final full PR comparison always begins at d83.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time
import traceback


HERE = Path(__file__).resolve().parent
BASE = "d83f70f38137a99a86a3afd122199ba9cdae4f79"
BASE_TREE = "ef7a3e525f6b191fbaf73ba99ed95acd958eeb5f"
ANCHOR = "9dfded9cecc74e39a19bccd14b9de9dc46c02c63"
ANCHOR_TREE = "d07a8a95a2f0921387446063a1a51661cbd62df7"
PREPARATION_SHA = "f455cd2fd4b120957fc496a76e5848eb079926412760a90ffd6f32c4caecd6ae"
HELPER_SHA = "d76c4bfefd34fd1ea0cfc6af1afc6f2815e21e9369d16c14644f3a1d0d69b55b"
CHECKER = ("18bc6175c274abaeabe3ef0c32d82627d498bbe7", "eb7a9eab936b7c7948ed13fbd6d6aca09aa38997c20685a8ee12d72e388d52c3")
TESTS = ("71f726876ee37adab36594e53eedb144934da3f1", "f5017bd436f694f25b3d605fd247d34b47d3b4aa73a2c3c3c9539c39e8348231")
ANCHOR_ALLOWLIST = ("a7f889fc5ee56581587bebad77a8768928866581", "636c75d6ed08bfad2a686fbdd966a470bf65d5a90fd4c2cf48a55b41ff01c943")
ALLOWLIST_PATH = ".github/blob-size-allowlist.txt"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def checked_path(value):
    path = PurePosixPath(value)
    assert value and not path.is_absolute() and ".." not in path.parts
    assert ".git" not in path.parts and str(path) == value and "\0" not in value
    return value


def state(repository):
    answer = {name: sha((repository / name).read_bytes()) if (repository / name).is_file() else None for name in ("HEAD", "config", "index", "packed-refs")}
    answer["refs"] = {str(path.relative_to(repository)): sha(path.read_bytes()) for path in (repository / "refs").rglob("*") if path.is_file()}
    return answer


def run_original(argv, cwd, environment, output, label):
    start = time.monotonic()
    try:
        child = subprocess.run(argv, cwd=cwd, env=environment, capture_output=True, timeout=120)
        stdout, stderr, code, timed_out = child.stdout, child.stderr, child.returncode, False
    except subprocess.TimeoutExpired as error:
        stdout, stderr, code, timed_out = error.stdout or b"", error.stderr or b"", None, True
    (output / (label + ".stdout")).write_bytes(stdout)
    (output / (label + ".stderr")).write_bytes(stderr)
    result = {"argv": argv, "cwd": str(cwd), "timeout_seconds": 120, "exit_code": code, "timed_out": timed_out, "wall_seconds": time.monotonic() - start, "stdout_sha256": sha(stdout), "stderr_sha256": sha(stderr)}
    save(output / (label + ".json"), result)
    return result, stdout, stderr


def main(args):
    args.output = args.output.resolve()
    assert args.output.is_relative_to(HERE), "all new state must stay inside the isolated cloud preparation directory"
    args.output.mkdir(exist_ok=False)
    began = time.monotonic()
    result = {"schema": "hepta.e6.full-original-pr-cloud-blob-gate.v1", "host": "managed-cloud-workspace", "base": BASE, "source_anchor": ANCHOR, "head": args.head, "maximum_bytes": 512000, "timeout_seconds_per_original_command": 120, "controller_sha256": sha(Path(__file__).read_bytes()), "model_calls": 0, "training_updates": 0, "native_experiments": 0, "remote_objects_or_refs_changed": False, "source_qualification_transferred": False, "original_seven_tests_executed": False, "original_full_pr_gate_executed": False, "status": "PREPARING"}
    repository, identity_before, materialized = None, None, {}
    try:
        helper_path = HERE / "prepare_known_objects.py"
        assert sha(helper_path.read_bytes()) == HELPER_SHA
        specification = importlib.util.spec_from_file_location("exact_object_preparation", helper_path)
        exact = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(exact)
        preparation_bytes = (HERE / "prepared-shadow/MANIFEST.json").read_bytes()
        assert sha(preparation_bytes) == PREPARATION_SHA
        preparation = json.loads(preparation_bytes)
        assert (preparation["base"], preparation["base_tree"], preparation["source_anchor"], preparation["source_tree"]) == (BASE, BASE_TREE, ANCHOR, ANCHOR_TREE)
        assert preparation["original_full_diff"]["paths"] == 153
        assert preparation["future_head_gate_executed"] is False
        result["preparation_manifest_sha256"] = PREPARATION_SHA
        result["input_files"] = {}
        def read_input(path, expected=None):
            path = Path(path).resolve()
            raw = path.read_bytes()
            if expected:
                assert sha(raw) == expected, str(path)
            result["input_files"][str(path)] = {"bytes": len(raw), "sha256": sha(raw)}
            return raw

        environment = dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
        repository = args.output / "objects.git"
        child = subprocess.run(["git", "init", "--bare", str(repository)], capture_output=True, timeout=15, env=environment)
        (args.output / "init.stdout").write_bytes(child.stdout)
        (args.output / "init.stderr").write_bytes(child.stderr)
        assert child.returncode == 0
        identity_before = state(repository)
        def git(*parts, data=None):
            return subprocess.check_output(["git", "--git-dir", str(repository), *parts], input=data, env=environment, stderr=subprocess.PIPE, timeout=15)

        imported = {}
        def put(kind, raw, expected):
            assert kind in ("commit", "tree", "blob") and exact.oid(kind, raw) == expected
            assert git("hash-object", "-t", kind, "-w", "--stdin", data=raw).decode().strip() == expected
            assert git("cat-file", kind, expected) == raw
            row = {"oid": expected, "type": kind, "bytes": len(raw), "sha256": sha(raw)}
            assert expected not in imported or imported[expected] == row
            imported[expected] = row
            return expected

        objects = list(preparation["objects"])
        for path in args.extra_objects_manifest:
            extra = json.loads(read_input(path))
            objects.extend(extra if isinstance(extra, list) else extra["objects"])
        for row in objects:
            raw = read_input(row["local_path"], row["sha256"])
            assert len(raw) == row["bytes"]
            put(row["type"], raw, row["oid"])
        assert git("rev-parse", BASE + "^{tree}").decode().strip() == BASE_TREE
        assert git("rev-parse", ANCHOR + "^{tree}").decode().strip() == ANCHOR_TREE

        def lookup(tree, path):
            parts = path.split("/")
            for index, name in enumerate(parts):
                entries = exact.parse_tree(git("cat-file", "tree", tree))
                entry = entries.get(name)
                if entry is None:
                    return None
                if index == len(parts) - 1:
                    assert entry["type"] == "blob"
                    return {"sha": entry["sha"], "mode": entry["mode"]}
                assert entry["type"] == "tree"
                tree = entry["sha"]

        def policy(tree, path, pin):
            entry = lookup(tree, path)
            assert entry and entry["sha"] == pin[0], path
            raw = git("cat-file", "blob", pin[0])
            assert sha(raw) == pin[1], path
            return raw

        def revise(tree, changes):
            entries = exact.parse_tree(git("cat-file", "tree", tree)) if tree else {}
            groups = {}
            for path, update in changes.items():
                first, separator, rest = path.partition("/")
                if separator:
                    groups.setdefault(first, {})[rest] = update
                else:
                    previous = entries.get(first)
                    if previous:
                        assert previous["mode"] in ("100644", "100755")
                        before = git("cat-file", "blob", previous["sha"])
                        assert exact.oid("blob", before) == previous["sha"]
                        assert (previous["sha"], previous["mode"]) != (update["sha"], update["mode"]), "unchanged path in stage manifest"
                    entries[first] = {"path": first, "sha": update["sha"], "mode": update["mode"], "type": "blob"}
            for first, updates in groups.items():
                previous = entries.get(first)
                assert previous is None or previous["type"] == "tree"
                new_tree = revise(previous["sha"] if previous else None, updates)
                entries[first] = {"path": first, "sha": new_tree, "mode": "40000", "type": "tree"}
            raw = exact.tree_bytes(entries.values())
            return put("tree", raw, exact.oid("tree", raw))

        stages = []
        if args.source_stages:
            stages = json.loads(read_input(args.source_stages))
            assert isinstance(stages, list) and 0 < len(stages) <= 8
            assert all(stage["kind"] == "source" for stage in stages)
        stages.append({"kind": "evidence", "head": args.head, "head_api": str(args.head_api), "head_raw": str(args.head_raw) if args.head_raw else None, "files_manifest": str(args.files_manifest)})
        previous_commit, previous_tree, allowlist = ANCHOR, ANCHOR_TREE, ANCHOR_ALLOWLIST
        full_original = json.loads(read_input(preparation["original_full_diff"]["local_path"], preparation["original_full_diff"]["sha256"]))
        touched = {row["path"] for row in full_original}
        stage_receipts = []
        for number, stage in enumerate(stages):
            files_bytes = read_input(stage["files_manifest"], stage.get("files_manifest_sha256"))
            files_rows = json.loads(files_bytes)
            files_rows = files_rows if isinstance(files_rows, list) else files_rows["files"]
            assert isinstance(files_rows, list) and files_rows
            files = {}
            for row in files_rows:
                path = checked_path(row["path"])
                assert path not in files
                before = lookup(previous_tree, path)
                if stage["kind"] == "evidence":
                    assert path.startswith("evidence/"), "source/policy changes cannot be classified as evidence"
                    assert before is None, "retained evidence cannot be overwritten by the new evidence-only stage"
                else:
                    assert not path.startswith("evidence/"), "source-only stage must not mix in evidence publication"
                expected = row.get("git_blob", row.get("git_blob_sha1", row.get("sha")))
                assert re.fullmatch(r"[0-9a-f]{40}", expected or "")
                mode = row.get("mode", "100644")
                assert mode in ("100644", "100755")
                raw = read_input(row["local_path"], row["sha256"])
                assert len(raw) == row["bytes"]
                files[path] = {"sha": put("blob", raw, expected), "mode": mode}
            tree = revise(previous_tree, files)
            api = exact.api_record(json.loads(read_input(stage["head_api"], stage.get("head_api_sha256"))))
            assert api["sha"] == stage["head"] and api["tree"]["sha"] == tree
            assert [row["sha"] for row in api["parents"]] == [previous_commit], "stage must be the declared exact direct successor"
            if stage.get("head_raw"):
                raw_commit = read_input(stage["head_raw"], stage.get("head_raw_sha256"))
                reconstruction = {"method": "supplied exact raw commit"}
            else:
                raw_commit, reconstruction = exact.reconstruct_commit(api)
            put("commit", raw_commit, stage["head"])
            committed_header = git("cat-file", "commit", stage["head"]).split(b"\n\n", 1)[0].splitlines()
            committed_trees = [line[5:].decode("ascii") for line in committed_header if line.startswith(b"tree ")]
            committed_parents = [line[7:].decode("ascii") for line in committed_header if line.startswith(b"parent ")]
            assert committed_trees == [tree], "actual commit tree must equal the reconstructed stage tree"
            assert committed_parents == [previous_commit], "actual commit parents must equal the declared direct predecessor"
            actual = git("diff", "--name-status", "--no-renames", previous_commit, stage["head"]).decode().splitlines()
            assert all(line.startswith(("A\t", "M\t")) for line in actual)
            assert sorted(line.split("\t", 1)[1] for line in actual) == sorted(files)
            if stage["kind"] == "source":
                next_allowlist = (stage["allowlist_git_blob"], stage["allowlist_sha256"])
                if next_allowlist != allowlist:
                    assert ALLOWLIST_PATH in files, "allowlist transition must be an explicit source delta"
                allowlist = next_allowlist
            policy(tree, "scripts/check_blob_size.py", CHECKER)
            policy(tree, "scripts/tests/test_blob_size_policy.py", TESTS)
            policy(tree, ALLOWLIST_PATH, allowlist)
            receipt = {"kind": stage["kind"], "parent": previous_commit, "head": stage["head"], "tree": tree, "changed_paths": sorted(files), "allowlist": allowlist, "commit_reconstruction": reconstruction}
            stage_receipts.append(receipt)
            save(args.output / f"stage-{number:02d}.json", receipt)
            previous_commit, previous_tree = stage["head"], tree
            touched.update(files)
        assert previous_commit == args.head
        expected = []
        for path in sorted(touched):
            before, after = lookup(BASE_TREE, path), lookup(previous_tree, path)
            assert after is not None, "deletions are outside this controller scope"
            if before != after:
                expected.append({"path": path, "status": "A" if before is None else "M", "before": before, "after": after})
        actual = git("diff", "--name-status", "--no-renames", BASE, args.head)
        assert actual.decode().splitlines() == [row["status"] + "\t" + row["path"] for row in expected], "complete original-PR diff does not match every declared stage"
        (args.output / "full-original-pr-diff.stdout").write_bytes(actual)
        save(args.output / "FULL_PR_EXPECTED_DIFF.json", expected)
        save(args.output / "EXACT_OBJECTS.json", list(imported.values()))
        result.update({"tree": previous_tree, "source_head_before_evidence": stage_receipts[-1]["parent"], "stages": stage_receipts, "full_pr_changed_paths": len(expected), "exact_objects": len(imported), "original_checker": CHECKER, "original_tests": TESTS, "actual_allowlist": allowlist})

        workspace = args.output / "policy"
        for path, pin in (("scripts/check_blob_size.py", CHECKER), ("scripts/tests/test_blob_size_policy.py", TESTS), (ALLOWLIST_PATH, allowlist)):
            raw = policy(previous_tree, path, pin)
            target = workspace / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            materialized[str(target)] = sha(raw)
        assert state(repository) == identity_before, "object preparation must not move refs or change Git identity"
        temporary = args.output / "test-tmp"
        temporary.mkdir()
        test_environment = dict(environment, TMPDIR=str(temporary))
        test_argv = [sys.executable, "-B", "-m", "unittest", "discover", "-s", "scripts/tests", "-p", "test_blob_size_policy.py"]
        gate_argv = [sys.executable, "-B", str(workspace / "scripts/check_blob_size.py"), "--base", BASE, "--head", args.head, "--max-bytes", "512000", "--allowlist", str(workspace / ALLOWLIST_PATH)]
        save(args.output / "INTENT.json", {"tests": test_argv, "gate": gate_argv, "timeout_seconds_each": 120, "before": identity_before, "materialized": materialized, "full_pr_changed_paths": len(expected)})
        result["original_seven_tests_executed"] = True
        unit, _, unit_stderr = run_original(test_argv, workspace, test_environment, args.output, "original-seven-tests")
        result["original_seven_tests"] = unit
        assert unit["exit_code"] == 0 and re.search(rb"\bRan 7 tests in ", unit_stderr) and unit_stderr.rstrip().endswith(b"OK"), "all seven original tests must actually run"
        result["original_full_pr_gate_executed"] = True
        gate, gate_stdout, _ = run_original(gate_argv, repository, environment, args.output, "original-full-pr-gate")
        result["original_full_pr_gate"] = gate
        expected_header = f"Checked {len(expected)} changed file(s) against the 512000-byte limit.".encode()
        assert gate["exit_code"] == 0 and gate_stdout.splitlines()[0] == expected_header
        after = state(repository)
        result["identity_before"], result["identity_after"] = identity_before, after
        assert identity_before == after
        assert all(sha(Path(path).read_bytes()) == digest for path, digest in materialized.items())
        assert sha(helper_path.read_bytes()) == HELPER_SHA and sha((HERE / "prepared-shadow/MANIFEST.json").read_bytes()) == PREPARATION_SHA
        result.update({"status": "PASS", "repository_identity_unchanged": True, "materialized_policy_bytes_unchanged": True, "source_qualification_transferred": False})
    except Exception as error:
        result.update({"status": "FAIL", "error": type(error).__name__ + ": " + str(error)})
        (args.output / "exception.txt").write_text(traceback.format_exc())
    finally:
        if repository is not None and identity_before is not None:
            result["identity_before"] = identity_before
            result["identity_after"] = state(repository)
            result["repository_identity_unchanged"] = result["identity_after"] == identity_before
        result["materialized_policy_bytes_unchanged"] = all(Path(path).is_file() and sha(Path(path).read_bytes()) == digest for path, digest in materialized.items())
        result["input_bytes_remain_current"] = all(Path(path).is_file() and sha(Path(path).read_bytes()) == row["sha256"] for path, row in result.get("input_files", {}).items())
        if not result.get("repository_identity_unchanged", True) or not result["materialized_policy_bytes_unchanged"] or not result["input_bytes_remain_current"]:
            result.update({"status": "FAIL", "identity_or_input_changed": True})
    result["owner_wall_seconds"] = time.monotonic() - began
    save(args.output / "RESULT.json", result)
    print(json.dumps({key: result.get(key) for key in ("status", "base", "head", "tree", "full_pr_changed_paths", "error", "owner_wall_seconds")}, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--head", required=True)
    parser.add_argument("--head-api", required=True, type=Path)
    parser.add_argument("--head-raw", type=Path)
    parser.add_argument("--files-manifest", required=True, type=Path)
    parser.add_argument("--source-stages", type=Path)
    parser.add_argument("--extra-objects-manifest", action="append", type=Path, default=[])
    parser.add_argument("--output", required=True, type=Path)
    raise SystemExit(main(parser.parse_args()))
