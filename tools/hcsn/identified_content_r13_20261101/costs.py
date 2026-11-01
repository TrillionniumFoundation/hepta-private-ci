"""Predeclared CPU ledgers; distinct scientific, search and deployment questions."""

import json
from pathlib import Path

from contract import PROTOCOL


def fit_costs(folder, seed):
    folder = Path(folder)
    costs = {core: json.loads((folder/'receipts'/f'{seed}_{core}.json').read_text())
             ['whole_process_cpu_seconds'] for core in PROTOCOL['cores']}
    frontend = json.loads((folder/'frontend_receipt.json').read_text())['whole_process_cpu_seconds']
    return costs, frontend


def attach_cost(result, core, selected, costs, frontend, count, world_preparation_cpu,
                service_setup_cpu=0.0):
    calibration = costs['hx_distribution']
    own = costs[core] if core in costs else 0.0
    # Both analytic and generic filters use the one already-calibrated shared model.
    unique_fit = calibration + (own if core in PROTOCOL['cores'][1:] else 0.0) + frontend + service_setup_cpu
    ordinary_search = sum(costs[n] for n in PROTOCOL['cores'][1:])
    # All candidate fits are reported; no discarded SSM disappears from the ledger.
    model_search = calibration + ordinary_search + frontend + service_setup_cpu
    runtime = result['inference_cpu_seconds'] + world_preparation_cpu
    amortization = PROTOCOL['training_amortization_episodes']
    result.update(full_process_own_fit_cpu_seconds=own,
        shared_calibration_cpu_seconds=calibration, frontend_fit_cpu_seconds=frontend,
        unique_fit_cpu_seconds=unique_fit, all_candidate_search_cpu_seconds=model_search,
        world_preparation_cpu_seconds=world_preparation_cpu,
        service_setup_cpu_seconds=service_setup_cpu,
        runtime_cpu_per_episode=runtime/count,
        unique_amortized_cpu_per_episode=runtime/count+unique_fit/amortization,
        # Additional experiment-search ledger includes the same work for every arm; primary unique deployment cost is separately explicit.
        total_search_amortized_cpu_per_episode=runtime/count+model_search/amortization,
        equal_calibration_charge_cpu_per_episode=runtime/count+(own+calibration+frontend+service_setup_cpu)/amortization,
        cost_scope='Full child CPU for fit/imports/data/serialization; frontend; common model search; world construction; actual read/encode/recovery; native create/cache/build online; inference and controller. Offline compiler/build/benchmark and evaluation orchestration reported globally, not hidden in per-episode measurements.')
