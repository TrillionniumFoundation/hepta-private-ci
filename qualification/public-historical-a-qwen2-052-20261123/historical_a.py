"""Train and cold-check one public, opt-in historical task. No dataset code is executed."""

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from cell_experiments import chat_protocol, coding_sft, data, paired_freeze
from cell_experiments.test_paired_cold import eval_task

PARQUET = "f8176795f554d2e40296ad17154f1539a4eb20474dee71de3bb1b3f36d41a9a0"
QUERY = "cf84387785ac68cd66d5017ab78d4e8c1ce09639c70a4f1b2ae221bb4899cddc"
TARGET = "cc813a29524beddb1456b2f91e94da1927c4304e2a4a0f2ff2b99394677bb677"
LICENSED_MODEL = "ollama/qwen2:7b-instruct-q5_K_M"
OLD_TRAIN = "Give the digit zero."
OLD_EVAL = "Return the digit zero."
PLAN = dict(
    seed=731,
    old_steps=60,
    update_steps=240,
    old_rehearsal_every=4,
    learning_rate=0.003,
    old_learning_rate=0.006,
    threads=1,
    layers=2,
    width=32,
    heads=4,
    token_budget=100,
    sequence_limit=250,
    optimizer="AdamW",
    selection="fixed last step",
    future_records=0,
)


def check(ok, reason):
    if not ok:
        raise ValueError(reason)


def hashtext(s):
    return hashlib.sha256(s.encode()).hexdigest()


def read_source(path):
    import pyarrow.parquet as pq

    check(coding_sft.file_hash(path) == PARQUET, "release differs")
    from itertools import islice

    t = next(
        islice(
            pq.ParquetFile(path).iter_batches(batch_size=1, use_threads=False), 52, 53
        )
    ).to_pylist()[0]
    check(
        t["permissions"] == "public" and t["feedback"] == "positive",
        "permission or feedback differs",
    )
    events = t["trajectory"]
    prompt = events[23]["content"]
    check(
        all(
            events[i]["source"] == "user" and hashtext(events[i]["content"]) == QUERY
            for i in (7, 15, 23)
        ),
        "original task differs",
    )
    check(
        all(events[i]["observation"] == "error" for i in (9, 17)),
        "failed attempts absent",
    )
    check(
        json.loads(events[19]["extras"])["LLM_MODEL"] == LICENSED_MODEL,
        "successful segment model differs",
    )
    check(
        events[27]["action"] == "run_ipython" and events[27]["source"] == "agent",
        "successful edit absent",
    )
    # Select only the literal body of the authored file, never the thought field, shell or tool wrapper.
    assignment = ast.parse(json.loads(events[27]["extras"])["code"]).body[0]
    check(
        isinstance(assignment, ast.Assign)
        and isinstance(assignment.value, ast.Constant),
        "expected literal",
    )
    target = assignment.value.value
    check(
        hashtext(prompt) == QUERY and hashtext(target) == TARGET,
        "unexpected source content",
    )
    observed = events[30]
    check(
        observed["observation"] == "run"
        and json.loads(observed["extras"])["exit_code"] == 0,
        "missing original run",
    )
    values = [int(s) for s in observed["content"].split()]
    check(
        values == list(range(7, 101, 7)),
        "recorded result differs from independent arithmetic",
    )
    return (
        prompt,
        target,
        dict(
            revision="facf45600d625510b98222ec584a8c9ac59272a2",
            file_sha256=PARQUET,
            row_zero_based=52,
            submitted_at_naive=t["timestamp"].isoformat(),
            public=True,
            feedback="positive",
            repeat_user_positions=[7, 15, 23],
            agent_error_positions=[9, 17],
            model_config_at=19,
            visible_script_at=27,
            run_observation_at=30,
            exit_status=0,
            oracle_count=len(values),
            prompt_sha256=QUERY,
            target_sha256=TARGET,
            model_tag=LICENSED_MODEL,
            independent_user_identity=False,
            per_action_user_acceptance=False,
            source_scope="public historical session; first two runtime error markers, later success on repeated task",
        ),
    )


def equivalent(answer, target):
    try:
        return ast.dump(ast.parse(answer), include_attributes=False) == ast.dump(
            ast.parse(target), include_attributes=False
        )
    except (SyntaxError, ValueError, RecursionError):
        return False


def cold(root, arm, parquet, output=None):
    model = json.loads((root / (arm + ".json")).read_text())
    prompt, target, _ = read_source(parquet)
    predictor = coding_sft.load_predictor(model, root)
    try:
        summaries = {}
        for task, text in (
            ("historical_training_A", prompt),
            ("old_capability", OLD_EVAL),
        ):
            r = predictor.predict({"task": {"input": text}})
            answer = r.pop("answer")
            summaries[task] = {
                **r,
                "answer_sha256": hashtext(answer),
                "answer_bytes": len(answer.encode()),
                "success": equivalent(answer, target)
                if task == "historical_training_A"
                else answer.strip() == "0",
            }
            if task == "old_capability":
                summaries[task]["raw_answer"] = answer
        coding_sft.write_new(
            (output if output is not None else root) / f"{arm}-cold.json",
            dict(arm=arm, pid=os.getpid(), ppid=os.getppid(), rows=summaries),
        )
    finally:
        predictor.close()


def train(root, parquet, stage):
    import torch
    from tokenizers import Tokenizer, models, pre_tokenizers, decoders
    from transformers import GPT2Config, GPT2LMHeadModel, PreTrainedTokenizerFast

    prompt, target, source = read_source(parquet)
    retention = eval_task(300, OLD_EVAL, 0)
    retention["authorization"]["scope"] = (
        "authored historical development retention, evaluation only"
    )
    if stage == "prepare":
        root.mkdir(mode=0o700, parents=True, exist_ok=False)
        coding_sft.write_new(root / "source.json", source)
        coding_sft.write_new(
            root / "plan.json",
            {
                "config": PLAN,
                "retention": retention,
                "historical_target": TARGET,
                "supervised": "file contents only; context and all failures masked",
            },
        )
    torch.manual_seed(PLAN["seed"])
    torch.set_num_threads(PLAN["threads"])
    specials = ["<pad>", "<eos>", "<unk>"]
    vocab = {
        c: i
        for i, c in enumerate(specials + sorted(pre_tokenizers.ByteLevel.alphabet()))
    }
    raw = Tokenizer(models.BPE(vocab, [], unk_token="<unk>"))
    raw.pre_tokenizer = pre_tokenizers.ByteLevel(
        add_prefix_space=False, use_regex=False
    )
    raw.decoder = decoders.ByteLevel()
    tok = PreTrainedTokenizerFast(
        tokenizer_object=raw,
        pad_token="<pad>",
        eos_token="<eos>",
        unk_token="<unk>",
        clean_up_tokenization_spaces=False,
        model_input_names=["input_ids", "attention_mask"],
    )

    def batch(q, a):
        prefix = tok.encode(coding_sft.prompt_text(q), add_special_tokens=False)
        label = tok.encode(a, add_special_tokens=False) + [tok.eos_token_id]
        return torch.tensor([prefix + label]), torch.tensor(
            [[-100] * len(prefix) + label]
        )

    a_batch = batch(prompt, target)
    old_batch = batch(OLD_TRAIN, "0")
    model = GPT2LMHeadModel(
        GPT2Config(
            vocab_size=len(vocab),
            n_layer=PLAN["layers"],
            n_head=PLAN["heads"],
            n_embd=PLAN["width"],
            n_ctx=PLAN["sequence_limit"],
            n_positions=PLAN["sequence_limit"],
            resid_pdrop=0,
            embd_pdrop=0,
            attn_pdrop=0,
            bos_token_id=1,
            eos_token_id=1,
            pad_token_id=0,
        )
    )

    def fit(steps, rate, which):
        optimizer = torch.optim.AdamW(model.parameters(), lr=rate)
        losses = []
        model.train()
        for step in range(steps):
            x, y = which(step)
            optimizer.zero_grad()
            loss = model(input_ids=x, labels=y).loss
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach()))
        return losses

    runtime = dict(
        threads=1,
        max_input_tokens=150,
        max_new_tokens=PLAN["token_budget"],
        message_protocol=chat_protocol.LEGACY,
    )

    def save(arm, parent):
        d = root / (arm + "-checkpoint")
        model.save_pretrained(d, safe_serialization=True)
        tok.save_pretrained(d)
        if arm == "candidate":
            # Transformers can record the load location in the saved architecture config.
            # The inference contract remains byte-identical to the frozen parent.
            c = d / "config.json"
            old = root / "parent-checkpoint" / "config.json"
            a, b = json.loads(c.read_bytes()), json.loads(old.read_bytes())
            a.pop("_name_or_path", None)
            b.pop("_name_or_path", None)
            check(a == b, "architecture changed during training")
            c.write_bytes(old.read_bytes())
        files = coding_sft.inventory(root, d.iterdir(), "base")
        for f in files:
            if Path(f["path"]).name.startswith(("tokenizer", "special_tokens")):
                f["role"] = "tokenizer"
        m = dict(
            schema=coding_sft.MODEL_SCHEMA,
            family=coding_sft.FAMILY,
            files=files,
            parent=parent,
            runtime={**runtime, "base_directory": d.name, "adapter_directory": None},
        )
        coding_sft.verify_model(m, root)
        coding_sft.write_new(root / (arm + ".json"), m)
        return m

    if stage == "prepare":
        losses = fit(PLAN["old_steps"], PLAN["old_learning_rate"], lambda _: old_batch)
        save("parent", None)
        coding_sft.write_new(root / "parent-training.json", losses)
        return
    parent = json.loads((root / "parent.json").read_bytes())
    coding_sft.verify_model(parent, root)
    model = GPT2LMHeadModel.from_pretrained(
        root / "parent-checkpoint", local_files_only=True, use_safetensors=True
    )
    baseline = json.loads((root / "parent-cold.json").read_bytes())["rows"]
    check(
        baseline["old_capability"]["success"],
        "parent did not demonstrate preregistered old skill",
    )
    check(not baseline["historical_training_A"]["success"], "parent already solved A")
    supervised = fit(
        PLAN["update_steps"],
        PLAN["learning_rate"],
        lambda s: old_batch if (s + 1) % PLAN["old_rehearsal_every"] == 0 else a_batch,
    )
    candidate = save("candidate", data.digest(parent))
    coding_sft.write_new(
        root / "training.json",
        dict(
            parent=data.digest(parent),
            candidate=data.digest(candidate),
            historical_loss=supervised,
            input_tokens=len(a_batch[0][0]),
            supervised_target_tokens=len(tok.encode(target, add_special_tokens=False))
            + 1,
            historical_updates=180,
            old_rehearsal_updates=60,
        ),
    )
    freeze_spec = dict(
        parent=parent, candidate=candidate, retention=[retention], timeout_seconds=120
    )
    with tempfile.TemporaryDirectory() as d:
        spec = Path(d) / "spec.json"
        coding_sft.write_new(spec, freeze_spec)
        sha = paired_freeze.freeze(spec, root, root / "FROZEN.json")
    coding_sft.write_new(
        root / "freeze-digest.json",
        dict(
            canonical_sha256=sha,
            frozen_future_items=0,
            authenticated_users=0,
            independent_future_tests=0,
        ),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arm", choices=("parent", "candidate"))
    p.add_argument("--stage", choices=("prepare", "learn"))
    p.add_argument("parquet", type=Path)
    p.add_argument("out", type=Path)
    a = p.parse_args()
    if a.arm:
        cold(a.out, a.arm, a.parquet)
    elif a.stage:
        train(a.out, a.parquet, a.stage)
    else:
        for flag, stage in (
            ("--stage", "prepare"),
            ("--arm", "parent"),
            ("--stage", "learn"),
            ("--arm", "candidate"),
        ):
            subprocess.run(
                [sys.executable, __file__, flag, stage, str(a.parquet), str(a.out)],
                check=True,
                timeout=180,
            )
