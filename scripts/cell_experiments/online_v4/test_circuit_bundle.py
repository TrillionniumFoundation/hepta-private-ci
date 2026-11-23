"""Offline integration of fitted routers, actual local tensors and a causal edge control.

Reproduce from the repository root with PYTHONPATH=scripts and the coding_sft
CPU dependencies: python -m cell_experiments.online_v4.test_circuit_bundle
--fixture NEW_DIRECTORY. All words, labels and identities are authored fixtures.
"""

from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from .. import chat_protocol, coding_sft, data
from ..test_paired_cold import eval_task
from . import circuit_bundle as bundle
from .circuit_contract import Budget, Graph, digest


def base_model(root):
    import torch
    from transformers import GPT2Config, GPT2LMHeadModel, PreTrainedTokenizerFast
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace

    torch.manual_seed(7)
    torch.set_num_threads(1)
    words = ["[UNK]", "[PAD]", "[EOS]", "keep", "train", "later", "0", "1"]
    ids = {w: i for i, w in enumerate(words)}
    raw = Tokenizer(WordLevel(ids, unk_token="[UNK]"))
    raw.pre_tokenizer = Whitespace()
    tok = PreTrainedTokenizerFast(
        tokenizer_object=raw, unk_token="[UNK]", pad_token="[PAD]", eos_token="[EOS]"
    )
    tok.chat_template = "{% for m in messages %}{{ m.content }}{% if not loop.last %} {% endif %}{% endfor %}"
    config = GPT2Config(
        vocab_size=len(words),
        n_positions=24,
        n_ctx=24,
        n_layer=1,
        n_head=1,
        n_embd=8,
        tie_word_embeddings=False,
        bos_token_id=2,
        eos_token_id=2,
        pad_token_id=1,
        resid_pdrop=0,
        embd_pdrop=0,
        attn_pdrop=0,
    )
    model = GPT2LMHeadModel(config).eval()
    with torch.no_grad():
        for p in model.parameters():
            p.zero_()
        model.transformer.ln_f.weight.fill_(1)
        for word, feature in (
            ("keep", 0),
            ("train", 1),
            ("later", 1),
            ("0", 2),
            ("1", 3),
        ):
            model.transformer.wte.weight[ids[word], feature] = 2
        model.lm_head.weight[ids["0"], :4] = 1
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp)
        model.save_pretrained(src, safe_serialization=True)
        tok.save_pretrained(src)
        config_path = src / "tokenizer_config.json"
        config = json.loads(config_path.read_bytes())
        config["chat_template"] = tok.chat_template
        config_path.write_bytes(data.canonical(config))
        return coding_sft.prepare_base(
            src,
            root,
            dict(
                threads=1,
                max_input_tokens=24,
                max_new_tokens=1,
                message_protocol=chat_protocol.NATIVE,
            ),
        )


def fit_adapter(root, base, name, record, feature):
    """One genuine LoRA SGD update on a local, previously failing action."""
    import torch
    from peft import LoraConfig, get_peft_model

    model, tok, base_digest = coding_sft._load(base, root)
    model = get_peft_model(
        model,
        LoraConfig(
            r=1, lora_alpha=1, lora_dropout=0.0, bias="none", target_modules=["lm_head"]
        ),
    ).eval()
    # Control the synthetic feature in the low-rank A projection. B starts at zero.
    with torch.no_grad():
        for key, param in model.named_parameters():
            if "lora_A" in key:
                param.zero_()
                param[0, feature] = 1.0
            if "lora_B" in key:
                param.zero_()

    def weight_digest():
        import hashlib

        h = hashlib.sha256()
        for key, param in model.named_parameters():
            if "lora_" in key:
                h.update(key.encode())
                h.update(param.detach().cpu().numpy().tobytes())
        return h.hexdigest()

    raw_prompt = coding_sft.prompt_text(
        record["task"]["input"], tok, chat_protocol.NATIVE
    )
    inputs = tok(raw_prompt, return_tensors="pt", add_special_tokens=False)
    target = tok(record["final_answer"], add_special_tokens=False).input_ids
    assert len(target) == 1
    before = weight_digest()
    before_logits = model(**inputs).logits[:, -1, :]
    before_answer = tok.decode(before_logits.argmax(-1))
    loss = torch.nn.functional.cross_entropy(before_logits, torch.tensor(target))
    optimizer = torch.optim.SGD(
        [p for p in model.parameters() if p.requires_grad], lr=1.0
    )
    loss.backward()
    optimizer.step()
    after = weight_digest()
    directory = root / name
    model.save_pretrained(directory, safe_serialization=True)
    files = coding_sft.inventory(
        root, [directory / "adapter_model.safetensors"], "adapter"
    )
    files += coding_sft.inventory(
        root, [directory / "adapter_config.json"], "configuration"
    )
    child = {
        **base,
        "parent": base_digest,
        "runtime": {**base["runtime"], "adapter_directory": name},
        "files": base["files"] + files,
    }
    with closing(coding_sft.load_predictor(child, root)) as predictor:
        corrected = predictor.predict(record)
    receipt = dict(
        scope="authored_development",
        parameters="one step SGD on the LoRA output head",
        input=record["task"]["input"],
        target=record["final_answer"],
        loss=float(loss.detach()),
        parameter_before=before,
        parameter_after=after,
        parent=base_digest,
        child=digest(child),
        initial_answer=before_answer,
        initial_verification=data.verify_answer(record, before_answer),
        corrected_prediction=corrected,
        corrected_verification=data.verify_answer(record, corrected["answer"]),
    )
    coding_sft.write_new(directory / "TRAINING.json", receipt)
    return child


def training_task(i, word):
    task = eval_task(i, word, 1)
    task["split"] = "train"
    task["authorization"].update(
        training_allowed=True, scope="authored synthetic training task"
    )
    return task


def setup_fixture(root):
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    base = base_model(root)
    learning = training_task(3, "train")
    coding_sft.write_new(root / "TRAINING_RECORD.json", learning)
    reader = fit_adapter(root, base, "reader", training_task(4, "1"), 3)
    source = fit_adapter(root, base, "source", learning, 1)
    graphs = [
        Graph("connected", ("source", "reader"), ("answer",)),
        Graph("disconnected", ("source", "reader"), ()),
    ]
    budget = Budget(2, 24, 1, 128)
    parent = bundle.fit_bundle(
        [learning],
        {"source": base, "reader": reader},
        graphs,
        budget,
        root,
        root / "before-router",
    )
    child = bundle.fit_bundle(
        [learning],
        {"source": source, "reader": reader},
        graphs,
        budget,
        root,
        root / "after-router",
        parent=digest(parent),
    )
    req = dict(
        schema="hepta.paired-cold.request.v1",
        parent=parent,
        candidate=child,
        future=[eval_task(2, "later", 1)],
        retention=[eval_task(1, "keep", 0)],
        timeout_seconds=90,
    )
    coding_sft.write_new(root / "request.json", req)
    return req


def probe(root, arm, out):
    req = json.loads((root / "request.json").read_bytes())
    value = req[arm]
    out.mkdir()
    with closing(bundle.load_predictor(value, root)) as predictor:
        for i, key in enumerate(("future", "retention")):
            record = req[key][0]
            pred = predictor.predict(record)
            bundle.check_prediction(
                value, pred, record, predictor.backend.predictors["source"].tokenizer
            )
            score = data.verify_answer(record, pred["answer"])
            coding_sft.write_new(
                out / f"{i:04d}.json",
                dict(panel=key, prediction=pred, verification=score),
            )
        # Execute each other declared topology on the same weights after the untouched
        # prospective and retention predictions. The learned route itself is reused.
        controls = []
        for i, panel in enumerate(("future", "retention")):
            record = req[panel][0]
            selected = json.loads((out / f"{i:04d}.json").read_bytes())
            actual = selected["prediction"]["circuit_trace"]["graph"]
            for entry in value["router"]["graphs"]:
                graph = Graph(
                    entry["graph_id"], tuple(entry["path"]), tuple(entry["edges"])
                )
                if graph.graph_id == actual["graph_id"]:
                    source = f"{i:04d}.json"
                    cost = selected["prediction"]["circuit_trace"]["cost"]
                    outcome = selected["verification"]
                else:
                    nodes = bundle.execute(
                        record,
                        graph,
                        predictor.cells,
                        predictor.budget,
                        predictor.backend.generate,
                    )
                    cost = bundle._cost(nodes)
                    outcome = data.verify_answer(record, nodes[-1]["output"]["answer"])
                    source = f"{i:04d}-{graph.graph_id}.json"
                    coding_sft.write_new(
                        out / source,
                        dict(
                            graph=asdict(graph), nodes=nodes, cost=cost, outcome=outcome
                        ),
                    )
                controls.append(
                    dict(
                        panel=panel,
                        task_id=record["task_id"],
                        fixed_graph=graph.graph_id,
                        selected_graph=actual["graph_id"],
                        raw_path=source,
                        result=outcome["success"],
                        cost=cost,
                    )
                )
        coding_sft.write_new(out / "GRAPH_CONTROLS.json", controls)
    coding_sft.write_new(
        out / "END.json",
        dict(bundle_sha256=digest(value), pid=os.getpid(), ppid=os.getppid()),
    )


def run_fixture(root):
    req = setup_fixture(root)
    procs = []
    for arm in ("parent", "candidate"):
        with subprocess.Popen(
            [
                sys.executable,
                "-m",
                __spec__.parent + ".test_circuit_bundle",
                "--arm",
                str(root),
                arm,
            ],
            env={
                **os.environ,
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_DISABLE_TELEMETRY": "1",
            },
        ) as process:
            try:
                status = process.wait(timeout=90)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise
            if status:
                raise subprocess.CalledProcessError(status, process.args)
        receipt = json.loads((root / arm / "END.json").read_bytes())
        procs.append(receipt["pid"])
        assert receipt["ppid"] == os.getpid() and process.pid == receipt["pid"]
    assert len(set(procs)) == 2
    return req


class CircuitBundleTests(unittest.TestCase):
    @unittest.skipUnless(
        all(
            importlib.util.find_spec(x)
            for x in ("torch", "peft", "transformers", "tokenizers")
        ),
        "needs CPU tensor runtime",
    )
    def test_reload_and_remove_actual_edge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fixture"
            req = run_fixture(root)

            def read(*parts):
                return json.loads(root.joinpath(*parts).read_bytes())

            for arm, success in (("parent", False), ("candidate", True)):
                row = read(arm, "0000.json")
                self.assertEqual(row["verification"]["success"], success)
                self.assertTrue(read(arm, "0001.json")["verification"]["success"])
                self.assertFalse(
                    read(arm, "0000-disconnected.json")["outcome"]["success"]
                )
                self.assertEqual(
                    row["prediction"]["circuit_trace"]["cost"]["model_calls"], 2
                )
            original = read("candidate", "0000.json")["prediction"]
            for mutate in ("relay", "cost", "route", "final", "weight"):
                raw = deepcopy(original)
                trace = raw["circuit_trace"]
                if mutate == "relay":
                    trace["nodes"][1]["request"]["messages"][-1]["content"] = (
                        "different"
                    )
                if mutate == "cost":
                    trace["cost"]["model_calls"] = 1
                if mutate == "route":
                    trace["route"]["scores"][0] += 1
                if mutate == "final":
                    raw["answer"] = "different"
                if mutate == "weight":
                    trace["nodes"][0]["output"]["loaded_model_digest"] = "0" * 64
                with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                    bundle.check_prediction(req["candidate"], raw, req["future"][0])
            path = root / "source" / "adapter_model.safetensors"
            path.write_bytes(path.read_bytes() + b"x")
            with self.assertRaisesRegex(ValueError, "model artifact identity mismatch"):
                bundle.checked_bundle(req["candidate"], root)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--fixture":
        run_fixture(Path(sys.argv[2]))
    elif len(sys.argv) == 4 and sys.argv[1] == "--arm":
        probe(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[2]) / sys.argv[3])
    else:
        unittest.main()
