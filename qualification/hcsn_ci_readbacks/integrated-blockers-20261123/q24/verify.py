"""Read preserved native evidence. No build, test, or network access."""
import argparse
import gzip
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
JOBS = {"current": 137481302823, "e29f": 136902076765, "round05": 135632103498}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def load(path):
    return json.loads(path.read_text())


def stage(lines, group):
    matches = [(i, m) for i, line in enumerate(lines) if (m := re.search(group, line))]
    assert len(matches) == 1, group
    return matches[0]


def observed(lines):
    assert len(lines) == 67 and "original_next_use_evidence_timing_diagnostic stdout" in lines[0]
    start, command = stage(lines, r"command_readback_elapsed_us=(\d+) result=Ok\(\(\)\)")
    cutoff, evidence = stage(lines, r'evidence_readback_elapsed_us=(\d+) result=Err\(OwnerUnavailable')
    _, _ = stage(lines, r"evidence_peer_terminal=Err\(Transport\(DeadlineElapsed\)\)")
    for suffix in ("command_peer_terminal=Ok(2)", "underlying_peer_terminal=Ok(6)"):
        assert any(suffix in line for line in lines[cutoff:])
    reads = []
    selector_us = []
    trainer_us = []
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if m := re.search(r"HEPTA_PUBLISHED_ORIGINAL_READ request_id=(\d+) cut_receipts=(\d+) owner_io_us=(\d+) total_handler_us=(\d+)", line):
            req, cut, owner, handler = map(int, m.groups())
            assert owner <= handler
            reads.append({"cut": cut, "request_id": req, "read_original_us": owner, "handler_us": handler, "logged_before_caller_return": i < cutoff})
        if m := re.search(r"HEPTA_SELECTOR_REMOTE_READBACK elapsed_us=(\d+) result=Ok\(\(\)\)", line):
            selector_us.append(int(m[1]))
        if m := re.search(r"HEPTA_SELECTOR_REMOTE_TRAINER_(?:BEFORE|AFTER) elapsed_us=(\d+) result=Ok\(\(\)\)", line):
            trainer_us.append(int(m[1]))
    assert [(r["cut"], r["request_id"]) for r in reads] == [(4, 6), (3, 12), (3, 13), (4, 7), (3, 14), (3, 15)]
    assert len(selector_us) == 2 and len(trainer_us) == 4
    return {
        "command_elapsed_us": int(command[1]), "command_fixture_timeout_ms": 30000,
        "evidence_caller_us": int(evidence[1]), "evidence_timeout_ms": 500,
        "sequential_published_calls": reads,
        "published_read_original_total_us_by_cut": {str(c): sum(r["read_original_us"] for r in reads if r["cut"] == c) for c in (4, 3)},
        "published_read_original_total_us": sum(r["read_original_us"] for r in reads),
        "published_read_original_logged_before_caller_return_us": sum(r["read_original_us"] for r in reads if r["logged_before_caller_return"]),
        "published_handler_total_us": sum(r["handler_us"] for r in reads),
        "outer_c_handlers_plus_whole_selector_us": sum(r["handler_us"] for r in reads if r["cut"] == 4) + sum(selector_us),
        "within_selector_trainer_us": trainer_us,
        "peer_terminals": {"evidence": "Transport(DeadlineElapsed)", "command": "Ok(2)", "underlying": "Ok(6)"},
    }


def archived_join(tree):
    p = tree / "qa/repository-consolidation/20261116/graph-and-ci-audit/follow-up/paired-eval-source-union"
    manifest = json.loads(gzip.decompress((p / "manifest.json.gz").read_bytes()))
    raw = bytearray()
    for c in manifest["carriers"]:
        physical = (p / c["path"]).read_bytes()
        assert sha(physical) == c["sha256"] and git_blob(physical) == c["git_blob"]
        decoded = gzip.decompress(physical)
        assert sha(decoded) == c["decoded_sha256"] and len(raw) == c["decoded_offset"]
        raw.extend(decoded)
    assert sha(raw) == manifest["archive_sha256"] == "3e35aa8e62a620d55a4bc513e1d3515a8633e556cd9eb7a0055638022cb4ef23"
    selected = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for row in manifest["originals"]:
            item = archive.extractfile(row["path"]).read()
            assert len(item) == row["bytes"] and sha(item) == row["sha256"] and git_blob(item) == row["git_blob"]
            if row["path"].endswith(("evidence-diagnostic-join-proposal-v1/proposal.json", "native-existing-two-v1/results.json")):
                selected[row["path"].split("/")[-1]] = json.loads(item)
    prop, result = selected["proposal.json"], selected["results.json"]
    assert prop["preservation"]["original_timing_read_calls_order_unchanged"]
    return {"verified_originals": len(manifest["originals"]), "archive_sha256": sha(raw),
            "proposal_postimage": prop["postimage"]["blob"], "proposal_qualification": prop["qualification"],
            "earlier_reproduction": result["summary"][:4]}


def verify(tree):
    current = load(HERE / "source_blobs.json")
    hosted = load(HERE / "hosted_sources.json")
    excerpts = load(HERE / "native_job_excerpts.json")
    for path, blob in current["blobs"].items():
        assert git_blob((tree / path).read_bytes()) == blob
    hist = load(tree / "qa/repository-consolidation/20261118/round-08/verification.json")
    native = hist["native_scope"]
    success = native["test_evidence"][1]
    assert success["deadline_ms_unchanged"] == 500 and success["exit_code"] == 0
    assert all(sha((tree / p).read_bytes()) == digest for p, digest in native["tested_files"].items())
    controls = tree / "codex-rs/hepta-agentd/src/circuit_next_use_command_support_tests.rs"
    assert controls.read_text().count("Duration::from_millis(500)") >= 2
    assert controls.read_text().count("Duration::from_secs(30)") >= 2
    older = tree / "qualification/learn-ordinary-ce434/paired-owner-convergence-20261112/diagnostic-e5c7-recovered-native/terminal/focused-native.execution.log"
    raw = older.read_bytes()
    assert sha(raw) == "3f3344f5fd7918d7be34cfca0a806c9d911cf72eebf572c9ac19ae719fb9a276"
    results = {}
    for key, job in JOBS.items():
        sources = hosted[str(job)]
        common = sum(current["blobs"][p] == b for p, b in sources["blobs"].items())
        assert common == (8 if key == "round05" else 10)
        assert all(sources["blobs"][p] == current["blobs"][p] for p in native["tested_files"])
        results[key] = {"job": job, "checkout": sources["checkout"], "hosted_run":sources["run"],
                        "matching_head_path_blobs_of_ten": common, **observed(excerpts[key])}
    return {"source_head": current["ref"], "hosted": results,
            "diagnostic_excerpts_sha256": sha((HERE / "native_job_excerpts.json").read_bytes()),
            "historical_unchanged_budget_success": {"base": native["base_commit"], "log_sha256": success["log_sha256"], "timings": success["timings"], "summary": success["summary"], "tested_product_files_already_equal": len(native["tested_files"])},
            "older_single_thread_raw_log_sha256": sha(raw),
            "older_single_thread_timing": sorted(set(re.findall(r"LEARN_FDE_C_TIMING (?:command|evidence)_readback_elapsed_us=[^\n]+",raw.decode()))),
            "archived_join_change": archived_join(tree),
            "interpretation": "The six Published read_original scopes execute sequentially on this tested remote path. Some scopes conclude after the caller has returned. Each is total wall time around a synchronous semantic read and validation function. The observations do not isolate CPU, I/O, or scheduler shares or imply any one check may be removed."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("tree", type=Path)
    print(json.dumps(verify(parser.parse_args().tree), indent=2))
