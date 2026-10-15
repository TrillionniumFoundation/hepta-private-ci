"""Independent eager/SDPA operator check against pinned original Smol weights.

The reference equations follow the public Transformers v4.49.0 Llama architecture,
but this script does NOT execute the Transformers package or HF Tokenizers runtime.
Only the exact pinned original weight archive is admitted. An operator match
cannot certify tokenizer/HF-runtime parity or task correctness.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import time

import torch
import torch.nn.functional as F

from offline_smol_reader import OriginalSmol, PINS, digest

SOURCE = (
    "https://github.com/huggingface/transformers/blob/v4.49.0/"
    "src/transformers/models/llama/modeling_llama.py"
)


def independent_reference_logits(weights, ids):
    """Batch-first tensor layout, independent SDPA, no shared helper kernels."""
    if not 1 <= len(ids) <= 2048 or any(type(x) is not int for x in ids):
        raise ValueError("bounded frozen input tokens required")
    seq = len(ids)
    device = weights["model.embed_tokens.weight"].device
    position = torch.arange(seq, dtype=torch.float32, device=device)[None, None, :]
    dimension = torch.arange(0, 64, 2, dtype=torch.float32, device=device)
    frequency = 1 / torch.pow(torch.tensor(100000.0, device=device), dimension / 64)
    # HF implementation constructs frequencies by a float32 matrix product.
    phase = torch.matmul(frequency[None, :, None], position).transpose(1, 2)
    angles = torch.cat([phase, phase], dim=-1)
    cos, sin = angles.cos().unsqueeze(1), angles.sin().unsqueeze(1)

    def rotate(x):
        left, right = x.chunk(2, dim=-1)
        return torch.cat([-right, left], dim=-1)

    def norm(x, label):
        return (x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + 1e-5)) * weights[label]

    tokens = torch.tensor(ids, dtype=torch.long, device=device)[None, :]
    hidden = F.embedding(tokens, weights["model.embed_tokens.weight"])
    for layer in range(30):
        prefix = f"model.layers.{layer}."
        normalized = norm(hidden, prefix + "input_layernorm.weight")
        vectors = []
        for projection, count in (("q", 9), ("k", 3), ("v", 3)):
            x = F.linear(normalized, weights[prefix + f"self_attn.{projection}_proj.weight"])
            x = x.view(1, seq, count, 64).transpose(1, 2)
            vectors.append(x)
        q, k, v = vectors
        q, k = q * cos + rotate(q) * sin, k * cos + rotate(k) * sin
        k = k.repeat_interleave(3, dim=1)
        v = v.repeat_interleave(3, dim=1)
        attention = F.scaled_dot_product_attention(q, k, v, is_causal=True, dropout_p=0.0)
        combined = attention.transpose(1, 2).contiguous().reshape(1, seq, 576)
        hidden = hidden + F.linear(combined, weights[prefix + "self_attn.o_proj.weight"])
        residual = norm(hidden, prefix + "post_attention_layernorm.weight")
        gate = F.silu(F.linear(residual, weights[prefix + "mlp.gate_proj.weight"]))
        value = F.linear(residual, weights[prefix + "mlp.up_proj.weight"])
        hidden = hidden + F.linear(
            gate * value, weights[prefix + "mlp.down_proj.weight"]
        )
    final = norm(hidden[:, -1], "model.norm.weight")
    return F.linear(final, weights["model.embed_tokens.weight"])[0]


def run(root, raw_journal, output, source_commit):
    if output.exists():
        raise ValueError("do not overwrite parity observations")
    torch.set_num_threads(2)
    start = time.perf_counter()
    reader = OriginalSmol(root)
    rows = [json.loads(line) for line in Path(raw_journal).read_text().splitlines()]
    if len(rows) != 48 or any(r["status"] != "succeeded" for r in rows):
        raise ValueError("complete 48 original input sequences required")
    by_arm = {}
    for row in rows:
        by_arm.setdefault(row["arm"], []).append(row)
    if set(by_arm) != {
        "empty", "hybrid", "entity_time", "organized", "program_support",
        "without_prerequisite",
    } or any(len(v) != 8 for v in by_arm.values()):
        raise ValueError("original arm census drift")
    picks = [
        by_arm["empty"][0],
        by_arm["hybrid"][3],
        by_arm["entity_time"][2],
        by_arm["organized"][5],
        by_arm["program_support"][6],
        by_arm["without_prerequisite"][7],
    ]
    checks = []
    with torch.inference_mode():
        for row in picks:
            ids = row["input_ids"]
            if digest(ids) != row["input_ids_digest"]:
                raise ValueError("raw original input IDs changed")
            a, _ = reader.forward(ids)
            b = independent_reference_logits(reader.weights, ids)
            delta = (a - b).abs()
            top = int(a.argmax()), int(b.argmax())
            record = dict(
                question_id=row["question_id"],
                arm=row["arm"],
                input_tokens=len(ids),
                original_input_digest=row["input_ids_digest"],
                max_logit_absolute_error=float(delta.max()),
                mean_logit_absolute_error=float(delta.mean()),
                top1_tokens=top,
                top1_match=top[0] == top[1],
                # Tolerance is declared before any comparisons are examined.
                within_predeclared_tolerance=bool(delta.max() <= 2e-3 and top[0] == top[1]),
            )
            checks.append(record)
            print(json.dumps(record), flush=True)
        # Unlike cache-vs-cache, this compares two distinct full-context paths
        # after feeding already frozen greedy tokens, never the final target.
        continuation = []
        for row in (by_arm["organized"][0], by_arm["program_support"][3]):
            source_ids = row["input_ids"]
            for count in (1, 2, 4):
                context = source_ids + row["generated_ids"][:count]
                a, _ = reader.forward(context)
                b = independent_reference_logits(reader.weights, context)
                diff = (a - b).abs()
                record = dict(
                    question_id=row["question_id"],
                    arm=row["arm"],
                    continuation_tokens=count,
                    max_logit_absolute_error=float(diff.max()),
                    top1_match=int(a.argmax()) == int(b.argmax()),
                    within_predeclared_tolerance=bool(
                        diff.max() <= 2e-3 and int(a.argmax()) == int(b.argmax())
                    ),
                )
                continuation.append(record)
                print(json.dumps(record), flush=True)
    reader.verify_frozen()
    report = dict(
        schema="hepta.memory-smol-reference-operator-check.v1",
        tested_source=source_commit,
        original_weights_sha256=PINS["model.safetensors"],
        original_journal_sha256=hashlib.sha256(Path(raw_journal).read_bytes()).hexdigest(),
        reference_equations=SOURCE,
        actual_huggingface_transformers_library_executed=False,
        actual_hf_tokenizers_library_executed=False,
        hf_end_to_end_parity_certified=False,
        source_family_independence_certified=False,
        sampled_prefixes=len(checks),
        sampled_continuations=len(continuation),
        checked_original_evidence_arms=sorted(by_arm),
        per_prefix=checks,
        per_continuation=continuation,
        local_operator_tolerance=0.002,
        local_operator_check_passed=all(
            r["within_predeclared_tolerance"] for r in checks + continuation
        ),
        runtime_seconds=time.perf_counter() - start,
        model_calls_generated=0,
        model_parameters_updated=0,
        new_task_benefit_established=False,
        production_accepted=False,
    )
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reader", type=Path)
    parser.add_argument("raw", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    run(args.reader, args.raw, args.output, args.source_commit)
