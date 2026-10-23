"""Frozen residual-budget forecasts; estimates reserve work, never charge it.

CPU forecasts use only training probes/counters. They are scheduling estimates,
not bounds on hardware execution; the runner still rejects actual cap breaches.
"""

import math

from independent.evaluation import output_work
from independent.controller_cost import controller_work
from independent.inference import FrozenGenerator
from independent.learning import setup_work


def add_work(*parts):
    result = {}
    for part in parts:
        for key, value in part.items():
            result[key] = result.get(key, 0) + int(value)
    return result


def scale_work(work, count):
    return {key: int(value) * count for key, value in work.items()}


def observer_work(n):
    return {"macs": 4 * n * 12 * 12, "scalar_ops": 124 * n,
            "compare_ops": 14 * n, "div_ops": n}


def validation_modes(modes=None):
    modes = ("full", "low", "ensemble") if modes is None else tuple(modes)
    if (not modes or len(set(modes)) != len(modes)
            or any(mode not in ("full", "low", "ensemble") for mode in modes)):
        raise ValueError("unique supported static validation modes required")
    return modes


def validation_work(model, n, modes=None):
    modes = validation_modes(modes)
    generator = FrozenGenerator(model, prepare_low=False)
    return add_work(generator.full_work(n) if "full" in modes or "ensemble" in modes else {},
        add_work(generator.low_work(n), generator.prepare_work())
            if "low" in modes or "ensemble" in modes else {},
        {"scalar_ops": 24 * n, "div_ops": 24 * n} if "ensemble" in modes else {},
        scale_work(observer_work(n), len(modes)), setup_work(model.dimensions, "additive"))


def _output_work(model, n):
    pixels = model.dimensions[2]
    return add_work(scale_work(output_work(model.dimensions[1], pixels), n),
        {"scalar_ops": 3 * n * pixels, "compare_ops": 2 * n * pixels,
         "exp_ops": n * pixels, "div_ops": n * pixels})


def _observation_work(model, n):
    return add_work(scale_work(setup_work(model.dimensions, "additive"), 2),
        observer_work(n), {"macs": 2 * n * 12 * 12, "scalar_ops": 2 * n})


def _critic_work(model, generator, n, plan=None):
    kind = None if plan is None else plan.get("controller", {}).get("gain_head")
    if kind in (None, "probability-ridge-v1"):
        return generator.critic_work(n)
    if kind != "low-hidden-instruction-affine-v1":
        raise ValueError("unsupported gain head in residual forecast")
    from independent.gain_head import head_work
    return head_work(model.dimensions[3], n)


def _service_work(model, generator, n, mode, plan=None):
    if mode == "full":
        generation, prepare = generator.full_work(n), {}
    elif mode == "low":
        generation, prepare = generator.low_work(n), generator.prepare_work()
    elif mode == "ensemble":
        generation = add_work(generator.full_work(n), generator.low_work(n),
                              {"scalar_ops": 24 * n, "div_ops": 24 * n})
        prepare = generator.prepare_work()
    elif mode == "continuation":
        generation = add_work(generator.full_work(n), generator.low_work(n),
                              _critic_work(model, generator, n, plan))
        prepare = generator.prepare_work()
    elif mode == "random":
        generation = add_work(generator.full_work(n), {"scalar_ops": n, "compare_ops": n})
        # Random routing can require a folded low view even though all-full
        # generation is its upper arithmetic cost.
        prepare = generator.prepare_work()
    else:
        raise ValueError("unsupported frozen residual service mode")
    return add_work(generation, prepare, _output_work(model, n))


def reserve_work(model, system, mode, *, train_rows, validation_rows,
                 calibration_rows, calibration_repeats, raw_reward_cached=True, plan=None):
    """Per-selected-model future inventories, with worst-case optional passes."""
    if any(type(n) is not int or n <= 0 for n in
           (train_rows, validation_rows, calibration_rows, calibration_repeats)):
        raise ValueError("positive frozen row counts and repeats required")
    generator = FrozenGenerator(model, prepare_low=False)
    observation = _observation_work(model, validation_rows)
    service = _service_work(model, generator, validation_rows, mode, plan)
    critic, paired = {}, {}
    if system == "ndu_control":
        service = add_work(_service_work(model, generator, validation_rows, "continuation", plan),
                            _service_work(model, generator, validation_rows, "random", plan))
        observation = scale_work(observation, 2)
        # Each matched pair executes low+critic in both laws and full only in
        # the go law. Six measures prepare their own generator for 3 repeats.
        paired = scale_work(add_work(scale_work(generator.low_work(calibration_rows), 2),
            generator.full_work(calibration_rows),
            scale_work(_critic_work(model, generator, calibration_rows, plan), 2),
            scale_work(_output_work(model, calibration_rows), 2),
            scale_work(generator.prepare_work(), 2)), calibration_repeats)
        total_controller = controller_work(model, train_rows, calibration_rows,
            calibration_repeats, raw_reward_cached=raw_reward_cached,
            **({"plan": plan} if plan is not None else {}))
        # Keep probe CPU and fit CPU forecasts separate while deriving the
        # authoritative total (including fit/summary/formula extras) once.
        critic = {key: total_controller.get(key, 0) - paired.get(key, 0)
                  for key in total_controller.keys() | paired.keys()}
        if any(value < 0 for value in critic.values()):
            raise ValueError("controller inventory omits reserved paired work")
    return {"service": service, "observer": observation, "critic": critic,
            "paired_calibration": paired, "tail": add_work(service, observation, critic, paired),
            "revalidation": validation_work(model, validation_rows,
                None if plan is None else plan.get("static_modes"))}


def _preparation_forecast(calibration, mode, measures, plan):
    if type(measures) is not int or not 1 <= measures <= 2**63 - 1:
        raise ValueError("bounded positive future preparation count required")
    maximum = calibration["prepare_cpu_ns"][mode]
    if (type(maximum) not in (int, float) or not 0 <= maximum <= 2**63 - 1
            or not math.isfinite(maximum)):
        raise ValueError("finite nonnegative observed preparation CPU required")
    policy = plan.get("preparation_forecast")
    if "preparation_forecast" not in plan:
        return {"preparation_forecast": "legacy-repeated-maximum",
                "prepare_cpu_samples_ns": calibration.get("prepare_cpu_samples_ns", {}).get(mode),
                "prepare_cpu_median_ns": None, "prepare_cpu_max_ns": maximum,
                "prepare_cpu_observed_excess_ns": None,
                "prepare_cpu_forecast_ns": measures * maximum}
    if policy != "median-plus-one-observed-excess-v1":
        raise ValueError("unknown preparation forecast policy")
    if type(plan["calibration_repeats"]) is not int or plan["calibration_repeats"] != 3:
        raise ValueError("three TRAIN calibration repeats required by preparation forecast")
    samples = calibration.get("prepare_cpu_samples_ns", {}).get(mode)
    if (not isinstance(samples, (tuple, list)) or len(samples) != 3
            or any(type(value) is not int or not 0 <= value <= 2**63 - 1 for value in samples)):
        raise ValueError("exactly three bounded TRAIN preparation CPU samples required")
    ordered = sorted(samples)
    median, observed_max = ordered[1], ordered[2]
    if maximum != observed_max:
        raise ValueError("observed preparation maximum disagrees with TRAIN samples")
    excess = observed_max - median
    return {"preparation_forecast": policy, "prepare_cpu_samples_ns": list(samples),
            "prepare_cpu_median_ns": median, "prepare_cpu_max_ns": observed_max,
            "prepare_cpu_observed_excess_ns": excess,
            "prepare_cpu_forecast_ns": measures * median + excess}


def forecast(system, selected, candidates, common, plan, inventories, ledger):
    """Retain every training-only input used by the residual scheduler."""
    uses_actual_units = "adaptation_kernel" in plan
    if uses_actual_units and plan["adaptation_kernel"] != "folded-mixed-encoder-v1":
        raise ValueError("unsupported adaptation kernel")
    if not selected or len({row["seed"] for row in selected}) != len(selected):
        raise ValueError("one selected model per seed required")
    if not candidates or any(type(row["updates"]) is not int or row["updates"] <= 0
            or type(row["candidate_step_units"]) is not int or row["candidate_step_units"] <= 0
            or not math.isfinite(row["objective_step_cpu_seconds"])
            or row["objective_step_cpu_seconds"] <= 0 for row in candidates):
        raise ValueError("complete positive training counters required")
    if uses_actual_units and any(type(row.get("objective_step_units")) is not int
            or not 0 < row["objective_step_units"] <= row["updates"] * row["candidate_step_units"]
            for row in candidates):
        raise ValueError("bounded positive actual objective-step units required")
    unit_rates = [row["objective_step_cpu_seconds"] / (
        row["objective_step_units"] if uses_actual_units else row["updates"] * row["candidate_step_units"])
        for row in candidates]
    if not unit_rates or any(not math.isfinite(v) or v <= 0 for v in unit_rates):
        raise ValueError("positive observed training CPU/unit rates required")
    unit_rate = max(unit_rates)
    serialization = max(row["serialization_cpu_seconds"] for row in candidates)
    safety = plan["refinement_cpu_unit_safety"]
    multiplier = plan["refinement_service_cpu_multiplier"]
    if safety < 1 or multiplier <= 0 or not math.isfinite(safety + multiplier):
        raise ValueError("finite conservative arithmetic and service factors required")
    n = len(selected)
    priced = {key: n * ledger.estimate_kernel(**work) for key, work in inventories.items()}
    profiles, service_cpu, preparation_cpu = [], 0.0, 0.0
    val_rows = plan["data_profile"]["sources_per_class"]["validation"] * 12 * (
        plan["data_profile"]["instructions_per_source"] * plan["data_profile"]["variants"])
    for row in selected:
        calibration = common["calibrations"][row["seed"]]
        modes = plan["static_modes"] if system == "ndu_control" else [row["mode"]]
        mode = max(modes, key=lambda name: calibration["cpu_ns"][name])
        requests = val_rows * (2 if system == "ndu_control" else 1)
        measures = 2 if system == "ndu_control" else 1
        if system == "ndu_control":
            requests += 2 * plan["calibration_rows"] * plan["calibration_repeats"]
            measures += 2 * plan["calibration_repeats"]
        cpu_ns = calibration["cpu_ns"][mode]
        preparation = _preparation_forecast(calibration, mode, measures, plan)
        profiles.append({"seed": row["seed"], "mode": mode, "requests": requests,
            "cpu_ns_per_request": cpu_ns,
            "prepare_cpu_ns_per_measure": calibration["prepare_cpu_ns"][mode],
            "measures": measures, **preparation})
        service_cpu += requests * cpu_ns * multiplier / 1e9
        preparation_cpu += preparation["prepare_cpu_forecast_ns"] * multiplier / 1e9
    # The external observers are outside service probes and must be forecast
    # separately together with critic training and changed-model validation.
    arithmetic_cpu = safety * unit_rate * (priced["critic"] + priced["observer"])
    changed_cpu = safety * unit_rate * priced["revalidation"] + n * serialization
    floor = plan["tail_reserve_cpu_seconds"] + (
        plan["control_reserve_cpu_seconds"] if system == "ndu_control" else 0)
    tail_cpu = max(floor, service_cpu + preparation_cpu + arithmetic_cpu)
    return {"policy": "selected-residual-v1", "system": system,
        "cpu_cap": plan["cpu_seconds_per_system"], "tail_units": priced["tail"],
        "changed_model_units": priced["revalidation"], "tail_cpu_seconds": tail_cpu,
        "changed_model_cpu_seconds": changed_cpu, "training_cpu_per_unit_max": unit_rate,
        "training_cpu_per_unit_samples": unit_rates, "serialization_cpu_seconds_max": serialization,
        "training_rate_inputs": [{key: row[key] for key in ("name", "updates",
            "candidate_step_units", "objective_step_cpu_seconds")
            + (("objective_step_units",) if uses_actual_units else ())} for row in candidates],
        **({"training_rate_unit_basis": "objective-step-ledger-deltas-v1"} if uses_actual_units else {}),
        "arithmetic_safety": safety, "service_multiplier": multiplier,
        "tail_cpu_floor": floor, "service_profiles": profiles,
        "service_cpu_seconds": service_cpu, "preparation_cpu_seconds": preparation_cpu,
        "arithmetic_cpu_seconds": arithmetic_cpu, "inventory_units": priced,
        "inventories_per_selected_model": inventories,
        "forecast_scope": "training-only scheduling estimate; actual caps remain authoritative"}


def admit_round(receipt, ledger, cpu_seconds, step_units, *, guard_seconds):
    """Admit a complete seed round plus one final changed-model validation."""
    if (type(step_units) is not int or step_units <= 0
            or not math.isfinite(cpu_seconds) or cpu_seconds < 0
            or not math.isfinite(guard_seconds) or guard_seconds < 0):
        raise ValueError("positive round work and finite nonnegative CPU/guard required")
    return (ledger.remaining_units >= receipt["tail_units"] + receipt["changed_model_units"] + step_units
        and cpu_seconds + receipt["tail_cpu_seconds"] + receipt["changed_model_cpu_seconds"]
        + max(guard_seconds, receipt["arithmetic_safety"] * step_units
              * receipt["training_cpu_per_unit_max"]) <= receipt["cpu_cap"])
