"""Compare a publication revision with the exact native CI build-input identity.

This is an identity check, not a new test execution. The CI receipt separately
establishes the results for its exact source commit. Research/evidence files
outside the declared native build scope do not inherit that test conclusion.
"""

import argparse
import fnmatch
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[3]
IDENTITY = Path(__file__).parent / "native-ci/41062425475/NATIVE_BUILD_INPUTS.json"
IDENTITY_SHA256 = "7e18e949550eb5dceba94a13546c168cfdcb864f573345f51fbf0130c750b7e7"
WORKFLOW = ".github/workflows/memory-cell-v11-native.yml"


def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=ROOT)


def commit(revision):
    return git("rev-parse", "--verify", "--end-of-options", revision + "^{commit}").decode().strip()


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def in_scope(path, patterns):
    for pattern in patterns:
        if pattern.endswith("/**"):
            if path.startswith(pattern[:-2]):
                return True
        elif "/" in pattern:
            if path == pattern:
                return True
        elif "/" not in path and fnmatch.fnmatchcase(path, pattern):
            return True
    return False


def entries(revision, patterns):
    result = []
    for record in git("ls-tree", "-rz", "--full-tree", revision).split(b"\0"):
        if not record:
            continue
        header, raw_path = record.split(b"\t", 1)
        path = raw_path.decode("utf-8")
        if in_scope(path, patterns):
            mode, kind, sha = header.decode("ascii").split()
            result.append(dict(path=path, mode=mode, type=kind, git_object=sha))
    return sorted(result, key=lambda item: item["path"])


def verify(revision):
    identity_bytes = IDENTITY.read_bytes()
    if hashlib.sha256(identity_bytes).hexdigest() != IDENTITY_SHA256:
        raise ValueError("The pinned CI input manifest changed; its scope cannot be redefined")
    identity = json.loads(identity_bytes)
    source = commit(identity["source_commit"])
    target = commit(revision)
    expected = identity["entries"]
    if len(expected) != identity["entry_count"] or digest(expected) != identity["entries_sha256"]:
        raise ValueError("Native build-input identity is internally inconsistent")
    source_entries = entries(source, identity["patterns"])
    if source_entries != expected:
        raise ValueError("Recorded identity differs from the actual tested Git commit")
    for candidate in (source, target):
        workflow = git("show", candidate + ":" + WORKFLOW)
        if hashlib.sha256(workflow).hexdigest() != identity["workflow_sha256"]:
            raise ValueError("Native workflow changed; prior test conclusion cannot be inherited")
    actual = entries(target, identity["patterns"])
    expected_by_path = {item["path"]: item for item in expected}
    actual_by_path = {item["path"]: item for item in actual}
    changed = sorted(path for path in expected_by_path.keys() | actual_by_path.keys()
                     if expected_by_path.get(path) != actual_by_path.get(path))
    return dict(
        schema="hepta.memory.v11.native-publication-input-check.v1",
        tested_commit=source, publication_commit=target,
        publication_tree=git("rev-parse", target + "^{tree}").decode().strip(),
        expected_entries=len(expected), actual_entries=len(actual),
        expected_entries_sha256=identity["entries_sha256"], actual_entries_sha256=digest(actual),
        native_build_inputs_equal=not changed, changed_paths=changed,
        test_run_url="https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/41062425475",
        new_tests_executed=False,
        scope="Only the recorded native/build inputs; research/evidence publication is not a new whole-head test.",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="HEAD")
    arguments = parser.parse_args()
    result = verify(arguments.revision)
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["native_build_inputs_equal"] else 1)
