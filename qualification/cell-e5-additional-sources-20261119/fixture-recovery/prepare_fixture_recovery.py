"""Restore exact absent upstream fixtures and declared test dependency in a fresh root."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2) + "\n")


def main(previous, root, materials):
    assert sha(previous / "ACQUISITION_PLAN.json") == "8132c4f2ce9efa28c239dfd8e3fa96a57166dab5c557a6abc8415cd0e99afc84"
    assert sha(previous / "replay-1/RESULT.json") == "50abac1d0623247b549d85db241505cacede80d75386e579c430dc6570affdd7"
    assert json.loads((previous / "owner-1/RESULT.json").read_bytes())["stages"][-1]["exit_code"] == 2
    root.mkdir(exist_ok=False)
    plan = json.loads((materials / "ACQUISITION_PLAN.json").read_bytes())
    assert [entry["index"] for entry in plan["projects"]] == [7, 8]
    original = json.loads((previous / "ACQUISITION_PLAN.json").read_bytes())
    assert all(entry in original["projects"] for entry in plan["projects"])
    shutil.copyfile(materials / "ACQUISITION_PLAN.json", root / "ACQUISITION_PLAN.json")
    shutil.copyfile(previous / "ACQUISITION_PLAN.json", root / "ORIGINAL_ACQUISITION_PLAN.json")
    for name in ["replay_sources.py", "acquire_sources.py"]:
        shutil.copyfile(previous / name, root / name)
    receipts = []
    for entry in plan["projects"]:
        for variant in ("before", "after"):
            key = f"{entry['index']}-{variant}"
            manifest_path = previous / "snapshots" / (key + ".json")
            manifest = json.loads(manifest_path.read_bytes())
            src = previous / "repositories" / str(entry["index"]) / variant
            dst = root / "repositories" / str(entry["index"]) / variant
            for row in manifest["files"]:
                assert sha(src / row["path"]) == row["sha256"]
            shutil.copytree(src, dst)
            if entry["index"] == 8:
                tree_path = previous / "upstream-api" / f"8-{variant}-tree.json"
                tree = json.loads(tree_path.read_bytes())
                names = ["examples/__init__.py", "examples/jsonParser.py"]
                for name in names:
                    pinned = next(row for row in tree["tree"] if row["path"] == name)
                    data = (materials / "extra/8" / name).read_bytes()
                    git_hash = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
                    assert pinned["mode"] == "100644" and len(data) == pinned["size"] and git_hash == pinned["sha"]
                    target = dst / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as stream:
                        stream.write(data)
                    manifest["files"].append({"path": name, "bytes": len(data), "git_blob_sha1": git_hash, "sha256": sha(target), "mode": "100644"})
                manifest["omitted_from_execution_snapshot"] = [row for row in manifest["omitted_from_execution_snapshot"] if row["path"] not in names]
                manifest["fixture_recovery"] = {"original_manifest_sha256": sha(manifest_path), "tree_sha256": sha(tree_path), "exact_original_files": names, "reason": "Original test_unit.py imports original examples.jsonParser during collection."}
            write(root / "snapshots" / (key + ".json"), manifest)
            receipts.append({"identity": [entry["index"], variant], "source_manifest_sha256": sha(manifest_path), "recovery_manifest_sha256": sha(root / "snapshots" / (key + ".json"))})
    environment = root / "environment"
    environment.mkdir()
    wheels = root / "wheels"
    wheels.mkdir()
    for row in json.loads((previous / "environment/WHEELS.json").read_bytes()):
        src = previous / "wheels" / row["name"]
        assert sha(src) == row["sha256"] and src.stat().st_size == row["bytes"]
        shutil.copyfile(src, wheels / src.name)
    with urllib.request.urlopen("https://pypi.org/pypi/simplejson/json", timeout=30) as response:
        raw = response.read(32 * 1024 * 1024 + 1)
    (environment / "simplejson.pypi.json").write_bytes(raw)
    assert len(raw) <= 32 * 1024 * 1024
    version = json.loads(raw)["info"]["version"]
    requirements = json.loads((previous / "environment/DIRECT_REQUIREMENTS.json").read_bytes()) + ["simplejson==" + version]
    write(environment / "DIRECT_REQUIREMENTS.json", requirements)
    python = str(root / "venv/bin/python")
    commands = [[sys.executable, "-m", "venv", str(root / "venv")], [python, "-m", "pip", "--isolated", "--disable-pip-version-check", "download", "--only-binary=:all:", "--no-deps", "--dest", str(wheels), "simplejson==" + version], [python, "-m", "pip", "--isolated", "--disable-pip-version-check", "install", "--no-index", "--find-links", str(wheels), *requirements]]
    for i, argv in enumerate(commands):
        began = time.perf_counter()
        with (environment / f"{i}.stdout").open("xb") as out, (environment / f"{i}.stderr").open("xb") as err:
            process = subprocess.run(argv, stdout=out, stderr=err, timeout=240)
        row = {"argv": argv, "exit_code": process.returncode, "wall_seconds": time.perf_counter() - began}
        write(environment / f"{i}.EXIT.json", row)
        assert process.returncode == 0
    freeze = subprocess.run([python, "-m", "pip", "freeze", "--all"], capture_output=True, check=True, timeout=30).stdout
    (environment / "pip-freeze.txt").write_bytes(freeze)
    write(environment / "WHEELS.json", [{"name": path.name, "bytes": path.stat().st_size, "sha256": sha(path)} for path in sorted(wheels.iterdir())])
    write(root / "ACQUISITION.json", {"status": "ACQUIRED", "original_selection_unchanged": True, "recovery_pairs": [7, 8], "snapshots": receipts, "new_model_calls": 0, "new_training_updates": 0, "new_native_children": 0})
    print(json.dumps({"status": "READY", "recovery_pairs": [7, 8], "simplejson": version}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--materials", required=True, type=Path)
    args = parser.parse_args()
    main(args.previous, args.root, args.materials)
