"""Fit the registered candidates on the publicly opted-in historical task only."""

import argparse
import ast
import importlib.util
from itertools import islice
import json
from pathlib import Path
import shutil
import time

import pyarrow.parquet as pq
import torch

from cell_experiments import coding_sft, data
from episode import stage_prompt

ROOT = Path(__file__).resolve().parent
PLAN = json.loads((ROOT / "PLAN.json").read_text())


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify(condition, message):
    if not condition:
        raise ValueError(message)


def write(path, value):
    coding_sft.write_new(path, value)


def trajectory(case, path):
    query, script, source = case.read_source(path)
    events = next(
        islice(
            pq.ParquetFile(path).iter_batches(batch_size=1, use_threads=False), 52, 53
        )
    ).to_pylist()[0]["trajectory"]
    codes = [json.loads(events[i]["extras"]) for i in (25, 27, 29)]
    create = ast.parse(codes[0]["code"]).body
    verify(
        len(create) == 1
        and ast.unparse(create[0]) == "create_file('divisible_by_7.py')",
        "creation action changed",
    )
    edit = ast.parse(codes[1]["code"]).body
    verify(
        len(edit) == 2
        and ast.unparse(edit[1]) == "edit_file(start=1, end=1, content=EDITED_CODE)",
        "write action changed",
    )
    verify(
        codes[2]["command"] == "python3 divisible_by_7.py"
        and events[31]["source"] == "agent"
        and events[31]["action"] == "message",
        "run or finish missing",
    )
    verify(
        [events[i]["observation"] for i in (26, 28, 30)]
        == ["run_ipython", "run_ipython", "run"],
        "observed states missing",
    )
    memory = [
        dict(state=s, event=i, prompt=stage_prompt(query, s), target=a)
        for s, (i, a) in enumerate(
            zip((25, 27, 29, 31), ("create", script, "run", "done"), strict=True)
        )
    ]
    memory.append(dict(state=4, event=None, prompt=case.OLD_TRAIN, target="0"))
    return source, memory


def save(model, tokenizer, root, arm, parent, runtime):
    out = root / arm
    model.save_pretrained(out, safe_serialization=True)
    tokenizer.save_pretrained(out)
    files = coding_sft.inventory(root, out.iterdir(), "base")
    for f in files:
        if Path(f["path"]).name.startswith(("tokenizer", "special_tokens")):
            f["role"] = "tokenizer"
    manifest = dict(
        parent,
        parent=data.digest(parent),
        files=files,
        runtime={**runtime, "base_directory": arm},
    )
    coding_sft.verify_model(manifest, root)
    return manifest


def fit(args):
    torch.set_num_threads(1)
    case = load_module("historical_a", args.case / "historical_a.py")
    helper = load_module("compare_heads", args.heads / "compare_heads.py")
    material, parent = helper.verify_source(args.case)
    verify(data.digest(parent) == PLAN["parent"], "different parent")
    source, memory = trajectory(case, args.parquet)
    out = args.out
    out.mkdir(parents=True, exist_ok=False)
    runtime = {**parent["runtime"], "max_input_tokens": 170, "max_new_tokens": 80}
    shutil.copytree(
        material / parent["runtime"]["base_directory"],
        out / parent["runtime"]["base_directory"],
    )
    frozen = dict(parent, runtime=runtime)
    coding_sft.verify_model(frozen, out)
    write(out / "source.json", source)
    write(out / "memory.json", memory)
    manifests = {}
    costs = {}
    pairs = [(r["prompt"], r["target"]) for r in memory]
    for arm in PLAN["arms"]:
        torch.manual_seed(731)
        start, cpu = time.perf_counter(), time.process_time()
        steps, labels, trainable = 0, 0, 0
        if arm in ("frozen", "retrieval"):
            manifest = frozen
        else:
            p = coding_sft.load_predictor(parent, material)
            try:
                model, tok = p.model, p.tokenizer
                if arm == "direct":
                    x, y, base = helper.make_features(p, pairs)
                    delta, steps = helper.direct(x, y)
                    model.config.tie_word_embeddings = False
                    model.lm_head = torch.nn.Linear(
                        base.shape[0], base.shape[1], bias=False
                    )
                    model.lm_head.weight = torch.nn.Parameter(
                        (base + delta).T.float().contiguous()
                    )
                    trainable, labels = base.numel(), y.shape[0]
                else:
                    if arm == "local_bp":
                        model.requires_grad_(False)
                        model.transformer.h[-1].requires_grad_(True)
                    params = [v for v in model.parameters() if v.requires_grad]
                    trainable = sum(v.numel() for v in params)
                    opt = torch.optim.AdamW(params, lr=0.003)
                    examples = []
                    for q, a in pairs:
                        prefix = tok.encode(
                            coding_sft.prompt_text(q), add_special_tokens=False
                        )
                        target = tok.encode(a, add_special_tokens=False) + [
                            tok.eos_token_id
                        ]
                        verify(len(prefix) <= 170 and len(target) <= 80, "budget")
                        examples.append(
                            (
                                torch.tensor([prefix + target]),
                                torch.tensor([[-100] * len(prefix) + target]),
                                len(target),
                            )
                        )
                    model.train()
                    for i in range(600):
                        row = i % len(examples)
                        if arm == "write_only" and row not in (1, 4):
                            continue
                        ids, ys, n = examples[row]
                        opt.zero_grad(set_to_none=True)
                        loss = model(input_ids=ids, labels=ys, use_cache=False).loss
                        loss.backward()
                        opt.step()
                        labels += n
                        steps += 1
                manifest = save(model, tok, out, arm, parent, runtime)
            finally:
                p.close()
        write(out / (arm + ".json"), manifest)
        manifests[arm] = data.digest(manifest)
        costs[arm] = dict(
            seconds=time.perf_counter() - start,
            cpu_seconds=time.process_time() - cpu,
            parameter_count=trainable,
            update_steps=steps,
            supervised_token_presentations=labels,
        )
    write(out / "training-costs.json", costs)
    freeze = dict(
        parent=PLAN["parent"],
        plan=coding_sft.file_hash(ROOT / "PLAN.json"),
        inputs={
            n: coding_sft.file_hash(out / n) for n in ("source.json", "memory.json")
        },
        program={
            n: coding_sft.file_hash(ROOT / n)
            for n in ("train.py", "episode.py", "evaluate.py")
        },
        manifests=manifests,
        torch=str(torch.__version__),
    )
    write(out / "freeze.json", freeze)
    print(json.dumps(dict(freeze=data.digest(freeze), costs=costs)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    for field in ("case", "heads", "parquet", "out"):
        ap.add_argument(field, type=Path)
    fit(ap.parse_args())
