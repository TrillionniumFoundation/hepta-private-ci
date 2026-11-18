"""Execute and cold-observe a maintenance campaign through the real runtime."""

import os
from pathlib import Path
import subprocess
import time
import traceback

from runtime_process_bridge import RuntimeProcessBridge
from runtime_stdio import StdioRuntime, canonical, file_digest, require, strict_json


def run_campaign(profile, candidate, output, private, environment, request_id, *, campaign="syntax"):
    require(campaign in ("syntax", "semantic_updates"), "unknown campaign")
    semantic = campaign == "semantic_updates"
    prefix = "semantic-campaign" if semantic else "campaign"
    profile = strict_json(canonical(profile))
    worker = Path(profile["process"]["args"][1]).with_name(
        "hepta_cell_semantic_campaign_worker.py" if semantic else "hepta_cell_campaign_worker.py"
    )
    require(worker.is_file(), "fixed campaign worker is missing")
    candidate_path = profile["process"]["args"][3]
    profile["namespace"] += "-" + campaign + "-maintenance"
    profile["process"]["args"] = [
        "-B",
        str(worker),
        "--candidate",
        candidate_path,
        "--output",
        str(output / (prefix + "-worker")),
    ]
    if semantic:
        profile["process"]["args"].append("--with-updates")
    request = {
        "request_id": request_id + "-" + campaign + "-maintenance",
        "cell_id": "MEM+PRED",
        "operation": "semantic_maintenance" if semantic else "maintenance",
        "payload": {},
    }
    report = {
        "schema": "hepta.actual-runtime-maintenance.v1",
        "campaign": campaign,
        "status": "FAIL",
        "profile": profile,
        "request": request,
        "worker_sha256": file_digest(worker),
        "candidate_sha256": profile["candidate_sha256"],
        "sessions": [],
        "actual_runtime_transport": False,
        "no_second_process_submission": False,
        "controller_cold_restart_observed": False,
        "ordinary_daemon_qualification": False,
    }
    client = bridge = None
    started = time.monotonic()

    def close():
        nonlocal client, bridge
        if bridge is not None:
            bridge.close()
            bridge = None
        if client is not None:
            report["sessions"].append(
                {"runtime": client.identity, "protocol": client.records}
            )
            client.close()
            client = None

    try:
        client = StdioRuntime(profile["runtime"], environment=environment)
        pins = candidate["runtime_identity"]
        actual_tree = (
            subprocess.check_output(
                [
                    "git",
                    "-C",
                    profile["runtime"]["source_root"],
                    "rev-parse",
                    "HEAD^{tree}",
                ],
                timeout=10,
            )
            .decode()
            .strip()
        )
        require(
            pins["source_commit"] == client.identity["runtime_source_commit"]
            and pins["source_tree"] == actual_tree
            and pins["binary_sha256"] == client.identity["runtime_binary_sha256"]
            and pins["config_sha256"] == client.identity["runtime_config_sha256"],
            "campaign pins differ from the actual runtime controller",
        )
        bridge = RuntimeProcessBridge(
            profile,
            private / (prefix + "-bridge.sqlite3"),
            client.call,
            transport_identity=client.identity,
        )
        observed = bridge.execute(request)
        deadline = time.monotonic() + 150
        while (
            observed["state"] != "TERMINAL"
            and observed.get("job_id")
            and time.monotonic() < deadline
        ):
            time.sleep(0.1)
            observed = bridge.observe(request["request_id"])
        report["first_observation"] = observed
        require(
            observed["state"] == "TERMINAL"
            and observed["runtime_state"] == "succeeded"
            and observed["exit_code"] == 0,
            "actual maintenance process did not succeed",
        )
        domain = strict_json(bytes.fromhex(observed["streams"]["stdout"]["bytes_hex"]))
        result = domain.get("campaign_result", {})
        require(
            domain.get("status") == "campaign_observed"
            and domain.get("candidate_sha256") == profile["candidate_sha256"]
            and domain.get("request_id") == request["request_id"]
            and domain.get("runtime_identity") == candidate["runtime_identity"]
            and domain.get("native_image_sha256") == candidate["native"]["image_sha256"]
            and result.get("status") == ("SEMANTIC_FIXTURE_COMPLETE" if semantic else "CONTROLLED_FIXTURE_COMPLETE")
            and result.get("native_hia_enabled") is True,
            "maintenance output does not bind this runtime, candidate and image",
        )
        counts = domain.get("native_counts", {})
        require(
            set(counts) == {"memory", "predictor"}
            and all(
                set(v) == {"completed"}
                and type(v["completed"]) is int
                and v["completed"] > 0
                for v in counts.values()
            ),
            "maintenance has no complete original native continuation accounting",
        )
        report["worker_result"] = domain
        if semantic:
            updates = domain.get("updates", {})
            require(
                updates.get("status") == "THREE_UPDATE_EXAMPLES_OBSERVED"
                and domain.get("updates_native_image_sha256") == candidate["native"]["image_sha256"]
                and updates.get("parameters", {}).get("source_result_sha256") == domain.get("campaign_result_sha256")
                and updates.get("code", {}).get("outputs_and_states_equal") is True
                and updates.get("state", {}).get("pending_preserved") is True,
                "update examples do not bind this campaign and native image",
            )
            report["same_candidate_update_examples_observed"] = True
        close()
        client = StdioRuntime(profile["runtime"], environment=environment)
        bridge = RuntimeProcessBridge(
            profile,
            private / (prefix + "-bridge.sqlite3"),
            client.call,
            transport_identity=client.identity,
        )
        recovered = bridge.execute(request)
        report["recovered_observation"] = recovered
        require(
            recovered == observed,
            "cold maintenance observation changed original job or bytes",
        )
        calls = [
            item["request"]["params"]["name"]
            for item in client.records
            if item["request"].get("method") == "tools/call"
        ]
        require(
            "process_start" not in calls
            and "process_status" in calls
            and "process_read" in calls,
            "cold maintenance must freshly observe the original job",
        )
        report.update(
            status="PASS",
            actual_runtime_transport=True,
            no_second_process_submission=True,
            controller_cold_restart_observed=True,
        )
        return report
    except BaseException:
        report["error"] = traceback.format_exc()
        raise
    finally:
        close()
        report["elapsed_seconds"] = time.monotonic() - started
        with (output / (prefix + "-runtime.json")).open("xb") as stream:
            stream.write(canonical(report) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
