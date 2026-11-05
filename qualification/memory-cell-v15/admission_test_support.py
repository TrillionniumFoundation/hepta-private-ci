"""Artificial registration for protocol fixtures only; no measured future cohort."""

from dataclasses import replace

from admission import COSTS, digest
from cohort import INFORMATION


def fixture_cost_protocol(protocol):
    """Explicit artificial prices/caps for controls, never a device cost model."""
    prices = protocol.prices or (("train_cpu_s", 1.0),)
    positive = {name for name, value in prices if value > 0}
    return replace(protocol, prices=prices,
                   limits=(("serve_cpu_s", 32.0), ("peak_rss_bytes", 256 * 1024 * 1024)),
                   zero_cost_reasons=tuple((name, "Synthetic control: resource recorded without economic weight")
                                           for name in COSTS if name not in positive),
                   workload_digest=digest({"fixture": protocol.identity,
                                           "uniform_source_clusters": True,
                                           "horizon_reads": protocol.expected_reads}))


def fixture_ledger(evaluator, model):
    """Conservative synthetic worker allowance, not a measured production bill."""
    resources = dict.fromkeys(COSTS, 0.0)
    resources.update(serve_cpu_s=10.0, peak_rss_bytes=128 * 1024 * 1024)
    return dict(evaluator.cost_binding(model), all_searches_and_failures_included=True,
                synthetic_control_costs=True, resources=resources)


def fixture_registration(cases, protocol, candidate, incumbent):
    return {"schema": "hepta.memory.frozen-cohort.v1", "frozen_at": 4, "look_index": 1,
            "data": digest([vars(case) for case in cases]),
            "protocol_settings": digest(vars(protocol)),
            "phases": {"train": {"start": 0, "end": 1, "clusters": ["fixture-train"]},
                       "calibration": {"start": 2, "end": 2, "clusters": ["fixture-calibration"]},
                       "selection": {"start": 3, "end": 3, "clusters": ["fixture-selection"]},
                       "final": {"start": 5, "end": 5,
                                 "clusters": sorted({case.cluster for case in cases})}},
            "final_units": {case.key: {"unit": case.key, "cluster": case.cluster, "observed_at": 5}
                            for case in cases},
            "comparisons": [[candidate.bundle, incumbent.bundle]],
            "arms": {run.bundle: {key: getattr(run, key) for key in INFORMATION}
                     for run in (candidate, incumbent)}}
