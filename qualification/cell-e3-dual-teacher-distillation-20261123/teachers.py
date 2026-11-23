"""Run counterbalanced constrained-choice inference using the original local teachers."""

import argparse
import hashlib
import json
import platform
import time
from pathlib import Path
import torch
from transformers import AutoModelForCausalLM, AutoModelForSeq2SeqLM, AutoTokenizer
import transformers
from panel import panel, digest

MODELS = (
    ("t5", "flan-t5-small", "0fc9ddf78a1e988dac52e2dac162b0ede4fd74ab"),
    ("smol", "SmolLM2-135M-Instruct", "12fd25f77366fa6b3b4b768ec3050bf629380bac"),
)
PANEL_HASH = "5bae588836fd72c8aca79351bacbef87929605698de2bd1e921a268017371835"


def sha_file(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def question(prompt, reverse):
    options = "A. No\nB. Yes" if reverse else "A. Yes\nB. No"
    return f"{prompt}\n{options}\nAnswer with the letter A or B."


def measure(model_dir, records, name, revision, batch):
    identity = json.loads((model_dir / "identity.json").read_bytes())
    if identity["revision"] != revision or identity["license"] != "apache-2.0":
        raise ValueError("Model identity differs")
    before = time.perf_counter()
    cpu_before = time.process_time()
    tok = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    is_t5 = name == "t5"
    cls = AutoModelForSeq2SeqLM if is_t5 else AutoModelForCausalLM
    dtype = torch.float32 if is_t5 else torch.bfloat16
    model = cls.from_pretrained(
        model_dir, local_files_only=True, dtype=dtype, low_cpu_mem_usage=True
    ).eval()
    ids = [tok.encode(label, add_special_tokens=False) for label in ("A", "B")]
    if any(len(v) != 1 for v in ids):
        raise ValueError(f"Multi-token choice {ids}")
    a, b = [v[0] for v in ids]
    tok.padding_side = "right" if is_t5 else "left"
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    queued = []
    for item in records:
        for reverse in (False, True):
            q = question(item["prompt"], reverse)
            if not is_t5:
                q = tok.apply_chat_template(
                    [{"role": "user", "content": q}],
                    tokenize=False,
                    add_generation_prompt=True,
                )
            queued.append(q)
    start, cpu = time.perf_counter(), time.process_time()
    scores, input_tokens = [], 0
    with torch.inference_mode():
        for k in range(0, len(queued), batch):
            t = tok(
                queued[k : k + batch],
                return_tensors="pt",
                padding=True,
                add_special_tokens=is_t5,
            )
            ids, mask = t["input_ids"], t["attention_mask"]
            if is_t5:
                d = torch.full(
                    (len(ids), 1), model.config.decoder_start_token_id, dtype=torch.long
                )
                out = model(
                    input_ids=ids,
                    attention_mask=mask,
                    decoder_input_ids=d,
                    use_cache=False,
                ).logits[:, 0, :]
            else:
                positions = (mask.cumsum(1) - 1).clamp(min=0)
                out = model(
                    input_ids=ids,
                    attention_mask=mask,
                    position_ids=positions,
                    use_cache=False,
                    logits_to_keep=1,
                ).logits[:, 0, :]
            scores.extend((out[:, a] - out[:, b]).tolist())
            input_tokens += int(mask.sum())
    rows = []
    for i, item in enumerate(records):
        forward, reverse = scores[2 * i : 2 * i + 2]
        margin = forward - reverse
        rows.append(
            {
                "id": item["id"],
                "forward_A_minus_B": forward,
                "reverse_A_minus_B": reverse,
                "label": int(margin > 0),
                "margin": margin,
            }
        )
    elapsed, cpu_time = time.perf_counter() - start, time.process_time() - cpu
    return {
        "teacher": name,
        "dtype": str(dtype),
        "identity": identity,
        "original_weights_sha256": sha_file(model_dir / "model.safetensors"),
        "tokenizer_sha256": sha_file(model_dir / "tokenizer.json"),
        "choice_token_ids": [a, b],
        "rows": rows,
        "input_tokens": input_tokens,
        "forwards_examples": len(queued),
        "wall_inference_s": elapsed,
        "cpu_inference_s": cpu_time,
        "wall_load_prompt_and_inference_s": time.perf_counter() - before,
        "cpu_load_prompt_and_inference_s": time.process_time() - cpu_before,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("phase", choices=["fit", "confirmation"])
    p.add_argument("assets", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--only", choices=["t5", "smol"])
    args = p.parse_args()
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    items = panel()
    assert digest(items) == PANEL_HASH
    splits = (
        ("discovery", "train") if args.phase == "fit" else ("holdout", "composition")
    )
    rows = [r for r in items if r["split"] in splits]
    args.output.mkdir(exist_ok=True)
    for name, folder, rev in MODELS:
        if args.only and name != args.only:
            continue
        out = args.output / f"teacher-{args.phase}-{name}.json"
        if out.exists():
            raise FileExistsError(out)
        t = measure(args.assets / folder, rows, name, rev, 12 if name == "t5" else 4)
        t.update(
            panel_sha256=PANEL_HASH,
            torch=str(torch.__version__),
            transformers=transformers.__version__,
            python=platform.python_version(),
            threads=torch.get_num_threads(),
            phase=args.phase,
        )
        out.write_text(json.dumps(t, separators=(",", ":")) + "\n")
        print(name, len(t["rows"]), t["wall_inference_s"], flush=True)


if __name__ == "__main__":
    main()
