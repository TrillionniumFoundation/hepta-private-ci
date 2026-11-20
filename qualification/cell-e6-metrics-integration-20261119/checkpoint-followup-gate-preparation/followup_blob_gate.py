"""Bind the d1d follow-up to its exact prior passing Git objects.

Only the local object-preparation controller is new. The repository blob-size
checker, its allowlist, 512000-byte limit, and 120-second deadline are unchanged.
This imports the complete verified d1d preparation and permits one direct child.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback


HERE = Path(__file__).resolve().parent
BASE = "d1d3896e2a2628977bc466cee1e00aea93971949"
BASE_TREE = "05c2e91d6387b60b07952282a8911ca52dd3d0bd"
PREVIOUS = HERE / "checkpoint-final-gate-2"
OLD_CONTROLLER_SHA = "8d1a37bdde54509c2227834d7f129a21d4e2c7374753136e024ebf69d091558d"
OLD_RESULT_SHA = "5b9bb2e5904bf9c3c9fcb0ff8a7d712e5130c4b8ed55131870212bdd30d5b435"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def main(args):
    args.output.mkdir(exist_ok=False)
    start = time.monotonic()
    result = {
        "schema": "hepta.d1d-direct-followup-original-blob-gate.v1",
        "base": BASE,
        "base_tree": BASE_TREE,
        "head": args.head,
        "host": "managed-cloud-workspace",
        "controller_sha256": digest(Path(__file__).read_bytes()),
        "original_gate_maximum_bytes": 512000,
        "original_gate_timeout_seconds": 120,
        "model_calls": 0,
        "training_updates": 0,
        "native_task_children": 0,
    }
    try:
        old_path = HERE / "checkpoint_blob_gate.py"
        assert digest(old_path.read_bytes()) == OLD_CONTROLLER_SHA
        spec = importlib.util.spec_from_file_location("original_preparation", old_path)
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
        prior_bytes = (PREVIOUS / "RESULT.json").read_bytes()
        assert digest(prior_bytes) == OLD_RESULT_SHA
        prior = json.loads(prior_bytes)
        assert prior["status"] == "PASS" and prior["exit_code"] == 0
        assert prior["head"] == BASE and prior["tree"] == BASE_TREE
        assert prior["repository_identity_unchanged"] is True
        manifest_bytes = args.files_manifest.read_bytes()
        api_bytes = args.head_api.read_bytes()
        result["input_sha256"] = {
            "files_manifest": digest(manifest_bytes),
            "head_api": digest(api_bytes),
            "prior_result": OLD_RESULT_SHA,
            "prior_exact_objects": digest((PREVIOUS / "EXACT_OBJECTS.json").read_bytes()),
        }
        repo = args.output / "objects.git"
        environment = dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
        init = subprocess.run(["git", "init", "--bare", str(repo)], capture_output=True, timeout=15, env=environment)
        (args.output / "init.stdout").write_bytes(init.stdout)
        (args.output / "init.stderr").write_bytes(init.stderr)
        assert init.returncode == 0

        def git(*parts, data=None, directory=repo):
            return subprocess.check_output(["git", *parts], cwd=directory, input=data, env=environment, stderr=subprocess.PIPE, timeout=15)

        imported = {}

        def put(kind, raw, expected=None):
            expected = expected or old.oid(kind, raw)
            assert old.oid(kind, raw) == expected
            assert git("hash-object", "-t", kind, "-w", "--stdin", data=raw).decode().strip() == expected
            assert git("cat-file", kind, expected) == raw
            imported[expected] = {"oid": expected, "type": kind, "bytes": len(raw), "sha256": digest(raw), "exact_readback": True}
            return expected

        prior_objects = json.loads((PREVIOUS / "EXACT_OBJECTS.json").read_bytes())
        assert len(prior_objects) == prior["exact_objects"] == 158
        for row in prior_objects:
            raw = git("cat-file", row["type"], row["oid"], directory=PREVIOUS / "objects.git")
            assert len(raw) == row["bytes"] and digest(raw) == row["sha256"]
            put(row["type"], raw, row["oid"])
        assert git("rev-parse", BASE + "^{tree}").decode().strip() == BASE_TREE
        files = {}
        for row in old.file_rows(args.files_manifest):
            raw, oid = old.checked_file(row)
            assert row["path"] not in files, "duplicate changed path"
            mode = row.get("mode", "100644")
            assert mode in ("100644", "100755")
            files[row["path"]] = {"sha": put("blob", raw, oid), "mode": mode, "bytes": len(raw), "sha256": digest(raw)}
        assert files

        def revise(tree, updates, prefix=""):
            raw = git("cat-file", "tree", tree) if tree else b""
            entries, offset = {}, 0
            while offset < len(raw):
                end = raw.index(b"\0", offset)
                mode, name = raw[offset:end].split(b" ", 1)
                entries[name.decode()] = {"path": name.decode(), "mode": mode.decode(), "sha": raw[end + 1:end + 21].hex()}
                offset = end + 21
            assert offset == len(raw)
            groups = {}
            for path, update in updates.items():
                first, sep, rest = path.partition("/")
                if sep:
                    groups.setdefault(first, {})[rest] = update
                else:
                    if first in entries:
                        previous = entries[first]
                        assert previous["mode"] in ("100644", "100755")
                        old_raw = git("cat-file", "blob", previous["sha"])
                        assert old.oid("blob", old_raw) == previous["sha"]
                        assert previous["sha"] != update["sha"] or previous["mode"] != update["mode"], "unchanged path in manifest"
                    entries[first] = {"path": first, "mode": update["mode"], "sha": update["sha"]}
            for name, children in groups.items():
                previous = entries.get(name)
                assert previous is None or previous["mode"] == "40000"
                new_tree = revise(previous["sha"] if previous else None, children, prefix + name + "/")
                entries[name] = {"path": name, "mode": "40000", "sha": new_tree}
            return put("tree", old.tree_bytes(entries.values()))

        tree = revise(BASE_TREE, files)
        api = json.loads(api_bytes)
        assert api["sha"] == args.head and api["tree"]["sha"] == tree
        assert [p["sha"] for p in api["parents"]] == [BASE], "only exact direct d1d successor is admitted"
        commit, reconstruction = old.commit_bytes(api)
        put("commit", commit, args.head)
        save(args.output / "COMMIT_RECONSTRUCTION.json", reconstruction)
        changed = git("diff", "--name-only", "--diff-filter=AM", "--no-renames", "-z", BASE, args.head)
        paths = [p for p in changed.decode().split("\0") if p]
        assert sorted(paths) == sorted(files), "actual full incremental diff differs"
        all_status = git("diff", "--name-status", "--no-renames", BASE, args.head).decode().splitlines()
        assert all(row.startswith(("A\t", "M\t")) for row in all_status), "unexpected deletion/type change"
        (args.output / "changed-paths.stdout").write_bytes(changed)
        save(args.output / "EXPECTED_FILES.json", files)
        save(args.output / "EXACT_OBJECTS.json", list(imported.values()))
        for name, path, pin in (("check_blob_size.py", "scripts/check_blob_size.py", old.GATE), ("blob-size-allowlist.txt", ".github/blob-size-allowlist.txt", old.ALLOW)):
            assert git("rev-parse", args.head + ":" + path).decode().strip() == pin[0]
            raw = git("cat-file", "blob", pin[0])
            assert digest(raw) == pin[1]
            (args.output / name).write_bytes(raw)

        def state():
            answer = {name: digest((repo / name).read_bytes()) if (repo / name).is_file() else None for name in ("HEAD", "config", "index", "packed-refs")}
            answer["refs"] = {str(p.relative_to(repo)): digest(p.read_bytes()) for p in (repo / "refs").rglob("*") if p.is_file()}
            return answer

        before = state()
        argv = [sys.executable, str(args.output / "check_blob_size.py"), "--base", BASE, "--head", args.head, "--max-bytes", "512000", "--allowlist", str(args.output / "blob-size-allowlist.txt")]
        save(args.output / "INTENT.json", {"argv": argv, "cwd": str(repo), "timeout_seconds": 120, "before": before})
        began = time.monotonic()
        try:
            child = subprocess.run(argv, cwd=repo, env=environment, capture_output=True, timeout=120)
            stdout, stderr, code, timed_out = child.stdout, child.stderr, child.returncode, False
        except subprocess.TimeoutExpired as exc:
            stdout, stderr, code, timed_out = exc.stdout or b"", exc.stderr or b"", None, True
        (args.output / "stdout").write_bytes(stdout)
        (args.output / "stderr").write_bytes(stderr)
        after = state()
        result.update({"status": "PASS" if code == 0 and before == after else "FAIL", "exit_code": code, "timed_out": timed_out, "gate_wall_seconds": time.monotonic() - began, "tree": tree, "changed_paths": len(paths), "exact_objects": len(imported), "original_gate": old.GATE, "original_allowlist": old.ALLOW, "before": before, "after": after, "repository_identity_unchanged": before == after, "stdout_sha256": digest(stdout), "stderr_sha256": digest(stderr)})
    except Exception as exc:
        result.update({"status": "ERROR", "error": type(exc).__name__ + ": " + str(exc)})
        (args.output / "exception.txt").write_text(traceback.format_exc())
    result["owner_wall_seconds"] = time.monotonic() - start
    save(args.output / "RESULT.json", result)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files-manifest", required=True, type=Path)
    parser.add_argument("--head-api", required=True, type=Path)
    parser.add_argument("--head", required=True)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    arguments.output = arguments.output.resolve()
    raise SystemExit(main(arguments))
