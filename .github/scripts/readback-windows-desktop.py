"""Read the six existing desktop tests from the unchanged Windows sandbox unit target."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET

NAMES = {
    "legacy_refuses_before_workspace_desktop_mechanism_fixture",
    "legacy_refuses_before_readonly_desktop_mechanism_fixture",
    "desktop_rejects_unrestricted_and_invalid_tokens",
    "workspace_private_desktop_requires_a_qualified_token_backend",
    "readonly_desktop_requires_a_qualified_token_backend",
    "separate_desktop_roles_refuse_sessions_with_the_same_read_roots",
}

def evaluate(raw):
    lines = raw.decode("utf-8").splitlines()
    cases = []
    for line in lines:
        m = re.match(r"^test (\S+) \.\.\. (ok|FAILED|ignored)\b", line)
        if m:
            cases.append(m.groups())
    desktop = {n:v for n,v in cases if n.split("::")[-1] in NAMES}
    assert len(desktop) == len(NAMES) and {n.split("::")[-1] for n in desktop} == NAMES
    return {"desktop": desktop, "all_test_rows":len(cases),
            "counts":{k:sum(v==k for _,v in cases) for k in ("ok", "FAILED", "ignored")},
            "summaries":[s for s in lines if s.startswith("test result:")],
            "log_sha256":hashlib.sha256(raw).hexdigest()}

if __name__ == "__main__":
    out = Path(os.environ["RUNNER_TEMP"])/"desktop-owner"
    logs = list((Path(os.environ["BAZEL_OUTPUT_BASE"])/"execroot").glob(
        "*/bazel-out/*/testlogs/codex-rs/windows-sandbox-rs/windows-sandbox-rs-unit-tests/test.log"))
    assert len(logs) == 1, logs
    src = logs[0]
    shutil.copyfile(src, out/"test.log")
    shutil.copyfile(src.with_suffix(".xml"), out/"test.xml")
    ET.parse(out/"test.xml")
    result = evaluate(src.read_bytes())
    result["bazel_exit"] = int(sys.argv[1])
    (out/"result.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    assert result["bazel_exit"] == 0 and all(v=="ok" for v in result["desktop"].values())
