"""Pinned original SmolLM2 CPU diagnostic, not a serving backend.

A narrow FP32 Llama/ByteLevel implementation for disconnected research hosts.
Weights and tokenizer come from original artifact 11586991191. HF implementation
parity is NOT certified; this profile cannot silently replace ReferenceReader.
"""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import regex
import torch
import torch.nn.functional as F
from jinja2 import Environment
from safetensors.torch import load_file

PROFILE = "hepta.offline-original-smol135-fp32.v1"
PINS = {
    "model.safetensors": "5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c",
    "config.json": "8eb740e8bbe4cff95ea7b4588d17a2432deb16e8075bc5828ff7ba9be94d982a",
    "tokenizer.json": "9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c",
    "tokenizer_config.json": "4ec77d44f62efeb38d7e044a1db318f6a939438425312dfa333b8382dbad98df",
}


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def verify_files(root):
    root = Path(root)
    for name, expected in PINS.items():
        path = root / name
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise ValueError("non-symlink model material required")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise ValueError("original model/tokenizer bytes changed: " + name)


class ByteLevel:
    """Only the pinned Digits(individual)+GPT2 ByteLevel BPE configuration."""

    def __init__(self, root):
        value = json.loads((Path(root) / "tokenizer.json").read_text())
        self.vocab = value["model"]["vocab"]
        self.inverse = {v: k for k, v in self.vocab.items()}
        self.ranks = {
            tuple(pair.split()): i for i, pair in enumerate(value["model"]["merges"])
        }
        self.special = {r["content"]: r["id"] for r in value["added_tokens"]}
        self.split_special = regex.compile(
            "(" + "|".join(map(regex.escape, self.special)) + ")"
        )
        visible = list(range(33, 127)) + list(range(161, 173)) + list(range(174, 256))
        codepoints, extra = visible[:], 0
        for byte in range(256):
            if byte not in visible:
                visible.append(byte)
                codepoints.append(256 + extra)
                extra += 1
        self.encode_byte = dict(zip(visible, map(chr, codepoints)))
        self.decode_byte = {v: k for k, v in self.encode_byte.items()}
        self.pieces = regex.compile(
            r"'s|'t|'re|'ve|'m|'ll|'d| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+"
        )
        cfg = json.loads((Path(root) / "tokenizer_config.json").read_text())
        self.template = Environment().from_string(cfg["chat_template"])

    @lru_cache(maxsize=8192)
    def bpe(self, value):
        parts = tuple(value)
        while len(parts) > 1:
            pair = min(
                zip(parts, parts[1:]), key=lambda x: self.ranks.get(x, float("inf"))
            )
            if pair not in self.ranks:
                break
            merged, i = [], 0
            while i < len(parts):
                if i + 1 < len(parts) and (parts[i], parts[i + 1]) == pair:
                    merged.append(parts[i] + parts[i + 1])
                    i += 2
                else:
                    merged.append(parts[i])
                    i += 1
            parts = tuple(merged)
        return tuple(self.vocab[p] for p in parts)

    def encode(self, text):
        ids = []
        for section in self.split_special.split(text):
            if section in self.special:
                ids.append(self.special[section])
                continue
            for segment in regex.findall(r"\p{N}|[^\p{N}]+", section):
                for piece in self.pieces.findall(segment):
                    ids.extend(
                        self.bpe("".join(self.encode_byte[b] for b in piece.encode()))
                    )
        return ids

    def decode(self, ids):
        special_ids = set(self.special.values())
        data = "".join(self.inverse[i] for i in ids if i not in special_ids)
        return bytes(self.decode_byte[c] for c in data).decode(
            "utf-8", errors="replace"
        )

    def render(self, messages):
        if any(s in m["content"] for m in messages for s in self.special):
            raise ValueError("special-token control text in message data")
        return self.template.render(messages=messages, add_generation_prompt=True)


class OriginalSmol:
    """Original immutable 30-layer, grouped-query Llama weights; no optimizer."""

    def __init__(self, root):
        verify_files(root)
        self.tokenizer = ByteLevel(root)
        self.weights = {
            k: v.float().requires_grad_(False)
            for k, v in load_file(str(Path(root) / "model.safetensors")).items()
        }
        expected = {
            "model.embed_tokens.weight": (49152, 576),
            "model.norm.weight": (576,),
        }
        for i in range(30):
            prefix = f"model.layers.{i}."
            expected.update(
                {
                    prefix + k: shape
                    for k, shape in {
                        "input_layernorm.weight": (576,),
                        "post_attention_layernorm.weight": (576,),
                        "self_attn.q_proj.weight": (576, 576),
                        "self_attn.k_proj.weight": (192, 576),
                        "self_attn.v_proj.weight": (192, 576),
                        "self_attn.o_proj.weight": (576, 576),
                        "mlp.gate_proj.weight": (1536, 576),
                        "mlp.up_proj.weight": (1536, 576),
                        "mlp.down_proj.weight": (576, 1536),
                    }.items()
                }
            )
        if {k: tuple(v.shape) for k, v in self.weights.items()} != expected:
            raise ValueError("unexpected original tensor census")
        self.inverse_frequency = 1.0 / (
            100000.0 ** (torch.arange(0, 64, 2).float() / 64)
        )
        self.identity = digest(PINS)
        self.frozen = self.state_digest()

    def state_digest(self):
        h = hashlib.sha256()
        for name, weight in sorted(self.weights.items()):
            h.update(name.encode())
            h.update(weight.numpy().tobytes())
        return h.hexdigest()

    def verify_frozen(self):
        if self.state_digest() != self.frozen or any(
            w.requires_grad for w in self.weights.values()
        ):
            raise ValueError("research weights changed")

    def norm(self, x, name):
        return (
            x
            * torch.rsqrt(x.square().mean(-1, keepdim=True) + 1e-5)
            * self.weights[name]
        )

    @torch.inference_mode()
    def forward(self, ids, cache=None):
        if not ids or any(type(i) is not int or not 0 <= i < 49152 for i in ids):
            raise ValueError("invalid input token sequence")
        past = 0 if cache is None else cache[0][0].shape[1]
        if past + len(ids) > 8192:
            raise ValueError("original positional limit")
        positions = torch.arange(past, past + len(ids))
        angles = positions[:, None].float() * self.inverse_frequency[None, :]
        angles = torch.cat((angles, angles), dim=-1)[None, :, :]
        cosine, sine = angles.cos(), angles.sin()
        x = F.embedding(torch.tensor(ids), self.weights["model.embed_tokens.weight"])
        new_cache = []
        for i in range(30):
            prefix = f"model.layers.{i}."
            z = self.norm(x, prefix + "input_layernorm.weight")
            projections = []
            for name, heads in (("q", 9), ("k", 3), ("v", 3)):
                value = F.linear(
                    z, self.weights[prefix + f"self_attn.{name}_proj.weight"]
                )
                value = value.reshape(len(ids), heads, 64).transpose(0, 1)
                if name != "v":
                    rotated = torch.cat((-value[..., 32:], value[..., :32]), dim=-1)
                    value = value * cosine + rotated * sine
                projections.append(value)
            q, k, v = projections
            if cache is not None:
                k, v = (
                    torch.cat((cache[i][0], k), dim=1),
                    torch.cat((cache[i][1], v), dim=1),
                )
            new_cache.append((k, v))
            k, v = k.repeat_interleave(3, 0), v.repeat_interleave(3, 0)
            scores = (q @ k.transpose(-2, -1)) / 8.0
            mask = torch.arange(k.shape[1])[None, :] > positions[:, None]
            probabilities = scores.masked_fill(
                mask, torch.finfo(scores.dtype).min
            ).softmax(-1)
            attention = (probabilities @ v).transpose(0, 1).reshape(len(ids), 576)
            x = x + F.linear(
                attention, self.weights[prefix + "self_attn.o_proj.weight"]
            )
            z = self.norm(x, prefix + "post_attention_layernorm.weight")
            hidden = F.silu(F.linear(z, self.weights[prefix + "mlp.gate_proj.weight"]))
            hidden = hidden * F.linear(z, self.weights[prefix + "mlp.up_proj.weight"])
            x = x + F.linear(hidden, self.weights[prefix + "mlp.down_proj.weight"])
        x = self.norm(x[-1:], "model.norm.weight")
        return F.linear(x, self.weights["model.embed_tokens.weight"])[0], new_cache

    def generate(self, ids, maximum=64):
        if type(maximum) is not int or not 1 <= maximum <= 64 or len(ids) > 2048:
            raise ValueError("registered diagnostic token budget")
        logits, cache = self.forward(ids)
        emitted = []
        for _ in range(maximum):
            token = int(logits.argmax())
            emitted.append(token)
            if token == 2 or len(emitted) == maximum:
                break
            logits, cache = self.forward([token], cache)
        return emitted
