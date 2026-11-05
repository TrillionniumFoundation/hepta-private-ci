"""Artificial registration for protocol fixtures only; no measured future cohort."""

from admission import digest
from cohort import INFORMATION


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
