#!/usr/bin/env python3
"""Assemble this study's completed raw evidence without importing experiment code."""

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tarfile
import tempfile


WORKSPACE = Path("/workspace/scratch/1d69f04ee9f4")
HEAD = "07df4a9cc385375cddded5b5e3b99632ce0652ec"
SEEDS = [1907, 2719, 4051]
MAX_FILE = 64_000_000
MAX_TOTAL = 256_000_000
MAX_FILES = 20_000
VALIDATION = "memory-population-validation-20261023"
CI = "memory-population-ci-preflight-20261023"
CI_LOGS = [f"{CI}/job-{job}-original.log" for job in (120343720772, 120344727109)]
CI_ARTIFACT = f"{CI}/artifact-12492396909-original.zip"
CI_ARTIFACT_SHA = "8a860080dae8306d6498ed0ab2129008e4dc0d45b5b2b7e2f4463a9fd9d3b89c"
CI_CLOSURE = f"{CI}/receipt-final-pr-success-20261023T093631Z.json"
CI_CORRECTION = f"{CI}/receipt-final-push-tests-verified-20261023T0935Z.json"
REPLAY_OWNER_DATABASE = "memory-population-relocated-replay-20261023/attempt-002/replay/owners.sqlite3"
REPLAY_OWNER_DATABASE_BYTES = 20_480
REPLAY_OWNER_DATABASE_SHA = "faf9e3fc60388d9e3007f7a8820806d96ad2df367c0e77e7f69fae9e3c3bf03f"
REQUIRED = {
    f"{VALIDATION}/unified-tests.log",
    f"{VALIDATION}/unified-tests-receipt.json",
    f"{VALIDATION}/unified-tests-r2.log",
    f"{VALIDATION}/unified-tests-r2-receipt.json",
    f"{VALIDATION}/all-frozen-runtime-source-binding.json",
    f"{CI}/receipt-final-push-success-20261023T093415Z.json",
    CI_CLOSURE,
    CI_CORRECTION,
    CI_ARTIFACT,
    REPLAY_OWNER_DATABASE,
    *CI_LOGS,
}
TEXT_SUFFIXES = {
    ".json", ".jsonl", ".log", ".txt", ".md", ".py", ".sh", ".yml",
    ".yaml", ".stdout", ".stderr", ".out", ".err", ".csv", ".tsv",
    ".zlib9", ".lzma6",
}


class AssemblyError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise AssemblyError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def json_object(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key: " + key)
            result[key] = value
        return result

    def bad_constant(value):
        raise AssemblyError("nonfinite JSON value: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)


def relative_name(name):
    require(isinstance(name, str) and name and "\\" not in name,
            "nonempty workspace-relative POSIX path required")
    parts = name.split("/")
    require(not name.startswith("/") and all(p not in ("", ".", "..") for p in parts)
            and all(ord(c) >= 32 for c in name), "unsafe relative path: " + repr(name))
    return name


def workspace_path(name):
    relative_name(name)
    path = WORKSPACE
    for part in name.split("/"):
        path = path / part
        require(not path.is_symlink(), "symlink is not evidence: " + name)
    return path


def state(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def read_stable(name):
    path = workspace_path(name)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), "regular file required: " + name)
    require(before.st_size <= MAX_FILE, "file exceeds raw-evidence bound: " + name)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        require(state(opened) == state(before), "file replaced before read: " + name)
        raw = stream.read(MAX_FILE + 1)
        after = os.fstat(stream.fileno())
    require(state(before) == state(after) == state(path.lstat())
            and len(raw) == before.st_size, "file changed while reading: " + name)
    return raw


def inclusion_reason(name):
    path = PurePosixPath(name)
    lower = path.name.lower()
    if name == REPLAY_OWNER_DATABASE:
        return None
    if lower.endswith((".safetensors", ".quantized", ".pt", ".pth", ".ckpt",
                       ".npy", ".npz", ".sqlite", ".sqlite3", ".db",
                       ".sqlite-wal", ".sqlite-shm", ".sqlite3-wal", ".sqlite3-shm",
                       ".db-wal", ".db-shm")):
        return "model_or_database_payload_excluded"
    if path.suffix == ".bin" and path.name != "seed-and-generator.bin":
        return "model_or_router_binary_excluded"
    if name == CI_ARTIFACT or path.name == "seed-and-generator.bin":
        return None
    if path.suffix in TEXT_SUFFIXES:
        return None
    return "unlisted_binary_or_cache_excluded"


def inventory(spec):
    roots = list(spec["evidence_sources"])
    roots += [value for value in (spec.get("independent_audit"),
                                  spec.get("checkpoint_archive_receipt"),
                                  spec.get("restore_tools_archive_receipt"),
                                  spec.get("isolated_replay_receipt")) if value]
    roots += list(spec.get("narratives", {}).values())
    files = {}
    missing = []
    for root_name in sorted(set(roots)):
        path = workspace_path(root_name)
        if not path.exists():
            missing.append(root_name)
            continue
        require(path.is_dir() or path.is_file(), "special evidence root: " + root_name)
        candidates = [path]
        if path.is_dir():
            candidates = []
            for directory, directories, names in os.walk(path, followlinks=False):
                for child in directories + names:
                    require(not (Path(directory) / child).is_symlink(),
                            "symlink in evidence tree: " + str(Path(directory) / child))
                candidates.extend(Path(directory) / name for name in names)
        for candidate in candidates:
            name = candidate.relative_to(WORKSPACE).as_posix()
            relative_name(name)
            info = candidate.lstat()
            require(stat.S_ISREG(info.st_mode), "special file in evidence tree: " + name)
            files[name] = {"bytes": info.st_size, "state": state(info),
                           "excluded_reason": inclusion_reason(name)}
    require(len(files) <= MAX_FILES, "evidence file count exceeds bound")
    selected = {name: row for name, row in files.items() if row["excluded_reason"] is None}
    require(sum(row["bytes"] for row in selected.values()) <= MAX_TOTAL,
            "selected raw evidence exceeds total bound")
    require(all(row["bytes"] <= MAX_FILE for row in selected.values()),
            "selected raw evidence exceeds per-file bound")
    return files, selected, missing


def check_ci_tests(raw):
    lines = [line.split("Z ", 1)[1] for line in raw.decode("utf-8").splitlines()
             if "Z " in line]
    indexed = [(i, line) for i, line in enumerate(lines) if line.startswith("test_")]
    require(all(line.endswith(" ... ok") or (i + 1 < len(lines) and lines[i + 1] == "ok")
                for i, line in indexed), "a final CI test did not pass")
    identifiers = [line.split(" (", 1)[1].split(")", 1)[0] for _, line in indexed]
    counts = [int(line.split()[1]) for line in lines if line.startswith("Ran ")]
    require(counts == [9, 9, 55] and len(identifiers) == len(set(identifiers)) == 73,
            "final CI must contain 73 distinct tests, counted once per run")
    require(raw.decode().count('test "$(git rev-parse HEAD)" = "$SOURCE_SHA"') == 2,
            "missing pre/post exact-head CI checks")
    return set(identifiers)


def check_relocated_replay(replay, expected, replay_result):
    require(isinstance(replay, dict) and isinstance(replay_result, dict),
            "replay receipt and raw replay result must be objects")
    require(replay.get("schema") == "hepta.population.isolated-relocated-replay.v1"
            and replay.get("passed") is True,
            "completed isolated replay receipt required")
    require(set(expected) == {
        "source_head", "archive_sha256", "archive_manifest_sha256",
        "independent_audit_sha256", "aggregate_sha256", "seed_result_sha256",
        "seed", "variant", "checkpoint_manifest_sha256", "router_sha256",
        "original_route_plan_sha256", "replay_result_sha256",
    }, "complete replay binding contract required")
    require(all(replay.get(key) == value for key, value in expected.items())
            and type(replay.get("seed")) is int,
            "replay source/archive/audit/result/checkpoint/route binding mismatch")
    for key in ("all_observed_research_modules_from_pinned_bundle",
                "initial_pythonpath_runtime_only", "archive_and_bundle_unchanged"):
        require(replay.get(key) is True, "isolated replay invariant missing: " + key)
    for key in ("original_repository_import_fallback_used", "original_experiment_modified",
                "answer_correctness_required", "general_portability_across_platforms_proven"):
        require(replay.get(key) is False, "isolated replay boundary missing: " + key)
    comparison = replay.get("reference_comparison")
    router = replay.get("router_replay")
    work = replay.get("work")
    require(isinstance(comparison, dict) and comparison.get("available") is True
            and comparison.get("all_fields_match") is True,
            "replay must match the retained raw output/token/state reference")
    require(isinstance(router, dict) and router.get("reference_available") is True
            and router.get("matches_original_frozen_route") is True
            and router.get("evidence_bundle_unchanged") is True
            and router.get("route_plan_sha256") == expected["original_route_plan_sha256"],
            "replay router must match the original frozen route")
    require(isinstance(work, dict)
            and type(work.get("additional_fresh_worker_processes")) is int
            and work["additional_fresh_worker_processes"] == 1
            and type(work.get("actual_queries")) is int and work["actual_queries"] == 1
            and work.get("counted_in_original_study") is False,
            "replay must be one additional process/query outside the original study")
    require(replay_result.get("reference_comparison") == comparison
            and replay_result.get("work") == work
            and replay_result.get("owner_admitted_before_and_after") is True
            and replay_result.get("evidence_bundle_unchanged") is True
            and replay_result.get("original_experiment_replaced") is False
            and replay_result.get("production_accepted") is False,
            "isolated replay receipt disagrees with its raw result")


def check_replay_owner_database(name, raw, replay):
    require(name == REPLAY_OWNER_DATABASE
            and len(raw) == REPLAY_OWNER_DATABASE_BYTES
            and sha(raw) == REPLAY_OWNER_DATABASE_SHA,
            "exact replay owner database path/size/SHA mismatch")
    require(replay.get("all_prior_replay_file_pins", {}).get(str(WORKSPACE / name))
            == REPLAY_OWNER_DATABASE_SHA
            and replay.get("work", {}).get("owner_database_bytes")
            == REPLAY_OWNER_DATABASE_BYTES,
            "replay receipt does not bind the exact owner database")


def replay_result_name(spec, replay):
    name = spec.get("isolated_replay_result")
    require(isinstance(name, str), "explicit completed replay result path required")
    relative_name(name)
    root = PurePosixPath(spec["isolated_replay_receipt"]).parent
    require(root in PurePosixPath(name).parents
            and PurePosixPath(name).name == "replay-result.json"
            and replay.get("replay_result_path") == str(WORKSPACE / name),
            "explicit replay result path disagrees with its final receipt")
    return name


def completed_inputs(spec):
    require(spec["schema"] == "hepta.population.evidence-assembly-spec.v1"
            and spec["source_head"] == HEAD and spec["seeds"] == SEEDS,
            "this helper is bound to the published source and registered cohort")
    pins = {}

    def raw(name):
        value = read_stable(name)
        digest = sha(value)
        require(name not in pins or pins[name] == digest, "gate input changed: " + name)
        pins[name] = digest
        return value

    def obj(name):
        return json_object(raw(name))

    study = spec["study_root"]
    execution = obj(study + "/execution-receipt.json")
    require(execution["source_head_before"] == execution["source_head_after"] == HEAD
            and execution["source_head_unchanged"] is True
            and execution["all_registered_seeds_executed"] is True
            and set(execution["exit_codes"]) == {str(seed) for seed in SEEDS}
            and all(type(code) is int for code in execution["exit_codes"].values()),
            "launcher completion receipt is incomplete or source changed")
    present = sorted(int(path.name[5:]) for path in workspace_path(study).glob("seed-*")
                     if path.is_dir() and path.name[5:].isdigit())
    require(present == SEEDS, "all and only the three registered seed directories required")
    require(spec.get("independent_audit"), "final independent cohort audit path is unset")
    audit = obj(spec["independent_audit"])
    require(audit["schema"] == "hepta.memory-population.independent-cohort-audit.v1"
            and audit["passed"] is True and audit["seeds"] == SEEDS
            and [trial["seed"] for trial in audit["trials"]] == SEEDS
            and all(trial["passed"] is True for trial in audit["trials"]),
            "passed complete three-seed artifact-consistency audit required")
    aggregate = obj(study + "/aggregate.json")
    require(audit["aggregate_sha256"] == pins[study + "/aggregate.json"]
            and aggregate["seeds"] == SEEDS
            and audit["claim_gates"] == aggregate["claim_gates"]
            and audit["general_memory_proven"] is False,
            "aggregate/audit binding mismatch")
    results = []
    for seed, trial in zip(SEEDS, audit["trials"]):
        name = f"{study}/seed-{seed}/result.json"
        result = obj(name)
        require(result["seed"] == seed and result["source_identity"]["git_head"] == HEAD
                and trial["result_sha256"] == pins[name], "audited result pin mismatch")
        if results:
            require(result["source_identity"] == results[0]["source_identity"]
                    and result["protocol_sha256"] == results[0]["protocol_sha256"],
                    "mixed source/runtime/protocol across seeds")
        require(all(type(value) is bool for value in result["engineering_gates"].values()),
                "nonboolean engineering gate")
        expected_exit = 0 if all(result["engineering_gates"].values()) else 1
        require(execution["exit_codes"][str(seed)] == expected_exit,
                "launcher exit code and final engineering gates disagree")
        results.append(result)
    for suffix, expected_exit in (("", 1), ("-r2", 0)):
        receipt = obj(f"{VALIDATION}/unified-tests{suffix}-receipt.json")
        log = raw(f"{VALIDATION}/unified-tests{suffix}.log")
        require(receipt["exit_code"] == expected_exit and receipt["log_sha256"] == sha(log),
                "first unified failure and corrected passing run must both remain intact")
    closure = obj(CI_CLOSURE)
    correction = obj(CI_CORRECTION)
    require(closure["target_head"] == HEAD and closure["push_conclusion"] == "success"
            and closure["pull_request_conclusion"] == "success"
            and correction["head_sha"] == HEAD
            and correction["distinct_successful_test_id_count"] == 73,
            "exact-head CI closure/correction receipt mismatch")
    ci_sets = [check_ci_tests(raw(name)) for name in CI_LOGS]
    require(ci_sets[0] == ci_sets[1], "push and PR test identity sets disagree")
    require(sha(raw(CI_ARTIFACT)) == CI_ARTIFACT_SHA, "CI original ZIP digest mismatch")
    stack = obj(spec["source_stack"])
    require(stack["head"] == HEAD and stack["stages"][-1]["sha"] == HEAD,
            "published source stack does not end at the frozen head")
    require(spec.get("checkpoint_archive_receipt"), "checkpoint ZIP receipt path is unset")
    checkpoint = obj(spec["checkpoint_archive_receipt"])
    require(checkpoint["schema"] == "hepta.population.archive-verification.v1"
            and checkpoint["passed"] is True
            and checkpoint["source_head"] == HEAD
            and checkpoint["independent_audit_sha256"] == pins[spec["independent_audit"]]
            and checkpoint["study_inputs_unchanged"] is True
            and checkpoint["shared_base_included"] is False
            and checkpoint["immutable_receipts_rewritten"] is False
            and checkpoint["checkpoints"] == 21 and checkpoint["routers"] == 3
            and checkpoint["owner_databases"] == 6 and checkpoint["packed_quantized_payloads"] == 6
            and type(checkpoint["files_verified"]) is int and checkpoint["files_verified"] > 0
            and type(checkpoint["archive_bytes"]) is int and checkpoint["archive_bytes"] > 0
            and re.fullmatch(r"[0-9a-f]{64}", checkpoint["archive_sha256"])
            and isinstance(checkpoint.get("manifest_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", checkpoint["manifest_sha256"]),
            "checkpoint archive receipt does not bind the same immutable study/audit")
    replay_name = spec.get("isolated_replay_receipt")
    require(isinstance(replay_name, str)
            and PurePosixPath(replay_name).name == "isolated-replay-receipt.json",
            "atomic final isolated-replay receipt path is required")
    replay = obj(replay_name)
    result_name = replay_result_name(spec, replay)
    replay_result = obj(result_name)
    require(spec.get("raw_payload_exact_exceptions") == [{
        "path": REPLAY_OWNER_DATABASE, "bytes": REPLAY_OWNER_DATABASE_BYTES,
        "sha256": REPLAY_OWNER_DATABASE_SHA,
    }], "only the one pinned replay owner database may be excepted")
    check_replay_owner_database(REPLAY_OWNER_DATABASE, raw(REPLAY_OWNER_DATABASE), replay)
    require(not list(workspace_path(REPLAY_OWNER_DATABASE).parent.glob("owners.sqlite3-*")),
            "replay owner database has unarchived WAL/SHM or other sidecars")
    route_plan_name = study + "/seed-1907/final/route-plan.json"
    raw(route_plan_name)
    single_lineage_name = study + "/seed-1907/training/single/lineage.json"
    raw(single_lineage_name)
    single = results[0]["training"]["versions"]["single"]
    require(len(single) == 1
            and single[0]["manifest_sha256"] == pins[single_lineage_name],
            "single checkpoint lineage does not match the completed trial")
    replay_bindings = {
        "source_head": HEAD,
        "archive_sha256": checkpoint["archive_sha256"],
        "archive_manifest_sha256": checkpoint["manifest_sha256"],
        "independent_audit_sha256": pins[spec["independent_audit"]],
        "aggregate_sha256": pins[study + "/aggregate.json"],
        "seed_result_sha256": {
            str(seed): pins[f"{study}/seed-{seed}/result.json"] for seed in SEEDS},
        "seed": 1907, "variant": "single",
        "checkpoint_manifest_sha256": pins[single_lineage_name],
        "router_sha256": results[0]["selection"]["router_receipt"]["sha256"],
        "original_route_plan_sha256": pins[route_plan_name],
        "replay_result_sha256": pins[result_name],
    }
    check_relocated_replay(replay, replay_bindings, replay_result)
    require(spec.get("restore_tools_archive_receipt"), "restore-tools archive receipt required")
    restore_tools = obj(spec["restore_tools_archive_receipt"])
    require(restore_tools.get("schema") == "hepta.population.restore-tools-archive-verification.v1"
            and restore_tools.get("passed") is True
            and restore_tools.get("immutable_original_archive_unchanged") is True
            and restore_tools.get("original_checkpoint_sha256") == checkpoint["archive_sha256"]
            and restore_tools.get("isolated_replay_receipt_sha256") == pins[replay_name]
            and restore_tools.get("model_workers_started_to_fix_or_package_tools") == 0
            and restore_tools.get("members_verified") == 9
            and restore_tools.get("archive_bytes") == 28_880
            and restore_tools.get("archive_sha256")
            == "0d738a72630d0dd372209410860850fa1ab2e9275b980f08ff48ec1d822c40cc",
            "restore-tools receipt must bind the original archive and completed replay")
    return {"pins": pins, "execution": execution, "audit": audit, "aggregate": aggregate,
            "results": results, "stack": stack, "checkpoint": checkpoint,
            "ci_closure": closure, "distinct_ci_test_ids": sorted(ci_sets[0]),
            "isolated_replay": replay, "restore_tools": restore_tools}


def capture_manifest(spec, completed):
    all_files, selected, missing = inventory(spec)
    require(not missing, "missing evidence sources: " + repr(missing))
    require(REQUIRED <= selected.keys(), "mandatory failed/corrected evidence was omitted")
    require(set(completed["pins"]) <= selected.keys(), "a gate input is outside the archive")
    records = {}
    for name in sorted(selected):
        raw = read_stable(name)
        digest = sha(raw)
        require(name not in completed["pins"] or completed["pins"][name] == digest,
                "gate input changed before capture: " + name)
        records["raw/" + name] = {"bytes": len(raw), "sha256": digest}
    excluded = {name: {"bytes": row["bytes"], "reason": row["excluded_reason"],
                       "bytes_not_read_or_hashed_by_this_tool": True}
                for name, row in sorted(all_files.items()) if row["excluded_reason"]}
    manifest = {"schema": "hepta.population.raw-evidence-manifest.v1",
                "source_head": HEAD, "seeds": SEEDS, "files": records,
                "file_count": len(records), "raw_bytes": sum(r["bytes"] for r in records.values()),
                "excluded_files": excluded, "complete_input_pins": completed["pins"],
                "distinct_final_ci_tests": 73, "ci_runs_observed": 2,
                "same_tests_in_two_runs_are_not_146_independent_tests": True,
                "original_bytes_rewritten": False, "checkpoint_archive_receipt": spec["checkpoint_archive_receipt"],
                "isolated_replay_receipt": spec["isolated_replay_receipt"],
                "restore_tools_archive_receipt": spec["restore_tools_archive_receipt"],
                "raw_payload_exact_exceptions": spec["raw_payload_exact_exceptions"],
                "isolated_replay_is_additional_work_not_original_study": True,
                "checkpoint_zip_reopened_by_this_tool": False}
    return manifest, all_files


def deterministic_archive(path, manifest):
    with path.open("xb") as target:
        with gzip.GzipFile(filename="", mode="wb", fileobj=target, compresslevel=9, mtime=0) as packed:
            with tarfile.open(fileobj=packed, mode="w|", format=tarfile.GNU_FORMAT) as archive:
                for name in sorted(["MANIFEST.json", *manifest["files"]]):
                    if name == "MANIFEST.json":
                        raw = json_bytes(manifest)
                    else:
                        raw = read_stable(name[4:])
                        require({"bytes": len(raw), "sha256": sha(raw)} == manifest["files"][name],
                                "file changed after inventory: " + name)
                    member = tarfile.TarInfo(name)
                    member.size, member.mode, member.mtime = len(raw), 0o444, 0
                    member.uid = member.gid = 0
                    member.uname = member.gname = ""
                    archive.addfile(member, io.BytesIO(raw))


def table(rows):
    return "\n".join("| " + " | ".join(str(x).replace("|", "\\|").replace("\n", " ")
                                      for x in row) + " |" for row in rows)


def documents(spec, completed, manifest):
    aggregate = completed["aggregate"]
    claims = aggregate["claim_gates"]
    readme = f"""# Hepta memory population evidence — 2026-10-23

Frozen experimental source: `{HEAD}`. Registered seeds: 1907, 2719, 4051.

This directory preserves completed raw observations and negative outcomes. The evidence publication is separate from the frozen experimental source; publishing it does not change the source that produced the observations.

`raw-evidence.tar.gz` contains original bytes under `raw/` plus its own `MANIFEST.json`. `raw-evidence.manifest.json` is the same manifest outside the archive. Every included file has a byte count and SHA-256. Tar members are sorted with fixed metadata; gzip uses mtime zero and no original filename.

The archive contains {manifest['file_count']} original files ({manifest['raw_bytes']} bytes before tar/compression). Model weights, quantized/router binaries and SQLite files are excluded and listed explicitly, with one exact recovery-evidence exception: `{REPLAY_OWNER_DATABASE}` ({REPLAY_OWNER_DATABASE_BYTES} bytes, SHA-256 `{REPLAY_OWNER_DATABASE_SHA}`). Its original bytes are checked against the completed replay receipt; no other database or WAL/SHM is admitted by that exception. Original JSON, write/read/codec receipts, failure logs, corrections, source-stack records, launch review, CI logs and the small original CI artifact remain intact. Auxiliary validation payload omissions are also disclosed; this tool does not claim that every historical payload is in the checkpoint ZIP.

The separately verified checkpoint ZIP is referenced by its original receipt. ZIP SHA-256: `{completed['checkpoint']['archive_sha256']}`. This assembly tool validates the receipt's source/audit binding; it does not reopen that model archive. The shared base is not bundled. Keep costs and exclusions in the original receipts when interpreting compression claims.

The separately verified restore-tools supplement is {completed['restore_tools']['archive_bytes']} bytes, SHA-256 `{completed['restore_tools']['archive_sha256']}`. Its nine verified members contain the corrected optional wrapper, postprocessor, guide and replay completion receipts. Both the initial cross-device hardlink failure and the later import-trace parser failure remain in this raw archive. The correction used retained model output and one router inference; it started no additional model worker and did not rewrite the checkpoint ZIP.

The completed isolated relocated replay is bound to this same ZIP and archive manifest, original audit, aggregate, all three seed results, the seed-1907 single checkpoint and its frozen route. It executed one additional fresh worker query outside the original study and matched the original raw output/token/state and learned route. It establishes this specific source-isolated replay, not answer correctness, cross-platform portability, general memory or new study scores.

The two successful final CI runs executed the same 73 distinct tests. They are two executions, not 146 independent tests. The first local unified-run failure, its corrected rerun, the initial CI count-parser error receipt, and its correction are retained.

Verify without loading any model or executing experimental tests:

```bash
python -B tools/assemble_evidence.py verify --bundle .
```

See `summary.md`, `blocker-register.md`, and `source-stack.md`. Artifact consistency, successful mechanism tests, and scientific hypothesis support are separate results. This finite study does not establish general memory or production acceptance.
"""
    summary = "# Completed three-seed results\n\n"
    summary += table([["Claim", "Registered result"], ["---", "---"],
                      *[[key, str(value).lower()] for key, value in sorted(claims.items())]])
    summary += "\n\nAll registered seeds and failed hypotheses are retained. A passed independent audit establishes artifact consistency and reconstruction, not remote execution attestation or proof that the research hypotheses succeeded.\n"
    for result in completed["results"]:
        summary += f"\n## Seed {result['seed']}\n\n```json\n"
        summary += json_bytes({"summary": result["summary"],
                               "engineering_gates": result["engineering_gates"],
                               "research_gates": result["research_gates"]}).decode() + "```\n"
    blockers = "# Blocker and claim register\n\n"
    rows = [["Item", "Evidence status", "Meaning"], ["---", "---", "---"],
            ["Exact-head mechanism CI", "closed", "73 distinct tests; push and PR both passed"],
            ["Three registered trial processes", "complete", "All three exit codes and final results retained"],
            ["Independent cohort audit", "passed", "Original aggregate and all three result hashes match"],
            ["Checkpoint archive", "receipt-bound", "Separate original ZIP receipt bound to this audit and source"],
            ["Isolated relocated replay", "passed and receipt-bound",
             "One additional process/query; source/ZIP/audit/three results/raw output and route pins match"]]
    for key, value in sorted(claims.items()):
        rows.append([key, "supported on registered finite suite" if value else "not established",
                     "Scientific outcome; never relabeled as an engineering test failure or erased"])
    blockers += table(rows) + "\n\nEarlier workflow observations retained with the 09:36:31 UTC mechanism-CI closure are historical snapshots. The appended timestamped CI narrative records the final observation used for this publication.\n\n"
    blockers += "```json\n" + json_bytes(completed["ci_closure"]["other_exact_head_workflows"]).decode() + "```\n"
    blockers += "\nQueued workflows are neither successes nor failures. Their later status is not inferred here. Full system cost comparison, external authority, distributed consistency, and general memory retain the boundaries recorded in the original study.\n"
    stack = completed["stack"]
    source_stack = f"# Frozen source stack\n\nFinal HEAD: `{HEAD}`\n\nGit tree: `{stack['tree']}`\n\n"
    source_stack += "Predecessor HEAD: `2b42a265e51ad2ac0d2127e8f6b81cc4fa4d1b3b`.\n\n"
    source_stack += table([["Stage", "Change", "HEAD", "PR"], ["---", "---", "---", "---"],
                           *[[stage["index"], stage["title"], stage["sha"], stage["pr"]["url"]]
                             for stage in stack["stages"]]]) + "\n"
    source_stack += "\nThe original published-source-stack JSON is retained in the raw archive. Historical pre-fix source snapshots are evidence of earlier failures and are not substituted for this final source.\n"
    values = {"README.md": readme.encode(), "summary.md": summary.encode(),
              "blocker-register.md": blockers.encode(), "source-stack.md": source_stack.encode()}
    for name, source in spec.get("narratives", {}).items():
        require(name in values, "unknown root narrative filename: " + name)
        values[name] += b"\n\n---\n\n" + read_stable(source)
    return values


def verify_bundle(bundle):
    root = Path(bundle)
    require(root.is_dir() and not root.is_symlink(), "bundle directory required")
    checksums_path = root / "checksums.json"
    require(not checksums_path.is_symlink() and stat.S_ISREG(checksums_path.lstat().st_mode)
            and checksums_path.stat().st_size <= MAX_FILE, "bounded regular checksums file required")
    checksums = json_object(checksums_path.read_bytes())
    expected_names = set(checksums["files"]) | {"checksums.json"}
    actual_names = set()
    for path in root.rglob("*"):
        require(not path.is_symlink(), "symlink in assembled bundle")
        require(path.is_dir() or stat.S_ISREG(path.lstat().st_mode), "special file in assembled bundle")
        if path.is_file():
            actual_names.add(path.relative_to(root).as_posix())
    require(actual_names == expected_names, "unexpected/missing bundle files")
    for name, row in checksums["files"].items():
        relative_name(name)
        require(type(row["bytes"]) is int and 0 <= row["bytes"] <= MAX_TOTAL + MAX_FILE
                and (root / name).stat().st_size == row["bytes"], "bundle member size mismatch")
        raw = (root / name).read_bytes()
        require({"bytes": len(raw), "sha256": sha(raw)} == row, "bundle checksum mismatch: " + name)
    manifest_raw = (root / "raw-evidence.manifest.json").read_bytes()
    manifest = json_object(manifest_raw)
    seen = set()
    total = 0
    with tarfile.open(root / "raw-evidence.tar.gz", "r:gz") as archive:
        for member in archive:
            relative_name(member.name)
            require(member.isfile() and member.name not in seen and member.size <= MAX_FILE,
                    "unsafe/duplicate/oversize tar member")
            require(member.mode == 0o444 and member.uid == member.gid == member.mtime == 0
                    and member.uname == member.gname == "", "noncanonical tar metadata")
            seen.add(member.name)
            total += member.size
            require(total <= MAX_TOTAL + MAX_FILE, "archive exceeds cumulative bound")
            require(len(seen) <= MAX_FILES + 1, "too many archive entries")
            raw = archive.extractfile(member).read(MAX_FILE + 1)
            if member.name == "MANIFEST.json":
                require(raw == manifest_raw, "embedded manifest differs")
            else:
                require(member.name in manifest["files"] and
                        {"bytes": len(raw), "sha256": sha(raw)} == manifest["files"][member.name],
                        "tar member digest mismatch: " + member.name)
    require(seen == {"MANIFEST.json", *manifest["files"]}, "tar inventory mismatch")
    return {"passed": True, "raw_files_verified": len(manifest["files"]),
            "archive_sha256": checksums["files"]["raw-evidence.tar.gz"]["sha256"],
            "source_head": manifest["source_head"], "experimental_tests_executed": False}


def assemble(spec, output):
    completed = completed_inputs(spec)
    manifest, original_inventory = capture_manifest(spec, completed)
    destination = workspace_path(output)
    require(not destination.exists(), "output must not already exist")
    require(not destination.is_relative_to(WORKSPACE / "hepta-private-ci"),
            "stage evidence outside the frozen repository; publication is a separate action")
    for source in spec["evidence_sources"]:
        require(not destination.is_relative_to(workspace_path(source)), "output is inside an input tree")
    require(destination.parent.is_dir(), "output parent directory must exist")
    with tempfile.TemporaryDirectory(prefix=".population-assembly-", dir=destination.parent) as temporary:
        stage = Path(temporary)
        deterministic_archive(stage / "raw-evidence.tar.gz", manifest)
        outputs = documents(spec, completed, manifest)
        outputs["raw-evidence.manifest.json"] = json_bytes(manifest)
        outputs["assembly-spec.json"] = json_bytes(spec)
        outputs["tools/assemble_evidence.py"] = Path(__file__).read_bytes()
        outputs["assembly-receipt.json"] = json_bytes({
            "schema": "hepta.population.evidence-assembly-receipt.v1", "source_head": HEAD,
            "completed_execution_utc": completed["execution"]["finished_utc"],
            "seeds": SEEDS, "gate_input_sha256": completed["pins"],
            "distinct_final_ci_test_ids": completed["distinct_ci_test_ids"],
            "ci_successful_runs": 2, "distinct_final_tests": 73,
            "experimental_tests_executed_by_assembly": False,
            "source_files_modified": False, "remote_mutations": False,
            "helper_sha256": sha(outputs["tools/assemble_evidence.py"]),
            "original_evidence_bytes_rewritten": False})
        for name, raw in sorted(outputs.items()):
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(raw)
        require(inventory(spec)[0] == original_inventory, "input inventory changed during assembly")
        for name, row in manifest["files"].items():
            require(sha(read_stable(name[4:])) == row["sha256"], "input content changed during assembly: " + name)
        completed_again = completed_inputs(spec)
        require(completed_again["pins"] == completed["pins"], "completion/audit binding changed during assembly")
        hashes = {path.relative_to(stage).as_posix(): {"bytes": path.stat().st_size,
                  "sha256": sha(path.read_bytes())} for path in sorted(stage.rglob("*")) if path.is_file()}
        (stage / "checksums.json").write_bytes(json_bytes({"schema": "hepta.population.bundle-checksums.v1",
                                                           "files": hashes}))
        verified = verify_bundle(stage)
        for path in stage.rglob("*"):
            if path.is_file():
                path.chmod(0o444)
        require(not destination.exists(), "output appeared during assembly")
        os.rename(stage, destination)
    return {**verified, "output": str(destination)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inventory", "validate", "assemble", "verify"))
    parser.add_argument("--spec", help="workspace-relative JSON specification")
    parser.add_argument("--audit", help="workspace-relative completed cohort audit override")
    parser.add_argument("--checkpoint-receipt", help="workspace-relative checkpoint ZIP receipt override")
    parser.add_argument("--output", help="new workspace-relative staging directory, outside frozen repo")
    parser.add_argument("--bundle", help="assembled directory for read-only verification")
    args = parser.parse_args()
    if args.command == "verify":
        require(args.bundle, "--bundle is required")
        result = verify_bundle(args.bundle)
    else:
        require(args.spec, "--spec is required")
        spec = json_object(read_stable(args.spec))
        if args.audit:
            spec["independent_audit"] = args.audit
        if args.checkpoint_receipt:
            spec["checkpoint_archive_receipt"] = args.checkpoint_receipt
        if args.command == "inventory":
            files, selected, missing = inventory(spec)
            result = {"mode": "metadata_only_preflight_not_a_final_snapshot",
                      "selected_files": len(selected), "selected_bytes": sum(r["bytes"] for r in selected.values()),
                      "excluded_files": {k: {"bytes": v["bytes"], "reason": v["excluded_reason"]}
                                         for k, v in files.items() if v["excluded_reason"]},
                      "missing_sources": missing, "independent_audit_set": bool(spec.get("independent_audit")),
                      "final_packaging_performed": False}
        else:
            if args.command == "validate":
                completed = completed_inputs(spec)
                manifest, _ = capture_manifest(spec, completed)
                result = {"passed": True, "complete_input_pins": completed["pins"],
                          "selected_raw_files": manifest["file_count"], "final_packaging_performed": False}
            else:
                require(args.output, "--output is required")
                result = assemble(spec, args.output)
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except (AssemblyError, OSError, KeyError, TypeError, IndexError, EOFError,
            UnicodeDecodeError, tarfile.TarError, json.JSONDecodeError) as error:
        print(json.dumps({"passed": False, "error_type": type(error).__name__,
                          "message": str(error), "final_package_not_accepted": True}), file=sys.stderr)
        raise SystemExit(2)
