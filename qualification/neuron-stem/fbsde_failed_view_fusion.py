"""Replay the exact historical failed view through the frozen two Head kernels.

This is Head-only CPU research, not an FBSDE solver or a retry of the rejected
original action. Read the original public source and original VIEW 0, verify
the complete attempt hash chain, rebuild the *same* 384-d raw encoder vector,
then use the saved train-only normalizer. No gold labels or policy effects.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import json
import math
from pathlib import Path
import time
from zipfile import ZipFile

ZIP = "cd9997b69e88b88f0817985fca00cb5b359936bcd5589fd49cc2c5ac78cb200a"
EXPECTED_VECTOR_SHA = "ec410720bec0173fe0b631553d7e37925a3b4a647aa059a8e24402697df2eb39"
MAX_CPU_NS = 100_000_000
PREFIX = "acquisition-study/"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def journal_last(raw, *, expected_count, expected_last_sha):
    """Prove the whole source attempt chain, not merely the last JSON line."""
    from four_gate_common import strict_loads, digest
    require(raw.endswith(b"\n") and 1 <= expected_count <= 20000,
            "nonempty complete attempt journal required")
    rows = raw.splitlines()
    require(len(rows) == expected_count, "historical attempt inventory changed")
    previous = None
    last = None
    for i, line in enumerate(rows):
        row = strict_loads(line)
        require(type(row) is dict and "attempt_sha256" in row,
                "invalid typed attempt record")
        identity = row.pop("attempt_sha256")
        require(identity == digest(row) and row.get("previous_sha256") == previous
                and row.get("sequence") == i and row.get("split") == "test",
                "hash chain or attempted request order changed")
        previous, last = identity, row
    require(previous == expected_last_sha and last is not None
            and last.get("status") == "budget_exceeded"
            and last.get("prediction_returned") is False
            and last.get("cpu_ns", 0) > MAX_CPU_NS
            and last.get("head_sha256"), "expected over-budget last request missing")
    return last


def reconstruct_failed_view(source):
    """Read the SHA-pinned ZIP and reconstruct its actual model input, no gold."""
    import torch
    from four_gate_capture import tensor_digest
    from four_gate_common import digest, strict_loads
    from fbsde_acquisition_data import text_view, hashed_reference
    from fbsde_head_fusion_probe import ZIP_SHA256, sha

    path = Path(source)
    require(path.is_file() and not path.is_symlink()
            and 0 < path.stat().st_size < 32 * 1024**2,
            "bounded original archival ZIP required")
    archive_bytes = path.read_bytes()
    require(sha(archive_bytes) == ZIP_SHA256 == ZIP,
            "historical source ZIP is not exactly pinned")
    with ZipFile(BytesIO(archive_bytes)) as package:
        require(package.testzip() is None, "original ZIP CRC changed")
        def read(name):
            matches = [v for v in package.infolist() if v.filename == PREFIX + name]
            require(len(matches) == 1 and 0 < matches[0].file_size <= 16*1024**2,
                    "duplicated, oversized or missing historical material")
            return package.read(matches[0])
        failure = strict_loads(read("failure.json"))
        original = journal_last(read("test-view-attempts.jsonl"),
                                expected_count=failure["attempts_in_split"],
                                expected_last_sha=failure["last_attempt_sha256"])
        inventory = strict_loads(read("input-inventory.json"))
        checkpoint = torch.load(BytesIO(read("candidate-head.pt")),
                                map_location="cpu", weights_only=True)
    require(type(inventory) is dict and type(inventory.get("test")) is list,
            "complete original test source inventory required")
    matches = [v for v in inventory["test"] if v.get("id") == original["id"]]
    require(len(matches) == 1 and type(matches[0].get("text")) is str,
            "missing/duplicated original rejected input")
    item = matches[0]
    require(digest(item["text"]) == item["text_sha256"] ==
            original["source_input_sha256"] and original["view"] == 0,
            "original rejected task source drift")
    rendered = text_view(item["text"], original["view"])
    require(digest(rendered) == original["text_sha256"],
            "original exact view differs")
    raw = hashed_reference([rendered], torch)
    require(raw.shape == (1,384) and raw.dtype == torch.float32 and
            tensor_digest(raw) == EXPECTED_VECTOR_SHA,
            "reconstructed 384d frozen input differs from verified replay")
    require(type(checkpoint) is dict and set(checkpoint) == {"state","mean","scale"},
            "saved normalizer/model inventory changed")
    mean, scale = checkpoint["mean"], checkpoint["scale"]
    require(mean.shape == scale.shape == (384,) and
            bool(torch.isfinite(mean).all()) and bool(torch.isfinite(scale).all())
            and bool((scale > 0).all()), "invalid frozen normalizer state")
    x = ((raw-mean)/scale).clamp(-8,8).detach().cpu().contiguous()
    require(x.shape == (1,384) and bool(torch.isfinite(x).all()),
            "invalid original failed normalized Head vector")
    return x, {
        "failed_case_id": original["id"],
        "original_failed_cpu_ns": original["cpu_ns"],
        "original_failed_head_cpu_ns": original["phase_cpu_ns"]["head_cpu_ns"],
        "original_failed_attempt_sha256": failure["last_attempt_sha256"],
        "failed_source_text_sha256": original["source_input_sha256"],
        "failed_view_text_sha256": original["text_sha256"],
        "raw_vector_sha256": tensor_digest(raw),
        "normalized_vector_sha256": tensor_digest(x),
        "original_rejected": True, "source_labels_accessed": False,
    }


def quantiles(values):
    require(type(values) is list and len(values) >= 101
            and all(type(x) is int and x >= 0 for x in values),
            "complete measured CPU samples")
    ordered=sorted(values)
    return {f"p{p}": ordered[math.ceil(len(ordered)*p/100)-1]
            for p in (50,95,99)} | {"max": ordered[-1]}


def run(archive, output, *, threads=1, repetitions=513, warmup=20):
    import torch
    from fbsde_head_fusion_probe import original_material, pack_gates, fused_logits
    require(type(threads) is int and threads in (1,2)
            and type(repetitions) is int and 101 <= repetitions <= 4096
            and type(warmup) is int and 1 <= warmup <= 100,
            "registered fixed-work CPU replay required")
    model, identity = original_material(archive)
    x, bound = reconstruct_failed_view(archive)
    require(bound["original_failed_cpu_ns"] > MAX_CPU_NS
            and bound["original_failed_attempt_sha256"] == identity["failed_attempt_sha256"]
            and bound["original_failed_head_cpu_ns"] > 0,
            "wrong historical failure/Head coupling")
    torch.set_num_threads(threads)
    before={k:v.detach().clone() for k,v in model.state_dict().items()}
    with torch.inference_mode():
        packed=pack_gates(model)
        a,b=model(x),fused_logits(model,x,packed)
        difference=float((a-b).abs().max())
        flips=int((a.argmax(-1)!=b.argmax(-1)).sum())
        require(difference<=1e-6 and flips==0,
                "fused execution changes original failed-input logits/decision")
        for _ in range(warmup):
            model(x)
            fused_logits(model,x,packed)
        clocks={name:[] for name in ("original","fused")}
        walls={name:[] for name in clocks}
        for i in range(repetitions):
            order=("original","fused") if i%2==0 else ("fused","original")
            for name in order:
                wc,pc=time.perf_counter_ns(),time.process_time_ns()
                if name=="original":
                    model(x)
                else:
                    fused_logits(model,x,packed)
                clocks[name].append(time.process_time_ns()-pc)
                walls[name].append(time.perf_counter_ns()-wc)
        require(all(torch.equal(v,model.state_dict()[k]) for k,v in before.items()),
                "original historical learned Head mutated")
    report={"schema":"hepta.fbsde.pinned-failed-input-fusion.v1",
        "original_archive_sha256": ZIP, "source":identity, "failed_input":bound,
        "input_source":"exact_failed_view_0_normalized_frozen_hashing_reference",
        "threads":threads, "repetitions":repetitions, "warmup":warmup,
        "maximum_logits_difference":difference,"argmax_flips":flips,
        "cpu_ns":{k:quantiles(v) for k,v in clocks.items()},
        "wall_ns":{k:quantiles(v) for k,v in walls.items()},
        "cpu_attempts_over_original_limit":{k:sum(v>MAX_CPU_NS for v in ls)
                                             for k,ls in clocks.items()},
        "cpu_all_original_samples_retained":True,
        "same_input_repeated_not_independent":True,
        "head_only_not_full_view_cost":True,
        "original_failure_erased":False, "original_result_accepted":False,
        "pretrained_encoder_used":False, "new_training_steps":0,
        "runtime_cause_established":False, "production_promotion_permitted":False}
    output=Path(output)
    output.mkdir(parents=True,exist_ok=False)
    with (output/"report.json").open("x",encoding="utf-8") as out:
        json.dump(report,out,indent=2,sort_keys=True,allow_nan=False)
        out.write("\n")
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive",type=Path,required=True)
    parser.add_argument("--threads",type=int,choices=(1,2),default=1)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=run(args.archive,args.output,threads=args.threads)
    print(json.dumps({"argmax_flips":result["argmax_flips"],
        "cpu_attempts_over_original_limit":result["cpu_attempts_over_original_limit"],
        "original_failure_erased":False},sort_keys=True))


if __name__=="__main__":
    main()
