"""Original, SHA-checked MiniLM FP32 full-six-layer batch reference for G5.

This is not Hugging Face tokenizer/operator parity. It repeats the previous
source-pinned WordPiece and BERT parameter graph and uses exact key-mask semantics
so padding cannot contribute to pooled genuine token features.
"""
from __future__ import annotations

import math
from pathlib import Path

from feature_bus import Denied
from real_minilm_reference import CHECKSUMS, wordpiece
import hashlib
import json


def verified_encoder_only(root: Path) -> dict:
    """Verify model-only files; held publisher labels must be absent in Worker."""
    if not isinstance(root, Path):
        root = Path(root)
    required = ('encoder/model.safetensors','encoder/config.json',
                'encoder/tokenizer.json','encoder/vocab.txt')
    for key in required:
        f = root/key
        if not f.is_file() or f.is_symlink() or f.stat().st_size > 120_000_000:
            raise Denied('missing/unsafe SHA-pinned original Encoder bytes')
        digest = hashlib.sha256()
        with f.open('rb') as fh:
            for part in iter(lambda: fh.read(1 << 20),b''):
                digest.update(part)
        if digest.hexdigest() != CHECKSUMS[key]:
            raise Denied('original Encoder model-material digest drift')
    cfg=json.loads((root/'encoder/config.json').read_text())
    if not (cfg.get('model_type')=='bert' and cfg.get('hidden_size')==384
            and cfg.get('num_hidden_layers')==6 and cfg.get('num_attention_heads')==12
            and cfg.get('intermediate_size')==1536 and cfg.get('vocab_size')==30522
            and cfg.get('layer_norm_eps')==1e-12):
        raise Denied('unsupported original MiniLM source-pinned Encoder architecture')
    return cfg


class BatchedMiniLM:
    def __init__(self, root: Path, batch_size: int = 16):
        if type(batch_size) is not int or not 1 <= batch_size <= 32:
            raise Denied('bounded original-model batch size required')
        import torch
        from safetensors import safe_open
        self.config = verified_encoder_only(root)
        self.vocab = {word:i for i,word in enumerate((root/'encoder/vocab.txt').read_text().splitlines())}
        if len(self.vocab)!=30522 or self.vocab.get('[CLS]')!=101 or self.vocab.get('[SEP]')!=102:
            raise Denied('wrong actual original WordPiece materials')
        with safe_open(str(root/'encoder/model.safetensors'),framework='pt',device='cpu') as fh:
            self.weights={key:fh.get_tensor(key).to(torch.float32) for key in fh.keys()}
        self.calls=0
        self.tokens=0
        self.batch_size = batch_size
        self.actual_batches = 0

    def encode_batch(self, payloads: list[tuple[bytes, str]]) -> list[tuple[float, ...]]:
        import torch
        import torch.nn.functional as F
        if type(payloads) is not list or not 1 <= len(payloads) <= 1024:
            raise Denied('batched original forward input is bounded')
        output = []
        g, cfg = self.weights.__getitem__, self.config
        width, heads = cfg['hidden_size'], cfg['num_attention_heads']
        for start in range(0, len(payloads), self.batch_size):
            items = payloads[start:start + self.batch_size]
            if any(type(p) is not bytes or m != 'text' for p, m in items):
                raise Denied('G5 experiment is frozen text-only, never substitute other modalities')
            ids = [wordpiece(p.decode('utf-8', 'strict'), self.vocab) for p, _ in items]
            n = len(ids)
            max_len = max(len(x) for x in ids)
            padded = torch.zeros((n, max_len), dtype=torch.long)
            mask = torch.zeros((n, max_len), dtype=torch.bool)
            for i, t in enumerate(ids):
                padded[i, :len(t)] = torch.tensor(t, dtype=torch.long)
                mask[i, :len(t)] = True
            with torch.inference_mode():
                x = g('embeddings.word_embeddings.weight')[padded]
                x = x + g('embeddings.position_embeddings.weight')[:max_len].unsqueeze(0)
                x = x + g('embeddings.token_type_embeddings.weight')[0]
                x = F.layer_norm(x, (width,), weight=g('embeddings.LayerNorm.weight'),
                                 bias=g('embeddings.LayerNorm.bias'), eps=cfg['layer_norm_eps'])
                for layer in range(cfg['num_hidden_layers']):
                    pre = f'encoder.layer.{layer}.'
                    att = pre + 'attention.self.'
                    q, k, v = [F.linear(x, g(att + part + '.weight'),
                                        g(att + part + '.bias'))
                               .reshape(n, max_len, heads, width // heads).transpose(1, 2)
                               for part in ('query', 'key', 'value')]
                    logits = (q @ k.transpose(-2, -1)) / math.sqrt(width // heads)
                    logits = logits.masked_fill(~mask[:, None, None, :], -1e4)
                    weight = logits.softmax(-1)
                    y = (weight @ v).transpose(1, 2).contiguous().reshape(n, max_len, width)
                    o = pre + 'attention.output.'
                    y = F.linear(y, g(o + 'dense.weight'), g(o + 'dense.bias'))
                    x = F.layer_norm(x + y, (width,), weight=g(o + 'LayerNorm.weight'),
                                     bias=g(o + 'LayerNorm.bias'), eps=cfg['layer_norm_eps'])
                    o = pre + 'intermediate.dense.'
                    y = F.gelu(F.linear(x, g(o + 'weight'), g(o + 'bias')))
                    o = pre + 'output.'
                    y = F.linear(y, g(o + 'dense.weight'), g(o + 'dense.bias'))
                    x = F.layer_norm(x + y, (width,), weight=g(o + 'LayerNorm.weight'),
                                     bias=g(o + 'LayerNorm.bias'), eps=cfg['layer_norm_eps'])
                wmask = mask.unsqueeze(-1).to(torch.float32)
                pooled = (x * wmask).sum(1) / wmask.sum(1)
                pooled = F.normalize(pooled, dim=-1)
                if not torch.isfinite(pooled).all().item():
                    raise Denied('actual batched pretrained tensor is nonfinite')
                output.extend(tuple(float(y) for y in row) for row in pooled.cpu().tolist())
            self.actual_batches += 1
            self.calls += n  # logical completed six-layer sequence forwards, not layer calls
            self.tokens += sum(map(len, ids))
        if len(output) != len(payloads):
            raise Denied('original model batch output cardinality changed')
        return output
