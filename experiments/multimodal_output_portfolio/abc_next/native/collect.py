"""Execute frozen generator and reopen emitted media before offline labeling."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np
import torch

from ...abc_recovery.runtime import initialize, transition, public_frame, work_counts
from ...abc_recovery.training_run import file_sha, write_json
from ...v6.data import render_tokens
from ...v6.observer import observe_tensors, read_bundle, write_bundle
from ...v7.data import make_batch
from ...v7.evaluation import load_reward
from ...v7.snapshot import Snapshot
from ...v7.sources import load_roles
from .features import FEATURE_DIM, features


VIEWS = ("clean", "noise", "occlusion", "missing_trusted", "conflict_untrusted")


def segments(role):
    if role == "train":
        return ([("fit", v, 600 * i, 600) for i, v in enumerate(VIEWS)]
                + [("fit", "both_missing", 3000, 1000)]
                + [("development", v, 4000 + 200 * i, 200) for i, v in enumerate(VIEWS)]
                + [("development", "both_missing", 5000, 1000)])
    if role not in {"neuron_calibration", "neuron_verification"}:
        raise ValueError("Unregistered source role")
    return ([(role, v, 160 * i, 160) for i, v in enumerate(VIEWS)]
            + [(role, "both_missing", 800, 800)])


def collect(protocol, role, output, prerequisite=None):
    spec = json.loads(protocol.read_text())
    if role != "train":
        if prerequisite is None:
            raise ValueError("A prospective predictor freeze is required before reserved source access")
        frozen = json.loads(prerequisite.read_text())
        expected_phase = "predictor-frozen" if role == "neuron_calibration" else "calibrator-frozen"
        if frozen["phase"] != expected_phase or frozen["protocol_sha256"] != file_sha(protocol):
            raise ValueError("Wrong qualification barrier")
        for name, pin in frozen["files"].items():
            if file_sha(prerequisite.parent / name) != pin:
                raise ValueError("Frozen predictor/calibrator changed")
    output.mkdir(parents=True, exist_ok=False)
    paths = {k: Path(v) for k, v in spec["paths"].items()}
    for key, pin in spec["input_sha256"].items():
        if file_sha(paths[key]) != pin:
            raise ValueError("Registered source/model/observer changed")
    write_json(output / "access-registration.json", {
        "role": role, "opened_unix_ns": time.time_ns(), "protocol_sha256": file_sha(protocol),
        "prerequisite_sha256": file_sha(prerequisite) if prerequisite else None,
        "segments": segments(role), "rows_per_source_pair": 1,
        "source_identity_sha256": spec["source_roles"][role],
    })
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    torch.set_num_threads(1)
    corpus = load_roles(paths["cache"], paths["manifest"], roles=(role,))
    snapshot = Snapshot.load(paths["model"], expected_file_sha256=spec["input_sha256"]["model"])
    model = snapshot._model
    observer, _ = load_reward(paths["observer"], spec["input_sha256"]["observer"])
    xs, ys, groups, rows, timings = [], [], [], [], []
    for group, view, offset, count in segments(role):
        for start_pair in range(offset, offset + count, 32):
            size = min(32, offset + count - start_pair)
            seed = spec["seed"] + start_pair + (0 if role == "train" else
                         100000 if role == "neuron_calibration" else 200000)
            batch = make_batch(corpus, role, size, seed, view=view, offset=start_pair)
            rng = torch.Generator().manual_seed(seed + 1000000)
            begin = time.perf_counter_ns()
            with torch.inference_mode():
                run = initialize(model, batch.observation, generator=rng)
                for action in spec["continuation_actions"]:
                    run = transition(model, run, action, generator=rng)
                after_generation = time.perf_counter_ns()
                x = features(model, public_frame(run), batch.observation)
                after_features = time.perf_counter_ns()
            reopened, captions, media_hashes = [], [], []
            for i in range(size):
                media = write_bundle(output / "media" / f"{start_pair+i:04d}",
                                     render_tokens(run.tokens[i]), run.pixels[i])
                pixels, caption, hashes = read_bundle(media)
                reopened.append(pixels[0]); captions.append(caption); media_hashes.append(hashes)
            scored = observe_tensors(observer, torch.stack(reopened), captions,
                                     batch.target.pixels, batch.target.labels)
            y = [int(s["caption_valid"] and all(s[k] == 0 for k in
                     ("text_fact", "relation", "image_fact", "crossmodal_disagreement"))) for s in scored]
            x = x.double().numpy()
            xq = np.where(x >= 0, np.floor(x * 2**24 + .5), np.ceil(x * 2**24 - .5)).astype(np.int64)
            xs.append(xq); ys.extend(y); groups.extend([group] * size)
            timings.append({"pair_start": start_pair, "batch_size": size,
                "generation_wall_ns": after_generation-begin,
                "public_feature_wall_ns": after_features-after_generation,
                "batch_throughput_not_single_request_latency": True, "work": work_counts(run)})
            for i, s in enumerate(scored):
                rows.append({"pair": start_pair+i, "group": group, "view": view,
                    "source_ids": batch.source_ids[i], "joint_correct": y[i],
                    "feature_sha256": hashlib.sha256(xq[i].tobytes()).hexdigest(),
                    "raw_sha256": media_hashes[i], "is_declared_ood": view == "both_missing", **s})
            print(json.dumps({"role":role,"view":view,"completed_pairs":len(rows)}),flush=True)
    np.savez_compressed(output / "features.npz", x_q24=np.concatenate(xs),
                        y=np.asarray(ys,dtype=np.int64), group=np.asarray(groups))
    with gzip.open(output / "rows.jsonl.gz", "wt") as f:
        for row in rows: f.write(json.dumps(row,sort_keys=True)+"\n")
    write_json(output / "cost.json", {"wall_ns":time.perf_counter_ns()-start,
        "cpu_ns":time.process_time_ns()-cpu,"peak_rss_bytes":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        "measured_scope":"data loading, generator, public features, emitted media, independent observer, row persistence",
        "timings":timings,"role":role,"rows":len(rows),"feature_dim":FEATURE_DIM,
        "features_sha256":file_sha(output / "features.npz"),"rows_sha256":file_sha(output / "rows.jsonl.gz")})


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol",type=Path,required=True)
    parser.add_argument("--role",required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--prerequisite",type=Path)
    args=parser.parse_args(); collect(args.protocol,args.role,args.output,args.prerequisite)
