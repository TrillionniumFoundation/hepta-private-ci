"""TRAIN-only executable adapter controls; no fitted quality or TEST evaluation."""

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from experiments.hcsn_v7_support_20261101.content_interface.content_interface import Modality
from experiments.hcsn_v8_execution_20261101.scheduler.execution import ReadResult
from experiments.hcsn_v8_execution_20261101.scheduler.planning import Plan, Read, Wait
from ..joint_core.campaign import configure
from ..joint_core.data import Normalization, dataset, legacy_data
from ..joint_core.model import Model
from .runtime import ValueNet, VALUE_WIDTH, episode, feature


class FailedService:
    mode = "Explicit failed mandatory-request contract fixture"

    def __init__(self, *args):
        pass

    def request(self, step, clock):
        return self

    def wait_until(self, deadline, clock):
        return ReadResult(error="declared control failure")


class TimedOutService(FailedService):
    mode = "Explicit late mandatory-request contract fixture"

    def wait_until(self, deadline, clock):
        clock.wait_until(deadline)
        return None

    def drain(self, clock):
        clock.wait_until(5.)


def check(out):
    out.mkdir(parents=True, exist_ok=False)
    count = 0

    def require(ok):
        nonlocal count
        count += 1
        if not bool(ok):
            raise AssertionError("New-head adapter contract " + str(count))

    raw, _, _, orders, identity = dataset("async_av", "train")
    norm = Normalization.fit(raw.numpy())
    data = legacy_data("async_av", "train")
    public = {key: data[key] for key in ("x", "valid", "observed", "relative_times")}
    torch.manual_seed(139901)
    model = Model("hx_full", 6).eval()
    with torch.no_grad():
        model.asset_drive.weight.zero_(); model.asset_drive.bias.fill_(-10.)
    metadata = {"head_id": "v13-contract-new-head", "train_prior": [1/6]*6,
        "stop_calibration": {"rates": [.9]*5}, "future_calibration": {"rates": [.1]*5},
        "value_mean": [0.]*VALUE_WIDTH, "value_scale": [1.]*VALUE_WIDTH}
    candidate = model, norm, ValueNet().eval(), metadata
    fixed, updates = episode(candidate, public, 0, "fixed")
    require(fixed["requested_observations"] == 6 and len(updates) == 6)
    require([x["global_source_increment"] for x in updates] == [1, 0, 1, 0, 1, 0])
    order = ["audio", "video", "audio", "video", "audio", "video"]
    selected = next(i for i, sequence in enumerate(orders[:10]) if sequence == order)
    with torch.no_grad():
        direct, events = model(norm.apply(raw[selected:selected+1]), return_events=True)
        direct_p = torch.softmax(direct, -1).numpy()[0]
    for index, update in enumerate(updates):
        require(np.array_equal(norm.apply(raw[selected, index]).numpy(), np.asarray(update["model_row"])))
        require(np.allclose(direct_p[index], update["probabilities"], rtol=0, atol=1e-15))
        for event in ("reset", "restored"):
            require(events[index][event].tolist() == update["event"][event])
    require(all(updates[0]["event"]["reset"][0]))
    require(updates[1]["state"] == updates[0]["state"])
    require(all(updates[2]["event"]["restored"][0]))
    poisoned = {key: value.copy() for key, value in public.items()}
    future = poisoned["relative_times"] > 1
    poisoned["x"][future, :16] = np.nan
    clean, clean_updates = episode(candidate, public, 0, "value")
    contaminated, contaminated_updates = episode(candidate, poisoned, 0, "value")
    require(clean == contaminated and clean_updates == contaminated_updates)
    require(clean["requested_observations"] == 1)
    failed, accepted = episode(candidate, public, 0, "value", FailedService)
    require(failed["requested_observations"] == 1 and failed["observation_fee"] == .02 and not accepted)
    require(failed["output"]["probabilities"] == tuple(metadata["train_prior"]))
    timeout, accepted = episode(candidate, public, 0, "value", TimedOutService)
    require(timeout["requested_observations"] == 1 and timeout["observation_fee"] == .02 and not accepted)
    require(timeout["output_elapsed_seconds"] == 4. and timeout["post_drain_elapsed_seconds"] == 5.)
    require(timeout["late_drains"][0]["status"] == "discarded_after_output_attempt")
    rows, p = [updates[0]["model_row"]], updates[0]["probabilities"]
    a, v = Read(Modality.AUDIO, 2), Read(Modality.VIDEO, 2)
    require(not np.array_equal(feature(rows, p, Plan((a, v))), feature(rows, p, Plan((v, a)))))
    require(np.array_equal(feature(rows, p, Plan((a,))), feature(rows, p, Plan((Wait(.25), a)))))
    result = {"schema": "hcsn-v13-new-head-adapter-controls.v1", "checks": count, "all_checks_passed": True,
        "source_training_identity": identity, "real_joint_updates": len(updates), "test_or_val_opened": False,
        "scope": "Untrained actual HX content model and explicit execution fixtures only; not quality, trained calibration or scientific confirmation"}
    (out / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); configure(); check(args.out)
