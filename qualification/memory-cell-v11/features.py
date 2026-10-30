"""Measured, authenticated frozen encoding shared by every feature-based arm."""

import hashlib
import time

import numpy as np
import torch

from models import verify_base


class Encoder:
    def __init__(self, directory, *, max_tokens=256):
        from transformers import AutoModel, AutoTokenizer
        started = time.perf_counter()
        self.identity = verify_base(directory)
        self.tokenizer = AutoTokenizer.from_pretrained(str(directory), local_files_only=True,
                                                       trust_remote_code=False)
        self.model = AutoModel.from_pretrained(str(directory), local_files_only=True,
                                               trust_remote_code=False).eval()
        self.model.requires_grad_(False)
        self.max_tokens = max_tokens
        self.cache = {}
        self.stats = dict(load_wall_seconds=time.perf_counter() - started,
                          encode_wall_seconds=0.0, encode_cpu_seconds=0.0,
                          encoded_texts=0, padded_tokens=0, cache_hits=0,
                          base_identity=self.identity, max_tokens=max_tokens,
                          profile="pinned fp32 frozen Transformer, masked mean, L2 normalization")

    def encode(self, texts, *, batch_size=16):
        identities = [hashlib.sha256(text.encode()).hexdigest() for text in texts]
        missing = dict((key, text) for key, text in zip(identities, texts, strict=True)
                       if key not in self.cache)
        self.stats["cache_hits"] += len(texts) - len(missing)
        rows = list(missing.items())
        started, cpu = time.perf_counter(), time.process_time()
        for begin in range(0, len(rows), batch_size):
            part = rows[begin:begin + batch_size]
            inputs = self.tokenizer([text for _, text in part], padding=True, truncation=True,
                                    max_length=self.max_tokens, return_tensors="pt")
            with torch.no_grad():
                hidden = self.model(**inputs).last_hidden_state
                mask = inputs["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                pooled = (hidden * mask).sum(1) / mask.sum(1).clamp_min(1)
                values = torch.nn.functional.normalize(pooled, dim=-1).cpu().numpy()
            for (key, _), value in zip(part, values, strict=True):
                self.cache[key] = value
            self.stats["padded_tokens"] += int(inputs["input_ids"].numel())
        self.stats["encoded_texts"] += len(rows)
        self.stats["encode_wall_seconds"] += time.perf_counter() - started
        self.stats["encode_cpu_seconds"] += time.process_time() - cpu
        return np.stack([self.cache[key] for key in identities])

    def receipt(self):
        return dict(self.stats, cache_payload_bytes=sum(x.nbytes for x in self.cache.values()),
                    base_parameter_bytes=sum(p.numel() * p.element_size() for p in self.model.parameters()))
