"""Explicit synthetic owner fixtures; no fixture is real model-quality evidence."""
from copy import deepcopy
from pathlib import Path

from evaluation import BINDINGS, canonical, digest


FIXED_TEST_TIME = 1_800_000_000_000


def fixture_documents(now=FIXED_TEST_TIME):
    docs = {role: {"synthetic": True, "role": role, "revision": 1} for role in
            ("model_graph", "task", "input_schema", "label_source", "objective", "semantics")}
    units = []
    for index, seed in enumerate((11, 23, 37, 53, 71)):
        uid = f"synthetic_fit_{seed}"
        orig, edit, weak, run = (f"{prefix}:{uid}" for prefix in ("original", "edit", "weak", "training"))
        docs[orig] = {"synthetic_checkpoint": uid, "parameter": .2}
        docs[edit] = {"synthetic_checkpoint": uid, "parameter": .8}
        docs[weak] = {"synthetic_checkpoint": uid, "parameter": .3}
        docs[run] = {"training_seed": seed, "checkpoint_sha256": digest(canonical(docs[orig])),
                     "model_graph_sha256": digest(canonical(docs["model_graph"])), "status": "completed"}
        units.append({"id": uid, "training_seed": seed, "training_run_role": run, "original_role": orig})
    docs["originals"] = {"schema": "hepta.independent-fit-registry.v1", "units": units}
    p = {"schema": "hepta.finite-evaluation-protocol.v1", "experiment_id": "SYNTHETIC_POSITIVE_CONTROL",
         "frozen_ms": now-10000, "binding": {r: digest(canonical(docs[r])) for r in BINDINGS},
         "source_mode": "simulation", "freshness": {"clock_age_ms": 60000, "clock_uncertainty_ms": 1000,
            "source_age_ms": 20000, "label_age_ms": 20000}, "utility_unit": "synthetic_task_utility",
         "utility_bounds": [0, 1], "domains": ["iid", "ood"], "domain_weights": {"iid": .5, "ood": .5},
         "minimum_gain": {"iid": .005, "ood": .005},
         "statistics": {"method": "paired_t_bonferroni", "unit": "independently_trained_model_fit",
                        "minimum_units": 5, "assumptions": ["independent_fit_effects_conditional_on_fixed_task",
                        "approximately_normal_fit_level_paired_differences"]},
         "candidates": [{"id": "EDIT", "kind": "weight_edit"}, {"id": "WEAK", "kind": "training"}],
         "horizon_episodes": 100, "exchange_rates": {"CPU_second": {"utility_unit": "synthetic_task_utility",
                              "per_resource_unit": .01}}, "cost_scope": "incremental_future_fixed_horizon"}
    docs["protocol"] = p
    ph = digest(canonical(p))
    docs["clock"] = {"source": "clock.curr_time", "observed_utc_ms": now, "uncertainty_ms": 1000}
    seal = {"protocol_sha256": ph, "sealed_ms": now-8000, "selection_completed_ms": now-9000,
            "candidates": {cid: {u["id"]: f"{prefix}:{u['id']}" for u in units}
                           for cid,prefix in (("EDIT", "edit"), ("WEAK", "weak"))}}
    docs["seal"] = seal
    sh = digest(canonical(seal))
    samples, labels, outcomes = [], [], []
    for i, u in enumerate(units):
        for domain in p["domains"]:
            content = {"synthetic_world": f"{u['id']}:{domain}", "draw": i, "law": "fixture-only"}
            sid = digest(canonical(content))
            label = {"sample_id": sid, "available_ms": now-1000, "value": {"synthetic_target": 1}}
            label_sha = digest(canonical(label))
            labels.append(label)
            samples.append({"sample_id": sid, "content_sha256": sid, "content": content,
                "unit_id": u["id"], "domain": domain, "split": "CONFIRMATION", "source_ms": now-3000,
                "anchor_ms": now-3000, "target_end_ms": now-2000, "label_available_ms": now-1000,
                "label_record_sha256": label_sha})
            for cid, role, utility in (("ORIGINAL", u["original_role"], .2),
                                      ("EDIT", f"edit:{u['id']}", .8+.005*i),
                                      ("WEAK", f"weak:{u['id']}", .3+.005*i)):
                outcomes.append({"candidate_id": cid, "sample_id": sid,
                    "model_sha256": digest(canonical(docs[role])), "label_record_sha256": label_sha,
                    "utility": utility, "scored_ms": now-500})
    docs["samples"] = {"protocol_sha256": ph, "seal_sha256": sh, "samples": samples}
    docs["labels"] = {"protocol_sha256": ph, "label_source_sha256": p["binding"]["label_source"], "records": labels}
    docs["outcomes"] = {"protocol_sha256": ph, "seal_sha256": sh,
                        "utility_unit": p["utility_unit"], "records": outcomes}
    docs["exposures"] = {"protocol_sha256": ph, "history_scope": "available_local_recorded_history", "events": []}
    docs["costs"] = {"protocol_sha256": ph, "seal_sha256": sh, "scope": p["cost_scope"],
       "records": {cid: {"resources": {"CPU_second": 10}, "unmeasured_components": [],
                          "basis": "owner_pinned_upper_bound"} for cid in ("EDIT", "WEAK")}}
    return docs


def rebind_protocol(docs):
    """Owner-side fixture regeneration; never called by the decision evaluator."""
    p = docs["protocol"]
    p["binding"] = {r: digest(canonical(docs[r])) for r in BINDINGS}
    ph = digest(canonical(p))
    docs["seal"]["protocol_sha256"] = ph
    sh = digest(canonical(docs["seal"]))
    for role in ("samples", "labels", "exposures", "outcomes", "costs"):
        docs[role]["protocol_sha256"] = ph
        if "seal_sha256" in docs[role]:
            docs[role]["seal_sha256"] = sh


def specialization_fixture_documents(now=FIXED_TEST_TIME):
    """Synthetic equal-quality computation benefit with explicitly assumed bounds."""
    docs = fixture_documents(now)
    p = docs["protocol"]
    p["schema"] = "hepta.finite-evaluation-protocol.v2"
    p["experiment_id"] = "SYNTHETIC_COMPUTE_SPECIALIZATION"
    del p["minimum_gain"]
    p["maximum_quality_loss"] = {"iid": 0.0, "ood": 0.0}
    for candidate in p["candidates"]:
        candidate["kind"] = "compute_specialization"
    for row in docs["outcomes"]["records"]:
        row["utility"] = .2
    docs["costs"].update({"horizon_episodes": p["horizon_episodes"],
        "original": {"resources_lower_bound": {"CPU_second": 100},
                     "unmeasured_components": [], "basis": "owner_pinned_lower_bound"},
        "records": {cid: {"resources_upper_bound": {"CPU_second": value},
                     "unmeasured_components": [], "basis": "owner_pinned_upper_bound"}
                    for cid,value in (("EDIT", 10), ("WEAK", 60))}})
    rebind_protocol(docs)
    return docs


def write_fixture(directory, docs=None, now=FIXED_TEST_TIME, scope="synthetic_test"):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    docs = deepcopy(fixture_documents(now) if docs is None else docs)
    pins = {}
    for role, doc in docs.items():
        filename = role.replace(":", "_")+".json"
        raw = canonical(doc)
        path = directory / filename
        path.write_bytes(raw)
        pins[role] = {"path": filename, "sha256": digest(raw)}
    owner = {"schema": "hepta.research-owner-pins.v1", "owner_id": "EXPLICIT_SYNTHETIC_TEST_OWNER",
             "scope": scope, "pins": pins}
    raw = canonical(owner)
    (directory/"owner.json").write_bytes(raw)
    return "owner.json", digest(raw)
