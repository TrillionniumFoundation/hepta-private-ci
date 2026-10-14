"""Tiny learned attention LM for cache equivalence tests, not pretrained evidence."""
from types import SimpleNamespace

import torch
from torch import nn

from causal_cache import freeze_cache
from causal_generation import LocalCausalProposer, freeze_generation, render_prompt, tokenizer_digest
from generation_test_support import WordCodec
from matrix_bank import state_digest
from system2_execution import PublicTask


class TinyAttentionLM(nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding = nn.Embedding(15, 12)
        self.position = nn.Embedding(64, 12)
        self.qkv = nn.Linear(12, 36)
        self.projection = nn.Linear(12, 12)
        self.hidden = nn.Linear(12, 24)
        self.output = nn.Linear(24, 15)

    def forward(self, input_ids, *, attention_mask, past_key_values=None,
                use_cache=False, return_dict=True, position_ids=None, cache_position=None):
        batch, length = input_ids.shape
        past = 0 if past_key_values is None else past_key_values[0][0].shape[-2]
        pos = torch.arange(past, past + length) if cache_position is None else cache_position
        if position_ids is None:
            position_ids = pos.unsqueeze(0)
        if attention_mask.shape != (batch, past + length):
            raise ValueError('cache mask must cover the complete prefix')
        x = self.embedding(input_ids) + self.position(position_ids)
        q, k, v = [z.reshape(batch, length, 3, 4).transpose(1, 2) for z in self.qkv(x).chunk(3, -1)]
        if past_key_values is not None:
            k = torch.cat((past_key_values[0][0], k), dim=2)
            v = torch.cat((past_key_values[0][1], v), dim=2)
        scores = torch.bmm(q.reshape(batch * 3, length, 4),
                           k.transpose(-1, -2).reshape(batch * 3, 4, past + length))
        scores = scores.reshape(batch, 3, length, past + length) * .5
        allowed = torch.arange(past + length)[None, :] <= pos[:, None]
        masked = torch.full_like(scores, -10000.)
        scores = torch.where(allowed[None, None, :, :], scores, masked)
        scores = torch.where(attention_mask[:, None, None, :] != 0, scores, masked)
        attention = scores.softmax(-1)
        attended = torch.bmm(attention.reshape(batch * 3, length, past + length),
                             v.reshape(batch * 3, past + length, 4))
        attended = attended.reshape(batch, 3, length, 4).transpose(1, 2).reshape(batch, length, 12)
        logits = self.output(nn.functional.gelu(self.hidden(x + self.projection(attended))))
        return SimpleNamespace(logits=logits, past_key_values=((k, v),) if use_cache else None)


def train_attention():
    codec = WordCodec(); vocab = codec.get_vocab()
    prefixes, targets = [], []
    for colour in ('red', 'green', 'blue'):
        task = PublicTask('colour ' + colour, 5)
        for previous, feedback, answer in ((None, None, 'unsure'), ('unsure', 'revise', colour + ' done')):
            prefix = codec.encode(render_prompt(task, previous, feedback))
            for token in [vocab[w] for w in answer.split()] + [codec.eos_token_id]:
                prefixes.append(prefix.copy()); targets.append(token); prefix.append(token)
    x = torch.zeros(len(prefixes), max(map(len, prefixes)), dtype=torch.long)
    mask = torch.zeros_like(x)
    for i, row in enumerate(prefixes):
        x[i, :len(row)] = torch.tensor(row); mask[i, :len(row)] = 1
    ends = torch.tensor([len(row) - 1 for row in prefixes]); y = torch.tensor(targets)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(859)
        model = TinyAttentionLM()
        initial = state_digest(model)
        optimizer = torch.optim.AdamW(model.parameters(), lr=.02, weight_decay=0.)
        for _ in range(180):
            optimizer.zero_grad(set_to_none=True)
            logits = model(x, attention_mask=mask).logits[torch.arange(len(x)), ends]
            loss = nn.functional.cross_entropy(logits, y)
            loss.backward(); optimizer.step()
    model.eval().requires_grad_(False)
    return model, codec, dict(parameters=sum(p.numel() for p in model.parameters()),
                             steps=180, examples=len(prefixes), loss=float(loss.detach()),
                             initial_sha256=initial, trained_sha256=state_digest(model),
                             pretrained=False, generalization_tested=False)


def make_proposer(model, codec, *, cached=True, **changes):
    cfg = dict(model_sha256=state_digest(model), tokenizer_sha256=tokenizer_digest(codec),
               vocab_size=15, eos_token_id=1, context_tokens=64, max_new_tokens=6, max_output_bytes=128)
    if cached:
        cfg['cache_policy'] = freeze_cache(layers=1, heads=3, head_dim=4,
                                          max_cache_bytes=131072, cache_format='legacy_tuple')
    cfg.update(changes)
    return LocalCausalProposer(model, codec, freeze_generation(**cfg))
