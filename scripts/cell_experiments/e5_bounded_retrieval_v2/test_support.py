"""Synthetic byte fixtures only; no upstream package is imported or replayed."""

from v2_common import canonical, sha


def visible(runtime=None, task=None, cases=None):
    runtime = (
        runtime
        if runtime is not None
        else {
            "pkg/core.py": b"def bug(value):\n    return 'old'\n\ndef other():\n    return 'keep'\n"
        }
    )
    task = (
        task
        if task is not None
        else {"tests/test_core.py": b"def test_bug():\n    assert bug(1) == 'new'\n"}
    )
    cases = (
        cases
        if cases is not None
        else [
            {
                "classname": "tests.test_core",
                "name": "test_bug",
                "failure": "pkg/core.py:2: in bug\nE - old\nE + new\n",
                "skipped": False,
            }
        ]
    )
    identity = {
        "schema": "hepta.e5-visible-material.v1",
        "source_id": "synthetic:before-only",
        "before_commit": "a" * 40,
        "test_paths": ["tests/test_core.py"],
        "runtime": [
            {"path": p, "bytes": len(b), "sha256": sha(b)}
            for p, b in sorted(runtime.items())
        ],
        "task": [
            {"path": p, "bytes": len(b), "sha256": sha(b)}
            for p, b in sorted(task.items())
        ],
        "cases_sha256": sha(canonical(cases)),
    }
    return {
        "identity": identity,
        "identity_sha256": sha(canonical(identity)),
        "runtime": runtime,
        "task": task,
        "cases": cases,
    }
