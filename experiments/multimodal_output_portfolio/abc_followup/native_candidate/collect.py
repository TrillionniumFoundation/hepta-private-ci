"""Commit all three heads and both actions before drawing any actual future."""

import argparse
import gzip
import json
from pathlib import Path
import time

import numpy as np
import torch

from ...abc_recovery.runtime import initialize, transition, public_frame, public_digest
from ...abc_recovery.training_run import file_sha, write_json
from ...v6.data import render_tokens
from ...v6.observer import observe_tensors, read_bundle, write_bundle
from ...v7.data import make_batch
from ...v7.evaluation import load_reward
from ...v7.snapshot import Snapshot
from ..native.collect import durable_array
from ..native.forecast import ACTIONS, emitted_state, public_input
from .protocol import forecasts, heads, segments, verify
from .source_guard import materialize, register_access


def collect(protocol):
    spec = verify(protocol)
    output = Path(spec["output"])
    register_access(protocol, output)
    (output / "commits").mkdir()
    torch.set_num_threads(1)
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    corpus = materialize(Path(spec["paths"]["cache"]), protocol, output)
    generator = Snapshot.load(spec["paths"]["generator"],
        expected_file_sha256=spec["file_pins"]["generator"])._model
    observer, _ = load_reward(Path(spec["paths"]["observer"]), spec["file_pins"]["observer"])
    models, calibration = heads(spec)
    keys = ("x_q24", "past_q24", "future_q24", "future_tokens", "y", "pair", "action", "ood", "view",
            "forecast", "raw_probability", "calibrated_probability", "calibration_group")
    arrays = {key: [] for key in keys}; rows = []
    for view, offset, count in segments():
        for begin in range(offset, offset + count, 32):
            size = min(32, offset + count - begin); seed = spec["seed"] + begin
            batch = make_batch(corpus, spec["source_role"], size, seed, view=view, offset=begin)
            rng = torch.Generator().manual_seed(seed + 1000000)
            with torch.inference_mode():
                prefix = initialize(generator, batch.observation, generator=rng)
                prefix = transition(generator, prefix, "refine_image", generator=rng)
                frame = public_frame(prefix); past = emitted_state(generator, frame)
                parent = public_digest(frame); pending = []
                for action_index, action in enumerate(ACTIONS):
                    x = public_input(generator, frame, batch.observation, action)
                    predicted = forecasts(models, calibration, x)
                    name = f"{begin:04d}-{action}.npz"
                    digest = durable_array(output / "commits" / name, x_q24=x, past_q24=past, **predicted)
                    committed = time.time_ns()
                    pending.append((action_index, action, x, predicted, name, digest, committed))
                # Both branch files contain all three heads, fsynced before any future RNG draw.
                for action_index, action, x, predicted, name, digest, committed in pending:
                    started = time.time_ns()
                    future = transition(generator, prefix, action, generator=torch.Generator().manual_seed(
                        seed + 2000000 + action_index * 3000000))
                    state = emitted_state(generator, public_frame(future)); finished = time.time_ns()
                    pixels, captions, identities = [], [], []
                    for i in range(size):
                        media = write_bundle(output / "media" / f"{begin+i:04d}-{action}",
                            render_tokens(future.tokens[i]), future.pixels[i])
                        image, caption, identity = read_bundle(media)
                        if not torch.equal(image[0], future.pixels[i]) or caption != render_tokens(future.tokens[i]):
                            raise ValueError("Reopened media differs from actual generated output")
                        pixels.append(image[0]); captions.append(caption); identities.append(identity)
                    scored = observe_tensors(observer, torch.stack(pixels), captions,
                                             batch.target.pixels, batch.target.labels)
                    labels = [int(s["caption_valid"] and all(s[k] == 0 for k in
                        ("text_fact", "relation", "image_fact", "crossmodal_disagreement"))) for s in scored]
                    for key, value in {"x_q24": x, "past_q24": past, "future_q24": state,
                        "future_tokens": future.tokens.numpy(), "y": labels, "pair": range(begin, begin+size),
                        "action": [action_index]*size, "ood": [view=="both_missing"]*size,
                        "view": [view]*size, **predicted}.items():
                        arrays[key].append(np.asarray(value))
                    for i, score in enumerate(scored):
                        rows.append({"pair": begin+i, "source_ids": batch.source_ids[i], "action": action,
                            "view": view, "joint_correct": labels[i], "scores": score, "media": identities[i],
                            "commit_file": name, "commit_sha256": digest, "commit_unix_ns": committed,
                            "transition_started_unix_ns": started, "generation_finished_unix_ns": finished,
                            "prefix_public_digest": parent, "forecast_used_current_outcome": False})
            print(json.dumps({"pairs_completed": len(rows)//2, "view": view}), flush=True)
    durable_array(output / "data.npz", **{key: np.concatenate(value) for key, value in arrays.items()})
    with gzip.open(output / "rows.jsonl.gz", "wt") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    verify(protocol)
    write_json(output / "cost.json", {"protocol_sha256": file_sha(protocol),
        "source_pairs": len(rows)//2, "future_rows": len(rows), "model_predictions": len(rows)*3,
        "data_sha256": file_sha(output / "data.npz"), "rows_sha256": file_sha(output / "rows.jsonl.gz"),
        "wall_ns": time.perf_counter_ns()-began, "cpu_ns": time.process_time_ns()-cpu,
        "new_project_independent_source_pairs": 0,
        "scope": "source loading, actual prefix, six forecasts per pair committed, two real future branches, media readback and independent scoring; fixed predictor comparison without generator update"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    collect(parser.parse_args().protocol)
