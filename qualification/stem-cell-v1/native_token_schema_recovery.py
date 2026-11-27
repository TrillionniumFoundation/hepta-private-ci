"""Resume the first native holdout after the frozen schema namespace collision.

The original forty runtime files and all fitted artifacts remain unchanged.
This entry point is intentionally outside their inventory and separately attested.
It changes only the metadata comparison: validate the two schema namespaces
independently, then map only that schema key in an otherwise identical membership copy.
"""
import argparse
import json
from pathlib import Path
import time

import token_native_campaign as driver
from group_encoder import digest_json, file_digest
from reader_campaign_utils import write_json

PROTOCOL_SCHEMA = "hepta.multirc.token-protocol.v1"
CAMPAIGN_SCHEMA = "hepta.token-reader.native-campaign.v1"


def compatible_membership(design, membership):
    """Reject every change except the independently checked schema namespace."""
    if membership.get("schema") != PROTOCOL_SCHEMA or design.get("schema") != CAMPAIGN_SCHEMA:
        raise ValueError("unexpected protocol or native campaign schema")
    filtered = {key: value for key, value in membership.items() if key != "schema"}
    if any(key not in design or design[key] != value for key, value in filtered.items()):
        raise ValueError("non-schema membership drift")
    return dict(membership, schema=CAMPAIGN_SCHEMA)


def preflight(args):
    root = args.output
    if (root / "completion.json").exists() or any(root.glob("seed-*/final")):
        raise ValueError("recovery permits only the first native final inference")
    failure = json.loads(args.failed_command_receipt.read_text())
    commands = failure.get("commands", [])
    if (len(commands) != 2 or commands[0].get("exit_code") != 0
            or commands[1].get("exit_code") != 1
            or commands[1].get("name") != "native_evaluate"):
        raise ValueError("exact successful main and rejected native command required")
    log = Path(commands[1]["log"])
    if "native frozen source, binary, membership or main selection changed" not in log.read_text():
        raise ValueError("failure is not the recorded pre-inference metadata guard")
    design = json.loads((root / "design.json").read_text())
    frozen = json.loads((root / "all-artifacts-frozen.json").read_text())
    _, membership, _, _ = driver.training_inputs(args)
    compatible_membership(design, membership)
    current = driver.native_inventory()
    if (current != design["source_sha256"] or current != frozen["source_sha256"]
            or file_digest(args.native_binary) != design["native_binary_sha256"]
            or file_digest(args.campaign / "all-models-frozen.json") != design["main_freeze_sha256"]):
        raise ValueError("frozen runtime, binary, or selected models drifted")
    main_start = json.loads((args.campaign / "evaluation-start.json").read_text())
    if not 0 < frozen["frozen_ns"] < main_start["started_ns"]:
        raise ValueError("native artifacts did not precede the first main final")
    if not (args.campaign / "completion.json").is_file():
        raise ValueError("successful main evaluation required")
    files = [root / "design.json", root / "all-artifacts-frozen.json",
        args.campaign / "all-models-frozen.json", args.campaign / "completion.json",
        args.failed_command_receipt, log]
    for seed in driver.SEEDS:
        folder = root / f"seed-{seed}"
        path = folder / "artifacts.json"
        if file_digest(path) != frozen["artifact_manifests_sha256"][str(seed)]:
            raise ValueError("native selected artifact manifest drifted")
        artifact = json.loads(path.read_text())
        files.append(path)
        for name in ("verifier", "critic"):
            selected = folder / artifact[name]["file"]
            if file_digest(selected) != artifact[name]["file_sha256"]:
                raise ValueError("fitted artifact bytes drifted")
            files.append(selected)
    return membership, dict(schema="hepta.token-reader.schema-recovery.v1",
        started_ns=time.time_ns(), recovery_source_sha256=file_digest(__file__),
        recovery_scope="metadata_schema_namespaces_only_no_numerical_or_policy_change",
        created_after_main_evaluation=True, original_runtime_source_sha256=current,
        original_protocol_schema=membership["schema"], native_campaign_schema=design["schema"],
        original_membership_sha256=digest_json(membership),
        mapped_membership_sha256=digest_json(compatible_membership(design, membership)),
        original_files_sha256={str(path.resolve()): file_digest(path) for path in files},
        first_native_final_inference=True, failed_attempt_retained=True,
        original_models_thresholds_verifier_critic_bounds_and_feedback_policy_unchanged=True,
        original_runtime_files_unchanged=True, hosted_ci_consulted=False,
        production_authorized=False)


def evaluate(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    membership, attestation = preflight(args)
    start_path = args.output / "schema-recovery-start.json"
    with start_path.open("x") as stream:
        json.dump(attestation, stream, sort_keys=True, indent=2)
        stream.write("\n")
    original_inputs = driver.training_inputs

    def checked_inputs(repeated_args):
        parts, actual, frozen, manifests = original_inputs(repeated_args)
        if actual != membership:
            raise ValueError("membership changed after recovery preflight")
        design = json.loads((args.output / "design.json").read_text())
        return parts, compatible_membership(design, actual), frozen, manifests

    try:
        driver.training_inputs = checked_inputs
        driver.evaluate(args)
    finally:
        driver.training_inputs = original_inputs
    if file_digest(__file__) != attestation["recovery_source_sha256"]:
        raise ValueError("recovery entry point changed during evaluation")
    if any(file_digest(path) != expected for path, expected in attestation["original_files_sha256"].items()):
        raise ValueError("frozen input changed during recovered evaluation")
    write_json(args.output, "schema-recovery-completion.json", dict(
        schema=attestation["schema"], completed_ns=time.time_ns(),
        start_sha256=file_digest(start_path), recovery_source_sha256=file_digest(__file__),
        original_completion_sha256=file_digest(args.output / "completion.json"),
        cpu_ns=time.process_time_ns() - started[1], wall_ns=time.perf_counter_ns() - started[0],
        nested_original_evaluation_cost_is_not_additive=True,
        native_child_cpu_excluded_from_self_cpu=True, original_inputs_unchanged=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("campaign", "prepared", "source", "snapshot", "previous-design", "native-binary", "output",
                 "failed-command-receipt"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--steps", type=int, default=1000)
    args = parser.parse_args()
    driver.torch.set_num_threads(1)
    evaluate(args)


if __name__ == "__main__":
    main()
