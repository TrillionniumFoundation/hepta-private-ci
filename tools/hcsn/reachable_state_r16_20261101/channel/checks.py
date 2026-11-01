"""Development-only independent equivalence to the unchanged R15 executor."""

import json
import time
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from ...addressed_decision_r15_20261101.execution import feature_view, run_episode
from ...addressed_decision_r15_20261101.law import Law
from ...addressed_decision_r15_20261101.planner import features
from ...addressed_decision_r15_20261101.world import make_episode
from .campaign import PROTOCOL, inputs
from .execution import execute
from .features import KINDS, actual_features, prepare


def check():
    started = time.process_time()
    rows, maximum_feature_error = [], 0.
    owner = Law()
    for seed in PROTOCOL["fit_seeds"]:
        training, digest = inputs(seed)
        for domain in PROTOCOL["domains"]:
            for index in range(PROTOCOL["development_episodes_per_fit_domain"]):
                sample = 917 * 10**12 + seed * 10**5 + (10000 if domain == "ood" else 0) + index
                world = make_episode(owner, sample, domain)
                for kind in KINDS:
                    law = Law.from_payload(training["calibration"]["models"]["hx"]["payload"])
                    prepared = prepare(law, kind, domain)
                    expected_risk_cache = 3 if kind == "value_risk" else 0
                    if len(law._event_cache) != expected_risk_cache:
                        raise AssertionError("Unused risk cache prepared")
                    learned = training["learned"]["models"][kind]
                    new = execute(law, world, learned)
                    if len(law._event_cache) != expected_risk_cache:
                        raise AssertionError("Unused risk cache created during actual execution")
                    old = run_episode(law, world, policy="learned", learned=learned)
                    for old_query, new_query in zip(old["queries"], new["queries"], strict=True):
                        if old_query != {key: new_query[key] for key in old_query}:
                            raise AssertionError("New one-action owner differs from frozen R15")
                        p = np.asarray(new_query["prefix_checkpoint"]["beliefs"])[new_query["key"]]
                        dt, scale = new_query["dt"], new_query["price_scale"]
                        expected = feature_view(features(law, p, dt, 3, .025 * scale, .07 * scale), kind)
                        error = float(np.max(np.abs(expected - new_query["features"])))
                        maximum_feature_error = max(maximum_feature_error, error)
                        if error != 0:
                            raise AssertionError("Frozen feature values changed")
                        if len(new_query["actions"]) > 1:
                            raise AssertionError("Controller acquired extra action capability")
                    rows.append(dict(seed=seed, domain=domain, world_seed=sample, feature_kind=kind,
                                     training_sha256=digest, risk_matrices=prepared["risk_matrices"],
                                     queries_equal=6, feature_values_bitwise_equal=True))
    class NoExtraChannels:
        def transition(self, dt):
            raise AssertionError("Unneeded STOP-value transition")

        def first_hit(self, p, dt):
            raise AssertionError("Unneeded first-hit risk")

    for kind in ("state_confidence", "ordinary_dual"):
        actual_features(NoExtraChannels(), owner.prior, .5, 3, .025, .07, kind)
    return dict(schema="hcsn-r16-channel-development-equivalence-v1", development_only=True,
                comparisons=rows, arm_episodes=len(rows), query_comparisons=6 * len(rows),
                maximum_feature_error=maximum_feature_error, no_unused_channel_computation=True,
                cpu_seconds=time.process_time() - started,
                scope="No registered namespace17 generation; exact query records/features against R15 under development namespace917.")


if __name__ == "__main__":
    with threadpool_limits(limits=1):
        result = check()
    output = Path(__file__).with_name("DEVELOPMENT_EQUIVALENCE.json")
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("arm_episodes", "query_comparisons", "maximum_feature_error", "cpu_seconds")}))
