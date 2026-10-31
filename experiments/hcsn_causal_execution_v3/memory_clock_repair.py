"""Post-diagnostic, frozen clock-cap intervention; no model fit or cap search."""

import argparse
import json
from pathlib import Path
import resource
import time
import types

import numpy as np

from .memory_probe import file_hash, infer, summarize, write_json


DT_CAP = .15
TIME_CAP = 3.2


def capped_clock_encode(common, x, dt, observed):
    """Bound content-only time fields causally; adapter receives untouched dt."""
    import torch
    from experiments.hcsn_mechanism_content_v2.content import positional
    if common.audiovisual:
        raise ValueError("This frozen intervention is restricted to synthetic content")
    content_dt = dt.clamp(max=DT_CAP)
    content_time = dt.cumsum(1).clamp(max=TIME_CAP)
    clock = torch.stack((content_dt, content_time, observed.to(x.dtype)), -1)
    encoded = common.encoder(torch.cat((x, clock), -1))
    index = torch.arange(x.shape[1], dtype=x.dtype, device=x.device)[None]
    return (common.norm(encoded) + .2 * positional(index, common.width)
            + .1 * positional(content_time, common.width))


def prepare(output, memory):
    output.mkdir(parents=True, exist_ok=False)
    original = json.loads((memory / "PROTOCOL.json").read_text())
    checkpoints = [item for item in original["checkpoints"] if item["family"] == "shared"]
    data = [dict(path=str(p), sha256=file_hash(p)) for p in sorted((memory / "data").glob("*.npz"))
            if "_L512_" not in p.name]
    plan = dict(schema="hcsn-memory-clock-intervention.v3", prepared_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                source_path=str(Path(__file__)), source_sha256=file_hash(__file__),
                helper_path=str(Path(__file__).with_name("memory_probe.py")),
                helper_sha256=file_hash(Path(__file__).with_name("memory_probe.py")),
                checkpoints=checkpoints, data=data, memory_root=str(memory),
                original_results_sha256=file_hash(memory / "RESULTS.json"),
                caps=dict(dt=DT_CAP, cumulative_time=TIME_CAP), caps_selected_on_test=False,
                all_prespecified_caps=[dict(dt=DT_CAP, cumulative_time=TIME_CAP)],
                training=False, classification="Post-diagnostic exploratory intervention on previously evaluated inputs",
                intervention="Only common encoder dt, cumulative-time and time positional embedding capped; ordinal position and model weights unchanged",
                causality="Fixed thresholds; prefix cumsum only; no total horizon, future input, labels, or per-example normalization",
                physical_adapter_dt="Untouched; this assay evaluates shared donors with no physical adapter",
                confirmation=False, inferential_test=None)
    write_json(output / "PROTOCOL.json", plan)


def run(output):
    import torch
    from experiments.hcsn_mechanism_content_v2.content import ContentModel
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    plan = json.loads((output / "PROTOCOL.json").read_text())
    if file_hash(plan["source_path"]) != plan["source_sha256"] or file_hash(plan["helper_path"]) != plan["helper_sha256"]:
        raise ValueError("Frozen intervention sources changed")
    for item in plan["data"] + plan["checkpoints"]:
        if file_hash(item["path"]) != item["sha256"]:
            raise ValueError("Frozen input changed")
    memory = Path(plan["memory_root"])
    if file_hash(memory / "RESULTS.json") != plan["original_results_sha256"]:
        raise ValueError("Original results changed")
    originals = json.loads((memory / "RESULTS.json").read_text())["rows"]
    original = {(r["task"], r["seed"], r["length"], r["horizon"]): r for r in originals if r["family"] == "shared"}
    (output / "predictions").mkdir()
    rows = []
    for item in plan["checkpoints"]:
        payload = torch.load(item["path"], map_location="cpu", weights_only=False)
        model = ContentModel(**payload["config"])
        model.load_state_dict(payload["model_state"], strict=True)
        model.eval()
        model.common.encode = types.MethodType(capped_clock_encode, model.common)
        for source in plan["data"]:
            path = Path(source["path"])
            if not path.stem.startswith(item["task"] + "_L"):
                continue
            length = int(path.stem.rsplit("_L", 1)[1].split("_H")[0])
            horizon = float(path.stem.rsplit("_H", 1)[1])
            with np.load(path, allow_pickle=False) as archive:
                data = {name: archive[name] for name in archive.files}
            # Prefix check uses actual observations without reading any future label.
            x, dt = torch.from_numpy(data["x"][:1]), torch.from_numpy(data["dt"][:1])
            with torch.inference_mode():
                full = model.common.encode(x, dt, torch.ones_like(dt, dtype=torch.bool))
                prefix = model.common.encode(x[:, :11], dt[:, :11], torch.ones_like(dt[:, :11], dtype=torch.bool))
                torch.testing.assert_close(full[:, :11], prefix, rtol=0, atol=0)
            probabilities, cost = infer(model, data, disabled=False)
            name = f"{item['job']}_L{length}_H{horizon}_capped.npz"
            np.savez_compressed(output / "predictions" / name, probabilities=probabilities,
                                gold=data["gold"], episode_id=data["episode_id"],
                                checkpoint_sha256=np.asarray(item["sha256"]))
            old = original[(item["task"], item["seed"], length, horizon)]
            result = summarize(probabilities, data["gold"])
            rows.append(dict(task=item["task"], seed=item["seed"], length=length, horizon=horizon,
                             **result, original_exact_recall=old["exact_recall"],
                             exact_recall_delta=result["exact_recall"] - old["exact_recall"],
                             cost=cost, prefix_encode_exact=True, prediction="predictions/" + name))
    write_json(output / "RESULTS.json", dict(rows=rows, protocol_sha256=file_hash(output / "PROTOCOL.json"),
        all_outcomes_reported=True, candidates_tried=1, scope=plan["classification"]))
    usage = resource.getrusage(resource.RUSAGE_SELF)
    write_json(output / "RECEIPT.json", dict(process_cpu_seconds=usage.ru_utime + usage.ru_stime,
        worker_body_cpu_seconds=time.process_time() - start_cpu, worker_body_wall_seconds=time.perf_counter() - start_wall,
        process_maxrss_kib=usage.ru_maxrss, energy_joules=None, host_shared=True,
        training_performed=False, performance_comparison="descriptive only; not isolated benchmark"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--memory", type=Path)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare(args.output, args.memory)
    if args.run:
        run(args.output)
