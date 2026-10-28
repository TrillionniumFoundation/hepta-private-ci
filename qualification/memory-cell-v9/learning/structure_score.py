"""Independent V9 structure matrix audit, preserving a measured NoChange result."""

import json
from pathlib import Path

from evidence import child_path, decode, digest, identity, integer, owner_facts, read_bytes, read_json, require, transitions, verify_batch
from resource_evidence import verify_resources
from score import code_identity
from structure_evidence import population, selection, verify_gate


PROJECT = Path(__file__).resolve().parent
FIXTURE_HASH = "750ecabdcdbc0aa9f5bf253615efaff090800c3a96a2958e0d17a4df829c6502"
ROLES = [*(f"fixed-{count}" for count in range(1, 9)), "prefix-selected-fixed", "prefix-selected-learned", "direct-owner", "keep-fixed-2"]


def direct_acquisition(claimed, export, facts):
    require(claimed["schema"] == "hepta.memory.direct-owner-acquisition.v1" and claimed["trained_models"] == 0
            and claimed["logical_cache_budget_bytes"] == 32768, "direct source-only profile")
    rows = {}
    for index, page in enumerate(claimed["pages"]):
        require(page["schema"] == "hepta.memory.owner-snapshot-page.v1" and page["scope"] == export["scope"]
                and page["owner_cut_digest"] == export["owner_cut_digest"], "direct page owner binding")
        for row in page["records"]:
            require(row["source_id"] not in rows, "repeated paginated source")
            rows[row["source_id"]] = row
        require(page["next_after"] == (page["records"][-1]["source_id"] if index + 1 < len(claimed["pages"]) else None), "direct page cursor")
    expected = {row["source_id"]: row for row in export["records"] if row["source_id"] in export["current_source_ids"]}
    require(rows == expected, "direct baseline did not fetch the same current facts")
    size = len(json.dumps(facts, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode())
    require(claimed["logical_cache_bytes"] == size <= 32768, "direct source cache exceeds common budget")
    integer(claimed["acquisition_wall_ns"], "direct acquisition time", 1)


def stage_score(root, claimed, independent, code, previous):
    require(claimed == read_json(root / "STAGE.json") and [role["role"] for role in claimed["roles"]] == ROLES, "complete role inventory")
    export = identity(root / "OWNER_EXPORT.json", claimed["owner"])
    facts = owner_facts(export)
    require(len(facts) == 1 + 8 * (claimed["stage"] + 1), "continual structure support inventory")
    for write in independent["writes"]:
        require(all(facts[write["entity"]][kind][1] == write[kind] for kind in ("event", "semantic", "procedure")), "structure facts differ from independently frozen writes")
    if previous is not None:
        require(all(facts[entity] == row for entity, row in previous["facts"].items()), "structure lost old source facts")
    prefix = read_json(root / "completed-prefix.json")
    prefix_score = verify_batch(prefix, export, independent["prefix"], claimed["prefix_publication"])
    require(prefix_score["correct_reads"] == prefix_score["reads"], "completed prefix contains failed owner reads")
    selected, selection_cost = selection(root / "selection", code, export, prefix, claimed["selection"])
    lock = read_json(root / "SELECT_LOCK.json")
    require(lock == {"source_cut": export["owner_cut_digest"], "code_identity": code,
                     "selection_request_digest": selected["request_digest"], "selected": selected["selected"],
                     "trace_digest": selected["trace"]["trace_digest"], "future_outcomes_seen": False}, "future-blind structural lock")
    models, fit_costs = {}, {}
    for count in range(1, 9):
        name = f"fixed-{count}"
        models[name], fit_costs[name] = population(root / name, code, export, count)
    learned_count, light_count = selected["selected"]["learned"], selected["selected"]["fixed"]
    models["learned"], fit_costs["learned"] = population(root / "learned", code, export, learned_count, selected)
    for kind in ("semantic", "procedure"):
        require(claimed["prefix_publication"][f"{kind}_digest"] == models["fixed-2"][kind]["native_digest"], "prefix bootstrap differs from fixed-2 fit")
    generation = claimed["prefix_publication"]["generation"]
    require(generation == (1 if previous is None else previous["generation"] + 1), "stage bootstrap generation")
    scored, summaries = {}, {}
    requests = None
    for role in claimed["roles"]:
        name, publication = role["role"], role["publication"]
        direct = name == "direct-owner"
        if direct:
            acquisition = read_json(root / "direct-owner-acquisition.json")
            require(acquisition == role["acquisition"], "direct acquisition evidence changed")
            direct_acquisition(acquisition, export, facts)
        else:
            expected_fit = "learned" if name == "prefix-selected-learned" else f"fixed-{light_count}" if name == "prefix-selected-fixed" else "fixed-2" if name == "keep-fixed-2" else name
            count = learned_count if expected_fit == "learned" else int(expected_fit.rsplit("-", 1)[1])
            require(role["fit_directory"] == expected_fit and role["shards"] == count, "future outcomes altered locked role choice")
            generation += 1
            require(publication["generation"] == generation and publication["source_cut"] == export["owner_cut_digest"], "structural release sequence")
            for kind in ("semantic", "procedure"):
                require(publication[f"{kind}_digest"] == models[expected_fit][kind]["native_digest"], "runtime role did not use exact trained native parameters")
        phases = {}
        require(len(role["phases"]) == 2, "incomplete future/retention role")
        for phase, phase_claim in zip(("future", "retention"), role["phases"]):
            pin = phase_claim["identity"]
            require(pin["path"] == f"{name}-{phase}.json", "role/phase filename changed")
            batch = identity(child_path(root, pin["path"]), pin)
            phases[phase] = verify_batch(batch, export, independent[phase], publication)
            for key in ("queries", "correct", "tasks", "decisions_correct", "wall_ns", "traffic"):
                require(phase_claim[key] == batch[key], "role phase summary changed")
            if not direct:
                require(phase_claim["native_cost"] == batch["native_cost"] and len(batch["native_cost"]) == 2, "role native cost snapshot")
                for kind, cost in zip(("semantic", "procedure"), batch["native_cost"]):
                    require(cost["resident_budget_bytes"] == 16384 and cost["serialized_bytes"] == models[expected_fit][kind]["native_bytes"]
                            and cost["parameter_bytes"] == models[expected_fit][kind]["parameter_bytes"], "role logical budget or actual model cost")
                    require(sum(integer(cost[f"resident_{field}_bytes"], "resident cost") for field in ("parameter", "catalog", "support", "lineage")) <= 16384, "budget exceeded decoded residency")
            elif phase == "future":
                require(phases[phase]["correct_reads"] == phases[phase]["reads"], "exact owner baseline did not recover facts")
        if requests is None:
            requests = phases["future"]["request_digests"]
        require(phases["future"]["request_digests"] == requests, "role future requests differ")
        scored[name] = phases
        summaries[name] = {phase: {key: value for key, value in score.items() if key not in {"items", "decisions", "request_digests"}} for phase, score in phases.items()}
    verify_gate(claimed["structure_gate"], claimed["roles"], code, export["owner_cut_digest"])
    require(claimed["structure_gate"]["selected_generation_unchanged"] == generation, "NoChange changed the selected version")
    best_fixed = max((f"fixed-{count}" for count in range(1, 9)), key=lambda name: (scored[name]["future"]["correct_reads"], scored[name]["future"]["correct_decisions"]))
    learned = scored["prefix-selected-learned"]["future"]
    comparison = {}
    for reference in (best_fixed, "prefix-selected-fixed", "direct-owner", "keep-fixed-2"):
        comparison[reference] = {"reads": transitions(scored[reference]["future"]["items"], learned["items"]),
                                 "decisions": transitions(scored[reference]["future"]["decisions"], learned["decisions"])}
    routes = models["learned"]["semantic"]["routes"]
    earlier = {} if previous is None else previous["routes"]
    require(claimed["actual_training_processes"] == 9 and claimed["actual_selection_processes"] == 1
            and claimed["actual_fit_calls"] == 72 + 2 * learned_count, "complete search/fitting budget")
    result = {"stage": claimed["stage"], "id": claimed["id"], "selected_counts": selected["selected"], "roles": summaries,
              "oracle_fixed_reference_by_accuracy": best_fixed, "oracle_reference_was_not_deployment_selection": True,
              "learned_vs_references": comparison, "fit_workers": fit_costs, "selection_worker": selection_cost,
              "all_search_worker_wall_ns": sum(item["whole_worker_wall_ns"] for item in fit_costs.values()) + selection_cost["whole_worker_wall_ns"],
              "all_search_worker_transport_bytes": sum(item["request_bytes"] + item["response_bytes"] for item in [*fit_costs.values(), selection_cost]),
              "old_addresses_reassigned": sum(routes[key] != old for key, old in earlier.items()), "new_addresses": len(set(routes) - set(earlier)),
              "complete_model_audit": models, "structure_gate": claimed["structure_gate"],
              "source_ledger_logical_bytes": integer(claimed["source_ledger_logical_bytes"], "source ledger", 1),
              "artifact_owner_logical_bytes": integer(claimed["artifact_owner_logical_bytes"], "artifact owner", 1),
              "actual_fit_calls": claimed["actual_fit_calls"], "full_cost_gain_established": False}
    return result, {"facts": facts, "generation": generation, "routes": routes}


def score(path):
    raw = read_bytes(path)
    main = decode(raw)
    require(main["schema"] == "hepta.memory.v9.actual-structure.v1" and main["fixture_sha256"] == FIXTURE_HASH, "structure parent schema")
    directory = child_path(path.parent, main["artifact_directory"])
    fixture_raw = read_bytes(PROJECT.parent / "evaluation" / "continual-held.json")
    require(digest(fixture_raw) == FIXTURE_HASH, "structure independent future changed")
    fixture = decode(fixture_raw)
    protocol = read_bytes(PROJECT / "STRUCTURE_PROTOCOL.json")
    require(protocol == read_bytes(directory / "PROTOCOL.json") and decode(protocol)["maximum_retention_error_permyriad"] == 0, "structure protocol changed or relaxed retention")
    code_identity(main["code_identity"])
    lock = read_json(directory / "MANIFEST.json")
    require(lock == {"code_identity": main["code_identity"], "fixture_sha256": FIXTURE_HASH,
                     "protocol_sha256": digest(protocol), "future_outcomes_seen": False}, "structure manifest")
    child = identity(directory / "trial" / "CHILD.json", main["child_identity"])
    require(child == main["child"] and child["schema"] == "hepta.memory.v9.structure-child.v1"
            and child["code_identity"] == main["code_identity"] and child["fixture_sha256"] == FIXTURE_HASH
            and len(child["stages"]) == 3, "structure child inventory/binding")
    resources = verify_resources(directory, identity(directory / "resources.json", main["resource_identity"]), child["pid"], main["parent_supervision_wall_ns"])
    stages, previous = [], None
    for index, stage in enumerate(child["stages"]):
        require(stage["stage"] == index and stage["id"] == fixture["stages"][index]["id"], "structure stage identity")
        result, previous = stage_score(child_path(directory / "trial", stage["directory"]), stage, fixture["stages"][index], main["code_identity"], previous)
        stages.append(result)
    require(child["actual_training_processes"] == 27 and child["actual_selection_processes"] == 3
            and child["actual_fit_calls"] == sum(stage["actual_fit_calls"] for stage in stages), "structure complete cost inventory")
    return {"schema": "hepta.memory.v9.structure-score.v1", "integrity": "verified", "input_sha256": digest(raw),
            "fixture_sha256": FIXTURE_HASH, "stages": stages, "resources": resources, "actual_training_processes": 27,
            "actual_selection_processes": 3, "actual_fit_calls": child["actual_fit_calls"],
            "full_cost_gain_established": False, "decision": "NoChange", "exact_continuous_cost_established": False,
            "specialization_learned_from_completed_prefix_only": True, "new_domains_are_independent_trials": False,
            "new_semantic_type_or_program_discovery_established": False, "natural_language_addressing_evaluated": False,
            "evidence_grants_authority": False}
