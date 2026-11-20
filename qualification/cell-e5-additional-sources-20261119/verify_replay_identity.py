"""Read original native receipts and compare test identities relative to their work root."""

import argparse
import hashlib
import json
from pathlib import Path
import time
import xml.etree.ElementTree as ET


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def case_identities(xml, work, pytest_root, test_files):
    prefix = ".".join(work.relative_to(pytest_root).parts) + "."
    modules = [".".join(Path(path).with_suffix("").parts) for path in test_files]
    result = []
    for case in ET.parse(xml).getroot().iter("testcase"):
        original = case.get("classname")
        assert original.startswith(prefix), (original, prefix)
        relative = original[len(prefix):]
        assert any(relative == module or relative.startswith(module + ".") for module in modules), relative
        result.append({"class": relative, "name": case.get("name"), "original_class": original})
    return result


def main(root, replay, output, source_commit):
    output.mkdir(exist_ok=False)
    began = time.perf_counter()
    plan = json.loads((root / "ACQUISITION_PLAN.json").read_bytes())
    original = json.loads((replay / "RESULT.json").read_bytes())
    assert original["actual_owned_children"] == len(original["stages"])
    index, sources = [], []
    for entry in plan["projects"]:
        old = next(row for row in original["by_source"] if row["project_id"] == entry["project_id"])
        if old["native_children"] == 0:
            sources.append(old)
            continue
        pair = []
        for variant in ("before", "after"):
            folder = replay / f"{entry['index']}-{variant}"
            work = folder / "work"
            receipt = json.loads((folder / "EXIT.json").read_bytes())
            assert receipt in original["stages"]
            assert sha(folder / "STDOUT.txt") == receipt["stdout_sha256"]
            assert sha(folder / "STDERR.txt") == receipt["stderr_sha256"]
            intent = json.loads((folder / "PYTEST_INTENT.json").read_bytes())
            returned = json.loads((folder / "PYTEST_RETURN.json").read_bytes())
            assert returned["exit_code"] == receipt["wait_returncode"]
            assert returned["execution_inputs_unchanged"]
            assert intent["revision"] == entry[variant + "_commit"]
            assert Path(intent["runtime_import"]).is_relative_to(work)
            after = json.loads((root / "snapshots" / f"{entry['index']}-after.json").read_bytes())
            by_path = {row["path"]: row for row in after["files"]}
            for test in intent["test_files"]:
                assert test["sha256"] == by_path[test["path"]]["sha256"] == sha(work / test["path"])
            ids = []
            if (folder / "junit.xml").exists():
                assert sha(folder / "junit.xml") == receipt["junit_sha256"]
                assert len(list(ET.parse(folder / "junit.xml").getroot().iter("testcase"))) == receipt["tests"]
                if receipt["errors"] == 0:
                    ids = case_identities(folder / "junit.xml", work, root, entry["test_files"])
                    assert len(ids) == receipt["tests"]
            pair.append({"receipt": receipt, "identities": ids})
            for name in ["EXIT.json", "PYTEST_INTENT.json", "PYTEST_RETURN.json", "EXECUTION_MANIFEST.json", "STDOUT.txt", "STDERR.txt", "junit.xml"]:
                path = folder / name
                if path.exists():
                    index.append({"path": str(path.relative_to(root)), "bytes": path.stat().st_size, "sha256": sha(path)})
        before, after = pair
        ids = lambda item: [(row["class"], row["name"]) for row in item["identities"]]
        left, right = before["receipt"], after["receipt"]
        equal = bool(ids(before)) and ids(before) == ids(after)
        admitted = left["wait_returncode"] == 1 and left.get("failures", 0) > 0 and left.get("errors", 1) == 0 and right["wait_returncode"] == 0 and right.get("passed", 0) > 0 and right.get("errors", 1) == 0 and left.get("tests") == right.get("tests") and equal and not left["timed_out"] and not right["timed_out"]
        if before["identities"]:
            tampered = list(ids(before))
            tampered[0] = (tampered[0][0], tampered[0][1] + "[foreign-parameter]")
            assert tampered != ids(before)
        sources.append({"project_id": entry["project_id"], "source_id": entry["source_id"], "original_regression_demonstrated": admitted, "case_identity_equal": equal, "before_failures": left.get("failures"), "after_passed": right.get("passed"), "before": before, "after": after, "original_failed_readout_preserved": True})
    result = {"schema": "hepta.original-native-relative-case-readback.v1", "source_commit": source_commit, "original_replay_result_sha256": sha(replay / "RESULT.json"), "original_plan_sha256": sha(root / "ACQUISITION_PLAN.json"), "identity_rule": "Strip only the exact known work-directory prefix imposed by pytest's configured root. Preserve full original test module, class, function, parameter identity, order and count.", "by_source": sources, "new_admitted_sources": sum(row["original_regression_demonstrated"] for row in sources), "original_native_children_reused": original["actual_owned_children"], "new_native_children": 0, "new_model_calls": 0, "new_training_updates": 0, "authenticated_users": 0, "source_growth_qualified": False, "full_system_cost_known": False, "wall_seconds": time.perf_counter() - began}
    for name, value in [("READOUT.json", result), ("EVIDENCE_INDEX.json", index)]:
        with (output / name).open("x") as stream:
            stream.write(json.dumps(value, sort_keys=True, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "by_source"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--replay", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    main(args.root.resolve(strict=True), args.replay.resolve(strict=True), args.output, args.source_commit)
