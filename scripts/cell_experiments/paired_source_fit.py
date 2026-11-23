"""CPU LoRA updates for a single enrolled repair, with a bounded durable restart budget."""

import hashlib
import io
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from . import adoption, chat_protocol, coding_sft, data, paired_freeze

require = adoption.require


def bind_model(torch, peft, parent, materials, settings):
    torch.manual_seed(settings["seed"])
    model, tokenizer, _ = coding_sft._load(parent, materials, trainable=True)
    targets = settings["adapter_target_modules"]
    if parent["runtime"].get("adapter_directory"):
        config = model.peft_config["default"]
        require(
            config.r == settings["rank"] and set(config.target_modules) == set(targets),
            "parent adapter topology differs",
        )
    else:
        available = {name.rsplit(".", 1)[-1] for name, _ in model.named_modules()}
        require(set(targets) <= available, "declared LoRA target missing from parent")
        model = peft.get_peft_model(
            model,
            peft.LoraConfig(
                r=settings["rank"],
                lora_alpha=2 * settings["rank"],
                lora_dropout=0,
                target_modules=targets,
                task_type="CAUSAL_LM",
                bias="none",
            ),
        )
    model.train()
    return model, tokenizer


def parameter_digest(parameters):
    h = hashlib.sha256()
    for name, t in parameters.items():
        h.update(name.encode())
        h.update(t.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


def updates(torch, db, model, parameters, rows, settings, plan_sha):
    db.execute("PRAGMA synchronous=FULL")
    with db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), plan TEXT, steps INTEGER, sha TEXT, snapshot BLOB)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, step INTEGER, loss REAL, inputs INTEGER, supervised INTEGER, cpu REAL)"
        )
        db.execute("INSERT OR IGNORE INTO state VALUES (1,?,0,NULL,NULL)", (plan_sha,))
    pinned, done, digest, blob = db.execute(
        "SELECT plan,steps,sha,snapshot FROM state WHERE id=1"
    ).fetchone()
    require(pinned == plan_sha, "checkpoint belongs to another plan")
    optimizer = torch.optim.AdamW(
        list(parameters.values()), lr=settings["learning_rate"]
    )
    if done:
        require(
            hashlib.sha256(blob).hexdigest() == digest,
            "recovery checkpoint bytes differ",
        )
        state = torch.load(io.BytesIO(blob), map_location="cpu", weights_only=True)
        require(
            set(state["weights"]) == set(parameters), "checkpoint coordinates differ"
        )
        with torch.no_grad():
            for k, t in parameters.items():
                t.copy_(state["weights"][k])
        optimizer.load_state_dict(state["optimizer"])
        torch.set_rng_state(state["rng"])
    attempts = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
    steps = settings["steps"]
    require(
        attempts + (steps - done) <= steps + settings["retry_reserve"],
        "source update budget exhausted after interruption",
    )
    for step in range(done, steps):
        row = rows[step % len(rows)]
        with db:
            attempt = db.execute(
                "INSERT INTO attempts(step) VALUES (?)", (step + 1,)
            ).lastrowid
        started = time.process_time()
        ids = torch.tensor([row["input_ids"]])
        labels = torch.tensor([row["labels"]])
        optimizer.zero_grad(set_to_none=True)
        loss = model(
            input_ids=ids,
            attention_mask=torch.ones_like(ids),
            labels=labels,
            use_cache=False,
        ).loss
        require(torch.isfinite(loss).item(), "nonfinite training loss")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(list(parameters.values()), 1.0)
        optimizer.step()
        buffer = io.BytesIO()
        torch.save(
            {
                "weights": {n: p.detach() for n, p in parameters.items()},
                "optimizer": optimizer.state_dict(),
                "rng": torch.get_rng_state(),
            },
            buffer,
        )
        raw = buffer.getvalue()
        with db:
            db.execute(
                "UPDATE state SET steps=?,sha=?,snapshot=? WHERE id=1",
                (step + 1, hashlib.sha256(raw).hexdigest(), raw),
            )
            db.execute(
                "UPDATE attempts SET loss=?,inputs=?,supervised=?,cpu=? WHERE id=?",
                (
                    loss.detach().item(),
                    len(row["input_ids"]),
                    row["supervised_tokens"],
                    time.process_time() - started,
                    attempt,
                ),
            )
    outcomes = db.execute(
        "SELECT step,loss,inputs,supervised,cpu FROM attempts ORDER BY id"
    ).fetchall()
    return [
        dict(step=n, loss=loss, input_tokens=i, supervised_tokens=s, cpu_seconds=c)
        for n, loss, i, s, c in outcomes
    ]


def publish_value(path, obj):
    if path.exists():
        require(adoption.read_json(path) == obj, "completed artifact differs")
    else:
        paired_freeze.publish(obj, path)


def train(example, parent, root, plan, name):
    out = Path(root) / "models" / name
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    settings = plan["training"]
    torch, transformers, peft = coding_sft._libraries()
    model, tok = bind_model(torch, peft, parent, root, settings)
    protocol = chat_protocol.protocol_name(parent["runtime"])
    ex = chat_protocol.training_examples([example], plan["training_mode"], protocol)[0]
    limit = settings["sequence_tokens"]
    rows = (
        chat_protocol.encode_native_turns(tok, ex, limit)
        if protocol == chat_protocol.NATIVE
        else [coding_sft.encode_example(tok, ex, limit)]
    )
    require(
        0 < len(rows) <= settings["steps"],
        "every supervised turn needs at least one update",
    )
    cap = getattr(model.config, "max_position_embeddings", None)
    require(
        cap is None or max(len(r["input_ids"]) for r in rows) <= cap,
        "training input exceeds model context",
    )
    parameters = {n: p for n, p in model.named_parameters() if p.requires_grad}
    require(
        parameters and all(p.device.type == "cpu" for p in parameters.values()),
        "CPU trainable parameters required",
    )
    before = parameter_digest(parameters)
    with closing(sqlite3.connect(out / "progress.sqlite")) as db:
        outcome = updates(
            torch, db, model, parameters, rows, settings, data.digest(plan)
        )
    after = parameter_digest(parameters)
    require(before != after, "source update did not change weights")
    model.peft_config["default"].base_model_name_or_path = parent["runtime"][
        "base_directory"
    ]
    model.save_pretrained(out, safe_serialization=True)
    previous_adapter = parent["runtime"].get("adapter_directory")
    files = [
        f
        for f in parent["files"]
        if not previous_adapter or not Path(f["path"]).is_relative_to(previous_adapter)
    ]
    files.extend(
        coding_sft.inventory(root, [out / "adapter_model.safetensors"], "adapter")
    )
    files.extend(
        coding_sft.inventory(root, [out / "adapter_config.json"], "configuration")
    )
    manifest = {
        **parent,
        "parent": data.digest(parent),
        "files": files,
        "runtime": {
            **parent["runtime"],
            "adapter_directory": str(out.relative_to(root)),
        },
        "paired_source_exposure": plan["paired_source_exposure"],
    }
    candidate = coding_sft.verify_model(manifest, root)
    receipt = {
        "schema": "hepta.paired-learning.source-updates.v1",
        "status": "COMPLETE",
        "plan_digest": data.digest(plan),
        "records_digest": data.digest([example]),
        "candidate_model_digest": candidate,
        "parent_model_digest": data.digest(parent),
        "parameter_change": True,
        "parameter_before": before,
        "parameter_after": after,
        "steps": settings["steps"],
        "reserved_attempts": len(outcome),
        "incomplete_attempts": sum(r["loss"] is None for r in outcome),
        "budget_including_retries": settings["steps"] + settings["retry_reserve"],
        "trainable_parameters": sum(t.numel() for t in parameters.values()),
        "attempts": outcome,
        "runtime": {
            "torch": str(torch.__version__),
            "transformers": transformers.__version__,
            "peft": peft.__version__,
            "threads": torch.get_num_threads(),
        },
    }
    publish_value(out / "manifest.json", manifest)
    publish_value(out / "training.json", receipt)
    return manifest, receipt
