#!/usr/bin/env python3
"""Rebuild original ZIPs and verify logs/source without running archived code."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
HEAD = "0b9da54535a7795b2433947a479e6d9e71525e0a"


def require(value, message):
    if not value:
        raise RuntimeError(message)


def check(data, record):
    require(len(data) == record["bytes"] and hashlib.sha256(data).hexdigest() == record["sha256"], "size/hash mismatch")


def safe(name):
    path = Path(name)
    require(not path.is_absolute() and ".." not in path.parts, "unsafe path")
    return path


def main():
    require(not sys.flags.optimize, "verification requires assertions; optimized Python is rejected")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for name, identity in json.loads((ROOT / "FILES.json").read_text()).items():
        check((ROOT / safe(name)).read_bytes(), identity)
    archives = json.loads((ROOT / "archives.json").read_text())["archives"]
    require(len(archives) == 24, "archive inventory")
    for row in archives:
        require(row["encoding"] == "ordered-gzip-parts", "archive encoding")
        parts = []
        for part in row["parts"]:
            data = (ROOT / safe(part["path"])).read_bytes()
            check(data, part)
            raw = gzip.decompress(data)
            check(raw, {"bytes": part["raw_bytes"], "sha256": part["raw_sha256"]})
            parts.append(raw)
        data = b"".join(parts)
        check(data, row)
        archive = output / safe(row["archive_name"])
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(data)
        with zipfile.ZipFile(archive) as bundle:
            require(bundle.testzip() is None, "ZIP CRC")
            expected = {member["path"]: member for member in row["members"]}
            names = [entry.filename for entry in bundle.infolist() if not entry.is_dir()]
            require(len(names) == len(set(names)) and set(names) == set(expected), "ZIP member inventory")
            for entry in bundle.infolist():
                name = safe(entry.filename)
                require((entry.external_attr >> 16) & 0o170000 != 0o120000, "ZIP symlink")
                if not entry.is_dir():
                    content = bundle.read(entry)
                    check(content, expected[entry.filename])
                    path = archive.with_suffix("") / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
    joint = output / "joint"
    shutil.copyfile(ROOT / "metadata/joint-download-verification.json", joint / "download-verification.json")
    downloads = json.loads((joint / "download-verification.json").read_text())
    for family in ["aws", "operator", "matrix", "yaml"]:
        target = joint / family
        target.mkdir()
        for row in downloads:
            if row["component"].startswith(family + "-"):
                aid = str(row["artifact_id"])
                shutil.copytree(joint / aid, target / aid)
                archive = joint / (aid + ".zip")
                shutil.copyfile(archive, target / (aid + ".zip"))
                if family in {"matrix", "yaml"}:
                    shutil.copyfile(archive, target / aid / "artifact.zip")
        if family in {"aws", "operator"}:
            shutil.copyfile(ROOT / ("metadata/" + family + "-download-verification.json"), target / "download-verification.json")
        else:
            shutil.copyfile(ROOT / ("metadata/" + family + "-artifacts.json"), target / ("9cf-artifacts.json" if family == "matrix" else "artifact-metadata.json"))
    scripts = ROOT / "verifiers"
    commands = [
        ["verify_aws.py", "--artifacts", str(joint / "aws"), "--repository", str(args.repo), "--commit", HEAD],
        ["verify_operator.py", "--artifacts", str(joint / "operator"), "--repo", str(args.repo)],
        ["verify_matrix_0b9.py", "--artifacts", str(joint / "matrix"), "--repo", str(args.repo)],
        ["verify_yaml_0b9.py", "--artifacts", str(joint / "yaml"), "--repo", str(args.repo)],
        ["verify_keyring_0b9.py", "--artifacts", str(joint), "--repo", str(args.repo)],
        ["verify_all_components_0b9.py", "--artifacts", str(joint), "--repo", str(args.repo)],
        ["verify_v8.py", "--artifacts", str(output / "v8"), "--repo", str(args.repo)],
    ]
    receipts = []
    for command in commands:
        result = subprocess.run([sys.executable, str(scripts / command[0]), *command[1:]], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (output / (command[0] + ".stdout")).write_bytes(result.stdout)
        (output / (command[0] + ".stderr")).write_bytes(result.stderr)
        receipts.append({"script": command[0], "exit": result.returncode})
        require(result.returncode == 0, "independent verifier failed: " + command[0])
    for name in ["joint/VERIFIED-all-components.json", "joint/aws/root-independent-verification.json",
                 "joint/operator/root-independent-verification.json", "joint/matrix/VERIFIED.json",
                 "joint/yaml/VERIFIED.json", "joint/keyring-native-REPLAY_VERIFIED.json", "v8/WINDOWS_VERIFIED.json"]:
        require((output / name).read_bytes() == (ROOT / "reports" / name).read_bytes(), "replayed report differs: " + name)
    result = {"schema": "joint-and-v8-exact-evidence-replay-v1", "original_zip_archives": 24,
              "original_zip_bytes": sum(row["bytes"] for row in archives), "original_members": sum(len(row["members"]) for row in archives),
              "source_commit": HEAD, "exact_joint_git_input_paths": 1936,
              "joint_native_test_executions": 1342, "joint_original_service_operations": 12,
              "separate_v8_source": "bede07d3050d897a505020215a46a3ec8d66020d", "separate_v8_complete_tests": 115,
              "separate_v8_fresh_regression": 1, "independent_verifiers": receipts,
              "source_or_test_execution_by_this_replay": False, "release_state": "Draft / HOLD_NO_GO / DENY_ALL"}
    (output / "REPLAY_VERIFIED.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
