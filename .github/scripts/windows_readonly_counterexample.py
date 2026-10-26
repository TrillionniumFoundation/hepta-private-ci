"""Run one disposable native readonly counterexample; restore every original byte."""

import argparse
import hashlib
import json
import re
import subprocess

import prepare_windows_delete_probe as original

CASE = "token::tests::readonly_counterexample::readonly_ambient_identity_does_not_write_or_delete"


def prepare(output):
    before = original.source()
    if before["trackedChanges"] or before["originalObjects"] != original.EXPECTED:
        raise RuntimeError("original token, ACL or test source differs")
    original.write(output, "source-before.json", before)
    path = original.ROOT / original.PATH
    path.write_text(
        '#[path = "../../../.github/scripts/windows_readonly_counterexample.rs"]\n'
        "mod readonly_counterexample;\n" + path.read_text()
    )
    original.write(
        output,
        "injection.json",
        {
            "originalObjects": original.EXPECTED,
            "instrumentedTestSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "originalAssertionsUnchanged": True,
            "productionAuthorityGranted": False,
            "securityQualification": False,
        },
    )


def collect(output):
    try:
        log = (output / "original-case.log").read_text(errors="replace")
        found = re.findall(r"HEPTA_READONLY_COUNTEREXAMPLE=(\{[^\n]+\})", log)
        if len(found) != 1:
            raise RuntimeError("exactly one actual readonly observation is required")
        facts = json.loads(found[0])
        assert facts["fixtureScopeOnly"] is True
        assert facts["productionAuthorityGranted"] is False
        assert facts["securityQualification"] is False
        original.write(output, "facts.json", facts)
    finally:
        subprocess.run(
            ["git", "restore", "--source=HEAD", "--worktree", "--", original.PATH],
            cwd=original.ROOT,
            check=True,
        )
        after = original.source()
        original.write(output, "source-after.json", after)
        before = json.loads((output / "source-before.json").read_text())
        original.write(
            output,
            "receipt.json",
            {
                "schema": "hepta.readonly-counterexample-receipt.v1",
                "status": "OBSERVATION_ONLY",
                "sourceRestored": before == after,
                "originalSourceUnchanged": after["originalObjects"]
                == original.EXPECTED,
                "testRetries": 0,
                "productionAuthorityGranted": False,
                "securityQualification": False,
            },
        )
        if before != after:
            raise RuntimeError("original production and test source was not restored")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run", "collect"))
    parser.add_argument("--output", type=original.Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.action == "prepare":
        prepare(args.output)
    elif args.action == "run":
        original.CASE = CASE
        return original.run(args.output)
    else:
        collect(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
