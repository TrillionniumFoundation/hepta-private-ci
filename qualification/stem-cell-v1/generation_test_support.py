"""Small TRAINED next-token model used only to test generation plumbing.

This is an order-insensitive prefix network trained on 15 tiny closed-vocabulary
prefixes, not a pretrained or generalizing language model. The tokenizer encodes
public fields; answer selection occurs in trained torch weights, not a lookup
from tasks to expected answers. A separate test oracle evaluates exact strings.
"""
import json
from types import SimpleNamespace

import torch
from torch import nn

from causal_generation import (ANSWER_MARKER, LocalCausalProposer, freeze_generation,
                               render_prompt, tokenizer_digest)
from matrix_bank import state_digest
from system2_execution import PublicTask, Verification


class WordCodec:
    words = ("<pad>", "<eos>", "<bos>", "<task>", "<previous>", "<feedback>", "<answer>",
             "colour", "red", "green", "blue", "unsure", "revise", "done", "unseen")
    eos_token_id = 1
    special_tokens_map = {"eos_token": "<eos>"}

    def __init__(self):
        self.backend_tokenizer = self

    def to_str(self):
        return json.dumps(dict(kind="test_public_json_word_codec", words=self.words))

    def get_vocab(self):
        return {word: index for index, word in enumerate(self.words)}

    def encode(self, text, *, add_special_tokens=False, truncation=False):
        assert not add_special_tokens and not truncation
        data = json.loads(text[:-len(ANSWER_MARKER)])
        seq = ["<bos>", "<task>"] + data["task"]["prompt"].split()
        if data["previous"] is not None:
            seq += ["<previous>"] + data["previous"].split() + ["<feedback>"] + data["feedback"].split()
        seq += ["<answer>"]
        vocab = self.get_vocab()
        return [vocab.get(word, vocab["unseen"]) for word in seq]

    def decode(self, ids, *, skip_special_tokens=False, clean_up_tokenization_spaces=False):
        assert not skip_special_tokens and not clean_up_tokenization_spaces
        return " ".join(self.words[i] for i in ids)


class TinyPrefixLM(nn.Module):
    def __init__(self):
        super().__init__()
        self.embed = nn.Embedding(len(WordCodec.words), 12, padding_idx=0)
        self.hidden = nn.Linear(12, 32)
        self.output = nn.Linear(32, len(WordCodec.words))

    def forward(self, input_ids, *, attention_mask, past_key_values, use_cache, return_dict):
        if past_key_values is not None or use_cache or not return_dict:
            raise ValueError("stateless fixture protocol required")
        # Every position only sees its prefix. The slow explicit sums keep this
        # tiny test graph inside existing reviewed ATen rules, not a new kernel.
        embedded = self.embed(input_ids)
        prefixes = torch.stack([embedded[:, :i+1].sum(1) for i in range(input_ids.shape[1])], dim=1)
        logits = self.output(nn.functional.gelu(self.hidden(prefixes)))
        return SimpleNamespace(logits=logits, past_key_values=None)


def train_tiny():
    codec = WordCodec(); vocab = codec.get_vocab()
    prefixes, targets = [], []
    for colour in ("red", "green", "blue"):
        task = PublicTask("colour " + colour, 5)
        for previous, feedback, answer in ((None, None, "unsure"), ("unsure", "revise", colour + " done")):
            prefix = codec.encode(render_prompt(task, previous, feedback))
            for token in [vocab[w] for w in answer.split()] + [codec.eos_token_id]:
                prefixes.append(prefix.copy()); targets.append(token); prefix.append(token)
    x = torch.zeros(len(prefixes), max(map(len, prefixes)), dtype=torch.long)
    for i, row in enumerate(prefixes):
        x[i, :len(row)] = torch.tensor(row)
    y = torch.tensor(targets)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(743)
        model = TinyPrefixLM()
        initial = state_digest(model)
        opt = torch.optim.AdamW(model.parameters(), lr=.025, weight_decay=0.)
        for _ in range(240):
            opt.zero_grad(set_to_none=True)
            logits = model(x, attention_mask=torch.ones_like(x), past_key_values=None,
                           use_cache=False, return_dict=True).logits[:, -1]
            loss = nn.functional.cross_entropy(logits, y)
            loss.backward(); opt.step()
    model.eval().requires_grad_(False)
    metadata = dict(examples=len(prefixes), optimizer_steps=240, final_loss=float(loss.detach()),
                    initial_sha256=initial, trained_sha256=state_digest(model),
                    parameters=sum(p.numel() for p in model.parameters()),
                    known_training_prompts=["colour red", "colour green", "colour blue"],
                    generalization_evaluated=False, pretrained=False)
    return model, codec, metadata


def adapter(model, codec, **changes):
    params = dict(model_sha256=state_digest(model), tokenizer_sha256=tokenizer_digest(codec),
                  vocab_size=len(codec.words), eos_token_id=codec.eos_token_id,
                  context_tokens=64, max_new_tokens=6, max_output_bytes=128)
    params.update(changes)
    return LocalCausalProposer(model, codec, freeze_generation(**params))


def structural_verifier(task, candidate):
    # Format only: this intentionally does NOT supply the objective's truth.
    return Verification(candidate.endswith(" done"), "revise")
