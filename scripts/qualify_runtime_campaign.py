"""Execute and cold-observe a maintenance campaign through the real runtime."""

import argparse
import os
from pathlib import Path
import stat
import subprocess
import time
import traceback

from runtime_process_bridge import RuntimeProcessBridge
from runtime_stdio import (
    StdioRuntime,
    canonical,
    digest,
    file_digest,
    require,
    strict_json,
)


def _read_original(root, relative):
    """Read bounded regular JSON bytes below one fixed Unix directory owner."""
    relative = Path(relative)
    require(
        not relative.is_absolute()
        and relative.parts
        and all(part not in (".", "..") for part in relative.parts),
        "original path must stay below the worker output",
    )
    flags = os.O_RDONLY | os.O_NOFOLLOW
    directory = os.open(root, flags | os.O_DIRECTORY)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(relative.name, flags | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            require(
                stat.S_ISREG(os.fstat(stream.fileno()).st_mode),
                "original is not a regular file: " + str(relative),
            )
            raw = stream.read(16 * 1024 * 1024 + 1)
        require(len(raw) <= 16 * 1024 * 1024, "original JSON exceeds size bound")
    finally:
        os.close(directory)
    value = strict_json(raw)
    require(type(value) is dict, "original JSON is not an object: " + str(relative))
    return value, digest(raw)


def bind_worker_originals(worker_output, domain, *, campaign):
    """Bind fixed-path retained originals to one parsed runtime stdout value.

    File descriptors reject symlink escapes. Each JSON value and its raw digest
    come from the same read; timestamps and producer-supplied paths are unused.
    This checks correspondence, not producer authentication or task benefit.
    """
    require(campaign in ("syntax", "semantic_updates"), "unknown campaign")
    require(type(domain) is dict, "worker output is not an object")
    paths = ["campaign/RESULT.json", "campaign/PLAN.json", "OBSERVATION.json"]
    if campaign == "semantic_updates":
        paths += ["updates/RESULT.json", "updates/PLAN.json"]
    originals = {}
    hashes = {}
    for relative in paths:
        originals[relative], hashes[relative] = _read_original(worker_output, relative)
    result = originals["campaign/RESULT.json"]
    require(
        hashes["campaign/RESULT.json"] == domain.get("campaign_result_sha256")
        and canonical(result) == canonical(domain.get("campaign_result")),
        "campaign RESULT original differs from runtime stdout",
    )
    require(
        hashes["campaign/PLAN.json"] == result.get("plan_sha256")
        and originals["campaign/PLAN.json"].get("native", {}).get("image_sha256")
        == domain.get("native_image_sha256"),
        "campaign PLAN original differs from the result or native image",
    )
    require(
        canonical(originals["OBSERVATION.json"]) == canonical(domain),
        "OBSERVATION original differs from runtime stdout",
    )
    if campaign == "semantic_updates":
        updates = originals["updates/RESULT.json"]
        require(
            hashes["updates/RESULT.json"] == domain.get("updates_result_sha256")
            and canonical(updates) == canonical(domain.get("updates"))
            and updates.get("parameters", {}).get("source_result_sha256")
            == hashes["campaign/RESULT.json"],
            "updates RESULT original differs from runtime stdout or campaign",
        )
        plan = originals["updates/PLAN.json"]
        require(
            hashes["updates/PLAN.json"] == updates.get("plan_sha256")
            and plan.get("learning_result_sha256") == hashes["campaign/RESULT.json"]
            and plan.get("native", {}).get("image_sha256")
            == domain.get("updates_native_image_sha256")
            == domain.get("native_image_sha256"),
            "updates PLAN original differs from campaign or native image",
        )
    return {
        "schema": "hepta.runtime-campaign-original-binding.v1",
        "campaign": campaign,
        "worker_result_sha256": digest(canonical(domain)),
        "files_sha256": hashes,
        "scope": "retained original bytes bound to parsed runtime stdout; no producer authentication or benefit claim",
    }


def bind_review_originals(review, binding, *, native_image_sha256):
    """Check raw or snapshot review results against already bound original bytes."""
    require(type(review) is dict, "independent review is not an object")
    semantic = binding["campaign"] == "semantic_updates"
    review_format = "raw_review"
    if (
        "review" in review
        or review.get("schema") == "hepta.maintenance-readonly-snapshot-review.v1"
    ):
        require(
            review.get("schema") == "hepta.maintenance-readonly-snapshot-review.v1"
            and review.get("status") == "READ_ONLY_SNAPSHOT_CONSISTENCY_PASS"
            and review.get("source_unchanged_verified") is True
            and review.get("snapshot_unchanged_during_review") is True
            and review.get("semantic_profile") is semantic
            and type(review.get("review")) is dict,
            "snapshot review did not preserve source and snapshot",
        )
        for name in (
            "source_before",
            "source_during_copy",
            "source_after_copy",
            "source_after_review",
            "snapshot_before_review",
            "snapshot_after_review",
        ):
            inventory = review.get(name, {})
            expected_inventory = (
                review["snapshot_before_review"]
                if name.startswith("snapshot_")
                else review["source_before"]
            )
            require(
                type(inventory) is dict
                and canonical(inventory) == canonical(expected_inventory)
                and all(
                    inventory.get("files", {}).get(path, {}).get("sha256")
                    == binding["files_sha256"]["campaign/" + path]
                    for path in ("RESULT.json", "PLAN.json")
                ),
                "snapshot review inventory differs from runtime campaign originals",
            )
        require(
            type(review.get("original_verifier_sha256")) is str
            and review["original_verifier_sha256"]
            == review.get("original_verifier_expected_sha256")
            == review["review"].get("verifier_sha256"),
            "snapshot review verifier identity differs",
        )
        review, review_format = review["review"], "readonly_snapshot_review"
    require(
        review.get("schema")
        == (
            "hepta.semantic-maintenance-readonly-review.v1"
            if semantic
            else "hepta.controlled-maintenance-readonly-review.v1"
        )
        and review.get("status") == "READ_ONLY_CONSISTENCY_PASS"
        and review.get("result_sha256")
        == binding["files_sha256"]["campaign/RESULT.json"]
        and review.get("plan_sha256") == binding["files_sha256"]["campaign/PLAN.json"]
        and review.get("native_image_sha256") == native_image_sha256,
        "independent review does not bind the runtime campaign originals",
    )
    return review_format


def verify_review_binding(runtime_report_path, review_path):
    """Recheck originals and bind an independent review to the same runtime job."""
    runtime_report_path, review_path = Path(runtime_report_path), Path(review_path)
    report, report_hash = _read_original(
        runtime_report_path.parent, runtime_report_path.name
    )
    review, review_hash = _read_original(review_path.parent, review_path.name)
    campaign = report.get("campaign", "syntax")
    require(campaign in ("syntax", "semantic_updates"), "unknown reviewed campaign")
    semantic = campaign == "semantic_updates"
    require(
        report.get("status") == "PASS"
        and report.get("actual_runtime_transport") is True
        and report.get("controller_cold_restart_observed") is True
        and report.get("no_second_process_submission") is True,
        "runtime campaign report did not complete",
    )
    observed = report["first_observation"]
    require(
        observed.get("state") == "TERMINAL"
        and observed.get("runtime_state") == "succeeded"
        and observed.get("exit_code") == 0
        and canonical(report["recovered_observation"]) == canonical(observed),
        "runtime report does not retain the same successful cold observation",
    )
    stdout = bytes.fromhex(observed["streams"]["stdout"]["bytes_hex"])
    domain = strict_json(stdout)
    require(
        canonical(domain) == canonical(report.get("worker_result"))
        and domain.get("candidate_sha256") == report.get("candidate_sha256"),
        "reported worker result differs from the retained runtime stdout",
    )
    prefix = "semantic-campaign" if semantic else "campaign"
    binding = bind_worker_originals(
        runtime_report_path.parent / (prefix + "-worker"), domain, campaign=campaign
    )
    if semantic or "originals_binding" in report:
        require(
            report.get("originals_binding") == binding
            and report.get("originals_rechecked_after_cold") is True
            and report.get("worker_stdout_sha256") == digest(stdout),
            "runtime report does not bind these original bytes before and after cold observation",
        )
    review_format = bind_review_originals(
        review, binding, native_image_sha256=domain.get("native_image_sha256")
    )
    return {
        "schema": "hepta.runtime-campaign-review-binding.v1",
        "status": "REVIEW_BOUND_TO_RUNTIME_ORIGINALS",
        "campaign": campaign,
        "candidate_sha256": report["candidate_sha256"],
        "runtime_report_sha256": report_hash,
        "review_sha256": review_hash,
        "review_format": review_format,
        "worker_stdout_sha256": digest(stdout),
        "originals_binding": binding,
        "scope": "runtime report, retained originals and independent review correspond; no producer authentication or task-benefit claim",
    }


def run_campaign(
    profile, candidate, output, private, environment, request_id, *, campaign="syntax"
):
    require(campaign in ("syntax", "semantic_updates"), "unknown campaign")
    semantic = campaign == "semantic_updates"
    prefix = "semantic-campaign" if semantic else "campaign"
    profile = strict_json(canonical(profile))
    if semantic:
        profile["process"]["timeout_seconds"] = 180
    worker = Path(profile["process"]["args"][1]).with_name(
        "hepta_cell_semantic_campaign_worker.py"
        if semantic
        else "hepta_cell_campaign_worker.py"
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
        deadline = time.monotonic() + (210 if semantic else 150)
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
        stdout = bytes.fromhex(observed["streams"]["stdout"]["bytes_hex"])
        domain = strict_json(stdout)
        result = domain.get("campaign_result", {})
        require(
            domain.get("status") == "campaign_observed"
            and domain.get("candidate_sha256") == profile["candidate_sha256"]
            and domain.get("request_id") == request["request_id"]
            and domain.get("runtime_identity") == candidate["runtime_identity"]
            and domain.get("native_image_sha256") == candidate["native"]["image_sha256"]
            and result.get("status")
            == (
                "SEMANTIC_FIXTURE_COMPLETE"
                if semantic
                else "CONTROLLED_FIXTURE_COMPLETE"
            )
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
        report["worker_stdout_sha256"] = digest(stdout)
        report["originals_binding"] = bind_worker_originals(
            output / (prefix + "-worker"), domain, campaign=campaign
        )
        if semantic:
            updates = domain.get("updates", {})
            require(
                updates.get("status") == "THREE_UPDATE_EXAMPLES_OBSERVED"
                and domain.get("updates_native_image_sha256")
                == candidate["native"]["image_sha256"]
                and updates.get("parameters", {}).get("source_result_sha256")
                == domain.get("campaign_result_sha256")
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
        require(
            bind_worker_originals(
                output / (prefix + "-worker"), domain, campaign=campaign
            )
            == report["originals_binding"],
            "retained campaign originals changed during cold observation",
        )
        report.update(
            status="PASS",
            actual_runtime_transport=True,
            no_second_process_submission=True,
            controller_cold_restart_observed=True,
            originals_rechecked_after_cold=True,
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Bind an independent review to runtime originals"
    )
    parser.add_argument("--runtime-report", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()
    print(canonical(verify_review_binding(args.runtime_report, args.review)).decode())
