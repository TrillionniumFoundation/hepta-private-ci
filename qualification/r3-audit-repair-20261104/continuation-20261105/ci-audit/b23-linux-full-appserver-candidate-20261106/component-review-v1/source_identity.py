import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

BASE_COMMIT = "67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed"
BASE_TREE = "3982ba56dc5a3f1da0c1de7ea57992f88125c359"
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
HEAD_REF = "codex/b23-linux-app-server-original-gate-20261106"
WORKFLOW = ".github/workflows/hepta-b23-linux-app-server-original-gate.yml"
SOURCE_BLOBS = {
    ".github/workflows/bazel.yml": "9eed8ed8fa46c88d9d89d1499f55cb8c303137af",
    "defs.bzl": "6f588ec3057fddfea35170e28e74036162ce6a23",
    "codex-rs/app-server/BUILD.bazel": "a3c8ba463f34b031cc517501f41d67b60f2b9feb",
    "codex-rs/app-server/src/lib.rs": "484970198d5a8c71f0d4bf8e92fa0e8a2780f45e",
    "codex-rs/app-server/src/shutdown_signals.rs": "a45eca7491eb9d588a703668c10ab4aadf20b101",
    "codex-rs/app-server/src/shutdown_signals_tests.rs": "cf2f370bf35fc7cbb8d3b339f92f7da25b87cb51",
    ".bazelrc": "3d5877b283b887091af507f3672003f84c500687",
    ".github/scripts/run_bazel_with_buildbuddy.py": "21a5fdf0e7afcde4b6141229e95fcff8f6a7e763",
    ".github/actions/setup-ci/action.yml": "8abd2dbd5f09585734f8213011a9ed540a2ee88e",
    ".github/actions/check-clean-worktree/action.yml": "5a7bdddcf8f560d20fcd6639761a500b7ef12cf3",
    ".bazelversion": "b13d146a7b02b96e4c30340e69388d539c9721be",
    ".github/actions/prepare-bazel-ci/action.yml": "f9508a1659e5f2c54a6ae5b263bb9328095438d7",
    ".github/scripts/run-bazel-ci.sh": "42b59b6354b5933c8155b992519682c06d024ca1",
    "codex-rs/app-server/src/drain_handle_tests.rs": "18d30754feae43b4cfa358c96ab4161067935c24"
}


def git(*args):
    return subprocess.check_output(["git", *args], stderr=subprocess.PIPE)


def object_sha(kind, body):
    return hashlib.sha1(
        kind.encode() + b" " + str(len(body)).encode() + b"\0" + body
    ).hexdigest()


def tree_sha(entries):
    ordered = sorted(
        entries,
        key=lambda entry: entry["name"].encode()
        + (b"/" if entry["type"] == "tree" else b""),
    )
    body = b"".join(
        ("40000" if entry["type"] == "tree" else entry["mode"]).encode()
        + b" "
        + entry["name"].encode()
        + b"\0"
        + bytes.fromhex(entry["sha"])
        for entry in ordered
    )
    return object_sha("tree", body)


def flat_tree_sha(entries):
    directories = {"": []}
    for entry in entries:
        parent = entry["path"].rpartition("/")[0]
        while parent:
            directories.setdefault(parent, [])
            parent = parent.rpartition("/")[0]
    for entry in entries:
        parent, _, name = entry["path"].rpartition("/")
        directories[parent].append({**entry, "name": name})
    for path in sorted(
        (path for path in directories if path),
        key=lambda path: (-path.count("/"), path),
    ):
        parent, _, name = path.rpartition("/")
        directories[parent].append(
            {"name": name, "mode": "040000", "type": "tree",
             "sha": tree_sha(directories[path])}
        )
    return tree_sha(directories[""])


def check(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    phase = sys.argv[1]
    check(phase in ("before", "after"), "unknown source-check phase")
    public = Path(os.environ["RUNNER_TEMP"]) / "b23-app-server-evidence"
    public.mkdir(parents=True, exist_ok=True)
    record = {
        "phase": phase,
        "base_commit": BASE_COMMIT,
        "base_tree": BASE_TREE,
        "scope": "original full Linux AppServer target; diagnostic evidence only",
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "job": os.environ.get("GITHUB_JOB"),
        "runner_os": os.environ.get("RUNNER_OS"),
        "status": "failed",
    }
    try:
        check(os.environ.get("GITHUB_EVENT_NAME") == "pull_request",
              "expected pull_request event")
        check(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY,
              "unexpected repository")
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        pr = event["pull_request"]
        check(pr["base"]["sha"] == BASE_COMMIT, "base commit changed")
        check(pr["base"]["ref"] == "main", "unexpected base ref")
        check(pr["head"]["ref"] == HEAD_REF, "unexpected diagnostic ref")
        check(pr["head"]["repo"]["full_name"] == REPOSITORY,
              "unexpected head repository")
        check(os.environ.get("GITHUB_REF")
              == "refs/pull/" + str(event["number"]) + "/merge",
              "expected original PR merge checkout")
        checkout = git("rev-parse", "HEAD").decode().strip()
        check(checkout == os.environ["GITHUB_SHA"], "checkout SHA mismatch")
        commit = git("cat-file", "-p", "HEAD")
        header = commit.split(b"\n\n", 1)[0].splitlines()
        parents = [line[7:].decode() for line in header if line.startswith(b"parent ")]
        check(parents == [BASE_COMMIT, pr["head"]["sha"]],
              "merge parents differ from original base/head")
        raw_tree = git("ls-tree", "-r", "-z", "HEAD")
        entries = []
        seen = set()
        for item in raw_tree.split(b"\0"):
            if not item:
                continue
            fields, path_bytes = item.split(b"\t", 1)
            mode, kind, sha = fields.decode().split()
            path = path_bytes.decode()
            check(path not in seen, "duplicate Git path")
            seen.add(path)
            check(kind in ("blob", "commit"), "unexpected recursive leaf kind")
            entries.append({"path": path, "mode": mode, "type": kind, "sha": sha})
        workflow = [entry for entry in entries if entry["path"] == WORKFLOW]
        check(len(workflow) == 1 and workflow[0]["type"] == "blob"
              and workflow[0]["mode"] == "100644",
              "missing or unexpected diagnostic workflow leaf")
        original = [entry for entry in entries if entry["path"] != WORKFLOW]
        check(sum(entry["type"] == "blob" for entry in original) == 10582,
              "original blob leaf count changed")
        projected = flat_tree_sha(original)
        check(projected == BASE_TREE, "original tree projection changed")
        tree = git("rev-parse", "HEAD^{tree}").decode().strip()
        check(flat_tree_sha(entries) == tree, "complete checkout tree mismatch")
        check(object_sha("blob", Path(WORKFLOW).read_bytes()) == workflow[0]["sha"],
              "workflow working bytes differ from checkout")
        source = []
        for path, expected in sorted(SOURCE_BLOBS.items()):
            data = Path(path).read_bytes()
            actual = object_sha("blob", data)
            check(actual == expected, "original source working bytes changed")
            source.append({"path": path, "bytes": len(data), "git_blob": actual,
                           "sha256": hashlib.sha256(data).hexdigest()})
        subprocess.run(["git", "diff", "--exit-code", "--quiet", "HEAD", "--"],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        check(not git("ls-files", "--others", "--exclude-standard"),
              "unexpected untracked repository files")
        (public / ("source-tree-" + phase + ".ls-tree")).write_bytes(raw_tree)
        record.update({
            "status": "passed", "checkout_commit": checkout, "checkout_tree": tree,
            "event_head": pr["head"]["sha"], "merge_parents": parents,
            "original_tree_projection": projected,
            "original_blob_leaves": 10582, "workflow_blob": workflow[0]["sha"],
            "source_files": source,
        })
    except Exception as error:
        record["error_type"] = type(error).__name__
        # Error messages are fixed diagnostics, not event bodies or environment values.
        record["error"] = str(error)
    (public / ("source-" + phase + ".json")).write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"phase": phase, "status": record["status"]}))
    raise SystemExit(0 if record["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
