"""Frozen-fit legacy parity, immutable input values and unchanged rejection predicates."""

import gzip
import json
from pathlib import Path
import tempfile
import time

import numpy as np

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.world import make_episode
from ..planner_fastpath_r18_20261101.planner import BatchedPlanner, KernelCache
from ..support_retention_r16_20261101.compression import BlockLaw
from ..support_retention_r16_20261101.execution import execute as legacy
from .campaign import save
from .execution import execute
from .planner import BatchOwnedPlanner

HERE = Path(__file__).resolve().parent


def run(output):
    started = time.process_time()
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    owner, values, executions, controls = Law(), [], [], []
    for fit in protocol["fits"]:
        models = json.loads(gzip.decompress((HERE.parent / f"addressed_decision_r15_20261101/run_01/training/{fit}.json.gz").read_bytes()))["calibration"]["models"]
        for model in protocol["models"]:
            law = BlockLaw.from_payload(models[model]["payload"])
            for representation in protocol["representations"]:
                projection = "block" if representation == "anchored" else "full"
                for dt in (.25, .35, .5, .65, .75, .95):
                    rng = np.random.default_rng([fit, 200001, int(100 * dt)])
                    for fee in (0., .025):
                        old = BatchedPlanner(law, dt, fee, 2 * fee, projection=projection, anchored=representation == "anchored")
                        new = BatchOwnedPlanner(law, dt, fee, 2 * fee, projection=projection, anchored=representation == "anchored")
                        for belief in (law.prior.copy(), rng.dirichlet(np.ones(40))):
                            belief.setflags(write=False)
                            before = belief.tobytes()
                            for remaining in range(4):
                                a, b = old.values(belief, remaining), new.values(belief, remaining)
                                assert a == b and belief.tobytes() == before
                                values.append(dict(fit=fit, model=model, representation=representation,
                                                   dt=dt, fee=fee, remaining=remaining, values=a))
                with tempfile.TemporaryDirectory(prefix="r20-legacy-parity-") as directory:
                    for domain_index, domain in enumerate(("iid", "ood")):
                        episode = make_episode(owner, 200008 * 10**10 + fit * 10**4 + domain_index, domain)
                        reference = legacy(BlockLaw.from_payload(models[model]["payload"]), episode,
                                           representation=representation)
                        for variant in ("baseline", "r20"):
                            actual = execute(BlockLaw.from_payload(models[model]["payload"]), episode, variant,
                                             representation, Path(directory) / (variant + ".json"), KernelCache())
                            fields = ("seed", "world", "representation", "utility", "reward", "fee", "queries", "belief_evaluations")
                            assert all(reference[k] == actual[k] for k in fields)
                            executions.append(dict(fit=fit, model=model, representation=representation,
                                                   domain=domain, variant=variant, exact=True))
    law = BlockLaw.from_payload(models["hx"]["payload"])
    for projection in ("full", "block"):
        planners = [BatchedPlanner(law, .5, projection=projection), BatchOwnedPlanner(law, .5, projection=projection)]
        for count in (1, 3):
            for kind in ("finite", "nan", "inf", "negative", "mass", "width", "tiny_negative"):
                p = law.prior.copy()
                if kind == "nan": p[0] = np.nan
                if kind == "inf": p[0] = np.inf
                if kind == "negative": p[0] = -.01
                if kind == "tiny_negative": p[0] = -1e-14; p[1] += 1e-14
                if kind == "mass": p *= .99
                if kind == "width": p = p[:-1]
                outcomes = []
                for planner in planners:
                    try:
                        result = planner._project_many([p.reshape(1, -1) for _ in range(count)])
                        outcomes.append([a.tolist() for a in result])
                    except ValueError:
                        outcomes.append("ValueError")
                assert outcomes[0] == outcomes[1]
                controls.append(dict(projection=projection, frames=count, kind=kind,
                                     accepted=outcomes[0] != "ValueError"))
    save(output, dict(passed=True, values=values, legacy_executions=executions, controls=controls,
                      value_case_count=len(values), legacy_case_count=len(executions), control_count=len(controls),
                      measured_body_cpu_seconds=time.process_time() - started,
                      scope="Development exact legacy/differential checks across8frozenfits; not continuumproof or newefficacyconfirmation"))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)
