"""Score original V9 evidence independently. Valid negative results exit zero.

CLI: python -I -B score.py /absolute/continual.json /absolute/score.json
The pinned checkout and complete sibling .artifacts directory are required.
Evidence integrity is not publication or final-use authority.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evidence import VARIANTS, canonical, child_path, decode, digest, identity, integer
from evidence import owner_facts, read_bytes, read_json, require, transitions, verify_batch
from model_evidence import audit_pairs
from resource_evidence import verify_resources, verify_runtime_storage


PROJECT = Path(__file__).resolve().parent
QUALIFICATION = PROJECT.parents[1]
FIXTURE_HASH = "750ecabdcdbc0aa9f5bf253615efaff090800c3a96a2958e0d17a4df829c6502"


def code_identity(claimed):
    for name, pin in claimed["files"].items():
        path = QUALIFICATION / name
        require(path.resolve().is_relative_to(QUALIFICATION.resolve()), "training source path escaped")
        raw = read_bytes(path)
        require(pin == {"bytes": len(raw), "sha256": digest(raw)}, "pinned training source changed")
    require(claimed["digest"] == digest(canonical(claimed["files"])), "code identity aggregate digest")


def model_costs(batch, audit, intervention):
    costs = batch["native_cost"]
    require(len(costs) == 2, "missing native cost snapshots")
    for kind, item in zip(("semantic", "procedure"), costs):
        expected = audit[kind]["interventions"][intervention]
        require(item["parameter_bytes"] == expected["parameter_bytes"] and item["serialized_bytes"] == expected["native_bytes"], "runtime used different model accounting")
        require(item["resident_budget_bytes"] == 262144, "matched logical budget changed")
        resident = sum(integer(item[f"resident_{name}_bytes"], "resident payload") for name in ("parameter", "catalog", "support", "lineage"))
        require(resident <= 262144, "runtime exceeded logical budget")
        for name in ("read_count", "wake_count", "eviction_count", "artifact_load_wall_ns", "read_wall_ns", "wake_wall_ns"):
            integer(item[name], name)
    return costs


def stage_score(directory, stage, independent, representation, code, previous):
    require(stage == read_json(directory / "STAGE.json"), "stage report differs from raw artifact")
    export = identity(directory / "OWNER_EXPORT.json", stage["owner"])
    facts = owner_facts(export)
    require(len(facts) == 1 + 8 * (stage["stage"] + 1) and stage["new_records"] == 24, "new typed fact inventory")
    for write in independent["writes"]:
        require(all(facts[write["entity"]][kind][1] == write[kind] for kind in ("event", "semantic", "procedure")), "new write differs from independently frozen source")
    request = read_json(directory / "FIT_REQUEST.json")
    frame = decode(request["request_json"])
    response = read_json(directory / "FIT_RESPONSE.json")
    result = decode(response["response_json"])
    require(set(frame) == {"schema", "representation", "configuration", "export", "parents"}
            and frame["schema"] == "hepta.memory.v9.paired-fit.v1" and frame["export"] == export
            and frame["representation"] == representation and frame["configuration"] == result["configuration"], "fit input scope")
    require(frame["parents"] == ({} if previous is None else previous["artifacts"]), "continuation parent is not exact prior trained artifact")
    require(request["request_sha256"] == result["request_digest"] == digest(request["request_json"].encode()), "exact fit request binding")
    require(request["code_identity"] == response["code_identity"] == code, "worker code identity differs")
    require(response["exit_code"] == 0 and response["request_bytes"] == len(request["request_json"].encode()) <= 16777216
            and response["response_bytes"] == len(response["response_json"].encode()) <= 16777216
            and response["stderr_bytes"] == len(response["stderr"].encode()) <= 8192, "bounded worker evidence")
    integer(response["whole_worker_wall_ns"], "whole fit process wall", 1)
    lock = read_json(directory / "FIT_LOCK.json")
    require(lock["future_outcomes_seen"] is False and lock["request_digest"] == result["request_digest"]
            and lock["owner_cut"] == export["owner_cut_digest"] and lock["code_identity"] == code
            and lock["fixture_sha256"] == FIXTURE_HASH and lock["configuration"] == result["configuration"], "pre-evaluation fit lock")
    audit, trained = audit_pairs(result, export, representation, None if previous is None else previous["models"])
    require(stage["training_receipt"] == result["receipt"], "stage training receipt differs from original worker")
    require([item["intervention"] for item in stage["interventions"]] == list(VARIANTS), "intervention order/inventory")
    scored, costs = {}, {}
    for item in stage["interventions"]:
        name, publication = item["intervention"], item["publication"]
        require(publication["source_cut"] == export["owner_cut_digest"] and publication["intervention"] == name, "intervention publication owner")
        for kind in ("semantic", "procedure"):
            require(publication[f"{kind}_digest"] == audit[kind]["interventions"][name]["native_digest"], "published native model differs from paired fit")
        phases = {}
        for phase, pin in zip(("future", "retention"), item["phases"]):
            require(pin["path"] == f"{name}-{phase}.json", "phase filename changed")
            batch = identity(child_path(directory, pin["path"]), pin)
            phases[phase] = verify_batch(batch, export, independent[phase], publication)
            costs[f"{name}-{phase}"] = model_costs(batch, audit, name)
        require(len(item["phases"]) == 2, "extra phase")
        scored[name] = phases
    selected = stage["continuation_selection"]
    last = stage["interventions"][-1]["publication"]
    require(selected["generation"] == last["generation"] + 1 and selected["intervention"] == "trained"
            and selected["source_cut"] == export["owner_cut_digest"], "continuation policy changed")
    for kind in ("semantic", "procedure"):
        require(selected[f"{kind}_digest"] == audit[kind]["interventions"]["trained"]["native_digest"], "continuation did not restore trained candidate")
    generations = [item["publication"]["generation"] for item in stage["interventions"]]
    start = 1 if previous is None else previous["publication"]["generation"] + 1
    require(generations == list(range(start, start + 4)), "release generation sequence")
    prefix = verify_batch(read_json(directory / "completed-prefix.json"), export, independent["prefix"], stage["interventions"][0]["publication"])
    require(prefix["reads"] == prefix["correct_reads"], "source current prefix failed")
    retention = None
    if previous is not None:
        before_export = read_json(directory / "BEFORE_OWNER.json")
        require(before_export["records"] == previous["export"]["records"] and before_export["current_source_ids"] == previous["export"]["current_source_ids"], "before-retention source changed")
        before = verify_batch(identity(directory / "before-retention.json", stage["before_retention"]), before_export,
                              independent["retention"], previous["publication"])
        after = scored["trained"]["retention"]
        retention = {"reads": transitions(before["items"], after["items"]), "decisions": transitions(before["decisions"], after["decisions"])}
    gains = {}
    for control in ("zero", "frozen"):
        before, after = scored[control]["future"], scored["trained"]["future"]
        require(before["request_digests"] == after["request_digests"], "future task/query pairs changed")
        gains[control] = {"reads": transitions(before["items"], after["items"]), "decisions": transitions(before["decisions"], after["decisions"]),
                          "correct_read_gain": after["correct_reads"] - before["correct_reads"],
                          "correct_decision_gain": after["correct_decisions"] - before["correct_decisions"]}
    summaries = {name: {phase: {key: value for key, value in score.items() if key not in {"items", "decisions", "request_digests"}}
                       for phase, score in phases.items()} for name, phases in scored.items()}
    passed = all(value["correct_read_gain"] >= 1 and value["correct_decision_gain"] >= 1 for value in gains.values())
    passed &= retention is None or all(retention[unit]["lost"] == 0 for unit in ("reads", "decisions"))
    summary = {"stage": stage["stage"], "id": stage["id"], "source_cut": export["owner_cut_digest"], "owner_current_entities": len(facts),
               "future": {"paired_gains": gains, "written_support_and_authored_task_composition_only": True},
               "retention_before_after": retention, "interventions": summaries, "model_audit": audit, "native_costs": costs,
               "whole_worker_wall_ns": response["whole_worker_wall_ns"],
               "source_ledger_logical_bytes": integer(stage["source_ledger_logical_bytes"], "source ledger bytes", 1),
               "artifact_owner_logical_bytes": integer(stage["artifact_owner_logical_bytes"], "artifact owner bytes", 1),
               "causal_read_decision_and_retention_gate_passed": passed}
    return summary, {"artifacts": result["artifacts"]["trained"], "models": trained, "publication": selected, "export": export}


def score(input_path):
    raw = read_bytes(input_path)
    main = decode(raw)
    require(main["schema"] == "hepta.memory.v9.actual-continual.v1" and main["fixture_sha256"] == FIXTURE_HASH, "continual parent schema")
    independent_raw = read_bytes(PROJECT.parent / "evaluation" / "continual-held.json")
    require(digest(independent_raw) == FIXTURE_HASH, "independent future fixture changed")
    independent = decode(independent_raw)
    directory = child_path(input_path.parent, main["artifact_directory"])
    code_identity(main["code_identity"])
    require(read_bytes(directory / "PROTOCOL.json") == read_bytes(PROJECT / "PROTOCOL.json"), "archived protocol differs")
    lock = read_json(directory / "MANIFEST.json")
    require(lock["code_identity"] == main["code_identity"] and lock["fixture_sha256"] == FIXTURE_HASH
            and lock["future_outcomes_seen"] is False and lock["representations"] == ["catalog", "byte"]
            and lock["interventions"] == list(VARIANTS) and lock["stages"] == 3
            and lock["resident_budget_per_type"] == 262144, "episode protocol lock")
    require([item["representation"] for item in main["children"]] == ["catalog", "byte"], "representation inventory")
    require(set(lock["runtime_roots"]) == {"catalog", "byte"}
            and len(set(lock["runtime_roots"].values())) == 2, "separate recorded runtime storage roots")
    children = []
    for entry in main["children"]:
        root = child_path(directory, entry["directory"])
        child = identity(root / "CHILD.json", entry["child_identity"])
        require(child == entry["child"] and child["schema"] == "hepta.memory.v9.continual-child.v1"
                and child["representation"] == entry["representation"] and child["code_identity"] == main["code_identity"]
                and child["fixture_sha256"] == FIXTURE_HASH, "child identity")
        require(len(child["stages"]) == 3 and child["actual_training_processes"] == 3 and child["actual_fit_calls"] == 18, "child process/fit inventory")
        resources = identity(child_path(directory, entry["resource_identity"]["path"]), entry["resource_identity"])
        config = read_json(directory / f"{entry['representation']}-config.json")
        require(set(config) == {"representation", "output_dir", "runtime_root"}
                and config["representation"] == entry["representation"]
                and Path(config["output_dir"]).name == entry["directory"], "continual child launch configuration")
        verify_runtime_storage(config, child, resources, lock["runtime_roots"][entry["representation"]])
        resources = verify_resources(directory, resources, child["pid"], entry["parent_supervision_wall_ns"])
        resources["runtime_storage_roots_verified"] = True
        stages, previous = [], None
        for index, stage in enumerate(child["stages"]):
            require(stage["stage"] == index and stage["id"] == independent["stages"][index]["id"], "stage order")
            result, previous = stage_score(child_path(root, stage["directory"]), stage, independent["stages"][index],
                                           child["representation"], child["code_identity"], previous)
            stages.append(result)
        children.append({"representation": child["representation"], "stages": stages, "resources": resources,
                         "gate_passed": all(stage["causal_read_decision_and_retention_gate_passed"] for stage in stages)})
    require(main["actual_training_processes"] == 6 and main["actual_fit_calls"] == 36, "complete paired process budget")
    return {"schema": "hepta.memory.v9.continual-score.v1", "integrity": "verified", "input_sha256": digest(raw),
            "fixture_sha256": FIXTURE_HASH, "children": children, "actual_worker_processes": 6, "actual_fit_calls": 36,
            "parent_wall_ns_before_final_receipt": integer(main["parent_wall_ns_before_final_receipt"], "episode wall", 1),
            "causal_parameter_gate_passed": all(child["gate_passed"] for child in children),
            "system_compression_established": False, "full_cost_net_gain_established": False,
            "exact_rss_byte_time_available": False, "three_stages_are_independent_trials": False,
            "novel_address_or_open_world_program_discovery_established": False,
            "natural_language_addressing_evaluated": False, "evidence_grants_authority": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    require(args.input.is_absolute() and args.output.is_absolute(), "absolute evidence and score paths required")
    failed = False
    try:
        if read_json(args.input).get("schema") == "hepta.memory.v9.actual-structure.v1":
            from structure_score import score as score_structure
            result = score_structure(args.input)
        else:
            result = score(args.input)
    except (ValueError, KeyError, TypeError, OSError, OverflowError, AssertionError, IndexError, StopIteration) as error:
        result = {"schema": "hepta.memory.v9.continual-score.v1", "integrity": "failed", "error": f"{type(error).__name__}: {error}"}
        failed = True
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"integrity": result["integrity"], "output": str(args.output)}))
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
