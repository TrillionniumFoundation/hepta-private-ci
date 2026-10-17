"""Research CPU path: actual SHA-pinned Granite97 forward + 4096 resident Heads.

Only runnable with the frozen parent Stem source/materials and authentic hosted
weights. Source-only tests use an explicit synthetic callback and never enter
this genuine-pretrained CLI. No training, natural reasoning, promotion or effect.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time

from feature_bus import Borrow, Denied, Scope, SharedFeatureBus, canon
from circuit_ndu import EvidenceCircuit, Fact, Objective

SIZES = (64, 256, 1024, 4096)
WIDTH = 384
PER_HEAD = 6914
ACTIVE = 32
SCHEMA = "hepta.hdsi.granite97-fanout-unattested.v1"


def make_heads(count: int):
    """Actually allocate every Head. The zero-update init is a baseline only."""
    import torch
    if type(count) is not int or count not in SIZES:
        raise Denied("unknown fleet size")
    shape = (count, WIDTH)
    bank = {
        "a": torch.zeros((count, 8, WIDTH), dtype=torch.float32),
        "b": torch.zeros((count, WIDTH, 8), dtype=torch.float32),
        "gate": torch.zeros(shape, dtype=torch.float32),
        "gate_bias": torch.zeros((count,), dtype=torch.float32),
        "out": torch.arange(WIDTH, dtype=torch.float32).repeat(count, 1) * 1e-5,
        "out_bias": torch.arange(count, dtype=torch.float32) * 1e-4,
    }
    scalar_count = sum(t.numel() for t in bank.values())
    if scalar_count != PER_HEAD * count:
        raise Denied("resident cell slots not physically allocated")
    return bank


def head_scores_tensor(bank, x):
    """Differentiable active-Head primitive; inactive parameter slots untouched."""
    import torch
    if x.shape != (ACTIVE, WIDTH) or not torch.isfinite(x).all().item():
        raise Denied("nonfinite or wrong actual model feature")
    a = bank["a"][:ACTIVE]
    b = bank["b"][:ACTIVE]
    h = torch.einsum("bd,brd->br", x, a)
    r = torch.einsum("br,bdr->bd", h, b)
    g = torch.sigmoid((x * bank["gate"][:ACTIVE]).sum(-1)
                      + bank["gate_bias"][:ACTIVE])
    y = x + g.unsqueeze(1) * r / 8.0
    return (y * bank["out"][:ACTIVE]).sum(-1) + bank["out_bias"][:ACTIVE]


def head_scores(bank, feature_rows):
    import torch
    if len(feature_rows) != ACTIVE:
        raise Denied("active head count")
    x = torch.tensor(feature_rows, dtype=torch.float32)
    with torch.no_grad():
        out = head_scores_tensor(bank, x)
    if not torch.isfinite(out).all().item():
        raise Denied("invalid computed Head result")
    return out.detach().cpu().contiguous().numpy().tobytes()


def run_physical(prepared: dict, materials: dict) -> dict:
    # Explicitly import existing original-data/model-owner code, with no
    # replacement download code, unpinned revision or remote-code execution.
    parent = Path(__file__).resolve().parents[1] / "stem-optimal-v1"
    if not (parent / "stem_candidate_v1.py").is_file():
        raise Denied("frozen parent Stem implementation required")
    sys.path.insert(0, str(parent))
    from stem_candidate_v1 import _material_model, _encode, load_materials, verify_prepared

    verify_prepared(prepared)
    manifest = load_materials(parent / "MODEL_MATERIALS.json")
    if materials != manifest:
        raise Denied("model material manifest mismatch")
    spec = manifest["candidates"]["granite97"]
    if spec["weight_sha256"] != "f3ea88b230492811046145513710e76b4cc8c2ad49e8708da0e7247e548903be":
        raise Denied("changed original Granite97 bytes")
    import torch
    torch.set_num_threads(2)
    started, cpu_started = time.perf_counter(), time.process_time()
    tokenizer, model = _material_model(spec)  # verifies weight SHA before any forward
    load_seconds = time.perf_counter() - started
    rows = prepared["heldout"]
    if len(rows) != ACTIVE:
        raise Denied("frozen original public source count")
    scope = Scope("original-public-test", "hdsi-shadow", 1, 0,
                  hashlib.sha256(b"hdsi-study-revocation-unattested").hexdigest(),
                  spec["weight_sha256"], hashlib.sha256(manifest["preprocessing"].encode()).hexdigest())
    out = []
    first_keys = None
    # Four separate cache lifetimes, but ONE warmed model instance. No
    # comparison of four independent process peak RSS or cold starts.
    for count in SIZES:
        produced = {"actual_pretrained_model_batches": 0, "actual_pretrained_model_sequences": 0}
        def batch_encoder(inputs):
            if any(modality != "text" for _, modality in inputs):
                raise Denied("original text-only experiment")
            mat, batches = _encode([payload.decode("utf-8", "strict")
                                    for payload, _ in inputs], tokenizer, model)
            produced["actual_pretrained_model_batches"] += batches
            produced["actual_pretrained_model_sequences"] += len(inputs)
            return [tuple(float(v) for v in vec.tolist()) for vec in mat]

        bus = SharedFeatureBus(WIDTH,
                               lambda _p, _m: (_ for _ in ()).throw(Denied("unbatched path forbidden")),
                               lambda b: b.scope == scope and b.approved_use == "read-only-original",
                               batch_encode=batch_encoder)
        borrowed = [Borrow(scope, "text", rows[i % ACTIVE]["text"].encode(),
                           f"cell:{i}", "read-only-original") for i in range(count)]
        cohort_start, cohort_cpu = time.perf_counter(), time.process_time()
        before_f = bus.physical_calls
        replies = bus.fanout(borrowed)
        encode_end = time.perf_counter()
        head = make_heads(count)
        scores = head_scores(head, [reply.values for reply in replies[:ACTIVE]])
        keys = [r.key for r in replies[:ACTIVE]]
        if first_keys is None:
            first_keys = keys
        elif keys != first_keys:
            raise Denied("cross-fleet source-feature identities changed")
        # This is deliberately a 2-hop *metadata provenance* graph, not a
        # natural language answer or learned relational reasoning benchmark.
        # It joins exactly the original source bytes to the actual Encoder
        # feature identity; NDU must match a separate ordinary DP enumerator.
        metadata_parity = 0
        for item, feature_key in zip(rows, keys):
            source_sha = item["source_sha256"]
            edges = (Fact("source", source_sha, item["case_id"], "has_input", source_sha, "0", "0"),
                     Fact("feature", source_sha, source_sha, "encoded_as", feature_key, "0", "0"))
            objective = Objective(item["case_id"], feature_key, ("has_input", "encoded_as"),
                                  "0", "1", "0")
            proof = EvidenceCircuit(objective, edges).compare_same_profile()
            if not proof["success"] or proof["hops"] != 2:
                raise Denied("two-hop source/feature metadata circuit broken")
            metadata_parity += 1
        scalar_count = sum(t.numel() for t in head.values())
        scalar_bytes = sum(t.numel() * t.element_size() for t in head.values())
        out.append({"fleet_size": count, "active_heads": ACTIVE,
                    "logical_borrows": bus.borrow_count,
                    "unique_inputs": bus.resident_features,
                    "distinct_encoded_inputs": bus.physical_calls - before_f,
                    "physical_encoder_batches": produced["actual_pretrained_model_batches"],
                    "physical_encoder_sequences": produced["actual_pretrained_model_sequences"],
                    "head_scalars": scalar_count, "head_weight_bytes_fp32": scalar_bytes,
                    "metadata_circuit_parity_count": metadata_parity,
                    "head_output_sha256": hashlib.sha256(scores).hexdigest(),
                    "scoped_feature_digest": hashlib.sha256(canon([r.key for r in replies])).hexdigest(),
                    "cohort_wall_seconds": time.perf_counter() - cohort_start,
                    "cohort_cpu_seconds": time.process_time() - cohort_cpu,
                    "feature_wall_seconds": encode_end - cohort_start,
                    "maxrss_bytes_process": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024})
        if not (produced["actual_pretrained_model_batches"] == 2 and
                bus.physical_calls == ACTIVE and
                bus.borrow_count == count and
                len({r.input_sha for r in replies}) == ACTIVE):
            raise Denied("physical fanout accounting invariant")
    return {"schema": SCHEMA, "parent_source_plan_sha256": prepared["source_plan_sha256"],
            "model_repo": spec["repo"], "model_revision": spec["revision"],
            "model_sha256": spec["weight_sha256"], "candidate": "granite97",
            "source_case_ids": [r["case_id"] for r in rows],
            "source_digest_ids": [r["source_sha256"] for r in rows],
            "source_feature_keys": first_keys,
            "cohorts": out, "total_wall_seconds": time.perf_counter() - started,
            "total_cpu_seconds": time.process_time() - cpu_started,
            "model_download_load_wall_seconds": load_seconds,
            "host_attested": False, "stem_winner_verified": False,
            "ndu_task_lift_verified": False, "natural_reasoning_verified": False,
            "future_holdout_verified": False, "production_authorized": False,
            "disposition": "HOLD_NO_GO"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--materials", required=True)
    p.add_argument("--output", required=True)
    opts = p.parse_args()
    result = run_physical(json.loads(Path(opts.source).read_text()),
                          json.loads(Path(opts.materials).read_text()))
    output = Path(opts.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # New file, never overwrite source/evidence.
    with output.open("xb") as f:
        f.write(canon(result) + b"\n")
        f.flush()
        os.fsync(f.fileno())
    print(json.dumps({"physical_summary_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                      "disposition": "HOLD_NO_GO"}, sort_keys=True))


if __name__ == "__main__":
    main()
