"""Make a new source-pinned supervisor for the newly qualified metadata core."""
import difflib
import hashlib
import json
from pathlib import Path
import sys
import zipfile

OLD_PROGRAM = "3ac51d32012f274f8a5a6afc4967569d0b9707b993cab0f5f9550c4e6495dbc1"
OLD_ENTRY = "7f2762c444031bc3d84131ec4cb6dd74790cbebd4b6a9229c6027886885ec0f9"
HELPER = "f58ca60428d3abafea377ca64e1d71040df98c4f149adce88436951187c990d6"
PLAN = "4ccfa7cc21ec37312e48d095e8f4b7373c765dd6d33fa9314ce724d161e8b06b"


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    original, program, output = map(Path, sys.argv[1:4])
    before = {n: (original / n).read_bytes() for n in ("complete_os_envelope.py", "os_processes.py")}
    assert identity(before["complete_os_envelope.py"])["sha256"] == OLD_ENTRY
    assert identity(before["os_processes.py"])["sha256"] == HELPER
    manifest = (program / "MANIFEST.json").read_bytes()
    new_program = identity(manifest)["sha256"]
    for name, expected in json.loads(manifest)["files"].items():
        assert identity((program / name).read_bytes()) == expected, name
    assert identity((program / "PLAN.json").read_bytes())["sha256"] == PLAN
    text = before["complete_os_envelope.py"].decode()
    old_line = "PROGRAM_SHA = '" + OLD_PROGRAM + "'"
    new_line = "PROGRAM_SHA = '" + new_program + "'"
    assert text.count(old_line) == 1 and new_program != OLD_PROGRAM
    changed = text.replace(old_line, new_line)
    assert changed.replace(new_line, old_line) == text
    output.mkdir(exist_ok=False)
    sources = {"complete_os_envelope.py": changed.encode(), "os_processes.py": before["os_processes.py"]}
    for name, raw in sources.items():
        compile(raw, name, "exec")
        (output / name).write_bytes(raw)
    patch = "".join(difflib.unified_diff(text.splitlines(True), changed.splitlines(True),
                                      fromfile="recovered-v2/complete_os_envelope.py", tofile="rebound-v3/complete_os_envelope.py"))
    (output / "DIFF-v2-to-v3.patch").write_text(patch)
    disabled = {"schema": "c2-resource-complete-os-authorization-v1", "execution_authorized": False,
                "limits": {"whole_wall_seconds": 120, "peak_RSS_bytes": 536870912, "workers": 1,
                           "threads": 1, "automatic_retry": False},
                "metadata_finalization_seconds": 30, "native_whole_seconds": 155,
                "startup_allowance_seconds": 5, "output_directory": None, "core_program_directory": None,
                "runtime_sources": {n: identity(raw) for n, raw in sources.items()},
                "source_sha256": identity(sources["complete_os_envelope.py"])["sha256"]}
    (output / "AUTHORIZATION-FRAGMENT-TEMPLATE.json").write_text(json.dumps(disabled, indent=2) + "\n")
    note = {"schema": "hcsn-complete-os-supervisor-rebind-v3", "program_manifest_sha256": new_program,
            "original_entry": OLD_ENTRY, "original_program_manifest": OLD_PROGRAM, "helper_unchanged": HELPER,
            "runtime_sources": disabled["runtime_sources"], "plan_sha256": PLAN,
            "changed_runtime_lines": 1, "compile_only_passed": True, "actual_execution_authorized": False,
            "actual_analysis_executed": False, "whole_supervisor_functional_tests_run": 0,
            "scope": "One literal program-manifest binding changed. Original v2 bytes retained separately. Current helper lifecycle validation and independent static review are separate records; no lost test credit inherited."}
    (output / "REBIND.json").write_text(json.dumps(note, indent=2) + "\n")
    (output / "prepare_complete_os_rebind_v3.py").write_bytes(Path(__file__).read_bytes())
    assert all((original / n).read_bytes() == raw for n, raw in before.items())
    assert (program / "MANIFEST.json").read_bytes() == manifest
    files = {p.name: identity(p.read_bytes()) for p in sorted(output.iterdir()) if p.is_file()}
    (output / "MANIFEST.json").write_text(json.dumps({"schema": "hcsn-complete-os-supervisor-v3-files", "files": files}, indent=2) + "\n")
    archive_path = output.with_suffix(".zip")
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.iterdir()):
            archive.write(path, path.name)
    print(json.dumps({"program_manifest_sha256": new_program, "runtime_sources": disabled["runtime_sources"],
                      "archive": identity(archive_path.read_bytes())}))


if __name__ == "__main__":
    main()
