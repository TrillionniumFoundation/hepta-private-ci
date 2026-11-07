"""Bind the original ARM42 failure and fixed source meanings without replay."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import stat
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
VIEW = HERE / "reviewed-diagnostics"
HEAD = "8b0fcf80afb95c5199be9b5f131d6454663c1632"
TREE = "8b46b24ccca6bf77227e1b21aa66ec84b0ea5473"
MERGE = "99e81f8e932e805869d57bd8534761b9f3266ed8"
RUN, JOB = 42353199414, 128346079305
CASE = "real_synapse_dual_agentd_dual_matrixd_restart_and_isolation"
AGENT_A = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12"
AGENT_B = "019153a4-3088-7e03-a56a-9b1964f75dd3"
TEST_SOURCE = Path(
    "/dev/shm/ndu_arm_session_20261107/post_format/codex-rs/hepta-matrixd/tests/real_synapse_e2e.rs"
)
PRIMARY_ERROR = (
    "Error: timed out decrypting @hepta-agent-b:localhost: agent-b-authority-probe"
)
CHILD_ERROR = "Error: Matrix durable store operation record reconciled Core turn failed: Matrix durable-core storage is unavailable"


def need(value, code):
    if not value:
        raise ValueError(code)


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def file_identity(path):
    return {"path": str(path), **identity(path.read_bytes())}


def original(name):
    path = VIEW / name
    meta = path.lstat()
    need(
        stat.S_ISREG(meta.st_mode) and stat.S_IMODE(meta.st_mode) == 0o600,
        "ORIGINAL_MODE",
    )
    raw = path.read_bytes()
    need(
        identity(raw) == projection["retained_files_identities"][name], "ORIGINAL_DRIFT"
    )
    return raw


def git_object(kind, body):
    return hashlib.sha1(
        kind.encode() + b" " + str(len(body)).encode() + b"\0" + body
    ).hexdigest()


def source_bindings(api):
    need(
        api["head"]["sha"] == HEAD
        and api["head"]["commit"]["tree"]["sha"] == TREE
        and api["root_tree"] == TREE,
        "SOURCE_ROOT",
    )
    trees = api["trees"]
    need(len(trees) == 10 and trees[""]["sha"] == TREE, "SOURCE_TREE_SET")
    for prefix, tree in trees.items():
        need(tree.get("truncated") is False, "INCOMPLETE_TREE")
        entries = tree["tree"]
        need(
            len({entry["path"] for entry in entries}) == len(entries),
            "REPEATED_TREE_PATH",
        )
        ordered = sorted(
            entries,
            key=lambda entry: (
                entry["path"] + ("/" if entry["type"] == "tree" else "")
            ).encode(),
        )
        body = b"".join(
            entry["mode"].lstrip("0").encode()
            + b" "
            + entry["path"].encode()
            + b"\0"
            + bytes.fromhex(entry["sha"])
            for entry in ordered
        )
        need(git_object("tree", body) == tree["sha"], "TREE_HASH")
        if prefix:
            parent, _, leaf = prefix.rpartition("/")
            links = [
                entry
                for entry in trees[parent]["tree"]
                if entry["path"] == leaf and entry["type"] == "tree"
            ]
            need(len(links) == 1 and links[0]["sha"] == tree["sha"], "TREE_LINK")
    result = []
    for name, row in api["leaves"].items():
        parent, _, leaf = name.rpartition("/")
        links = [entry for entry in trees[parent]["tree"] if entry["path"] == leaf]
        need(
            len(links) == 1 and links[0] == row["leaf"] and row["ref"] == HEAD,
            "SOURCE_LEAF_LINK",
        )
        expected = row["leaf"]
        path = Path(row["local"])
        raw = path.read_bytes()
        need(
            expected["mode"] == "100644"
            and expected["type"] == "blob"
            and len(raw) == expected["size"]
            and git_object("blob", raw) == expected["sha"],
            "SOURCE_BLOB",
        )
        result.append(
            {
                "path": name,
                "local": str(path),
                **identity(raw),
                "git_blob": expected["sha"],
                "git_mode": expected["mode"],
            }
        )
    need(len(result) == 4, "SOURCE_FILE_COUNT")
    return result


projection_path = HERE / "PROJECTION_PAYLOAD_VALIDATION.json"
need(
    identity(projection_path.read_bytes())
    == {
        "bytes": 27421,
        "sha256": "edaa438f48de3f81222d83c5002e031984cd2d0109adb0bbb414e84f36ff7bb2",
    },
    "PROJECTION_RECEIPT",
)
projection = json.loads(projection_path.read_bytes())
need(
    projection["source_head"] == HEAD
    and projection["source_tree"] == TREE
    and projection["workflow_merge"] == MERGE
    and projection["run_id"] == RUN
    and projection["job_id"] == JOB
    and projection["attempt"] == 1,
    "ORIGINAL_SCOPE",
)
need(
    projection["declared_selected_files"] == 1474
    and projection["selected_bytes"] == 68665776
    and projection["source_catalogue_entries"] == 84475
    and projection["all_member_sizes_sha256_crc32_verified"]
    and projection["all_catalogue_classifications_recomputed"],
    "ORIGINAL_GUARDS",
)
api_path = HERE / "ERROR_SOURCE_API.json"
need(
    identity(api_path.read_bytes())
    == {
        "bytes": 143238,
        "sha256": "e8bbbc097ad5fddba6436422d7deb39b2c8bd0e3aeb0973815bae91178f7fdc9",
    },
    "PRIMARY_API_RECEIPT",
)
sources = source_bindings(json.loads(api_path.read_bytes()))
run = json.loads((HERE / "TERMINAL_RUN_API.json").read_bytes())
jobs = json.loads((HERE / "TERMINAL_JOBS_API.json").read_bytes())
need(
    run["id"] == RUN
    and run["run_attempt"] == 1
    and run["head_sha"] == HEAD
    and run["status"] == "completed"
    and run["conclusion"] == "failure",
    "TERMINAL_RUN",
)
need(jobs["total_count"] == len(jobs["jobs"]) == 11, "COMPLETE_JOB_LIST")
need(
    all(
        job["run_id"] == RUN
        and job["run_attempt"] == 1
        and job["head_sha"] == HEAD
        and job["status"] == "completed"
        for job in jobs["jobs"]
    ),
    "JOB_SCOPE",
)
arm = [job for job in jobs["jobs"] if job["id"] == JOB]
need(
    len(arm) == 1
    and arm[0]["name"] == "native-arm64-synapse"
    and arm[0]["conclusion"] == "failure",
    "ARM_JOB",
)
console_path = HERE / f"job-{JOB}.log"
console = console_path.read_bytes()
need(
    stat.S_IMODE(console_path.stat().st_mode) == 0o600
    and identity(console)
    == {
        "bytes": 45011,
        "sha256": "ff7ab787bdcb96287b2744b5928523e10ede0b29cdab34364513b6b7f6d8c6dd",
    },
    "PRIVATE_CONSOLE",
)
need(
    json.loads((HERE / "SECOND_LOG_READ.json").read_bytes())[
        "fresh_second_decoded_log_equal"
    ]
    is True,
    "SECOND_CONSOLE_READ",
)
console_lines = console.decode().splitlines()
checkout = []
for position, line in enumerate(console_lines):
    if "git log -1 --format=%H" in line:
        match = re.fullmatch(
            r"[0-9TZ:.\-]+\s+([a-f0-9]{40})", console_lines[position + 1]
        )
        need(match is not None, "CHECKOUT_LINE")
        checkout.append(match.group(1))
need(checkout == [HEAD], "ORIGINAL_CHECKOUT")

seal_name = "qualification/plan/SOURCE_SEAL.json"
seal = json.loads(original(seal_name))
need(
    seal["producer_source_commit"] == HEAD
    and seal["candidate_tree"] == seal["qualification_tree"] == TREE
    and seal["source_clean"]
    and seal["test_overlay"] is None
    and seal["producer_candidate_patch"] == identity(b""),
    "EXECUTED_SOURCE_TREE",
)
test_raw = TEST_SOURCE.read_bytes()
need(
    identity(test_raw)
    == seal["bound_files"]["codex-rs/hepta-matrixd/tests/real_synapse_e2e.rs"]
    == {
        "bytes": 239842,
        "sha256": "7d6c72402524b28f663cb0a27f93e17f854244a761f107431813f21d631fffb3",
    },
    "EXECUTED_TEST_SOURCE",
)
test_source = test_raw.decode()
build_name = "qualification/build/BUILD_RESULT.json"
build = json.loads(original(build_name))
need(
    build["status"] == "built_not_executed"
    and build["source_clean"]
    and build["seed_unchanged"],
    "BUILD_BOUNDARY",
)
end_name = "qualification/runtime/commands/025-END.json"
end = json.loads(original(end_name))
stderr_name = "qualification/runtime/commands/025-actual-just-test.stderr"
stderr_raw = original(stderr_name)
need(
    end["exit_code"] == 100
    and end["executable_unchanged"]
    and {key: end["stderr"][key] for key in ("bytes", "sha256")}
    == identity(stderr_raw),
    "ACTUAL_JUST_RESULT",
)
need(end["wall_seconds"] == 439.03385301399976, "ACTUAL_JUST_WALL")
lines = stderr_raw.decode().splitlines()
need(
    any(
        "0 passed; 1 failed; 0 ignored; 0 measured; 8 filtered out" in line
        for line in lines
    ),
    "FRAMEWORK_COUNTS",
)
junit_name = "qualification/runtime/nextest-store/linux-synapse/junit.xml"
cases = list(ET.fromstring(original(junit_name)).iter("testcase"))
need(
    len(cases) == 1
    and cases[0].get("name") == CASE
    and len(cases[0].findall("failure")) == 1
    and cases[0].get("time") == "438.885",
    "JUNIT_CASE",
)
stages = []
manifest_path = Path("/dev/shm/ndu_arm_session_20261107/final_unit/manifest.json")
need(
    identity(manifest_path.read_bytes())
    == {
        "bytes": 11265,
        "sha256": "907d8885e755dce93c71033a0c3efe47d86ff84f3e13fc8288e67419107adeb0",
    },
    "FROZEN_SIX_SOURCE_MANIFEST",
)
registration_rows = [
    row
    for row in json.loads(manifest_path.read_bytes())["files"]
    if row["path"]
    == "codex-rs/hepta-matrixd/tests/fixtures/linux_qualification/registration.rs"
]
need(len(registration_rows) == 1, "REGISTRATION_STAGE_SOURCE")
registration_path = Path(registration_rows[0]["source_file"])
registration_raw = registration_path.read_bytes()
registration_pin = registration_rows[0]["postimage"]
need(
    identity(registration_raw)
    == {key: registration_pin[key] for key in ("bytes", "sha256")}
    and git_object("blob", registration_raw) == registration_pin["git_blob"],
    "REGISTRATION_STAGE_SOURCE_BYTES",
)
source_labels = set(
    re.findall(
        r'"R4_STAGE ([a-z_]+(?::[a-z_]+)+)"', test_source + registration_raw.decode()
    )
)
for ending in ("start", "done"):
    need(
        '"R4_STAGE agent_{label}_join:' + ending + '"' in test_source,
        "FIXED_TWO_AGENT_STAGE_FORMATTER",
    )
    source_labels.update(f"agent_{label}_join:{ending}" for label in ("a", "b"))
for number, original_line in enumerate(lines, 1):
    line = original_line.strip()
    if line.startswith("R4_STAGE "):
        parsed = re.fullmatch(
            r"R4_STAGE ([a-z_]+(?::[a-z_]+)+)(?: elapsed_ms=([0-9]+))?", line
        )
        need(parsed is not None, "STAGE_SHAPE")
        stage, elapsed = parsed.groups()
        row = {"line": number, "stage": stage}
        if elapsed is None:
            need(stage in source_labels, "STAGE_NOT_IN_FIXED_SOURCE")
        else:
            need(
                '"R4_STAGE ' + stage + ' elapsed_ms={}"' in test_source,
                "TIMED_STAGE_NOT_IN_FIXED_SOURCE",
            )
            row["elapsed_ms"] = int(elapsed)
        stages.append(row)
counts = Counter(row["stage"] for row in stages)
need(
    counts["agent_join_whoami:done"] == counts["agent_join_logout:done"] == 2,
    "SETUP_SESSION_PHASE",
)
need(
    all(
        counts[name] == 1
        for name in (
            "agent_pair_ready:done",
            "first_encrypted_turn:done",
            "outbound_post_send_pre_mark:done",
            "authority_probe:cancelled",
            "authority_probe:resume_and_queue_start:done",
        )
    ),
    "OBSERVED_PROGRESS",
)
need(
    stages[-1]["stage"] == "authority_probe:resume_and_queue_start:done"
    and not counts["authority_probe:done"]
    and not counts["network_disconnect_recovery:done"],
    "FAILED_BOUNDARY",
)
primary_lines = [
    number for number, line in enumerate(lines, 1) if line.strip() == PRIMARY_ERROR
]
child_lines = [
    number
    for number, line in enumerate(lines, 1)
    if line.strip() == f"R4_DIAGNOSTIC agent={AGENT_B} stream=Stderr log={CHILD_ERROR}"
]
need(primary_lines == [210] and child_lines == [204], "FIXED_ORIGINAL_ERRORS")
need(
    '"timed out decrypting {sender}: {body}"' in test_source
    and '"authority_probe_wait_for_body"' in test_source,
    "PRIMARY_ERROR_SOURCE",
)
runtime_source = (HERE / "source/runtime.rs").read_text()
store_source = (HERE / "source/store.rs").read_text()
need(
    '.store_operation("record reconciled Core turn")' in runtime_source
    and '#[error("Matrix durable store operation {operation} failed: {source}")]'
    in runtime_source
    and "StoreOperation {" in runtime_source,
    "STORE_OPERATION_SOURCE",
)
need(
    '#[error("Matrix durable-core storage is unavailable")]\n    Unavailable,'
    in store_source,
    "UNAVAILABLE_ENUM_SOURCE",
)
diagnostics = []
status_pattern = re.compile(
    r"R4_DIAGNOSTIC agent=("
    + AGENT_A
    + "|"
    + AGENT_B
    + r') active=(true|false) healthy=(true|false) matrix_active=(true|false) matrix_healthy=(true|false) matrix_degraded=(true|false) matrix_last_error=Some\("Matrix companion exited while its agent remained healthy"\)'
)
for number, line in enumerate(lines, 1):
    match = status_pattern.fullmatch(line.strip())
    if match:
        agent, active, healthy, matrix_active, matrix_healthy, degraded = match.groups()
        diagnostics.append(
            {
                "line": number,
                "agent": agent,
                "active": active == "true",
                "healthy": healthy == "true",
                "matrix_active": matrix_active == "true",
                "matrix_healthy": matrix_healthy == "true",
                "matrix_degraded": degraded == "true",
                "matrix_last_error": "Matrix companion exited while its agent remained healthy",
            }
        )
need(
    len(diagnostics) == 2
    and diagnostics[1]["agent"] == AGENT_B
    and not diagnostics[1]["matrix_active"]
    and diagnostics[1]["active"]
    and diagnostics[1]["healthy"],
    "B_PROCESS_BOUNDARY",
)

server_name = "qualification/controller-commands/083-container-final-log.stderr"
server_lines = original(server_name).decode().splitlines()
requests, users_by_request, rate_reason_lines = [], {}, []
for number, line in enumerate(server_lines, 1):
    request = re.search(r" - ((?:POST|GET)-[0-9]+) - ", line)
    if request:
        users = re.findall(r"@hepta-(?:agent-a|agent-b|human):localhost", line)
        users_by_request.setdefault(request.group(1), set()).update(users)
    if "Too Many Requests (rc_login.address)" in line:
        rate_reason_lines.append(number)
    for method, endpoint in (
        ("POST", "login"),
        ("GET", "account/whoami"),
        ("POST", "logout"),
    ):
        token = f'"{method} /_matrix/client/v3/{endpoint} HTTP/1.1"'
        if token not in line:
            continue
        pattern = (
            r"([0-9-]+ [0-9:,]+) - synapse\.access\.http\.8008 - [0-9]+ - INFO - ((?:POST|GET)-[0-9]+) - ::ffff:127\.0\.0\.1 - 8008 - \{[^}]*\} Processed request: .* ([0-9]+)B ([0-9]{3}) "
            + re.escape(token)
            + r' "(matrix-rust-sdk|-)" \[0 dbevts\]'
        )
        match = re.fullmatch(pattern, line)
        need(match is not None, "AUTH_ENDPOINT_LOG_SHAPE")
        timestamp, request_id, size, status, user_agent = match.groups()
        requests.append(
            {
                "line": number,
                "endpoint": endpoint,
                "method": method,
                "server_timestamp_literal": timestamp,
                "request_id": request_id,
                "response_bytes": int(size),
                "status": int(status),
                "user_agent": user_agent,
                "peer": "::ffff:127.0.0.1",
            }
        )
for row in requests:
    row["fixed_users_from_same_request"] = sorted(
        users_by_request.get(row["request_id"], set())
    )

report = {
    "scope": "Original ARM42 terminal failure and fixed source meanings; no new native execution, candidate, timeout or retry change",
    "run": RUN,
    "attempt": 1,
    "job": JOB,
    "head": HEAD,
    "tree": TREE,
    "workflow_merge": MERGE,
    "workflow_result": "FAILURE",
    "other_successful_job_API_conclusions": sum(
        job["conclusion"] == "success" for job in jobs["jobs"]
    ),
    "job_API_counts_are_test_counts": False,
    "projection_validation": file_identity(projection_path),
    "primary_source_API": file_identity(api_path),
    "complete_primary_trees_rehashed": 10,
    "primary_sources": sources,
    "registration_stage_source": {
        "manifest": file_identity(manifest_path),
        "source": file_identity(registration_path),
        "git_blob": registration_pin["git_blob"],
        "scope": "Previously root-qualified six-source manifest; the original qualification tree is the same published tree",
    },
    "original_console": {
        **identity(console),
        "mode": "0600",
        "fresh_second_decoded_read_equal": True,
        "actual_checkout": checkout[0],
    },
    "executed_source": {
        "seal_member": seal_name,
        **identity(original(seal_name)),
        "qualification_commit": seal["qualification_commit"],
        "candidate_tree": seal["candidate_tree"],
        "qualification_tree": seal["qualification_tree"],
        "candidate_patch": seal["producer_candidate_patch"],
        "test_overlay": seal["test_overlay"],
        "source_clean": seal["source_clean"],
        "test_source": file_identity(TEST_SOURCE),
    },
    "build": {
        "member": build_name,
        **identity(original(build_name)),
        "status": build["status"],
        "source_clean": build["source_clean"],
        "seed_unchanged": build["seed_unchanged"],
        "cold_test_seconds": build["cold_test_seconds"],
        "cold_product_seconds": build["cold_product_seconds"],
    },
    "actual_test": {
        "just_invoked": True,
        "end_member": end_name,
        **identity(original(end_name)),
        "exit_code": end["exit_code"],
        "wall_seconds": end["wall_seconds"],
        "child_cpu_seconds": end["child_cpu_seconds"],
        "executable_unchanged": end["executable_unchanged"],
        "stderr_member": stderr_name,
        "stderr": identity(stderr_raw),
        "junit_member": junit_name,
        "junit": identity(original(junit_name)),
        "case": dict(cases[0].attrib),
        "direct_framework": {"passed": 0, "failed": 1, "ignored": 0, "filtered_out": 8},
    },
    "observed_stages": stages,
    "diagnostic_snapshots": diagnostics,
    "original_primary_error": {
        "line": primary_lines[0],
        "text": PRIMARY_ERROR,
        "context": "authority_probe_wait_for_body",
        "meaning": "Human B did not receive the required decrypted reply after the authority queue-start boundary",
    },
    "earlier_reported_B_child_error": {
        "line": child_lines[0],
        "text": CHILD_ERROR,
        "matrix_runtime_enum": "MatrixRuntimeError::StoreOperation",
        "operation": "record reconciled Core turn",
        "source_enum": "MatrixDurableError::Unavailable",
        "boundary": "B Matrix process failure reported by the original failure-path Supervisor poll; raw stderr ordering is not a calibrated process clock",
    },
    "auth_endpoint_observations": {
        "server_member": server_name,
        **identity(original(server_name)),
        "records": requests,
        "rc_login_address_reason_lines": rate_reason_lines,
        "clock_scope": "Literal server timestamps only; no server-to-client clock calibration",
    },
    "limits": [
        "The Unavailable display does not identify the lower database or I/O error category or code.",
        "The recovery loop can process any pending inbox item for B. The operation label does not identify the failed event or turn.",
        "The failure-path Supervisor sample does not establish the child error time relative to queue-start completion.",
        "No claim of SQLite busy, lock contention, corruption, a specific race, or authorization to add a retry or extend a timeout.",
        "A was deliberately disconnected; the B reply wait fails before A reconnect and its later assertions.",
        "Stage completion supports only the checks before that marker; it does not qualify later recovery, shutdown, or the whole business case.",
        "No causal latency benefit follows from comparing different failed execution paths.",
        "No full large artifact, excluded contents, ambient credential filtering, candidate helper execution or native rerun.",
    ],
    "business_qualified": False,
    "all_blockers_closed": False,
    "large_scale_training_status": "NO_GO_FOR_LARGE_SCALE_TRAINING",
    "auditor": file_identity(Path(__file__)),
}
output = HERE / "NATIVE_FAILURE_ANALYSIS.json"
with output.open("x") as stream:
    json.dump(report, stream, indent=2)
    stream.write("\n")
print(
    json.dumps(
        {
            "report": str(output),
            **identity(output.read_bytes()),
            "actual_just_exit": end["exit_code"],
            "actual_just_wall_seconds": end["wall_seconds"],
            "primary_error_context": "authority_probe_wait_for_body",
            "B_source_error_enum": "MatrixDurableError::Unavailable",
            "source_trees_rehashed": 10,
            "business_qualified": False,
        }
    )
)
