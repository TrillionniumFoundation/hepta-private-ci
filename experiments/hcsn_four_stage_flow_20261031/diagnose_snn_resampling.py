"""Post-hoc FP32/FP64 diagnosis of one frozen SNN resampling failure.

No training, selection, new data, or replacement of the formal FP32 result.
Read-only hooks reconstruct threshold inputs without changing forward values.
"""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from . import runner


def forward_trace(model, data, dtype):
    logits, thresholds = [], []
    with torch.no_grad():
        for start in range(0, len(data["x"]), 64):
            batch = runner.tensors(data, slice(start, start + 64))
            hidden, incoming, recurrent = [], [], []
            hooks = [
                model.read.register_forward_pre_hook(
                    lambda module, inputs: hidden.append(inputs[0][:, :64].detach().clone())),
                model.incoming.register_forward_hook(
                    lambda module, inputs, output: incoming.append(output.detach().clone())),
                model.recurrent.register_forward_hook(
                    lambda module, inputs, output: recurrent.append(output.detach().clone())),
            ]
            try:
                output = model(batch["x"].to(dtype), batch["dt"].to(dtype), batch["observed"])
            finally:
                for hook in hooks:
                    hook.remove()
            margin = (torch.stack(hidden, 1) + torch.stack(incoming, 1)) + torch.stack(recurrent, 1) - 1
            logits.append(output.numpy())
            thresholds.append(margin.numpy())
    return np.concatenate(logits), np.concatenate(thresholds)


def comparison(base, alternative, labels):
    valid = labels >= 0
    a, b = base.argmax(-1), alternative.argmax(-1)
    return dict(max_logit_difference=float(np.abs(base - alternative).max()),
        max_query_logit_difference=float(np.abs(base - alternative)[valid].max()),
        argmax_changes_all_original_positions=int((a != b).sum()),
        argmax_changes_scored_queries=int(((a != b) & valid).sum()),
        base_accuracy=float((a[valid] == labels[valid]).mean()),
        alternative_accuracy=float((b[valid] == labels[valid]).mean()),
        accuracy_difference=float((b[valid] == labels[valid]).mean() - (a[valid] == labels[valid]).mean()))


def threshold_comparison(base, refined):
    disagreement = (base >= 0) != (refined >= 0)
    positions = np.argwhere(disagreement)
    first = None
    if len(positions):
        # Earliest original token, then episode and unit; preceding event marks
        # in this episode must agree before attributing the first divergence.
        index = np.lexsort((positions[:, 2], positions[:, 0], positions[:, 1]))[0]
        episode, token, unit = map(int, positions[index])
        first = dict(episode=episode, original_token=token, unit=unit,
            base_threshold_margin=float(base[episode, token, unit]),
            refined_threshold_margin=float(refined[episode, token, unit]),
            base_spike=bool(base[episode, token, unit] >= 0),
            refined_spike=bool(refined[episode, token, unit] >= 0),
            prior_spikes_identical=not bool(disagreement[episode, :token].any()))
    return dict(spike_disagreements_at_original_observations=int(disagreement.sum()),
                first_spike_divergence=first)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    started_wall, started_cpu = time.perf_counter(), time.process_time()
    protocol = json.loads((args.run / "PROTOCOL.json").read_text())
    if protocol["source_hashes"] != runner.source_hashes():
        raise ValueError("Frozen core changed")
    folder = args.run / "dynamics__snn__43"
    result = json.loads((folder / "result.json").read_text())
    checkpoint = folder / "checkpoint.pt"
    if (runner.digest(checkpoint) != result["checkpoint_sha256"]
            or runner.digest(folder / "predictions.npz") != result["predictions_sha256"]):
        raise ValueError("Formal checkpoint or predictions changed")
    payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
    if ((payload["task"], payload["arm"], payload["seed"]) != ("dynamics", "snn", 43)
            or payload["protocol_sha256"] != runner.digest(args.run / "PROTOCOL.json")
            or payload["frozen_commit"] != result["frozen_commit"]):
        raise ValueError("Wrong frozen fit")
    base = runner.synthetic("dynamics", 512, 81001, "test", "base")
    refined = runner.synthetic("dynamics", 512, 81001, "test", "resample")
    if (not np.array_equal(refined["y"][:, 1::2], base["y"])
            or not np.array_equal(refined["dt"].sum(1), base["dt"].sum(1))):
        raise ValueError("Resampling did not preserve the registered observations and clocks")
    outputs, precisions = {}, {}
    for name, dtype in (("float32", torch.float32), ("float64", torch.float64)):
        model = runner.new_model("dynamics", "snn")
        model.load_state_dict(payload["model"], strict=True)
        model = model.to(dtype).eval()
        original, margins = forward_trace(model, base, dtype)
        split, split_margins = forward_trace(model, refined, dtype)
        outputs[name] = (original, split[:, 1::2])
        precisions[name] = dict(**comparison(original, split[:, 1::2], base["y"]),
                               **threshold_comparison(margins, split_margins[:, 1::2]))
    with np.load(folder / "predictions.npz", allow_pickle=False) as saved:
        if not np.array_equal(saved["test__base__y"], base["y"]):
            raise ValueError("Regenerated labels differ from the formal evaluation")
        reproduction = dict(base_max_difference=float(np.abs(outputs["float32"][0] - saved["test__base__logits"]).max()),
            refined_max_difference=float(np.abs(outputs["float32"][1] - saved["test__resample__logits"][:, 1::2]).max()))
    roundoff_evidence = (precisions["float32"]["spike_disagreements_at_original_observations"] > 0
                        and precisions["float64"]["spike_disagreements_at_original_observations"] == 0
                        and precisions["float64"]["max_logit_difference"] < 1e-10)
    diagnosis = dict(schema="hcsn-four-stage.posthoc-snn-resampling.v1", post_hoc=True,
        task="dynamics", arm="snn", seed=43, episodes=512, predict_batch_size=64,
        frozen_commit=result["frozen_commit"], checkpoint_sha256=runner.digest(checkpoint),
        script_sha256=runner.digest(__file__), protocol_sha256=runner.digest(args.run / "PROTOCOL.json"),
        original_formal_resampling=result["evaluations"]["test__resample"],
        formal_result_reproduction=reproduction, precisions=precisions,
        base_float32_vs_float64=comparison(outputs["float32"][0], outputs["float64"][0], base["y"]),
        roundoff_amplification_supported=roundoff_evidence,
        conclusion=("For this frozen case, hard thresholds amplify FP32 split-step roundoff; FP64 restores the resampling relation."
                    if roundoff_evidence else "This bounded precision comparison does not isolate the failure as FP32 threshold amplification."),
        interpretation="Post-hoc numerical diagnosis only. The formal FP32 failure remains unchanged; FP64 is not a replacement result or a selected model.",
        unchanged_checkpoint=runner.digest(checkpoint) == result["checkpoint_sha256"],
        wall_seconds=time.perf_counter() - started_wall, cpu_seconds=time.process_time() - started_cpu,
        clock_scope="Diagnostic body after imports", energy_joules=None)
    runner.save_json(args.out / "SNN_RESAMPLING_DIAGNOSIS.json", diagnosis)
    print(json.dumps(diagnosis, sort_keys=True))


if __name__ == "__main__":
    main()
