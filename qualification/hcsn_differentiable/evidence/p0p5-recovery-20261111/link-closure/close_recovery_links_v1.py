"""Append the two omitted exact context files and preserve the first link check."""

import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parent
REPO = ROOT / "hcsn-repo"
PREFIX = REPO / "qualification/hcsn_differentiable/evidence/p0p5-recovery-20261111"


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    original_manifest = (PREFIX / "MANIFEST.json").read_bytes()
    assert identity(original_manifest)["sha256"] == "272675d4597282720cedddebc389deea3c7d243dfcf377e56ff4acfbdd08b1fb"
    rows = {}

    def write(name, raw):
        p = PREFIX / name
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("xb") as stream:
            stream.write(raw)
        rows[name] = identity(raw)

    context = REPO / "qualification/hcsn_differentiable/evidence/p0p5-terminal-numerics-20261110/mathematical-diagnosis"
    copies = []
    for name in ("SOURCE-INDEX.json", "FOLLOWUP-PLAN.json"):
        src = context / name
        raw = src.read_bytes()
        target = "rare-tail-context/sources/" + name
        write(target, raw)
        copies.append({"source": str(src.relative_to(REPO)), "destination": target, **identity(raw)})
        assert src.read_bytes() == raw
    failure = json.loads((ROOT / "recovery-local-validation-v1/integrity.json").read_bytes())
    assert len(failure["errors"]) == 2
    assert {e["target"] for e in failure["errors"]} == {"SOURCE-INDEX.json", "FOLLOWUP-PLAN.json"}
    archive = PREFIX / "link-closure/ORIGINAL-CHECKS.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    members = []
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        sources = [ROOT / "recovery-local-validation-v1/INPUTS.json", ROOT / "recovery-local-validation-v1/integrity.json"]
        for directory in ("recovery-local-validation-v1/integrity-execution", "recovery-local-validation-v1/format-execution", "recovery-local-validation-v1/codespell-execution", "recovery-appendix-build-execution-v1"):
            sources.extend(sorted((ROOT / directory).iterdir()))
        for p in sources:
            raw = p.read_bytes(); name = p.relative_to(ROOT).as_posix()
            z.writestr(name, raw)
            members.append({"path": name, **identity(raw)})
        z.writestr("MEMBER-MANIFEST.json", json.dumps({"files": members}, indent=2, sort_keys=True) + "\n")
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for row in members:
            assert identity(z.read(row["path"])) == {k: row[k] for k in ("bytes", "sha256")}
    rows["link-closure/ORIGINAL-CHECKS.zip"] = identity(archive.read_bytes())
    note = {
        "schema": "hcsn-recovery-relative-link-closure-v1",
        "original_manifest": identity(original_manifest), "original_manifest_changed": False,
        "first_integrity_check_returncode": 1, "first_check_errors": failure["errors"],
        "cause": "The preserved old note used two relative filenames that were omitted or renamed when its source context was copied.",
        "repair": "Append both original files under the unchanged relative names and bind them in a separate manifest. The old note, reviewed new note and all original evidence bytes remain unchanged.",
        "copied": copies, "first_check_archive": rows["link-closure/ORIGINAL-CHECKS.zip"],
        "model_or_oracle_execution": False, "validation_rerun_reason": "Verify the two actual omitted-file corrections and the full declared CI evidence gate.",
        "cost_scope": "The preserved first integrity child, formatter, spelling and builder receipts retain complete child clocks; enclosing and nested measurements are not added.",
    }
    write("link-closure/CLOSURE.json", (json.dumps(note, indent=2, sort_keys=True) + "\n").encode())
    write("link-closure/close_recovery_links_v1.py", Path(__file__).read_bytes())
    assert (PREFIX / "MANIFEST.json").read_bytes() == original_manifest
    assert max(v["bytes"] for v in rows.values()) < 500000
    with (PREFIX / "LINK-CLOSURE-MANIFEST.json").open("x") as stream:
        json.dump({"schema": "hcsn-recovery-link-closure-manifest-v1", "files": rows}, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"files": len(rows), "manifest": identity((PREFIX / "LINK-CLOSURE-MANIFEST.json").read_bytes())}))


if __name__ == "__main__":
    main()
