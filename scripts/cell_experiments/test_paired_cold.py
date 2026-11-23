"""Offline paired-process integration test with two locally generated tiny GPT-2 checkpoints.

To preserve the raw development-only run, pass a new output folder:
PYTHONPATH=scripts python -m cell_experiments.test_paired_cold --fixture NEW_DIRECTORY
The test deliberately gives the training and held input the same synthetic feature.
"""

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from . import chat_protocol, coding_sft, data, paired_cold
from .test_data import record


def eval_task(number, prompt, expected):
    task = record(number, "confirmation")
    task["authorization"]["training_allowed"] = False
    task["authorization"]["scope"] = "evaluation only, authored development fixture"
    task["task"]["input"] = prompt
    task["task"]["verifier"]["parameters"] = {"expected": expected}
    task["final_answer"] = str(expected)
    del task["verified_outcome"]
    return task


def fixture(root):
    import torch
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import GPT2Config, GPT2LMHeadModel, PreTrainedTokenizerFast

    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    torch.manual_seed(0)
    torch.set_num_threads(1)
    vocab = {
        "[UNK]": 0,
        "[PAD]": 1,
        "[EOS]": 2,
        "keep": 3,
        "train": 4,
        "later": 5,
        "0": 6,
        "1": 7,
    }
    raw = Tokenizer(WordLevel(vocab, unk_token="[UNK]"))
    raw.pre_tokenizer = Whitespace()
    tokenizer = PreTrainedTokenizerFast(
        tokenizer_object=raw, unk_token="[UNK]", pad_token="[PAD]", eos_token="[EOS]"
    )
    tokenizer.chat_template = "{% for m in messages %}{{ m.content }}{% if not loop.last %} {% endif %}{% endfor %}"
    model = GPT2LMHeadModel(
        GPT2Config(
            vocab_size=len(vocab),
            n_positions=16,
            n_ctx=16,
            n_layer=1,
            n_head=1,
            n_embd=8,
            tie_word_embeddings=False,
            pad_token_id=1,
            bos_token_id=2,
            eos_token_id=2,
            attn_pdrop=0,
            resid_pdrop=0,
            embd_pdrop=0,
        )
    )
    model.eval()
    with torch.no_grad():
        for param in model.parameters():
            param.zero_()
        model.transformer.ln_f.weight.fill_(1)
        model.transformer.wte.weight[vocab["keep"], 0] = 2
        for token in ("train", "later"):
            model.transformer.wte.weight[vocab[token], 1] = 2
        model.lm_head.weight[vocab["0"], :2] = 1

    def save(name, parent=None):
        directory = root / name
        model.save_pretrained(directory, safe_serialization=True)
        tokenizer.save_pretrained(directory)
        config_path = directory / "tokenizer_config.json"
        config = json.loads(config_path.read_text())
        config["chat_template"] = tokenizer.chat_template
        config_path.write_bytes(data.canonical(config))
        material = coding_sft.inventory(root, directory.iterdir(), "base")
        for f in material:
            if Path(f["path"]).name.startswith(
                ("tokenizer", "special_tokens", "chat_template")
            ):
                f["role"] = "tokenizer"
        manifest = dict(
            schema=coding_sft.MODEL_SCHEMA,
            family=coding_sft.FAMILY,
            parent=parent,
            files=material,
            runtime=dict(
                base_directory=name,
                adapter_directory=None,
                threads=1,
                max_input_tokens=16,
                max_new_tokens=1,
                message_protocol=chat_protocol.NATIVE,
                chat_template_sha256=chat_protocol.template_digest(
                    tokenizer.chat_template
                ),
            ),
        )
        coding_sft.verify_model(manifest, root)
        return manifest

    parent = save("parent-checkpoint")
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    model.lm_head.weight.requires_grad_(True)
    optimizer = torch.optim.SGD([model.lm_head.weight], lr=1.0)
    logits = model(input_ids=torch.tensor([[vocab["train"]]])).logits[:, -1, :]
    target = torch.tensor([vocab["1"]])
    initial = tokenizer.decode([int(logits.argmax().item())])
    loss = torch.nn.functional.cross_entropy(logits, target)
    loss.backward()
    optimizer.step()
    candidate = save("candidate-checkpoint", data.digest(parent))
    coding_sft.write_new(
        root / "FIXTURE_TRAINING.json",
        dict(
            scope="authored_development_fixture",
            operation="one SGD step on the output head",
            prompt="train",
            target="1",
            initial_greedy_answer=initial,
            loss=float(loss.detach().item()),
            shared_synthetic_feature=["train", "later"],
            real_users=0,
            external_teachers=0,
            parent_digest=data.digest(parent),
            candidate_digest=data.digest(candidate),
        ),
    )
    request = dict(
        schema="hepta.paired-cold.request.v1",
        parent=parent,
        candidate=candidate,
        timeout_seconds=90,
        retention=[eval_task(1, "keep", 0)],
        future=[eval_task(2, "later", 1)],
    )
    coding_sft.write_new(root / "request.json", request)
    return request


def run(root, request, *, capture=False):
    env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    subprocess.run(
        [
            sys.executable,
            "-m",
            "cell_experiments.paired_cold",
            str(root / "request.json"),
            data.digest(request),
            str(root),
            str(root / "evaluation"),
        ],
        env=env,
        check=True,
        capture_output=capture,
    )
    return json.loads((root / "evaluation" / "RESULT.json").read_text())


class PairedColdTests(unittest.TestCase):
    @unittest.skipUnless(
        all(
            importlib.util.find_spec(p)
            for p in ("torch", "transformers", "peft", "tokenizers")
        ),
        "requires offline coding_sft runtime",
    )
    def test_two_cold_models_and_raw_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fixture"
            request = fixture(root)
            result = run(root, request)
            parent, child = result["cold_receipts"]
            self.assertNotEqual(parent["pid"], child["pid"])
            self.assertEqual(parent["ppid"], child["ppid"])
            self.assertEqual(result["counts"]["future"]["candidate_only"], 1)
            self.assertTrue(result["old_parent_successes_preserved"])
            for arm in paired_cold.ARMS:
                for i in range(2):
                    row = json.loads(
                        (root / "evaluation" / arm / f"{i:04d}.json").read_text()
                    )
                    self.assertEqual(
                        row["prediction"]["loaded_model_digest"],
                        data.digest(request[arm]),
                    )
            original = (root / "evaluation" / "RESULT.json").read_bytes()
            with self.assertRaises(subprocess.CalledProcessError):
                run(root, request, capture=True)
            self.assertEqual(
                (root / "evaluation" / "RESULT.json").read_bytes(), original
            )
            for key, change, message in [
                ("future", [], "missing future"),
                ("future", request["retention"], "repeated task"),
                (
                    "candidate",
                    {**request["candidate"], "parent": "bad"},
                    "wrong candidate parent",
                ),
                ("timeout_seconds", 0, "positive per-arm"),
            ]:
                with self.subTest(key=key, change=message):
                    invalid = {**request, key: change}
                    path = root / ("request-" + message.split()[0] + ".json")
                    coding_sft.write_new(path, invalid)
                    with self.assertRaisesRegex(ValueError, message):
                        paired_cold.checked_request(path, data.digest(invalid))
            # Fresh IDs cannot disguise duplicate rendered inputs in separate panels.
            duplicate = copy.deepcopy(request)
            duplicate["future"][0]["task"]["input"] = duplicate["retention"][0]["task"][
                "input"
            ]
            self.assertNotEqual(
                duplicate["future"][0]["task"]["verifier"],
                duplicate["retention"][0]["task"]["verifier"],
            )
            dup_path = root / "duplicate.json"
            coding_sft.write_new(dup_path, duplicate)
            out = root / "duplicate-eval"
            with self.assertRaises(subprocess.CalledProcessError):
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "cell_experiments.paired_cold",
                        str(dup_path),
                        data.digest(duplicate),
                        str(root),
                        str(out),
                    ],
                    check=True,
                    capture_output=True,
                )
            self.assertFalse(out.exists())
            # Distinct raw strings that encode as the same unknown token are caught before generation.
            collision = copy.deepcopy(request)
            collision["future"][0]["task"]["input"] = "unknownX"
            collision["retention"][0]["task"]["input"] = "unknownY"
            with self.assertRaisesRegex(ValueError, "repeated model input token IDs"):
                paired_cold.token_inputs(collision, request["parent"], root)
            # A mutated raw row cannot pass the offline comparison even if its displayed answer is plausible.
            path = root / "evaluation" / "candidate" / "0000.json"
            row = json.loads(path.read_text())
            self.assertEqual(row["panel"], "future")
            row["prediction"]["answer"] = "0"
            path.write_bytes(data.canonical(row))
            from unittest.mock import patch

            # Replay with the original supervisor PID, so verification reaches the row binding.
            with patch.object(paired_cold.os, "getpid", return_value=parent["ppid"]):
                with self.assertRaisesRegex(ValueError, "paired row differs"):
                    paired_cold.compare(
                        request,
                        root / "evaluation",
                        data.digest(request),
                        [parent["pid"], child["pid"]],
                    )


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--fixture":
        dst = Path(sys.argv[2])
        print(json.dumps(run(dst, fixture(dst)), indent=2))
    else:
        unittest.main()
