"""Run one immutable packet restore under -O and compare all original bytes."""

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess


ROOT = Path("/workspace/scratch/3f6a885bb83c")
WORK = Path(__file__).resolve().parent
BUNDLE = ROOT / "round3_core_evidence_supplement_partial_v4_v1"
PREVIOUS = ROOT / "round3_core_evidence_supplement_reporter_v3_v1"
DEST = WORK / "restored"


def require(value, message):
    if not value:
        raise ValueError(message)


def identity(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "mode": oct(path.lstat().st_mode)}


def write_json(path, value):
    with path.open("x") as output:
        output.write(json.dumps(value, indent=2) + "\n")


def main():
    require(not DEST.exists(), "Fresh restoration destination required")
    require(not (WORK / "RESTORATION.json").exists(), "Frozen receipt exists")
    before = {p.name: identity(p) for p in BUNDLE.iterdir()}
    index = json.loads((BUNDLE / "INDEX.json").read_bytes())
    reader = (BUNDLE / "restore.py").read_bytes()
    for current, old in [
        ("50325af62cbbcb0a9114ec73db3cd0f1e945dc1986e722255adc9ebf19fc2bac", "fe4eddb84725044d661fc880244a8c49ca5d7122f8a9325f76e264631320f24d"),
        ("d53dc79f547e8eb67238af93a618f3b0bed7383fdc00daf0cd424aac3d56e423", "5a8fdd5ca9c762535719bf078f01713f06f338a5f38415c50a3c3d569bdaeefd"),
    ]:
        require(reader.count(current.encode()) == 1, "Reader seal is not unique")
        reader = reader.replace(current.encode(), old.encode())
    require(reader == (PREVIOUS / "restore.py").read_bytes(), "Reader changed beyond seals")
    argv = ["python", "-O", "-B", str(BUNDLE / "restore.py"), str(BUNDLE), str(DEST)]
    completed = subprocess.run(argv, cwd=ROOT, capture_output=True, check=False)
    (WORK / "restore.stdout.log").open("xb").write(completed.stdout)
    (WORK / "restore.stderr.log").open("xb").write(completed.stderr)
    require(completed.returncode == 0, "Restore failed")
    expected = {row["path"]: row for row in index["files"]}
    actual = {p.relative_to(DEST).as_posix(): p for p in DEST.rglob("*") if p.is_file()}
    require(set(actual) == set(expected), "Restored file membership differs")
    for name, path in actual.items():
        require(stat.S_ISREG(path.lstat().st_mode), "Restored nonregular file")
        row = expected[name]
        current = identity(path)
        require(current == {key: row[key] for key in ("bytes", "sha256", "mode")}, "Restored bytes or mode differ")
        require(identity(ROOT / row["source_path"]) == current, "Original bytes or mode differ")
    after = {p.name: identity(p) for p in BUNDLE.iterdir()}
    require(before == after, "Bundle changed during restore")
    write_json(WORK / "RESTORATION.json", {
        "scope": "One real -O -B restoration and full original byte/mode/path comparison; no embedded code or tests executed.",
        "argv": argv, "exit_code": completed.returncode,
        "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
        "restored_files": len(actual), "restored_bytes": sum(row["bytes"] for row in expected.values()),
        "all_original_bytes_modes_source_paths_identical": True,
        "exact_member_set": True, "reader_equal_except_two_seals": True,
        "bundle_before": before, "bundle_after": after, "bundle_unchanged": True,
    })
    argv = ["python", "-m", "codespell_lib", "--ignore-words", ".codespellignore", "--skip", "./.git", *[str(p) for p in sorted(BUNDLE.iterdir())]]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "tooling/codespell-2.4.3")
    completed = subprocess.run(argv, cwd=ROOT / "hepta-complete-5083", env=env, capture_output=True, check=False)
    (WORK / "codespell.stdout.log").open("xb").write(completed.stdout)
    (WORK / "codespell.stderr.log").open("xb").write(completed.stderr)
    write_json(WORK / "CODESPELL.json", {
        "scope": "Original repository Codespell invocation on all five complete bundle files, including the gzip container.",
        "argv": argv, "cwd": str(ROOT / "hepta-complete-5083"), "exit_code": completed.returncode,
        "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
        "bundle_unchanged": before == {p.name: identity(p) for p in BUNDLE.iterdir()},
    })
    require(completed.returncode == 0, "Codespell failed")
    require(before == {p.name: identity(p) for p in BUNDLE.iterdir()}, "Bundle changed during checks")
    print(json.dumps({"restored_files": len(actual), "bytes": index["source_bytes"], "restore_exit": 0,
                      "codespell_exit": completed.returncode, "bundle_unchanged": True,
                      "restoration_receipt": identity(WORK / "RESTORATION.json"),
                      "codespell_receipt": identity(WORK / "CODESPELL.json")}, indent=2))


if __name__ == "__main__":
    main()
