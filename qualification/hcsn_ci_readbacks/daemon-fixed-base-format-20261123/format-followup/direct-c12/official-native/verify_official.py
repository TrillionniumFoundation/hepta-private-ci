"""Read, hash and independently recount the hosted daemon qualification snapshot."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = "fe38676fae170002fcdce90b36dc949fac3ff671"
DEFAULT_TREE = "7afec5e8ba43a101b4a4c1cf4f76a7a9af5384bf"
DEFAULT_RUN = 45150994913
FORMAT_BASE = "b8e8c6e82abc1479c573f61a5e17d28d581e6cad"
MAINTAINED_PACKAGES = ["codex-hepta-agentd", "codex-hepta-learning-artifacts", "codex-hepta-intelligence-eval", "codex-hepta-contracts", "codex-hepta-neuron", "codex-hepta-learning-ledger"]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git_tree(rows):
    root = {}
    for row in rows:
        if row.get("missing"):
            continue
        keys = row["path"].split("/")
        folder = root
        for key in keys[:-1]:
            folder = folder.setdefault(key, {})
        assert keys[-1] not in folder
        folder[keys[-1]] = (row["mode"], bytes.fromhex(row["blob"]))

    def digest_tree(folder):
        raw = bytearray()
        for key, value in sorted(folder.items(), key=lambda v: (v[0] + ("/" if isinstance(v[1], dict) else "")).encode()):
            mode, digest = ("40000", digest_tree(value)) if isinstance(value, dict) else value
            raw.extend(mode.encode() + b" " + key.encode() + b"\x00" + digest)
        return hashlib.sha1(b"tree " + str(len(raw)).encode() + b"\x00" + raw).digest()

    return digest_tree(root).hex()


def parse_xml(data):
    root = ET.fromstring(data)
    result = []
    for suite in root.iter("testsuite"):
        for case in suite.findall("testcase"):
            state = next((s for s in ("error", "failure", "skipped") if case.find(s) is not None), "passed")
            result.append((suite.get("name", ""), case.get("classname", ""), case.attrib["name"], state))
    assert len({r[:3] for r in result}) == len(result)
    return sorted(result)


def inspect_native(path, source, tree, run):
    outcome = {"archive_bytes": path.stat().st_size, "archive_sha256": sha(path.read_bytes()), "source": source, "run": run, "snapshots": {}, "cases": {}, "stages": {}}
    prior_bytes = (HERE / "previous-cases.json.gz").read_bytes()
    assert sha(prior_bytes) == "798bbf27e93646631a8a7dc22b7b5a5fc9825e2ab24550e6162e052fbdd0b747"
    baseline = json.loads(gzip.decompress(prior_bytes))
    with ZipFile(path) as z:
        names = set(z.namelist())
        load = lambda name: json.loads(z.read(name))
        status = load("qualification-status.json") if "qualification-status.json" in names else {}
        if status:
            assert status["source_sha"] == source
        outcome["qualification"] = status
        for label in ("checkout", "before-tests", "after-tests", "after-maintenance", "after-bins", "final"):
            if label + ".json" not in names:
                continue
            summary = load(label + ".json")
            raw = gzip.decompress(z.read(label + ".files.json.gz"))
            assert summary["commit"] == source and summary["tree"] == tree
            assert sha(raw) == summary["inventory_sha256"]
            rows = json.loads(raw)
            assert len(rows) == summary["files"]
            actual_tree = git_tree(rows)
            if summary["status"] == "":
                assert actual_tree == tree
            outcome["snapshots"][label] = dict(summary, physical_tree=actual_tree)
        for label in ("ordinary", "root"):
            if label + ".summary.json" not in names:
                continue
            text = z.read(label + ".xml")
            items = parse_xml(text)
            meta = load(label + ".summary.json")
            raw_exec = z.read(label + ".json")
            ex = json.loads(raw_exec)
            assert meta["source_sha"] == ex["source_sha"] == ex["tested_sha"] == source
            assert meta["source_tree"] == tree and int(meta["run_id"]) == int(ex["run_id"]) == run
            assert sha(text) == meta["junit_sha256"] and sha(raw_exec) == meta["execution_sha256"]
            assert meta["execution_file"] == label + ".json"
            counts = Counter(row[-1] for row in items)
            assert len(items) == meta["total_testcases"]
            assert (counts["failure"], counts["error"], counts["skipped"]) == (meta["failures"], meta["errors"], meta["skipped_in_xml"])
            actual_names = {tuple(row[:3]) for row in items}
            former = set(map(tuple, baseline[label]))
            launch = load(label + "-launch.json")
            uid = int(launch["required_euid"])
            assert (uid == 0) == (label == "root")
            if label == "root":
                assert launch["command"][:2] == ["sudo", "-n"] and b"Root fixture uid=0 " in z.read("root-setup.log")
                retained = load("root-parent-coverage.json")
                assert sorted(retained["expected"]) == sorted(retained["observed"]) == sorted(e[2] for e in items)
            outcome["cases"][label] = {"xml": dict(counts), "test_count": len(items), "required_euid": uid, "seconds": ex["elapsed_seconds"], "old_case_ids_absent": sorted(former - actual_names), "new_case_ids": sorted(actual_names - former), "source_tree": tree}
        if "original-learning-owner-coverage.json" in names:
            cover = load("original-learning-owner-coverage.json")
            assert cover["source_sha"] == source and cover["expected_count"] == len(cover["expected"])
            assert sha(z.read(cover["log_file"])) == cover["log_sha256"] and sha(z.read("ordinary.json")) == cover["execution_record_sha256"]
            outcome["ordinary_original_owner_coverage"] = [cover["expected_count"], cover["exact_pass_coverage"]]
        for label in ["source-closure", "helper-build", "ordinary", "root-setup", "root", "helper-verification", "fix", "fmt", "bins-check", "root-unmount-witness-bind", "root-unmount-bind"]:
            if label + ".json" not in names:
                continue
            row = load(label + ".json")
            raw = z.read(row.get("log_file", label + ".log"))
            assert len(raw) == row["log_bytes"] and sha(raw) == row["log_sha256"]
            assert not row.get("output_limit_exceeded", False) or row["returncode"] != 0
            if label in ("ordinary", "root", "fix", "bins-check"):
                command = row["command"]
                selected = [command[i+1] for i, token in enumerate(command[:-1]) if token == "-p"]
                assert selected == (["codex-hepta-agentd", "codex-hepta-contracts"] if label == "root" else MAINTAINED_PACKAGES)
            if label == "root-setup":
                assert ("Root fixture uid=0 path=/run/hepta-daemon-learning-" + str(run) + "-").encode() in raw
            if label == "fmt":
                assert row["command"] == ["just", "fmt", "--base", FORMAT_BASE]
            if label == "bins-check":
                assert row["command"][:4] == ["cargo", "check", "--locked", "--offline"] and row["command"][-1] == "--bins"
            outcome["stages"][label] = {"code": row.get("exit_code", row["returncode"]), "timed_out": row.get("timed_out", False), "log_bytes": len(raw), "log_sha256": sha(raw)}
        if "helpers/manifest.json" in names:
            helpers = load("helpers/manifest.json")
            assert helpers["source_sha"] == helpers["source_sha_after"] == source
            assert helpers["source_status_before"] == helpers["source_status_after"] == ""
            assert helpers["complete"] and helpers["exit_code"] == 0 and len(helpers["artifacts"]) == 2
            outcome["helpers"] = {key: {"bytes": value["bytes"], "sha256": value["sha256"], "package": value["package"]}
                                  for key, value in helpers["artifacts"].items()}
        if "maintenance-summary.json" in names:
            m = load("maintenance-summary.json")
            assert m["source_sha"] == source
            outcome["maintenance"] = {"complete": m["complete"], "paths": [v["path"] for v in m["files"]], "patch_sha256": sha(z.read("maintenance.patch")), "postimage_bytes": len(z.read("maintenance-postimages.jsonl"))}
            if not m["files"]:
                assert z.read("maintenance-postimages.jsonl") == z.read("maintenance.patch") == b""
        if "driver-error.json" in names:
            outcome["driver_error"] = load("driver-error.json")
    return outcome


def inspect_caller(path, source, tree):
    with ZipFile(path) as z:
        load = lambda n: json.loads(z.read(n))
        before, after = load("source-before.json"), load("source-after.json")
        assert before == after and before["head"] == source and before["tree"] == tree and before["status"] == ""
        stages = {}
        for phase in ("self-test", "verify"):
            row = load(phase + ".json")
            assert row["source_sha"] == source and row["command"] == ["python3", "scripts/verify_hepta_callers.py", phase]
            raw = z.read(phase + ".log")
            assert sha(raw) == row["log_sha256"] and len(raw) == row["log_bytes"]
            stages[phase] = {"code": row["returncode"], "log_bytes": len(raw), "log_sha256": sha(raw), "timed_out": row.get("timed_out")}
        detail = load("verify.log")
        assert detail["schema"] == "hepta.caller-proof-receipt.v2" and detail["status"] == "PASS_HEPTA_CALLER_CLOSED_SET"
        assert detail["authorityGranted"] is False
        summary = {key:len(detail[key]) for key in ("boundaries", "privilegedInventory", "protectedFiles")}
        summary["rustFilesScanned"] = detail["rustFilesScanned"]
        assert summary == {"boundaries":1652, "privilegedInventory":1652, "protectedFiles":826, "rustFilesScanned":9141}
        assert load("self-test.log")["status"] == "PASS_HEPTA_CALLER_PROOF_SELF_TEST"
    return {"archive_bytes": path.stat().st_size, "archive_sha256": sha(path.read_bytes()), "source_before_after": before, "original_inventory":summary, "stages": stages}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("native", type=Path)
    p.add_argument("--caller", type=Path)
    p.add_argument("--source", default=DEFAULT_SOURCE)
    p.add_argument("--tree", default=DEFAULT_TREE)
    p.add_argument("--run", type=int, default=DEFAULT_RUN)
    p.add_argument("--expect-all-green", action="store_true")
    a = p.parse_args()
    r = inspect_native(a.native, a.source, a.tree, a.run)
    if a.caller:
        r["caller"] = inspect_caller(a.caller, a.source, a.tree)
    if a.expect_all_green:
        assert a.caller and not r["qualification"]["failed"] and r["qualification"]["maintenance_complete"]
        assert set(r["snapshots"]) == {"checkout", "before-tests", "after-tests", "after-maintenance", "after-bins", "final"}
        assert not r["maintenance"]["paths"] and r["maintenance"]["complete"]
        assert r["ordinary_original_owner_coverage"] == [202, True]
        for n, count in [("ordinary", 2849), ("root", 68)]:
            v = r["cases"][n]
            assert v["xml"] == {"passed": count} and v["new_case_ids"] == v["old_case_ids_absent"] == []
        for key in ["source-closure", "helper-build", "ordinary", "root-setup", "root", "helper-verification", "fix", "fmt", "bins-check", "root-unmount-witness-bind", "root-unmount-bind"]:
            assert r["stages"][key]["code"] == 0 and not r["stages"][key]["timed_out"]
        assert all(v["code"] == 0 and not v["timed_out"] for v in r["caller"]["stages"].values())
    print(json.dumps(r, indent=2))


if __name__ == "__main__":
    main()
