"""Exercise the repository's original postimage guard with its own harness and 12 file names."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


REFS = ("c12ee03f3185d5a13949faca54f066dfd634e509", "fe38676fae170002fcdce90b36dc949fac3ff671")
GUARDS = {
    ".github/workflows/hepta-daemon-learning-native.yml": "f50a7cf7b0464dbe1803da6b95ad04162843d6cc",
    "scripts/test_hepta_c_observer_coverage.py": "74acd33f2df98293a67c6444850dc65709b11a9b",
    "scripts/hepta_c_observer_coverage.py": "7076345e68856e68719ca96dc2b035029ba09ec1",
    "scripts/hepta_ci_junit.py": "683626df091bdfe160a8965fdc92bf40f5783cf8",
}
HERE = Path(__file__).resolve().parent
RUNNER = """
from pathlib import Path
import json
import sys
import tempfile
import unittest
from test_hepta_c_observer_coverage import OriginalObserverCoverageTests as Tests

methods = [
    "test_actual_workflow_retains_all_five_maintained_owner_postimages",
    "test_actual_workflow_still_refuses_maintenance_outside_exact_owner_scope",
]
suite = unittest.TestSuite(Tests(name) for name in methods)
result = unittest.TextTestRunner().run(suite)
assert result.wasSuccessful() and result.testsRun == len(methods)
paths = json.loads(sys.stdin.read())
expected = "codex-rs/hepta-agentd/src/prompt_product_v3.rs"
observed = {}
for changed in [[p] for p in paths] + [paths]:
    with tempfile.TemporaryDirectory() as temp:
        run, records, original, saved = Tests().maintenance_driver(Path(temp), tuple(changed))
        try:
            run(True)
        except RuntimeError as err:
            assert "outside its Rust owners" in str(err), err
            assert not saved and not (records / "maintenance-postimages.jsonl").exists()
            status = "rejected"
        else:
            assert changed == [expected] and saved["maintenance-summary.json"]["complete"]
            assert saved["maintenance-summary.json"]["files"][0]["path"] == expected
            status = "accepted"
        observed[changed[0] if len(changed) == 1 else "all_twelve_at_once"] = status
assert list(observed.values()).count("accepted") == 1 and observed["all_twelve_at_once"] == "rejected"
print(json.dumps({"original_owner_cases": 2, "path_controls": observed}))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    git = ["git", "-C", str(args.repo.resolve())]
    old, direct = REFS
    assert subprocess.check_output([*git, "rev-parse", direct + "^"]).decode().strip() == old
    source = json.loads((HERE / "product-diff.json").read_bytes())
    names = [r[0] for r in source]
    assert len(names) == 18
    assert subprocess.check_output([*git, "diff", "--name-only", "--no-renames", old, direct]).decode().splitlines() == names
    files = [p for p in names if p.startswith("codex-rs/")]
    assert len(files) == 12
    arms = {}
    for ref in REFS:
        with tempfile.TemporaryDirectory(prefix="hepta-original-write-guard-") as tmp:
            root = Path(tmp)
            for key, digest in GUARDS.items():
                obj = ref + ":" + key
                assert subprocess.check_output([*git, "rev-parse", obj]).decode().strip() == digest
                file = root / key
                file.parent.mkdir(exist_ok=True, parents=True)
                file.write_bytes(subprocess.check_output([*git, "show", obj]))
            run = subprocess.run([sys.executable, "-B", "-c", RUNNER], cwd=root / "scripts", input=json.dumps(files), text=True, capture_output=True, check=True)
            arms[ref] = json.loads(run.stdout)
    assert arms[old] == arms[direct]
    output = json.dumps({"guard_blobs": GUARDS, "results": arms}, indent=2) + "\n"
    if args.output:
        args.output.write_text(output)
    print(output)


if __name__ == "__main__":
    main()
