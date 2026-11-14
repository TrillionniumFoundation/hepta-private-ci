"""V8 read-only PHYSICAL pretrained MiniLM shared-Encoder/Cell experiment.

Original archived LoCoMo SOURCE text and genuine BF16 pretrained MiniLM weights;
PyTorch FP32 reference BERT, not official Hugging Face tokenizer/operator parity.
Separate V7 immutable cache-key identities are checked for each active Cell.
No human accuracy, native production Worker, signed issuer or Stem winner claim.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import time
import unicodedata

SCHEMA = "hepta.stem.v8.archived-minilm-physical-share.shadow.v1"
SIZES = (64, 256, 1024, 4096)
SCENARIOS = ("identical", "four_inputs", "distinct_inputs", "partitioned_identity", "personalized")
SHA = {
    "archive": "07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af",
    "model_revision": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
    "model": "53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db",
    "tokenizer": "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037",
    "vocab": "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3",
    "config": "953f9c0d463486b10a6871cc2fd59f223b2c70184f49815e7efbcab5d8908b41",
    "locomo": "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4",
    "numeric_cls": "8bf8f3919fa6bf315043cca6473f133e98879efd14d4b7a1d54dc8c5ccd3ca78",
    "numeric_pooler": "05e1a97b267a136d176a1503222666d70b5ddf20ee1fcf00ceeec8229aca23d3",
}
PREPROCESS_SHA = hashlib.sha256(b"hepta.v8|wordpiece-candidate|masked-mean-unit-normalized|no-truncation|fp32-reference").hexdigest()
SEED = 7347
ACTIVE = 32
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_material(root: Path) -> dict:
    """Before loading tensors, check original file bytes; never follow symlinks."""
    root = Path(root)
    names = {"model": "encoder/model.safetensors", "tokenizer": "encoder/tokenizer.json",
             "vocab": "encoder/vocab.txt", "config": "encoder/config.json", "locomo": "locomo.json"}
    for slot, relative in names.items():
        p = root / relative
        if not p.is_file() or p.is_symlink() or file_sha(p) != SHA[slot]:
            raise ValueError("original model/source material changed: " + slot)
    cfg = json.loads((root / names["config"]).read_text())
    if (cfg.get("hidden_size") != 384 or cfg.get("num_hidden_layers") != 6
            or cfg.get("num_attention_heads") != 12 or cfg.get("layer_norm_eps") != 1e-12):
        raise ValueError("unreviewed original MiniLM architecture")
    return cfg


def bare_wordpiece(text: str, vocab: dict[str, int]) -> list[int]:
    """Candidate lower/strip WordPiece identical to AMCN manual CPU route (NOT HF parity)."""
    if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > 4096:
        raise ValueError("nonempty bounded source text only")
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
            end, part = len(chunk), None
            while end > start:
                sub = ("##" if start else "") + chunk[start:end]
                if sub in vocab:
                    part = vocab[sub]
                    break
                end -= 1
            if part is None:
                pieces = [100]
                break
            pieces.append(part)
            start = end
        ids.extend(pieces)
    ids.append(102)
    if len(ids) > 128:
        raise ValueError("input exceeds real MiniLM 128-token declared budget; refuse truncation")
    return ids


def source_only_records(corpus_path: Path) -> list[dict]:
    """Construct source-only inventory from conversation turns; NEVER read qa/labels.

    The original JSON parser sees full public file in memory, not an OS namespace
    isolation of answer fields. No answer object enters Encoder/prediction path.
    """
    if file_sha(Path(corpus_path)) != SHA["locomo"]:
        raise ValueError("original corpus SHA mismatch")
    original = json.loads(Path(corpus_path).read_text())
    if not isinstance(original, list) or len(original) != 10:
        raise ValueError("unexpected source roots")
    records, seen = [], set()
    for sample in original:
        fam = str(sample["sample_id"])
        conversation = sample["conversation"]
        if fam in seen or not isinstance(conversation, dict):
            raise ValueError("duplicate or invalid source family")
        seen.add(fam)
        selected = []
        for key, turns in conversation.items():
            if not key.startswith("session_") or not isinstance(turns, list):
                continue
            for turn in turns:
                if not isinstance(turn, dict) or not {"speaker", "dia_id", "text"}.issubset(turn):
                    raise ValueError("invalid original dialogue turn")
                raw = turn["text"]
                if not isinstance(raw, str) or not 15 <= len(raw) <= 180:
                    continue
                source = (turn["speaker"] + ": " + raw).strip()
                if len(source.encode("utf-8")) > 300:
                    continue
                selected.append({"family_id": fam, "source_id": str(turn["dia_id"]),
                                 "source_sha256": sha_bytes(source.encode()), "text": source})
        if not selected:
            raise ValueError("empty original source root")
        # Source ID/hash sort before any downstream result is available.
        records.extend(sorted(selected, key=lambda x: (x["source_sha256"], x["source_id"]))[:16])
    records.sort(key=lambda x: (x["source_sha256"], x["family_id"], x["source_id"]))
    unique = {r["source_sha256"]: r for r in records}
    if len(unique) < ACTIVE or len(seen) != 10:
        raise ValueError("insufficient original independent input texts")
    return list(unique.values())


class OriginalMiniLM:
    """Actual original checkpoint, frozen BF16 safetensors -> FP32 reference BERT."""

    def __init__(self, root: Path):
        import torch
        from safetensors import safe_open
        self.root = Path(root)
        self.config = verify_material(self.root)
        self.vocab = {w: i for i, w in enumerate((self.root / "encoder/vocab.txt").read_text().splitlines())}
        if len(self.vocab) != 30522 or self.vocab.get("[CLS]") != 101 or self.vocab.get("[SEP]") != 102:
            raise ValueError("original WordPiece inventory mismatch")
        with safe_open(str(self.root / "encoder/model.safetensors"), framework="pt", device="cpu") as f:
            self.weights = {key: f.get_tensor(key).to(torch.float32) for key in f.keys()}
        self.calls = 0
        self.tokens = 0

    def forward_ids(self, ids: list[int]):
        import torch
        import torch.nn.functional as F
        if not ids or len(ids) > 128 or any(type(i) is not int or i < 0 or i >= 30522 for i in ids):
            raise ValueError("bounded original token IDs required")
        g, cfg = self.weights.__getitem__, self.config
        n, hidden, heads = len(ids), cfg["hidden_size"], cfg["num_attention_heads"]
        x = g("embeddings.word_embeddings.weight")[torch.tensor(ids)]
        x = x + g("embeddings.position_embeddings.weight")[:n]
        x = x + g("embeddings.token_type_embeddings.weight")[0]
        norm = lambda y, w, b: F.layer_norm(y, (hidden,), weight=w, bias=b,
                                             eps=cfg["layer_norm_eps"])
        x = norm(x, g("embeddings.LayerNorm.weight"), g("embeddings.LayerNorm.bias"))
        for layer in range(6):
            pre = f"encoder.layer.{layer}."
            a = pre + "attention.self."
            q, k, v = (F.linear(x, g(a + w + ".weight"), g(a + w + ".bias"))
                       .reshape(n, heads, hidden // heads).transpose(0, 1)
                       for w in ("query", "key", "value"))
            weights = (q @ k.transpose(-1, -2) / math.sqrt(hidden // heads)).softmax(-1)
            y = (weights @ v).transpose(0, 1).contiguous().reshape(n, hidden)
            w = pre + "attention.output."
            y = F.linear(y, g(w + "dense.weight"), g(w + "dense.bias"))
            x = norm(x + y, g(w + "LayerNorm.weight"), g(w + "LayerNorm.bias"))
            w = pre + "intermediate.dense."
            y = F.gelu(F.linear(x, g(w + "weight"), g(w + "bias")))
            w = pre + "output."
            y = F.linear(y, g(w + "dense.weight"), g(w + "dense.bias"))
            x = norm(x + y, g(w + "LayerNorm.weight"), g(w + "LayerNorm.bias"))
        self.calls += 1    # counted only after completing all six physical layers
        self.tokens += n
        return x

    def numeric_probe(self):
        import torch
        import torch.nn.functional as F
        with torch.inference_mode():
            h = self.forward_ids([101, 2023, 2003, 1037, 3231, 102])
            g = self.weights.__getitem__
            pooled = torch.tanh(F.linear(h[0], g("pooler.dense.weight"), g("pooler.dense.bias")))
        cls_sha = sha_bytes(h[0].float().contiguous().numpy().astype("<f4", copy=False).tobytes())
        pool_sha = sha_bytes(pooled.float().contiguous().numpy().astype("<f4", copy=False).tobytes())
        from numeric_reference_v8 import reference
        expected = reference(self.root)
        if expected != {"cls": cls_sha, "pooler": pool_sha}:
            raise ValueError("independent original same-host BERT numeric implementation differs")
        return {"cls": cls_sha, "pooler": pool_sha,
                "same_host_reference_exact": True,
                "archived_cross_host_reference_exact": (cls_sha == SHA["numeric_cls"] and
                                                        pool_sha == SHA["numeric_pooler"])}

    def encode_text(self, text: str):
        import torch
        import torch.nn.functional as F
        ids = bare_wordpiece(text, self.vocab)
        with torch.inference_mode():
            x = self.forward_ids(ids)
            return F.normalize(x.mean(dim=0), dim=-1)


def scenario_rows(source: list[dict], scenario: str, size: int) -> list[dict]:
    """Physically identical/different original LoCoMo source text, fenced by V7 key."""
    if scenario not in SCENARIOS or size not in SIZES or len(source) < ACTIVE:
        raise ValueError("valid original source roster and registered fleet/scenario required")
    from stem_selection_v7 import cache_identity
    result = []
    for i in range(ACTIVE):
        source_ix = 0 if scenario in ("identical", "partitioned_identity", "personalized") else (i % 4 if scenario == "four_inputs" else i)
        text = source[source_ix]["text"]
        if scenario == "personalized":
            text = f"neuron cell number {i}: " + text
        principal = f"principal-{i}" if scenario == "partitioned_identity" else "research-only"
        identity = {
            "principal": principal, "purpose": "research-pretrained-sharing", "generation": 7,
            "authority_epoch": 1, "model_revision": SHA["model_revision"],
            "weights_sha256": SHA["model"], "tokenizer_sha256": SHA["tokenizer"],
            "preprocess_sha256": PREPROCESS_SHA, "modality": "text",
            "input_sha256": sha_bytes(text.encode("utf-8")),
        }
        # Original immutable archived model revision; SHA256 file pins are separately checked.
        result.append({"cell_id": i, "source_family": source[source_ix]["family_id"],
                       "input_sha256": identity["input_sha256"], "key": cache_identity(identity),
                       "text": text})
    return result


def _group_count(rows):
    return len({row["key"] for row in rows})


def actual_inference(encoder, heads, rows, *, deduplicate: bool):
    """No model call is skipped except exact source/authority-bound duplicate inputs."""
    import torch
    if not isinstance(rows, list) or len(rows) != ACTIVE or len({r["cell_id"] for r in rows}) != ACTIVE:
        raise ValueError("complete active Cell roster required")
    grouped = {}
    features = []
    before = encoder.calls
    for row in rows:
        key = row["key"]
        if deduplicate and key in grouped:
            vector = grouped[key]
        else:
            vector = encoder.encode_text(row["text"])
            if deduplicate:
                grouped[key] = vector
        features.append(vector)
    with torch.inference_mode():
        # Physical 32 active private Head matrices, 1 feature vector per Cell.
        features = torch.stack(features)
        ids = torch.arange(ACTIVE, dtype=torch.long)
        n, d, rank = heads["up"].shape
        z = torch.relu(torch.bmm(heads["down"][ids], features.unsqueeze(-1)))
        residual = torch.bmm(heads["up"][ids], z).squeeze(-1)
        gate = torch.sigmoid((heads["gate"][ids] * features).sum(-1) + heads["biases"][ids, 0])
        hidden = features + gate.unsqueeze(-1) * residual
        scores = (hidden * heads["readout"][ids]).sum(-1) + heads["biases"][ids, 1]
        if not torch.isfinite(scores).all():
            raise ValueError("nonfinite original-pretrained output")
    expected = _group_count(rows) if deduplicate else ACTIVE
    used = encoder.calls - before
    if used != expected:
        raise RuntimeError("physical Encoder invocation did not match complete source identity")
    return scores, used


def vmrss_kib():
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    raise RuntimeError("Linux VmRSS required")


def _percentile(values, q):
    s = sorted(values)
    return s[min(len(s)-1, math.ceil(q*len(s))-1)]


def measure_original(root: Path, size: int, *, iterations: int = 2) -> dict:
    import torch
    from stem_v7_physical_heads import _tensors, gated_head_count
    if size not in SIZES or type(iterations) is not int or not 1 <= iterations <= 10:
        raise ValueError("bounded physical experimental configuration")
    torch.set_num_threads(1)
    started, cpu_started = time.perf_counter(), time.process_time()
    baseline_rss = vmrss_kib()
    encoder = OriginalMiniLM(root)
    model_ready = time.perf_counter()
    anchor = encoder.numeric_probe()
    source = source_only_records(Path(root) / "locomo.json")
    heads = _tensors(size)
    rss_after_model_and_heads = vmrss_kib()
    rows = []
    for scenario in SCENARIOS:
        inputs = scenario_rows(source, scenario, size)
        expected = {"identical": 1, "four_inputs": 4, "distinct_inputs": 32,
                    "partitioned_identity": 32, "personalized": 32}[scenario]
        if _group_count(inputs) != expected:
            raise ValueError("actual immutable source material does not match expected sharing")
        direct_ms, shared_ms, parity, output_sha = [], [], [], None
        direct_calls = cached_calls = 0
        for iteration in range(iterations):
            t0 = time.perf_counter_ns()
            raw, raw_calls = actual_inference(encoder, heads, inputs, deduplicate=False)
            direct_ms.append((time.perf_counter_ns() - t0) / 1e6)
            t1 = time.perf_counter_ns()
            shared, reused_calls = actual_inference(encoder, heads, inputs, deduplicate=True)
            shared_ms.append((time.perf_counter_ns() - t1) / 1e6)
            if not torch.equal(raw, shared):
                raise ValueError("shared feature changed actual raw pretrained+Head predictions")
            output = sha_bytes(shared.contiguous().numpy().astype("<f4", copy=False).tobytes())
            parity.append(output)
            if output_sha is None:
                output_sha = output
            direct_calls += raw_calls
            cached_calls += reused_calls
        if len(set(parity)) != 1:
            raise ValueError("nondeterministic real pretrained results across iterations")
        rows.append({
            "scenario": scenario, "active_cell_heads": ACTIVE,
            "unique_source_authority_keys": expected,
            "source_root_groups_in_active_rows": len({x["source_family"] for x in inputs}),
            "baseline_encoder_forwards": direct_calls,
            "shared_encoder_forwards": cached_calls,
            "baseline_measured_ms": direct_ms, "shared_measured_ms": shared_ms,
            "baseline_p50_ms": statistics.median(direct_ms),
            "shared_p50_ms": statistics.median(shared_ms),
            "baseline_p95_ms": _percentile(direct_ms, .95),
            "shared_p95_ms": _percentile(shared_ms, .95),
            "readout_sha256": output_sha,
            "bitwise_equal": True, "source_text_logged": False,
        })
    result = {
        "schema": SCHEMA,
        "experiment": "real_original_pretrained_minilm_cpu_shared_encoder_same_head",
        "site": platform.system() + " isolated_analysis_not_user_dot",
        "source_script_sha256": file_sha(Path(__file__)),
        "material_sha256": {k: SHA[k] for k in ("model", "tokenizer", "vocab", "config", "locomo")},
        "numeric_probe": anchor,
        "archived_numeric_sha256": {"cls": SHA["numeric_cls"], "pooler": SHA["numeric_pooler"]},
        "real_pretrained_encoder_model_weights": True,
        "model_type": "archived_six_layer_BERT_MiniLM_not_Granite_or_421M",
        "original_bf16_weights_fp32_reference_compute": True,
        "hf_tokenizer_operator_parity_verified": False,
        "original_source_turns_model_input": True,
        "reader_natural_answer_calls": 0, "multimodal_tested": False,
        "human_task_accuracy": None, "source_owner_signature": None,
        "retention_gain_verified": False, "new_model_winner_verified": False,
        "real_target_host": False, "production_authorized": False,
        "independent_calendar_windows": 0,
        "model_load_wall_seconds": model_ready - started,
        "size": size, "resident_encoder_copies": 1,
        "resident_private_heads": size, "per_head_params": gated_head_count(),
        "actual_head_parameters": size * gated_head_count(),
        "active_per_dispatch": ACTIVE, "iterations_per_scenario": iterations,
        "rss_before_model_kib": baseline_rss,
        "rss_with_model_and_heads_kib": rss_after_model_and_heads,
        "rss_after_trials_kib": vmrss_kib(),
        "encoder_forwards_including_numeric_anchor": encoder.calls,
        "encoder_token_positions_including_anchor": encoder.tokens,
        "total_wall_seconds": time.perf_counter() - started,
        "total_cpu_seconds": time.process_time() - cpu_started,
        "energy_joules": None, "gpu_vram_bytes": None,
        "rows": rows,
    }
    validate_receipt(result)
    return result


def validate_receipt(result: dict, *, source_sha: str | None = None):
    if not isinstance(result, dict) or result.get("schema") != SCHEMA or result.get("size") not in SIZES:
        raise ValueError("V8 physical model receipt required")
    if source_sha is not None and result.get("source_script_sha256") != source_sha:
        raise ValueError("original V8 source SHA changed")
    if result.get("material_sha256") != {k: SHA[k] for k in ("model", "tokenizer", "vocab", "config", "locomo")}:
        raise ValueError("pretrained model material substitution")
    anchor = result.get("numeric_probe")
    if (not isinstance(anchor, dict) or set(anchor) != {"cls", "pooler", "same_host_reference_exact", "archived_cross_host_reference_exact"}
        or any(not isinstance(anchor[k], str) or not HEX64.fullmatch(anchor[k]) for k in ("cls", "pooler"))
        or anchor["same_host_reference_exact"] is not True
        or type(anchor["archived_cross_host_reference_exact"]) is not bool
        or anchor["archived_cross_host_reference_exact"] != (anchor["cls"] == SHA["numeric_cls"] and anchor["pooler"] == SHA["numeric_pooler"])):
        raise ValueError("missing same-host independent numeric reference or false cross-host claim")
    if result.get("archived_numeric_sha256") != {"cls": SHA["numeric_cls"], "pooler": SHA["numeric_pooler"]}:
        raise ValueError("original historical numeric reference altered")
    if any(result.get(flag) is not False for flag in (
        "hf_tokenizer_operator_parity_verified", "multimodal_tested", "retention_gain_verified",
        "new_model_winner_verified", "real_target_host", "production_authorized")):
        raise ValueError("unearned model/authority assertions")
    if result.get("real_pretrained_encoder_model_weights") is not True or result.get("original_source_turns_model_input") is not True:
        raise ValueError("original pretrained/source execution must be physically supplied")
    if result.get("human_task_accuracy") is not None or result.get("source_owner_signature") is not None or result.get("reader_natural_answer_calls") != 0 or result.get("independent_calendar_windows") != 0:
        raise ValueError("invented full-task result or issuer")
    n, m = result["size"], result.get("iterations_per_scenario")
    if type(m) is not int or not 1 <= m <= 10 or result.get("active_per_dispatch") != ACTIVE:
        raise ValueError("original trial identity changed")
    if (result.get("actual_head_parameters") != n * 6914 or result.get("per_head_params") != 6914
            or result.get("resident_private_heads") != n or result.get("resident_encoder_copies") != 1):
        raise ValueError("invalid private head/encoder copies")
    if not isinstance(result.get("rows"), list) or [r.get("scenario") for r in result["rows"]] != list(SCENARIOS):
        raise ValueError("missing original five-arm resource test")
    true_forwards = 1  # original numeric anchor
    for row in result["rows"]:
        expected = {"identical": 1, "four_inputs": 4, "distinct_inputs": 32,
                    "partitioned_identity": 32, "personalized": 32}[row["scenario"]]
        if (row.get("unique_source_authority_keys") != expected
            or row.get("active_cell_heads") != ACTIVE
            or row.get("baseline_encoder_forwards") != ACTIVE * m
            or row.get("shared_encoder_forwards") != expected * m
            or row.get("bitwise_equal") is not True or row.get("source_text_logged") is not False):
            raise ValueError("missing actual physical sharing/parity or source disclosure")
        for field in ("baseline_measured_ms", "shared_measured_ms"):
            a = row.get(field)
            if not isinstance(a, list) or len(a) != m or any(type(x) not in (int,float) or not math.isfinite(x) or x <= 0 for x in a):
                raise ValueError("invalid actual measured forward times")
        for stem, key in (("baseline", "baseline_measured_ms"), ("shared", "shared_measured_ms")):
            if (row.get(stem + "_p50_ms") != statistics.median(row[key])
                 or row.get(stem + "_p95_ms") != _percentile(row[key], .95)):
                raise ValueError("fake or inconsistent model timing")
        if not isinstance(row.get("readout_sha256"), str) or not HEX64.fullmatch(row["readout_sha256"]):
            raise ValueError("missing original output bytes SHA")
        true_forwards += (ACTIVE + expected) * m
    if result.get("encoder_forwards_including_numeric_anchor") != true_forwards:
        raise ValueError("actual forward counter does not conserve calls")
    for k in ("rss_before_model_kib", "rss_with_model_and_heads_kib", "rss_after_trials_kib", "encoder_token_positions_including_anchor"):
        if type(result.get(k)) is not int or result[k] <= 0:
            raise ValueError("missing actual physical observation")
    for k in ("model_load_wall_seconds", "total_wall_seconds", "total_cpu_seconds"):
        x = result.get(k)
        if type(x) not in (float, int) or not 0 < x < float("inf"):
            raise ValueError("missing physical CPU/wall measurements")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--size", type=int, choices=SIZES, default=64)
    p.add_argument("--iterations", type=int, default=2)
    args = p.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError("create-only original experiment receipt")
    result = measure_original(args.root, args.size, iterations=args.iterations)
    with args.output.open("x", encoding="utf-8") as out:
        out.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"size": result["size"], "encoder_forwards": result["encoder_forwards_including_numeric_anchor"],
                      "physical_pretrained": True, "production_authorized": False}, sort_keys=True))


if __name__ == "__main__":
    main()
