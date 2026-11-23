"""Compare two output-weight solvers on the public historical case pinned in PLAN.json."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

import torch
from transformers import GPT2LMHeadModel

from cell_experiments import coding_sft, data


def load_case(path):
    spec = importlib.util.spec_from_file_location(
        "historical_a", path / "historical_a.py"
    )
    case = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(case)
    return case


def verify_source(case_dir):
    plan = json.loads(Path(__file__).with_name("PLAN.json").read_text())
    run = case_dir / "run"
    frozen = json.loads((run / "FROZEN.json").read_text())
    parent = frozen["parent"]
    if (
        data.digest(frozen) != plan["source_freeze"]
        or data.digest(parent) != plan["source_parent"]
    ):
        raise ValueError("Source freeze or parent differs from study plan")
    coding_sft.verify_model(parent, run)
    return run, parent


def make_features(predictor, pairs):
    rows, targets, scales = [], [], []
    tok = predictor.tokenizer
    with torch.no_grad():
        for prompt, answer in pairs:
            prefix = tok.encode(
                coding_sft.prompt_text(prompt), add_special_tokens=False
            )
            labels = tok.encode(answer, add_special_tokens=False) + [tok.eos_token_id]
            ids = torch.tensor([prefix + labels[:-1]])
            features = predictor.model.transformer(ids).last_hidden_state[
                0, len(prefix) - 1 :
            ]
            rows.append(features.double())
            targets.extend(labels)
            scales.extend([1 / (len(pairs) * len(labels)) ** 0.5] * len(labels))
    x = torch.cat(rows)
    y = torch.nn.functional.one_hot(
        torch.tensor(targets), num_classes=len(tok)
    ).double()
    weight = predictor.model.lm_head.weight.detach().double().T.contiguous()
    scales = torch.tensor(scales, dtype=torch.float64)[:, None]
    return x * scales, (y - x @ weight) * scales, weight


REGULARIZATION = 0.01


def direct(x, y):
    gram = x.T @ x + REGULARIZATION * torch.eye(x.shape[1], dtype=x.dtype)
    return torch.linalg.solve(gram, x.T @ y), 1


def bp(x, y):
    step = 1 / (2 * (torch.linalg.matrix_norm(x, ord=2).square() + REGULARIZATION))
    delta = torch.zeros(x.shape[1], y.shape[1], dtype=x.dtype, requires_grad=True)
    initial = None
    for i in range(240):
        loss = (x @ delta - y).square().sum() + REGULARIZATION * delta.square().sum()
        (grad,) = torch.autograd.grad(loss, delta)
        norm = grad.norm().item()
        if initial is None:
            initial = norm
        if norm <= 1e-8 * initial:
            return delta.detach(), i
        with torch.no_grad():
            delta.sub_(grad * step)
    return delta.detach(), 240


def save_arm(name, out, run, manifest, predictor, weight):
    model = GPT2LMHeadModel.from_pretrained(
        run / manifest["runtime"]["base_directory"], local_files_only=True
    )
    model.config.tie_word_embeddings = False
    head = torch.nn.Linear(weight.shape[0], weight.shape[1], bias=False)
    head.weight = torch.nn.Parameter(weight.T.float().contiguous())
    model.lm_head = head
    arm = out / name
    model.save_pretrained(arm, safe_serialization=True)
    predictor.tokenizer.save_pretrained(arm)
    files = coding_sft.inventory(out, arm.iterdir(), "base")
    for item in files:
        if Path(item["path"]).name.startswith(("tokenizer", "special_tokens")):
            item["role"] = "tokenizer"
    result = dict(
        manifest,
        files=files,
        parent=data.digest(manifest),
        runtime={**manifest["runtime"], "base_directory": name},
    )
    coding_sft.verify_model(result, out)
    coding_sft.write_new(out / (name + ".json"), result)


def cold(args, case, prompt, target):
    start = time.perf_counter()
    manifest = json.loads((args.out / (args.arm + ".json")).read_bytes())
    predictor = coding_sft.load_predictor(manifest, args.out)
    try:
        load_time = time.perf_counter() - start
        result = {}
        for label, q in (("known_A", prompt), ("old", case.OLD_EVAL)):
            raw = predictor.predict({"task": {"input": q}})
            answer = raw.pop("answer")
            raw.update(
                answer_sha256=case.hashtext(answer),
                bytes=len(answer.encode()),
                success=case.equivalent(answer, target)
                if label == "known_A"
                else answer.strip() == "0",
            )
            if label == "known_A":
                raw["byte_exact"] = answer == target
            result[label] = raw
        coding_sft.write_new(
            args.out / (args.arm + "-cold.json"),
            dict(rows=result, load_seconds=load_time, pid=os.getpid(), arm=args.arm),
        )
    finally:
        predictor.close()


def run(args):
    torch.set_num_threads(1)
    case = load_case(args.case_dir)
    prompt, target, _ = case.read_source(args.parquet)
    material, manifest = verify_source(args.case_dir)
    if args.arm:
        cold(args, case, prompt, target)
        return
    args.out.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    predictor = coding_sft.load_predictor(manifest, material)
    try:
        loaded = time.perf_counter()
        x, y, base = make_features(predictor, [(prompt, target), (case.OLD_TRAIN, "0")])
        formed = time.perf_counter()
        methods = {"direct": direct, "bp": bp}
        raw_times = {name: [] for name in methods}
        fits = {}
        for method in methods.values():
            method(x, y)
        for i in range(6):
            for name in ("direct", "bp") if i % 2 == 0 else ("bp", "direct"):
                tick = time.perf_counter()
                delta, steps = methods[name](x, y)
                elapsed = time.perf_counter() - tick
                raw_times[name].append(elapsed)
                if name in fits and not torch.equal(delta, fits[name][0]):
                    raise ValueError("Repeated fit changed fitted coordinates")
                fits[name] = delta, steps
        result = {}
        for name, (delta, steps) in fits.items():
            objective = (
                (x @ delta - y).square().sum() + REGULARIZATION * delta.square().sum()
            ).item()
            result[name] = dict(
                steps=steps,
                objective=objective,
                seconds=raw_times[name],
                median_seconds=statistics.median(raw_times[name]),
            )
            save_arm(name, args.out, material, manifest, predictor, base + delta)
        coding_sft.write_new(
            args.out / "fits.json",
            dict(
                arms=result,
                source_parent=data.digest(manifest),
                half_weight_each=True,
                supervised_positions=x.shape[0],
                editable_parameters=base.numel(),
                load_seconds=loaded - start,
                feature_seconds=formed - loaded,
                torch=str(torch.__version__),
                python=sys.version.split()[0],
                threads=torch.get_num_threads(),
            ),
        )
    finally:
        predictor.close()
    for name in methods:
        subprocess.run(
            [
                sys.executable,
                __file__,
                str(args.case_dir),
                str(args.parquet),
                str(args.out),
                "--arm",
                name,
            ],
            check=True,
            timeout=180,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("parquet", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--arm", choices=["direct", "bp"])
    run(parser.parse_args())
