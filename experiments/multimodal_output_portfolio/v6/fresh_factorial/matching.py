"""Independent recipe fingerprints and pure receipt checks for a fresh generation."""

import hashlib

from .io import digest


PROFILES = ("supervised", "terminal_entropic_ndu")


def recipe_controls(plan, seed, source_ids, torch):
    """Reconstruct controls from the pinned recipe, without optimizing or reading outcomes."""
    from ..neural import ACTIONS, model_from_config, parameter_hash
    from ..plan_training import PlanHead
    config = plan["base_training"]
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        initial = model_from_config({key: config[key] for key in ("hidden", "noise_scale", "architecture")})
        base_initial = parameter_hash(initial)
        del initial
        torch.manual_seed(seed + 65537)
        gate_initial = parameter_hash(PlanHead(config["hidden"]))
    actions, sources, updates = hashlib.sha256(), hashlib.sha256(), hashlib.sha256()
    for iteration in range(config["steps"]):
        batch_seed = seed * 1000003 + iteration
        rng = torch.Generator().manual_seed(batch_seed)
        left = torch.randint(len(source_ids), (config["batch_size"],), generator=rng)
        right = (left + torch.randint(1, len(source_ids), (config["batch_size"],), generator=rng)) % len(source_ids)
        for i, j in zip(left.tolist(), right.tolist(), strict=True):
            sources.update((source_ids[i] + "\n" + source_ids[j] + "\n").encode())
        rng = torch.Generator().manual_seed(batch_seed + 104729)
        torch.randn((config["batch_size"] * config["scenarios"], config["hidden"]), generator=rng)
        indices = torch.randint(len(ACTIONS), (iteration % (config["refinement_steps"] + 1),), generator=rng).tolist()
        actions.update(f"{batch_seed}:{indices}\n".encode())
    rng = torch.Generator().manual_seed(seed + 131071)
    fit = plan["gate_fit"]
    for _ in range(fit["steps"]):
        ids = torch.randperm(fit["fit_pairs"], generator=rng)[:min(32, fit["fit_pairs"])]
        updates.update(ids.numpy().tobytes())
    return {"seed": seed, "base_initial_parameter_sha256": base_initial,
        "base_batch_action_schedule_sha256": actions.hexdigest(),
        "base_recipe_source_schedule_sha256": sources.hexdigest(),
        "gate_initial_parameter_sha256": gate_initial, "gate_update_schedule_sha256": updates.hexdigest(),
        "gate_source_ids_sha256": hashlib.sha256("\n".join(source_ids[:2 * fit["fit_pairs"]]).encode()).hexdigest(),
        "gate_scenario_seeds": [seed * 1000033 + k * 104729 for k in range(fit["scenarios"])],
        "scope": "independent recomputation of the published initializer and RNG schedule; not a second training execution"}


def verify_base_reports(rows, controls, plan):
    expected = {(seed, profile) for seed in plan["seeds"] for profile in PROFILES}
    if len(rows) != 6 or {(x["seed"], x["profile"]) for x in rows} != expected:
        raise ValueError("fresh generation requires exactly six matched base fits")
    if len(controls) != 3 or {x["seed"] for x in controls} != set(plan["seeds"]):
        raise ValueError("independent recipe controls omit a registered seed")
    by_seed = {x["seed"]: x for x in controls}
    for row in rows:
        report, control = row["report"], by_seed[row["seed"]]
        if (report["profile"] != row["profile"] or report["config"] != {"seed": row["seed"], **plan["base_training"]}
                or report["source_manifest_sha256"] != plan["dataset_manifest_sha256"]
                or report["optimizer_updates"] != 2000 or len(report["history"]) != 2000
                or [x["step"] for x in report["history"]] != list(range(1, 2001))
                or report["parameter_count"] != plan["base_parameter_count"]
                or report["conditional_noise_scenarios"] != plan["base_training"]["scenarios"]
                or report["initial_parameter_sha256"] != control["base_initial_parameter_sha256"]
                or report["batch_action_schedule_sha256"] != control["base_batch_action_schedule_sha256"]
                or report["final_parameter_sha256"] == report["initial_parameter_sha256"]):
            raise ValueError("fresh base training config, source, initial state, updates or schedule differs")
    for seed in plan["seeds"]:
        pair = [x["report"] for x in rows if x["seed"] == seed]
        for key in ("initial_parameter_sha256", "batch_action_schedule_sha256", "source_manifest_sha256"):
            if pair[0][key] != pair[1][key]:
                raise ValueError("base objective comparison is not matched within seed")


def matched_gate_reports(reports, controls, plan):
    if len(reports) != 12:
        raise ValueError("every registered fresh gate fit is required")
    common_keys = ("initial_gate_sha256", "gate_update_schedule_sha256", "source_ids_sha256",
                   "scenario_seeds", "batch_seed", "plans", "optimizer_updates")
    by_seed = {x["seed"]: x for x in controls}
    for seed in plan["seeds"]:
        selected = [r for r in reports if r["seed"] == seed]
        if {r["arm"] for r in selected} != set(plan["arms"]):
            raise ValueError("duplicate or missing seed/arm gate fit")
        reference, control = selected[0]["report"], by_seed[seed]
        for row in selected:
            report = row["report"]
            if (any(digest(report[key]) != digest(reference[key]) for key in common_keys)
                    or report["optimizer_updates"] != 120 or report["fit_pairs"] != 128
                    or report["seed"] != seed or report["fit_split"] != "train"
                    or report["batch_seed"] != seed * 1000003 + 4409
                    or report["content_plan_metric_sha256"] != plan["metric_sha256"]
                    or report["content_plan_scenario_count"] != plan["gate_fit"]["scenarios"]
                    or report["content_plan_risk_aversion"] != plan["gate_fit"]["risk_aversion"]
                    or report["source_manifest_sha256"] != plan["dataset_manifest_sha256"]
                    or report["initial_gate_sha256"] != control["gate_initial_parameter_sha256"]
                    or report["gate_update_schedule_sha256"] != control["gate_update_schedule_sha256"]
                    or report["source_ids_sha256"] != control["gate_source_ids_sha256"]
                    or report["scenario_seeds"] != control["gate_scenario_seeds"]
                    or report["content_plan_training_profile"] != plan["arms"][row["arm"]]["gate"]):
                raise ValueError("fresh gate initialization/source/scenario/schedule/objective is not matched")
        for base in PROFILES:
            same = [r["report"] for r in selected if plan["arms"][r["arm"]]["base"] == base]
            for key in ("base_sha256", "output_observation_sha256", "utility_table"):
                if digest(same[0][key]) != digest(same[1][key]):
                    raise ValueError("gate objectives did not receive identical frozen-base rewards")
