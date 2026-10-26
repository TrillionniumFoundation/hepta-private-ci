"""Execute the original complete Operator Windows scope after fixture discovery."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import windows_current_ci as original


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if sys.platform != "win32" or output.is_relative_to(root):
        raise RuntimeError(
            "native Windows and diagnostics outside the checkout are required"
        )
    before = original.source(root)
    if before["head"] != args.expected_head or before["trackedChanges"]:
        raise RuntimeError("the original fixture scope requires the exact clean source")
    output.mkdir(parents=True, exist_ok=False)
    compiler = subprocess.check_output(["rustc", "--version", "--verbose"], text=True)
    (output / "compiler.txt").write_text(compiler)
    if not compiler.startswith("rustc 1.96.0 "):
        raise RuntimeError("the pinned compiler is required")
    scope_bytes = (root / ".github/fixtures/windows-current-ci-scope.json").read_bytes()
    scope = json.loads(scope_bytes)
    groups = [group for group in scope["groups"] if group["id"] == "operator-native"]
    if len(groups) != 1 or groups[0]["expectedTestCount"] != 26:
        raise RuntimeError("the original complete Operator selection changed")
    (output / "scope.json").write_text(json.dumps(groups, indent=2) + "\n")
    case_temp = Path(os.environ["RUNNER_TEMP"]) / "openssh-original-case-temp"
    case_temp.mkdir(exist_ok=False)
    os.environ["TEMP"] = os.environ["TMP"] = str(case_temp.resolve(strict=True))
    results = original.execute_groups(root, output, groups)
    after = original.source(root)
    intact = original.valid_source(args.expected_head, before, after)
    passed = intact and all(result["passed"] for result in results)
    log = (output / "operator-native.log").read_text(errors="replace")
    receipt = {
        "schema": "hepta.windows-openssh-original-fixture-scope.v1",
        "status": "PASS_DECLARED_OPERATOR_SCOPE"
        if passed
        else "FAIL_DECLARED_OPERATOR_SCOPE",
        "sourceBefore": before,
        "sourceAfter": after,
        "sourceUnchanged": intact,
        "scopeSha256": hashlib.sha256(scope_bytes).hexdigest(),
        "groups": results,
        "observedFixtureExecutablePaths": sorted(
            set(re.findall(r"HEPTA_FIXTURE_OPENSSH_KEYGEN=([^\r\n]+)", log))
        ),
        "testRetries": 0,
        "productionTrustedBinaryPolicyChanged": False,
        "nativeInheritedPipeQualification": False,
        "productionAuthorityGranted": False,
        "finalProductQualification": False,
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
