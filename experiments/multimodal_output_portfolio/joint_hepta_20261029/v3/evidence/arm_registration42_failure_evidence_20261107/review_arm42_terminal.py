"""Independently bind the original ARM42 failure and its limited conclusions."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import stat
import xml.etree.ElementTree as ET

ROOT = Path("/dev/shm/ndu_root_continuation_20261107")
OWNER = Path("/dev/shm/ndu_arm42_failure_20261107")
HEAD = "8b0fcf80afb95c5199be9b5f131d6454663c1632"
TREE = "8b46b24ccca6bf77227e1b21aa66ec84b0ea5473"
RUN, JOB = 42353199414, 128346079305
CASE = "real_synapse_dual_agentd_dual_matrixd_restart_and_isolation"


def need(condition, message):
    if not condition:
        raise ValueError(message)


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def pinned(path, digest):
    raw = path.read_bytes()
    need(identity(raw)["sha256"] == digest, "PINNED_SOURCE_CHANGED")
    return json.loads(raw)


api = pinned(
    ROOT / "arm42_terminal_fresh_api.json",
    "da291ecdd31a60c61a7328fbb597d7ca93959bdf5b7aa888d89dc7c4c76f868d",
)
need(api["head"]["sha"] == HEAD and api["head"]["tree"]["sha"] == TREE, "HEAD_TREE")
need(
    api["merge"]["sha"] == "99e81f8e932e805869d57bd8534761b9f3266ed8"
    and api["merge"]["tree"]["sha"] == TREE
    and [p["sha"] for p in api["merge"]["parents"]]
    == ["2962db10db984c1f9bcafd124721cb213e5a71a4", HEAD],
    "MERGE_IDENTITY",
)
run, jobs = api["run"], api["jobs"]
need(
    (run["id"], run["run_attempt"], run["head_sha"], run["status"], run["conclusion"])
    == (RUN, 1, HEAD, "completed", "failure"),
    "RUN_SCOPE",
)
need(jobs["total_count"] == len(jobs["jobs"]) == 11, "COMPLETE_JOBS")
for job in jobs["jobs"]:
    need(
        (job["run_id"], job["run_attempt"], job["head_sha"], job["status"])
        == (RUN, 1, HEAD, "completed"),
        "JOB_SCOPE",
    )
arm = [j for j in jobs["jobs"] if j["id"] == JOB]
need(len(arm) == 1 and arm[0]["conclusion"] == "failure", "OWNING_JOB")
projection = pinned(
    OWNER / "PROJECTION_PAYLOAD_VALIDATION.json",
    "edaa438f48de3f81222d83c5002e031984cd2d0109adb0bbb414e84f36ff7bb2",
)
adaptation = json.loads((OWNER / "PROJECTION_ADAPTATION.json").read_bytes())
old = Path(adaptation["original_source"]).read_bytes()
need(identity(old) == adaptation["original"], "ORIGINAL_PROJECTION_GUARD")
adapted = old.decode()
for before, after in adaptation["literal_replacements"].items():
    need(before in adapted, "MISSING_LITERAL")
    adapted = adapted.replace(before, after)
guard = (OWNER / "audit_projection.py").read_bytes()
need(adapted.encode() == guard, "PROJECTION_LOGIC_CHANGED")
execution = json.loads((OWNER / "projection_execution/EXECUTION.json").read_bytes())
need(
    identity(guard) == {k: execution["source"][k] for k in ("bytes", "sha256")}
    and all(r["exit_code"] == 0 for r in execution["commands"])
    and execution["commands"][-1]["argv"][-3:]
    == ["-B", "-O", str(OWNER / "audit_projection.py")],
    "ORIGINAL_GUARD_EXECUTION",
)
need(
    (
        projection["source_head"],
        projection["source_tree"],
        projection["run_id"],
        projection["job_id"],
        projection["attempt"],
    )
    == (HEAD, TREE, RUN, JOB, 1)
    and projection["declared_selected_files"] == 1474
    and projection["selected_bytes"] == 68665776
    and projection["source_catalogue_entries"] == 84475
    and projection["all_member_sizes_sha256_crc32_verified"]
    and projection["all_catalogue_classifications_recomputed"],
    "PROJECTION_SCOPE",
)
read_members = {}


def original(name):
    path = OWNER / "reviewed-diagnostics" / name
    mode = path.lstat().st_mode
    need(stat.S_ISREG(mode) and stat.S_IMODE(mode) == 0o600, "PRIVATE_MEMBER_MODE")
    raw = path.read_bytes()
    need(identity(raw) == projection["retained_files_identities"][name], "MEMBER_BYTES")
    read_members[name] = identity(raw)
    return raw


seal = json.loads(original("qualification/plan/SOURCE_SEAL.json"))
need(
    seal["producer_source_commit"] == HEAD
    and seal["candidate_tree"] == seal["qualification_tree"] == TREE
    and seal["source_clean"]
    and seal["test_overlay"] is None
    and seal["producer_candidate_patch"] == identity(b""),
    "ACTUAL_SOURCE",
)
start = json.loads(original("qualification/runtime/commands/025-START.json"))
end = json.loads(original("qualification/runtime/commands/025-END.json"))
need(
    start["tool"] == end["tool"] == "just"
    and start["arguments"] == end["arguments"]
    and start["arguments"][2] == "test"
    and start["arguments"][-8:]
    == [
        "-E",
        "binary_id(=codex-hepta-matrixd::real_synapse_e2e) & test(=" + CASE + ")",
        "--retries",
        "0",
        "--test-threads",
        "1",
        "--no-tests",
        "fail",
    ]
    and end["exit_code"] == 100
    and end["executable_unchanged"]
    and end["wall_seconds"] == 439.03385301399976,
    "ACTUAL_JUST",
)
stderr = original("qualification/runtime/commands/025-actual-just-test.stderr")
need(
    identity(stderr) == {k: end["stderr"][k] for k in ("bytes", "sha256")},
    "JUST_STDERR",
)
lines = stderr.decode().splitlines()
primary = (
    "Error: timed out decrypting @hepta-agent-b:localhost: agent-b-authority-probe"
)
child = "R4_DIAGNOSTIC agent=019153a4-3088-7e03-a56a-9b1964f75dd3 stream=Stderr log=Error: Matrix durable store operation record reconciled Core turn failed: Matrix durable-core storage is unavailable"
need(
    [i for i, line in enumerate(lines, 1) if line.strip() == primary] == [210],
    "PRIMARY_ERROR",
)
need(
    [i for i, line in enumerate(lines, 1) if line.strip() == child] == [204],
    "CHILD_ERROR",
)
stage_rows = []
for i, line in enumerate(lines, 1):
    if line.strip().startswith("R4_STAGE "):
        match = re.fullmatch(
            r"R4_STAGE ([a-z_]+(?::[a-z_]+)+)(?: elapsed_ms=([0-9]+))?", line.strip()
        )
        need(match is not None, "STAGE_SHAPE")
        row = {"line": i, "stage": match.group(1)}
        if match.group(2) is not None:
            row["elapsed_ms"] = int(match.group(2))
        stage_rows.append(row)
owner = pinned(
    OWNER / "NATIVE_FAILURE_ANALYSIS.json",
    "1622bc6bbd22433e63eee524f0dfe148a229903fef1edb758dcf9704db6e705e",
)
need(stage_rows == owner["observed_stages"], "COMPLETE_STAGE_RECORDS")
counts = Counter(r["stage"] for r in stage_rows)
need(
    counts["agent_join_whoami:done"] == counts["agent_join_logout:done"] == 2,
    "SETUP_PHASE",
)
need(
    all(
        counts[s] == 1
        for s in (
            "agent_pair_ready:done",
            "first_encrypted_turn:done",
            "outbound_post_send_pre_mark:done",
            "authority_probe:cancelled",
            "authority_probe:resume_and_queue_start:done",
        )
    ),
    "COMPLETED_PREFIX",
)
need(
    stage_rows[-1]["stage"] == "authority_probe:resume_and_queue_start:done"
    and not counts["authority_probe:done"]
    and not counts["network_disconnect_recovery:done"],
    "FAILED_BOUNDARY",
)
cases = list(
    ET.fromstring(
        original("qualification/runtime/nextest-store/linux-synapse/junit.xml")
    ).iter("testcase")
)
need(
    len(cases) == 1
    and cases[0].get("name") == CASE
    and cases[0].get("time") == "438.885"
    and len(cases[0].findall("failure")) == 1,
    "ONE_FAILED_CASE",
)
for name, expected in read_members.items():
    need(
        identity((OWNER / "reviewed-diagnostics" / name).read_bytes()) == expected,
        "MEMBER_CHANGED",
    )
result = {
    "decision": "QUALIFIED_ORIGINAL_ARM42_FAILURE_ONLY",
    "head": HEAD,
    "tree": TREE,
    "run": RUN,
    "attempt": 1,
    "job": JOB,
    "fresh_terminal_api": identity(
        (ROOT / "arm42_terminal_fresh_api.json").read_bytes()
    ),
    "guard_literal_adaptation_exact": True,
    "owner_original_guard_optimized_execution_exit": 0,
    "guard_receipt_files_bytes_catalogue": [1474, 68665776, 84475],
    "root_reran_full_projection_guard": False,
    "independently_read_original_members": read_members,
    "just_exit": 100,
    "just_wall_seconds": end["wall_seconds"],
    "one_original_case": dict(cases[0].attrib),
    "observed_stage_records": len(stage_rows),
    "completed_prefix_does_not_qualify_later_phases": True,
    "failed_wait": "authority_probe_wait_for_body",
    "reported_child_operation": "record reconciled Core turn",
    "reported_child_source_variant": "MatrixDurableError::Unavailable",
    "underlying_SQLx_site_or_SQLite_code": "UNKNOWN",
    "failed_event_identity_and_error_clock_order": "UNKNOWN",
    "new_native_execution_or_candidate_helper_execution": False,
    "private_raw_exported": False,
    "business_qualified": False,
    "all_blockers_closed": False,
}
out = ROOT / "arm42_terminal_root"
out.mkdir()
with (out / "ROOT_REVIEW.json").open("x") as output:
    json.dump(result, output, indent=2)
    output.write("\n")
print(result["decision"])
