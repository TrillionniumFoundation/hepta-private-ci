"""Explicit synthetic fixtures. Never model, future-window or production evidence."""
from copy import deepcopy

from four_gate_common import PHASES, digest
from four_gate_outcomes import NDU_ARMS, REASON_ARMS, STRATA, WINDOWS


def plan_fixture():
    ceilings = {"cpu_ns": 10**12, "wall_ns": 10**12}
    cfg = {"parameter_ceiling": 1_000_000, "rss_ceiling_bytes": 10**9,
           "episode_ceilings": ceilings, "lifecycle_ceilings": ceilings}
    plan = {"schema": "hepta.four-gate.plan.v1", "source_sha": "1" * 40,
            "objective_sha256": digest("FIXTURE fixed external objective"),
            "evidence_kind": "synthetic_diagnostic", "min_groups": 2,
            "bootstrap_replicates": 1000, "seed": 7, "alpha": .05,
            "preregistered_at": "2026-08-01T00:00:00Z",
            "selection_cutoff": "2026-08-31T23:59:59Z",
            "assessment_time": "2026-10-01T00:00:00Z",
            "windows": {"future_1": ["2026-09-01T00:00:00Z", "2026-09-02T23:59:59Z"],
                        "future_2": ["2026-09-03T00:00:00Z", "2026-09-04T23:59:59Z"]},
            "required_cost_axes": ["cpu_ns", "wall_ns"],
            "compute": {"p99_ceiling_ns": 10**12, "rss_ceiling_bytes": 10**9,
                        "throughput_floor_rps": .01, "max_p99_ratio": 2,
                        "schedule_sha256s": {},
                        "arm_weights_sha256": {arm: digest("FIXTURE weights")
                                               for arm in ("no_change", "joint_batch", "feature_reuse")}},
            "learning": {"ood_far_regression_cap": 0},
            "reasoning": {**deepcopy(cfg), "selected_depth": 2,
                          "matching_relative_tolerance": .05, "match_axes": ["cpu_ns"],
                          "minimum_score_gain": 0},
            "ndu": {**deepcopy(cfg), "utility_profile_sha256": digest("FIXTURE utility profile"),
                    "cost_weights": {"cpu_ns": .01}, "quality_noninferiority_margin": 0,
                    "cost_noninferiority_margin": 0}}
    plan["ndu"]["utility_profile_sha256"] = digest({
        "profile": "registered_linear_external_score_minus_lifecycle_cost",
        "objective_sha256": plan["objective_sha256"],
        "cost_weights": plan["ndu"]["cost_weights"]})
    return plan


def cost_fixture(cpu=0, wall=0):
    return {"cpu_ns": cpu, "wall_ns": wall, "gpu_ns": 0, "energy_uj": None}


def lifecycle_fixture(arm, cpu=0, wall=0):
    return {phase: {"job_id": f"{arm}:{phase}",
                    "cost": cost_fixture(cpu, wall) if phase == "inference" else cost_fixture()}
            for phase in PHASES}


def nodes_fixture(root, depth=2, prefix="node"):
    nodes = []
    for index in range(depth):
        nodes.append({"id": f"{prefix}-{index}", "kind": "cell" if index == 0 else "group_reasoning",
                      "parents": [nodes[-1]["id"]] if nodes else [],
                      "start_ns": index * 10, "end_ns": (index + 1) * 10,
                      "input_refs": [nodes[-1]["output_sha256"]] if nodes else [root],
                      "output_sha256": digest([prefix, index])})
    return nodes


def outcomes_fixture(plan, gate="reasoning", groups=2):
    arms = REASON_ARMS if gate == "reasoning" else NDU_ARMS
    cases = []
    episodes = []
    for window in WINDOWS:
        for stratum in STRATA:
            for index in range(groups):
                cid = f"FIXTURE:{window}:{stratum}:{index}"
                case = {"case_id": cid, "window": window, "stratum": stratum,
                        "source_cluster": cid, "input_sha256": digest([cid, "input"]),
                        "structure_sha256": digest([cid, "novel structure"]),
                        "event_time": plan["windows"][window][0]}
                cases.append(case)
                for arm in arms:
                    depth = 1 if arm in ("single_step", "equal_compute_control") else 2
                    trace = nodes_fixture(case["input_sha256"], depth, cid + arm)
                    score = (float(arm == "fixed_depth") if gate == "reasoning" else
                             {"fixed_budget": .3, "confidence": .4,
                              "ndu_deterministic": .7, "ndu_stochastic": .9}[arm])
                    episodes.append({"case_id": cid, "arm": arm,
                                     "input_sha256": case["input_sha256"], "status": "succeeded",
                                     "external_outcome": {"objective_sha256": plan["objective_sha256"],
                                                          "observer_id": "FIXTURE observer",
                                                          "receipt_sha256": digest([cid, arm, "outcome"]),
                                                          "observed_at": case["event_time"], "score": score},
                                     "cost": cost_fixture(10, 20), "trace": trace,
                                     "prediction_sha256": trace[-1]["output_sha256"]})
    metadata = {}
    for arm in arms:
        metadata[arm] = {"source_sha": plan["source_sha"], "objective_sha256": plan["objective_sha256"],
                         "stem_sha256": digest("FIXTURE shared Stem"),
                         "tokenizer_sha256": digest("FIXTURE tokenizer"),
                         "training_data_sha256": digest("FIXTURE training data"),
                         "policy_sha256": digest(["FIXTURE policy", arm]),
                         "host_sha256": digest("FIXTURE host"),
                         "environment_sha256": digest("FIXTURE environment"),
                         "selection_time": plan["selection_cutoff"], "trainable_parameters": 128,
                         "producer_id": "FIXTURE model runner", "peak_rss_bytes": 1000,
                         "lifecycle": lifecycle_fixture(arm, 10 * len(cases), 20 * len(cases))}
    return {"schema": f"hepta.four-gate.{gate}-traces.v1", "arms": metadata,
            "training_source_clusters": ["FIXTURE historical source"],
            "training_structure_sha256s": [digest("FIXTURE historical structure")],
            "training_input_sha256s": [digest("FIXTURE historical input")],
            "cases": cases, "episodes": episodes,
            "utility_profile_sha256": plan["ndu"]["utility_profile_sha256"],
            "utility_profile": "registered_linear_external_score_minus_lifecycle_cost"}


def schedule_fixture(n=4, repeats=False):
    return [{"request_id": f"request-{i}", "cell_id": i,
             "principal": "fixture-principal", "scope": "fixture-scope", "purpose": "research",
             "generation": 1, "authority_epoch": 1,
             "state_sha256": digest(["fixture state", 0 if repeats else i]),
             "joint_sha256": digest(["fixture joint", i])} for i in range(n)]
