"""V9: original MiniLM frozen-feature source-disjoint LoCoMo continual ranker.

Research only, deliberately incapable of model promotion. Two separate processes:
  python stem_v9_original_continual.py run --original-root ROOT --output-dir PRIVATE
  python stem_v9_original_continual.py score --original-root ROOT --output-dir PRIVATE
No heldout answers/evidence enter the run process. Original source/QA is public,
but no OS sandbox or independent data issuer is claimed. Exact original archived
BF16 MiniLM is evaluated through the previously implemented experimental FP32
PyTorch BERT reference; this is NOT official HF tokenizer/operator parity.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import time

SCHEMA = "hepta.stem.v9.original-minilm-locomo-continual-shadow.v1"
OLD = ("conv-26", "conv-30", "conv-41")
NEW = ("conv-42", "conv-43", "conv-44")
HELD = ("conv-47", "conv-48", "conv-49", "conv-50")
SEEDS = (41, 47, 53)
ARMS = ("frozen", "new_only", "low_lr", "equal_budget_replay")
STEPS_OLD = 240
STEPS_NEW = 240
BATCH_SIZE = 64
TOP_K = 3
TOKEN_LIMIT = 128
HEAD_PARAMETERS = 6914
WORD = re.compile(r"\w+", re.UNICODE)


def jbytes(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(obj):
    return hashlib.sha256(jbytes(obj)).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for data in iter(lambda: f.read(1 << 20), b""):
            h.update(data)
    return h.hexdigest()


def emit_once(path, obj):
    path = Path(path)
    with path.open("xb") as f:
        f.write(jbytes(obj) + b"\n")
        f.flush()
        import os
        os.fsync(f.fileno())


def parse_source_only(raw):
    """Complete 10-family inventory, no labels. Declared split, no filtering."""
    if not isinstance(raw, list) or len(raw) != 10:
        raise ValueError("10 original source roots required")
    families = {}
    for item in raw:
        fam = item.get("sample_id")
        if fam in families or not isinstance(fam, str):
            raise ValueError("duplicate/invalid source family")
        conv = item.get("conversation")
        if not isinstance(conv, dict):
            raise ValueError("invalid original conversation")
        passages = []
        for key, value in conv.items():
            if re.fullmatch(r"session_\d+", key) is None or not isinstance(value, list):
                continue
            for turn in value:
                if not isinstance(turn, dict) or not all(k in turn for k in ("speaker", "dia_id", "text")):
                    raise ValueError("malformed original source turn")
                sid = turn["dia_id"]
                text = f'{turn["speaker"]}: {turn["text"]}'
                if not isinstance(sid, str) or not text.strip() or not isinstance(turn["text"], str):
                    raise ValueError("malformed original source identity")
                passages.append({"id": sid, "text": text})
        questions = []
        qa = item.get("qa")
        if not isinstance(qa, list):
            raise ValueError("questions missing")
        for idx, obj in enumerate(qa):
            q = obj.get("question")
            if not isinstance(q, str) or not q.strip():
                raise ValueError("malformed original question")
            questions.append({"id": f"{fam}/q{idx}", "text": q})
        if (len(passages) < 100 or len(questions) < 100
                or len({x["id"] for x in passages}) != len(passages)):
            raise ValueError("incomplete source or question inventory")
        families[fam] = {"passages": passages, "questions": questions}
    if set(families) != set(OLD + NEW + HELD):
        raise ValueError("split not complete/unaltered")
    return {"schema": SCHEMA + ".source-only", "families": families,
            "source_contains_publisher_gold": False,
            "future_calendar_windows": 0,
            "production_authorized": False}


def parse_train_labels(raw, sources):
    """Read only publisher weak source refs from OLD/NEW, never HELD."""
    out = {}
    for item in raw:
        fam = item["sample_id"]
        if fam not in OLD + NEW:
            continue
        known = {d["id"] for d in sources["families"][fam]["passages"]}
        for idx, q in enumerate(item["qa"]):
            ev = q.get("evidence")
            valid = ([v for v in ev if isinstance(v, str) and v in known]
                     if isinstance(ev, list) else [])
            # Do not pretend compound references or missing docs are positive.
            out[f"{fam}/q{idx}"] = sorted(set(valid))
    expected = {q["id"] for fam in OLD + NEW for q in sources["families"][fam]["questions"]}
    if set(out) != expected:
        raise ValueError("training label roster incomplete")
    return {"schema": SCHEMA + ".train-only-gold", "labels": out,
            "heldout_labels_present": False, "production_authorized": False}


def weak_gold(raw, sources):
    """Independent AFTER-SEAL scorer; full denominator, unknowns explicit."""
    out = {}
    for item in raw:
        fam = item["sample_id"]
        if fam not in HELD:
            continue
        known = {d["id"] for d in sources["families"][fam]["passages"]}
        for idx, q in enumerate(item["qa"]):
            refs = q.get("evidence")
            if not isinstance(refs, list) or not refs:
                out[f"{fam}/q{idx}"] = None
            elif not all(isinstance(v, str) and v in known for v in refs):
                out[f"{fam}/q{idx}"] = None
            else:
                out[f"{fam}/q{idx}"] = set(refs)
    expected = {q["id"] for fam in HELD for q in sources["families"][fam]["questions"]}
    if set(out) != expected:
        raise ValueError("heldout score denominator changed")
    return out


def lexical_bm25(question, passages):
    """Complete-source cheap lexical floor, no supervision or pretrained compute."""
    texts = [[w.lower() for w in WORD.findall(p["text"])] for p in passages]
    q = set(w.lower() for w in WORD.findall(question))
    if not texts:
        raise ValueError("empty retrieval family")
    n = len(texts)
    avg = sum(map(len, texts)) / n
    df = Counter(w for row in texts for w in set(row))
    scores = []
    for row in texts:
        tf = Counter(row)
        scale = 1.2 * (0.25 + 0.75 * len(row) / avg)
        s = sum(math.log1p((n - df[t] + 0.5) / (df[t] + 0.5))
                * (f * 2.2) / (f + scale) for t in q if (f := tf[t]) > 0)
        scores.append(s)
    return scores


def topk(scores, passages, k=TOP_K):
    if len(scores) != len(passages) or len(passages) < k:
        raise ValueError("invalid complete source ranking")
    if any(not math.isfinite(float(x)) for x in scores):
        raise ValueError("nonfinite source score")
    order = sorted(range(len(passages)), key=lambda i: (-float(scores[i]), passages[i]["id"]))
    return [passages[i]["id"] for i in order[:k]]


def encode_batch(model, ids):
    """Padded, masked FP32 complete original MiniLM reference; count BERT batches."""
    import torch
    import torch.nn.functional as F
    if not ids or len(ids) > 16 or any(not row or len(row) > TOKEN_LIMIT for row in ids):
        raise ValueError("unbounded or missing tokenizer inputs")
    cfg = model.config
    h, heads = int(cfg["hidden_size"]), int(cfg["num_attention_heads"])
    n = max(map(len, ids))
    tokens = torch.tensor([row + [0] * (n - len(row)) for row in ids], dtype=torch.int64)
    valid = tokens.ne(0)
    g = model.weights.__getitem__
    x = g("embeddings.word_embeddings.weight")[tokens]
    x = x + g("embeddings.position_embeddings.weight")[:n][None, :, :]
    x = x + g("embeddings.token_type_embeddings.weight")[0]
    x = F.layer_norm(x, (h,), g("embeddings.LayerNorm.weight"),
                     g("embeddings.LayerNorm.bias"), eps=cfg["layer_norm_eps"])
    missing = (~valid).unsqueeze(1).unsqueeze(2)
    for layer in range(int(cfg["num_hidden_layers"])):
        pre = f"encoder.layer.{layer}."
        att = pre + "attention.self."
        q, k, v = (F.linear(x, g(att + w + ".weight"), g(att + w + ".bias"))
                    .reshape(len(ids), n, heads, h // heads).transpose(1, 2)
                    for w in ("query", "key", "value"))
        scores = (q @ k.transpose(-1, -2) / math.sqrt(h // heads)).masked_fill(missing, -1e4)
        y = (scores.softmax(-1) @ v).transpose(1, 2).contiguous().reshape(len(ids), n, h)
        prefix = pre + "attention.output."
        y = F.linear(y, g(prefix + "dense.weight"), g(prefix + "dense.bias"))
        x = F.layer_norm(x + y, (h,), g(prefix + "LayerNorm.weight"),
                         g(prefix + "LayerNorm.bias"), eps=cfg["layer_norm_eps"])
        prefix = pre + "intermediate.dense."
        y = F.gelu(F.linear(x, g(prefix + "weight"), g(prefix + "bias")))
        prefix = pre + "output."
        y = F.linear(y, g(prefix + "dense.weight"), g(prefix + "dense.bias"))
        x = F.layer_norm(x + y, (h,), g(prefix + "LayerNorm.weight"),
                         g(prefix + "LayerNorm.bias"), eps=cfg["layer_norm_eps"])
    pooled = (x * valid.unsqueeze(-1)).sum(1) / valid.sum(1, keepdim=True)
    pooled = F.normalize(pooled, dim=-1)
    model.calls += 1
    model.tokens += int(valid.sum())
    return pooled.cpu()


class GatedHead:
    """Same 6,914 scalar budget as V7, real differentiable Torch parameters."""
    def __init__(self, seed):
        import torch
        torch.manual_seed(seed)
        self.up = torch.nn.Parameter(torch.randn(384, 8) * 0.015)
        self.down = torch.nn.Parameter(torch.randn(8, 384) * 0.015)
        self.gate = torch.nn.Parameter(torch.randn(384) * 0.015)
        self.readout = torch.nn.Parameter(torch.randn(384) * 0.015)
        self.biases = torch.nn.Parameter(torch.zeros(2))
        self.params = (self.up, self.down, self.gate, self.readout, self.biases)
        if sum(p.numel() for p in self.params) != HEAD_PARAMETERS:
            raise ValueError("wrong physical private Head budget")

    def __call__(self, x):
        import torch
        compressed = torch.relu(x @ self.down.T)
        resid = compressed @ self.up.T
        gate = torch.sigmoid(x @ self.gate + self.biases[0])
        return ((x + gate.unsqueeze(-1) * resid) * self.readout).sum(-1) + self.biases[1]

    def clone(self):
        import torch
        copy = GatedHead(7347)
        with torch.no_grad():
            for x, y in zip(copy.params, self.params):
                x.copy_(y)
        return copy


def feature(q, d):
    """Fixed 384D query-source product. Frozen pretrained embeddings only."""
    return q * d * 384.0


def sample_pairs(sources, train, embeddings, fams):
    import torch
    xs, ys = [], []
    per = {}
    for fam in fams:
        a = sources["families"][fam]
        docs = a["passages"]
        for q in a["questions"]:
            positive = train["labels"][q["id"]]
            if not positive:
                continue
            good = next((x for x in docs if x["id"] == positive[0]), None)
            if good is None:
                raise ValueError("training evidence source absent")
            qt = embeddings[q["id"]]
            # Each original question receives one positive and one hard lexical negative;
            # fixed source-only lexical order, excluding TRAIN gold only for negative.
            bm = lexical_bm25(q["text"], docs)
            bad = next((docs[i] for i in sorted(range(len(docs)), key=lambda j: (-bm[j], docs[j]["id"]))
                        if docs[i]["id"] not in positive), None)
            if bad is None:
                raise ValueError("no train negative available")
            for doc, y in ((good, 1.), (bad, 0.)):
                xs.append(feature(qt, embeddings[fam + "/" + doc["id"]]))
                ys.append(y)
            per[q["id"]] = 1
    if len(xs) < 100 or len(xs) != 2 * len(per):
        raise ValueError("train source/weak label coverage insufficient")
    return torch.stack(xs), torch.tensor(ys, dtype=torch.float32), len(per)


def train(head, x, y, *, seed, steps, lr, replay=None):
    import torch
    import torch.nn.functional as F
    if steps != STEPS_OLD and steps != STEPS_NEW:
        raise ValueError("unregistered train-work cap")
    rng = torch.Generator().manual_seed(seed)
    opt = torch.optim.Adam(head.params, lr=lr, foreach=False)
    count_old = count_new = 0
    t0 = time.process_time()
    for i in range(steps):
        if replay is None:
            indices = torch.randint(len(x), (BATCH_SIZE,), generator=rng)
            row, lbl = x[indices], y[indices]
            count_new += BATCH_SIZE
        else:
            ox, oy = replay
            a = torch.randint(len(x), (BATCH_SIZE // 2,), generator=rng)
            b = torch.randint(len(ox), (BATCH_SIZE // 2,), generator=rng)
            row = torch.cat((x[a], ox[b]));lbl = torch.cat((y[a], oy[b]))
            count_old += BATCH_SIZE // 2
            count_new += BATCH_SIZE // 2
        opt.zero_grad(set_to_none=True)
        scores = head(row)
        loss = F.binary_cross_entropy_with_logits(scores, lbl)
        if not torch.isfinite(loss):
            raise ValueError("nonfinite actual optimizer result")
        loss.backward()
        opt.step()
    return {"optimizer_steps": steps, "train_example_exposures": count_new + count_old,
            "new_examples": count_new, "old_replay_examples": count_old,
            "process_cpu_seconds": time.process_time() - t0}


def private_head_sha(head):
    import torch
    h = hashlib.sha256()
    for value in head.params:
        h.update(value.detach().to(torch.float32).cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


def main_run(original_root, output_dir):
    """Run original physical feature creation and learning; do not open heldout gold."""
    import numpy as np
    import torch
    from stem_v8_pretrained_share import SHA, OriginalMiniLM, bare_wordpiece, verify_material
    torch.set_num_threads(2)
    original_root, output_dir = Path(original_root), Path(output_dir)
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError("one fresh create-only V9 experiment per output root")
    verify_material(original_root)
    if file_sha(original_root / "locomo.json") != SHA["locomo"]:
        raise ValueError("original LoCoMo material mismatch")
    raw = json.loads((original_root / "locomo.json").read_bytes())
    sources = parse_source_only(raw)
    train_labels = parse_train_labels(raw, sources)
    # The original material owner is released now. The model/training code consumes
    # only the saved source-only snapshot and TRAIN labels; no test answer data.
    del raw
    output_dir.mkdir(parents=True, exist_ok=False)
    emit_once(output_dir / "source-only.json", sources)
    emit_once(output_dir / "train-only-labels.json", train_labels)
    source_sha = file_sha(output_dir / "source-only.json")
    train_sha = file_sha(output_dir / "train-only-labels.json")
    src = json.loads((output_dir / "source-only.json").read_bytes())
    train_doc = json.loads((output_dir / "train-only-labels.json").read_bytes())
    model_start = time.perf_counter()
    model = OriginalMiniLM(original_root)
    records = []
    for fam in sorted(src["families"]):
        family = src["families"][fam]
        records.extend((fam + "/" + doc["id"], doc["text"]) for doc in family["passages"])
        records.extend((q["id"], q["text"]) for q in family["questions"])
    if len(set(key for key, _ in records)) != len(records):
        raise ValueError("encoder record IDs collided")
    vectors = {}
    batch_count = 0
    with torch.inference_mode():
        for off in range(0, len(records), 16):
            group = records[off:off + 16]
            ids = [bare_wordpiece(text, model.vocab) for _, text in group]
            got = encode_batch(model, ids)
            for (key, _), v in zip(group, got, strict=True):
                vectors[key] = v
            batch_count += 1
    encode_wall = time.perf_counter() - model_start
    if len(vectors) != len(records) or model.calls != batch_count:
        raise ValueError("not all original model forwards accounted")
    # Original features remain PRIVATE and are not uploaded to public GitHub.
    arr = torch.stack([vectors[key] for key, _ in records]).numpy()
    np.save(output_dir / "private-vectors.npy", arr, allow_pickle=False)
    torch_vec_sha = hashlib.sha256(arr.tobytes()).hexdigest()
    old_x, old_y, old_q = sample_pairs(src, train_doc, vectors, OLD)
    new_x, new_y, new_q = sample_pairs(src, train_doc, vectors, NEW)
    train_rows = []
    decisions = {}
    precommit = {"schema": SCHEMA + ".registered-plan", "source_sha256": source_sha,
                 "train_sha256": train_sha, "weights_sha256": SHA["model"],
                 "tokenizer_sha256": SHA["tokenizer"], "dataset_sha256": SHA["locomo"],
                 "families_old": OLD, "families_new": NEW, "families_heldout": HELD,
                 "arms": ARMS, "seeds": SEEDS, "head_parameters": HEAD_PARAMETERS,
                 "steps_old": STEPS_OLD, "steps_new": STEPS_NEW,
                 "batch": BATCH_SIZE, "top_k": TOP_K,
                 "heldout_gold_admitted": False, "no_selected_model": True,
                 "production_authorized": False}
    emit_once(output_dir / "precommit.json", precommit)
    with torch.no_grad():
        # Fixed source-only cheap controls; one shared across all seeds.
        for fam in HELD:
            a = src["families"][fam]
            docs = a["passages"]
            matrix = torch.stack([vectors[fam + "/" + doc["id"]] for doc in docs])
            for q in a["questions"]:
                bm = lexical_bm25(q["text"], docs)
                dense = (matrix @ vectors[q["id"]]).tolist()
                decisions[q["id"]] = {"bm25_full": topk(bm, docs),
                                      "dense_full": topk(dense, docs)}
    for seed in SEEDS:
        head = GatedHead(seed)
        first = train(head, old_x, old_y, seed=seed * 100 + 1,
                      steps=STEPS_OLD, lr=0.001)
        start_head_sha = private_head_sha(head)
        for arm in ARMS:
            state = head.clone()
            if arm == "frozen":
                info = dict(optimizer_steps=0, train_example_exposures=0,
                            new_examples=0, old_replay_examples=0,
                            process_cpu_seconds=0.0)
            else:
                lr = 0.0002 if arm == "low_lr" else 0.001
                info = train(state, new_x, new_y, seed=seed * 1000 + 7,
                             steps=STEPS_NEW, lr=lr,
                             replay=(old_x, old_y) if arm == "equal_budget_replay" else None)
            first_id = f"seed{seed}/{arm}"
            train_rows.append({"arm": arm, "seed": seed, "warmup": first,
                               "continuation": info,
                               "head_start_sha256": start_head_sha,
                               "head_end_sha256": private_head_sha(state),
                               "head_parameters": HEAD_PARAMETERS})
            with torch.no_grad():
                for fam in HELD:
                    a = src["families"][fam]
                    docs = a["passages"]
                    ds = torch.stack([vectors[fam + "/" + doc["id"]] for doc in docs])
                    for q in a["questions"]:
                        qv = vectors[q["id"]]
                        s = state(feature(qv, ds)).tolist()
                        decisions[q["id"]][first_id] = topk(s, docs)
    # Seal the ORIGINAL per-question source-only rankings before any heldout
    # publisher support is opened in a separate scorer process.
    predicted = {"schema": SCHEMA + ".original-prediction-seal",
                 "precommit_sha256": file_sha(output_dir / "precommit.json"),
                 "source_sha256": source_sha,
                 "full_heldout_denominator": sum(len(src["families"][f]["questions"]) for f in HELD),
                 "top_k": TOP_K, "rankings": decisions,
                 "heldout_publisher_gold_not_read": True, "production_authorized": False}
    emit_once(output_dir / "original-predictions.json", predicted)
    receipt = {"schema": SCHEMA + ".original-physical-receipt",
               "original_source_sha256": SHA["locomo"],
               "original_model_sha256": SHA["model"],
               "original_tokenizer_sha256": SHA["tokenizer"],
               "precommit_sha256": file_sha(output_dir / "precommit.json"),
               "source_sha256": source_sha, "train_sha256": train_sha,
               "original_predictions_sha256": file_sha(output_dir / "original-predictions.json"),
               "private_feature_matrix_sha256": torch_vec_sha,
               "actual_original_encoder_forward_batches": model.calls,
               "encoded_original_sources_and_questions": len(records),
               "actual_original_encoder_token_positions": model.tokens,
               "encoder_and_input_preparation_wall_seconds": encode_wall,
               "physical_train_rows": train_rows, "old_train_question_count": old_q,
               "new_train_question_count": new_q,
               "frozen_source_only_rankings": True,
               "original_heldout_reader_answers": 0,
               "human_verified_end_to_end_task_success": None,
               "original_hf_operator_tokenizer_parity_verified": False,
               "original_future_calendar_windows": 0,
               "signed_model_owner": False,
               "complete_lifecycle_cost_matched": False,
               "stem_winner_verified": False,
               "retention_repair_verified": False,
               "production_authorized": False}
    emit_once(output_dir / "physical-receipt.json", receipt)
    return {"encoder_batches": model.calls, "questions_heldout": predicted["full_heldout_denominator"],
            "sealed_predictions_sha256": receipt["original_predictions_sha256"],
            "no_heldout_label_or_promotion_claim": True}


def score_original(original_root, output_dir):
    """Separate, after-seal read-only scorer. Outputs sanitized aggregate only."""
    from stem_v8_pretrained_share import SHA, verify_material
    output_dir = Path(output_dir)
    src_path = output_dir / "source-only.json"
    train_path = output_dir / "train-only-labels.json"
    plan_path = output_dir / "precommit.json"
    pred_path = output_dir / "original-predictions.json"
    physical_path = output_dir / "physical-receipt.json"
    for p in (src_path, train_path, plan_path, pred_path, physical_path):
        if not p.is_file() or p.is_symlink() or p.stat().st_size > 18_000_000:
            raise ValueError("missing/noncanonical original sealed material")
    original_root = Path(original_root)
    verify_material(original_root)
    if file_sha(original_root / "locomo.json") != SHA["locomo"]:
        raise ValueError("source has changed before scorer opened gold")
    src = json.loads(src_path.read_bytes())
    train_only = json.loads(train_path.read_bytes())
    plan = json.loads(plan_path.read_bytes())
    pred = json.loads(pred_path.read_bytes())
    receipt = json.loads(physical_path.read_bytes())
    if (src.get("schema") != SCHEMA + ".source-only"
        or src.get("source_contains_publisher_gold") is not False
        or train_only.get("schema") != SCHEMA + ".train-only-gold"
        or train_only.get("heldout_labels_present") is not False
        or set(train_only.get("labels", {})) != {
            q["id"] for f in OLD + NEW for q in src["families"][f]["questions"]}
        or pred.get("schema") != SCHEMA + ".original-prediction-seal"
        or pred.get("heldout_publisher_gold_not_read") is not True
        or plan.get("heldout_gold_admitted") is not False
        or plan.get("arms") != list(ARMS)
        or plan.get("seeds") != list(SEEDS)
        or receipt.get("production_authorized") is not False
        or receipt.get("original_predictions_sha256") != file_sha(pred_path)
        or receipt.get("precommit_sha256") != file_sha(plan_path)
        or pred.get("precommit_sha256") != file_sha(plan_path)
        or plan.get("source_sha256") != file_sha(src_path)
        or plan.get("train_sha256") != file_sha(train_path)
        or pred.get("source_sha256") != file_sha(src_path)
        or pred.get("top_k") != TOP_K):
        raise ValueError("original receipt/precommit/heldout isolation mismatch")
    roster = {q["id"]: fam for fam in HELD for q in src["families"][fam]["questions"]}
    if set(pred.get("rankings", {})) != set(roster):
        raise ValueError("missing or duplicate original question predictions")
    expect_arms = {"bm25_full", "dense_full"} | {
        f"seed{seed}/{arm}" for seed in SEEDS for arm in ARMS}
    for qid, arms in pred["rankings"].items():
        if set(arms) != expect_arms:
            raise ValueError("arm inventory or original complete denominator changed")
        valid = {d["id"] for d in src["families"][roster[qid]]["passages"]}
        for arm, ids in arms.items():
            if (not isinstance(ids, list) or len(ids) != TOP_K or len(set(ids)) != TOP_K
                    or any(x not in valid for x in ids)):
                raise ValueError("invented, duplicated or missing final evidence")
    orig = json.loads((original_root / "locomo.json").read_bytes())
    weak = weak_gold(orig, src)
    metrics = {}
    for arm in sorted(expect_arms):
        scores = {}
        for fam in HELD:
            ids = [q["id"] for q in src["families"][fam]["questions"]]
            any_hits = all_hits = supported = unknown = 0
            for qid in ids:
                truth = weak[qid]
                if truth is None:
                    unknown += 1
                    continue
                supported += 1
                got = set(pred["rankings"][qid][arm])
                any_hits += bool(truth & got)
                all_hits += truth.issubset(got)
            scores[fam] = dict(total_questions=len(ids), weak_supported=supported,
                               unknown_annotation=unknown, any_support_top3=any_hits,
                               all_support_top3=all_hits)
        metrics[arm] = scores
    # Fail closed: no threshold or winner is accepted from publisher-weak evidence.
    report = {"schema": SCHEMA + ".postseal-weak-scored", "precommit_sha256": file_sha(plan_path),
              "original_predictions_sha256": file_sha(pred_path),
              "original_source_sha256": SHA["locomo"],
              "heldout_source_family_count": len(HELD),
              "heldout_question_total": len(roster),
              "complete_original_source_universe": True,
              "independent_calendar_future_windows": 0,
              "publisher_weak_retrieval_proxy_only": True,
              "independent_human_task_success": None,
              "reader_full_task_answer_calls": 0,
              "equal_total_lifecycle_compute": False,
              "retention_old_training_panel_verified": False,
              "cross_task_learning_superiority_verified": False,
              "stem_winner_verified": False,
              "production_authorized": False,
              "per_arm_source_root_aggregates": metrics}
    emit_once(output_dir / "postseal-weak-score.json", report)
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=("run", "score"))
    p.add_argument("--original-root", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    result = (main_run(args.original_root, args.output_dir) if args.stage == "run"
              else score_original(args.original_root, args.output_dir))
    if args.stage == "score":
        print(json.dumps({k: v for k, v in result.items()
                          if k != "per_arm_source_root_aggregates"}, sort_keys=True))
    else:
        print(json.dumps(result, sort_keys=True))

if __name__ == "__main__":
    main()
