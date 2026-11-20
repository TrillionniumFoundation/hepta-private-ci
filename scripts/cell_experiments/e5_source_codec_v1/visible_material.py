"""One-way material boundary: before runtime and the already fixed native task.

No changed-file list, patch, changed-node mask, after runtime, or future panel is
returned. The selector receives ordinary bytes and has no material-store handle.
"""

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath

from source_actions import canonical
from source_units import sha


def runtime_path(path, roots):
    parts = PurePosixPath(path).parts
    return not ({"tests", "test"} & set(parts)) and any(
        path == root or path.startswith(root + "/") for root in roots
    )


def checked(root, binding):
    raw = (root / "blobs" / binding["sha256"]).read_bytes()
    if sha(raw) != binding["sha256"] or len(raw) != binding.get("bytes", len(raw)):
        raise ValueError("material blob changed")
    git_sha = hashlib.sha1(
        b"blob " + str(len(raw)).encode() + b"\x00" + raw
    ).hexdigest()
    if binding.get("git_blob_sha1", git_sha) != git_sha:
        raise ValueError("material Git identity changed")
    return raw


def load_visible(root, material):
    roots = material["runtime_roots"]
    before = {r["path"]: r for r in material["snapshots"]["before"]}
    runtime = {
        p: checked(root, r)
        for p, r in before.items()
        if runtime_path(p, roots) and p.endswith((".py", ".pyx"))
    }
    receipt = material["native_receipts"]["before"]
    intent = json.loads(checked(root, receipt["PYTEST_INTENT.json"]))
    # These files were fixed test inputs of the historical before execution.
    # The role list, where present, is stronger than inferred filename roles.
    if "EXECUTION_MANIFEST.json" in receipt:
        execution = json.loads(checked(root, receipt["EXECUTION_MANIFEST.json"]))
        task_bindings = [r for r in execution if r["role"] == "original_after_fixture"]
        if not intent.get("after_tests_and_fixtures_unchanged"):
            raise ValueError("before receipt does not bind the fixed task fixtures")
    else:
        if not intent.get("original_test_file_unchanged"):
            raise ValueError("legacy before receipt does not bind the fixed test file")
        # Legacy four-source collection ran the original after tests with the
        # before runtime on PYTHONPATH. Only its non-runtime task files enter.
        task_bindings = [
            r
            for r in material["snapshots"]["after"]
            if not runtime_path(r["path"], roots)
        ]
    if any(runtime_path(r["path"], roots) for r in task_bindings):
        raise ValueError("runtime bytes cannot cross the fixed-task boundary")
    task = {r["path"]: checked(root, r) for r in task_bindings}
    tests = []
    for row in material["native_test_files"]:
        raw = checked(root, row)
        if task.get(row["path"]) != raw:
            raise ValueError("selected original test is not the before execution task")
        tests.append(row["path"])
    xml = checked(root, receipt["junit.xml"])
    cases = []
    for node in ET.fromstring(xml).iter("testcase"):
        failure = node.find("failure")
        if failure is None:
            failure = node.find("error")
        cases.append(
            {
                "classname": node.get("classname", ""),
                "name": node.get("name", ""),
                "failure": None if failure is None else failure.text or "",
                "skipped": node.find("skipped") is not None,
            }
        )
    if not cases or not any(c["failure"] is not None for c in cases):
        raise ValueError(
            "original complete selected before case identities/failures absent"
        )
    identity = {
        "schema": "hepta.e5-visible-material.v1",
        "source_id": material["source_id"],
        "before_commit": material["before_commit"],
        "runtime_roots": roots,
        "runtime": [
            {"path": p, "sha256": sha(b), "bytes": len(b)}
            for p, b in sorted(runtime.items())
        ],
        "task": [
            {"path": p, "sha256": sha(b), "bytes": len(b)}
            for p, b in sorted(task.items())
        ],
        "test_paths": sorted(tests),
        "selector": material["native_test_selector"],
        "before_junit_sha256": sha(xml),
        "cases_sha256": sha(canonical(cases)),
        "before_intent_sha256": receipt["PYTEST_INTENT.json"]["sha256"],
    }
    return {
        "identity": identity,
        "identity_sha256": sha(canonical(identity)),
        "runtime": runtime,
        "task": task,
        "cases": cases,
    }
