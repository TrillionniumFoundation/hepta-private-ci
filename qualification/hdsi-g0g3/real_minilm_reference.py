"""Offline original MiniLM CPU reference with HDSI feature fanout (research only).

Requires ORIGINAL byte-pinned MiniLM+LoCoMo source from existing Hepta V8
artifact 11586991191, extracted into a private local directory. This is a
custom reference forward, NOT official HF/tokenizer parity, not Granite97 and
NOT natural reasoning, model selection, CellSplit or deployment evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import time
import unicodedata

from feature_bus import Borrow, Denied, Scope, SharedFeatureBus, canon
from physical_fanout import SIZES, ACTIVE, WIDTH, make_heads, head_scores
from circuit_ndu import EvidenceCircuit, Fact, Objective

CHECKSUMS = {
    "encoder/model.safetensors": "53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db",
    "encoder/tokenizer.json": "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037",
    "encoder/vocab.txt": "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3",
    "encoder/config.json": "953f9c0d463486b10a6871cc2fd59f223b2c70184f49815e7efbcab5d8908b41",
    "locomo.json": "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4",
}
ARCHIVE_SHA = "07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af"
SCHEMA = "hepta.hdsi.real-minilm-original-cpu.local-shadow.v1"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def verified_material(root: Path) -> dict:
    for filename, checksum in CHECKSUMS.items():
        f = root / filename
        if f.is_symlink() or not f.is_file() or f.stat().st_size > 120_000_000:
            raise Denied("unsafe/missing original model source: " + filename)
        h = hashlib.sha256()
        with f.open("rb") as inp:
            for part in iter(lambda: inp.read(1 << 20), b""):
                h.update(part)
        if h.hexdigest() != checksum:
            raise Denied("original model/source bytes not as recorded: " + filename)
    cfg = json.loads((root / "encoder/config.json").read_text())
    if not (cfg["model_type"] == "bert" and cfg["hidden_size"] == 384
            and cfg["num_hidden_layers"] == 6 and cfg["num_attention_heads"] == 12
            and cfg["intermediate_size"] == 1536 and cfg["vocab_size"] == 30522
            and cfg["layer_norm_eps"] == 1e-12):
        raise Denied("unsupported pretrained architecture")
    return cfg


def source_records(root: Path) -> list[dict]:
    corpus = json.loads((root / "locomo.json").read_text())
    if type(corpus) is not list or len(corpus) != 10:
        raise Denied("unregistered original source roots")
    records, families = [], set()
    for entry in corpus:
        fam = entry["sample_id"]
        if fam in families:
            raise Denied("duplicate source family")
        families.add(fam)
        # ONLY conversation utterances: never process qa/labels at model ingress.
        for key, turns in entry["conversation"].items():
            if not key.startswith("session_") or type(turns) is not list:
                continue
            for turn in turns:
                raw = turn.get("text")
                if type(raw) is not str or not 15 <= len(raw) <= 180:
                    continue
                text = str(turn["speaker"]) + ": " + raw
                if len(text.encode("utf-8")) > 300:
                    continue
                records.append({"root": fam, "id": str(turn["dia_id"]),
                                "source_sha256": sha(text.encode()), "text": text})
    records.sort(key=lambda r: (r["source_sha256"], r["root"], r["id"]))
    unique = {r["source_sha256"]: r for r in reversed(records)}
    selected = sorted(unique.values(), key=lambda r: r["source_sha256"])[:ACTIVE]
    if len(selected) != ACTIVE or len(families) != 10:
        raise Denied("insufficient original source coverage")
    return selected


def wordpiece(text: str, vocab: dict[str, int]) -> list[int]:
    if type(text) is not str or not text.strip() or len(text.encode()) > 4096:
        raise Denied("bad source input")
    text = "".join(c for c in unicodedata.normalize("NFD", text.lower())
                   if not unicodedata.combining(c) and unicodedata.category(c) != "Cc")
    chunks, word = [], ""
    for char in text + " ":
        cat = unicodedata.category(char)
        if char.isspace() or cat[0] in ("P", "S"):
            if word:
                chunks.append(word)
                word = ""
            if not char.isspace():
                chunks.append(char)
        else:
            word += char
    ids = [101]
    for chunk in chunks:
        if len(chunk) > 100:
            ids.append(100)
            continue
        if chunk in vocab:
            ids.append(vocab[chunk])
            continue
        pieces, start = [], 0
        while start < len(chunk):
            end, chosen = len(chunk), None
            while end > start:
                piece = ("##" if start else "") + chunk[start:end]
                if piece in vocab:
                    chosen = vocab[piece]
                    break
                end -= 1
            if chosen is None:
                pieces = [100]
                break
            pieces.append(chosen)
            start = end
        ids.extend(pieces)
    ids.append(102)
    if len(ids) > 128:
        raise Denied("original text exceeded registered 128 token budget")
    return ids


class RealMiniLM:
    """Original BF16 safetensors -> FP32 PyTorch full six BERT layers."""

    def __init__(self, root: Path):
        import torch
        from safetensors import safe_open
        self.config = verified_material(root)
        self.vocab = {w: i for i, w in enumerate((root / "encoder/vocab.txt").read_text().splitlines())}
        if len(self.vocab) != 30522 or self.vocab.get("[CLS]") != 101 or self.vocab.get("[SEP]") != 102:
            raise Denied("original WordPiece vocab mismatch")
        with safe_open(str(root / "encoder/model.safetensors"), framework="pt", device="cpu") as f:
            self.weights = {k: f.get_tensor(k).float() for k in f.keys()}
        self.calls = 0
        self.tokens = 0

    def forward_ids(self, ids: list[int]):
        import torch
        import torch.nn.functional as F
        if not ids or len(ids) > 128 or any(type(i) is not int or not 0 <= i < 30522 for i in ids):
            raise Denied("invalid original token sequence")
        g, cfg = self.weights.__getitem__, self.config
        n, hidden, heads = len(ids), cfg["hidden_size"], cfg["num_attention_heads"]
        x = g("embeddings.word_embeddings.weight")[torch.tensor(ids)]
        x = x + g("embeddings.position_embeddings.weight")[:n]
        x = x + g("embeddings.token_type_embeddings.weight")[0]
        def norm(y, w, b):
            return F.layer_norm(y, (hidden,), weight=w, bias=b, eps=cfg["layer_norm_eps"])
        x = norm(x, g("embeddings.LayerNorm.weight"), g("embeddings.LayerNorm.bias"))
        for layer in range(6):
            pre = f"encoder.layer.{layer}."
            att = pre + "attention.self."
            q, k, v = (F.linear(x, g(att + name + ".weight"), g(att + name + ".bias"))
                       .reshape(n, heads, hidden // heads).transpose(0, 1)
                       for name in ("query", "key", "value"))
            attention = (q @ k.transpose(-1, -2) / math.sqrt(hidden // heads)).softmax(-1)
            y = (attention @ v).transpose(0, 1).contiguous().reshape(n, hidden)
            prefix = pre + "attention.output."
            y = F.linear(y, g(prefix + "dense.weight"), g(prefix + "dense.bias"))
            x = norm(x + y, g(prefix + "LayerNorm.weight"), g(prefix + "LayerNorm.bias"))
            prefix = pre + "intermediate.dense."
            y = F.gelu(F.linear(x, g(prefix + "weight"), g(prefix + "bias")))
            prefix = pre + "output."
            y = F.linear(y, g(prefix + "dense.weight"), g(prefix + "dense.bias"))
            x = norm(x + y, g(prefix + "LayerNorm.weight"), g(prefix + "LayerNorm.bias"))
        if not torch.isfinite(x).all().item():
            raise Denied("nonfinite original forward")
        self.calls += 1
        self.tokens += n
        return x

    def encode(self, text: str) -> tuple[float, ...]:
        import torch
        import torch.nn.functional as F
        ids = wordpiece(text, self.vocab)
        with torch.inference_mode():
            x = F.normalize(self.forward_ids(ids).mean(dim=0), dim=-1)
        return tuple(float(i) for i in x.tolist())


def run(root: Path) -> dict:
    import torch
    torch.set_num_threads(1)
    start = time.perf_counter()
    cstart = time.process_time()
    enc = RealMiniLM(root)  # validate original material BEFORE reading public inputs
    selected = source_records(root)
    load_elapsed = time.perf_counter() - start
    preprocess_sha = sha(b"hepta.v8|wordpiece-candidate|masked-mean-unit-normalized|no-truncation|fp32-reference")
    scope = Scope("research-public-minilm", "original-locomo-shadow", 7, 1,
                  sha(b"research-minilm-test-only-current-revocation"), CHECKSUMS["encoder/model.safetensors"],
                  preprocess_sha)
    def allowed(b: Borrow) -> bool:
        return b.scope == scope and b.approved_use == "read-only-original"
    def encode(payload, modality):
        if modality != "text":
            raise Denied("not a multimodal trained encoder")
        return enc.encode(payload.decode("utf-8", "strict"))

    output, feature_references, first_features = [], None, None
    baseline_full = []
    for size in SIZES:
        bus = SharedFeatureBus(WIDTH, encode, allowed)
        borrowers = [Borrow(scope, "text", selected[i % ACTIVE]["text"].encode(),
                            f"cell:{i}", "read-only-original") for i in range(size)]
        t0, c0, before = time.perf_counter(), time.process_time(), enc.calls
        answers = bus.fanout(borrowers)
        elapsed_encoder = time.perf_counter() - t0
        if bus.physical_calls != ACTIVE or enc.calls - before != ACTIVE or len({r.key for r in answers}) != ACTIVE:
            raise Denied("true original model forward census mismatch")
        # Cache hits must return same original tensor values at large fleet size.
        head = make_heads(size)
        raw = head_scores(head, [r.values for r in answers[:ACTIVE]])
        refs = [r.key for r in answers[:ACTIVE]]
        if feature_references is None:
            feature_references = refs
            first_features = [r.values for r in answers[:ACTIVE]]
        else:
            if refs != feature_references or [r.values for r in answers[:ACTIVE]] != first_features:
                raise Denied("independent pretrained rerun changed features")
        metadata_matches = 0
        for row, reference in zip(selected, refs):
            s = row["source_sha256"]
            edges = (Fact("source", s, s, "has_input", s, "0", "0"),
                     Fact("feature", s, s, "encoded_as", reference, "0", "0"))
            decision = EvidenceCircuit(Objective(s, reference, ("has_input", "encoded_as"),
                                                 "0", "1", "0"), edges).compare_same_profile()
            if decision["success"] and decision["hops"] == 2:
                metadata_matches += 1
        if metadata_matches != ACTIVE:
            raise Denied("source/feature metadata not composed")
        hit = bus.fanout(borrowers[:ACTIVE])
        if not all(r.cache_hit for r in hit) or enc.calls-before != ACTIVE:
            raise Denied("cache revalidation unexpectedly called the model")
        scored = head_scores(head, [r.values for r in hit])
        if raw != scored:
            raise Denied("cache-hit original Head scores changed")
        output.append({"resident_cells": size, "active_heads": ACTIVE,
                       "actual_original_encoder_full_forwards": enc.calls-before,
                       "encoder_token_positions": enc.tokens,
                       "logical_fanout": size,
                       "original_pretrained_sequence_calls_if_unshared": size,
                       "resident_scalar_head_count": sum(t.numel() for t in head.values()),
                       "head_weight_bytes_fp32": sum(t.numel()*t.element_size() for t in head.values()),
                       "source_feature_identity_parity": metadata_matches,
                       "actual_feature_cost_wall_seconds": elapsed_encoder,
                       "cohort_wall_seconds": time.perf_counter() - t0,
                       "cohort_cpu_seconds": time.process_time() - c0,
                       "maxrss_bytes_whole_process_unattested": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                       "head_output_sha256": sha(raw)})
        del head, bus
    # Paired real-model no-cache reference: independently recompute all 32
    # original texts, not replayed or synthetic, and require exact values.
    t0 = time.perf_counter()
    fresh = [enc.encode(row["text"]) for row in selected]
    if fresh != first_features:
        raise Denied("no-cache real model baseline differs from cached encoding")
    direct_elapsed = time.perf_counter() - t0
    # No historical publisher answers are used to claim real task correctness.
    return {"schema": SCHEMA, "archive_sha256": ARCHIVE_SHA,
            "original_model_sha256": CHECKSUMS["encoder/model.safetensors"],
            "original_locomo_sha256": CHECKSUMS["locomo.json"],
            "source_root_count_available": 10,
            "actual_source_roots_selected": len({r["root"] for r in selected}),
            "source_sha256": [r["source_sha256"] for r in selected],
            "identical_input_rerun_fp32_parity": True,
            "no_cache_reference_32_fresh_forwards": len(fresh),
            "no_cache_reference_wall_seconds": direct_elapsed,
            "total_actual_full_model_forwards": enc.calls,
            "total_original_tokens": enc.tokens,
            "model_load_wall_seconds": load_elapsed,
            "end_to_end_wall_seconds": time.perf_counter()-start,
            "end_to_end_cpu_seconds": time.process_time()-cstart,
            "cohorts": output,
            "model_reference_mode": "original-six-layer-custom-fp32-no-official-hf-parity",
            "pretrained_model_real": True,
            "numeric_cross_host_parity": False,
            "natural_reasoning_verified": False,
            "ndu_incremental_utility_verified": False,
            "future_task_improvement_verified": False,
            "production_authorized": False,
            "disposition": "HOLD_NO_GO"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    opts = parser.parse_args()
    result = run(opts.original_root)
    opts.output.parent.mkdir(parents=True, exist_ok=True)
    # Create only; same source cannot silently rewrite an observation receipt.
    with opts.output.open("xb") as f:
        f.write(canon(result) + b"\n")
        f.flush()
        os.fsync(f.fileno())
    print(json.dumps({"report_sha256": sha(opts.output.read_bytes()), "disposition": "HOLD_NO_GO",
                      "physical_original_encoder_forwards": result["total_actual_full_model_forwards"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
