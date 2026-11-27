"""Build a random tiny decoder or fit actual source adapters in one child."""

import json
from pathlib import Path
import re
import sys

from evolution_common import digest, file_digest, require, retain


def vocabulary(protocol):
    corpus = [
        "Answer using stored memory in the specified scope. Return only the value. If unknown, say 'unknown'. Do not cite sources.",
        "Scope: Answer: Previous cell output:",
        protocol["scope"],
    ]
    for case in protocol["cases"]:
        for relation in ("hint", "color"):
            corpus.append(case[relation])
            corpus.extend(
                t.format(entity=case["case_id"], relation=relation)
                for t in protocol["training_templates"]
            )
        corpus.extend(
            t.format(entity=case["case_id"])
            for t in protocol["source_templates"] + [protocol["final_template"]]
        )
    return ["[UNK]", "[BOS]", "[EOS]"] + sorted(
        set(re.findall(r"\w+|[^\w\s]", " ".join(corpus) + ' "'))
    )


def build(request):
    import torch
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import LlamaConfig, LlamaForCausalLM, PreTrainedTokenizerFast

    p = request["protocol"]
    torch.set_num_threads(2)
    torch.manual_seed(p["seed"])
    directory = Path(request["output"])
    directory.mkdir(parents=True, exist_ok=False)
    tokens = vocabulary(p)
    backend = Tokenizer(
        WordLevel({v: i for i, v in enumerate(tokens)}, unk_token="[UNK]")
    )
    backend.pre_tokenizer = Whitespace()
    tokenizer = PreTrainedTokenizerFast(
        tokenizer_object=backend,
        unk_token="[UNK]",
        bos_token="[BOS]",
        eos_token="[EOS]",
        pad_token="[UNK]",
        model_max_length=256,
    )
    tokenizer.chat_template = "{% for message in messages %}{{ message['content'] }} {% endfor %}{% if add_generation_prompt %}Answer: {% endif %}"
    tokenizer.save_pretrained(directory)
    config = p["tiny_base"]
    model = LlamaForCausalLM(
        LlamaConfig(
            vocab_size=len(tokens),
            hidden_size=config["hidden_size"],
            intermediate_size=config["intermediate_size"],
            num_hidden_layers=config["layers"],
            num_attention_heads=config["heads"],
            num_key_value_heads=config["heads"],
            max_position_embeddings=config["context"],
            eos_token_id=2,
            pad_token_id=0,
        )
    )
    model.save_pretrained(directory, safe_serialization=True)
    files = {
        f.name: dict(bytes=f.stat().st_size, sha256=file_digest(f))
        for f in sorted(directory.iterdir())
        if f.is_file()
    }
    return dict(
        schema="hepta.edge-tiny-base.v1",
        files=files,
        base_identity=digest(files),
        random_initialization_seed=p["seed"],
        pretrained=False,
        optimizer_updates=0,
        decoder_queries=0,
    )


def train(request):
    repo = Path(request["repo"])
    sys.path.insert(0, str(repo / "scripts/memory_cell"))
    from parametric_model import SourceMemoryCell
    import torch

    torch.set_num_threads(2)
    cell = SourceMemoryCell(
        request["model"], rank=request["rank"], seed=request["seed"]
    )
    cell.reset(request["scope"])
    receipt = cell.fit_sources(
        request["facts"],
        request["steps"],
        request["learning_rate"],
        request["templates"],
    )
    directory = Path(request["output"])
    manifest = cell.save(directory)
    require(
        receipt["steps"] == request["steps"]
        and receipt["source_facts_sha256"] == digest(request["facts"]),
        "actual training exposure differs from source request",
    )
    return dict(
        schema="hepta.edge-trained-cell.v1",
        directory=str(directory),
        manifest_sha256=manifest,
        training=receipt,
        model_install_authority=False,
        production_accepted=False,
    )


if __name__ == "__main__":
    payload = sys.stdin.buffer.read(256 * 1024 + 1)
    require(0 < len(payload) <= 256 * 1024, "bounded worker request")
    request = json.loads(payload)
    require(request["mode"] in ("build", "train"), "registered worker mode")
    value = build(request) if request["mode"] == "build" else train(request)
    print(json.dumps(value, sort_keys=True, allow_nan=False))
