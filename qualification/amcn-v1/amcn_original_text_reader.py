"""Research-only original SmolLM (Llama) text inference from pinned archived weights.

No Hugging Face parity, no independent Reader score, no safety admission, no
production authorization. Implements an offline GPT-2 byte-level BPE reader
from the *original* tokenizer.json, and a bounded FP32 reference Llama with KV
cache from the *original* BF16 safetensors. Gold answers are not accepted.
"""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
import json
import math
from pathlib import Path
import regex
import torch
import torch.nn.functional as F
from safetensors import safe_open

WEIGHT_SHA256 = "5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c"
MAX_CONTEXT = 1024
MAX_NEW_TOKENS = 96


def file_sha(path: Path):
    h = sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_file(path: Path, *, max_bytes: int, expected_sha: str | None = None):
    if not path.is_file() or path.is_symlink() or path.stat().st_size > max_bytes:
        raise ValueError("missing, unsafe, or oversized pinned model material")
    current = file_sha(path)
    if expected_sha is not None and current != expected_sha:
        raise ValueError("original reader material SHA mismatch")
    return current


def bytes_to_unicode():
    # Original GPT-2 ByteLevel mapping, used by the archived GPT2Tokenizer.
    bs = list(range(ord("!"), ord("~") + 1))
    bs += list(range(ord("¡"), ord("¬") + 1))
    bs += list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, map(chr, cs)))


class ArchivedByteLevelBPE:
    """Local *candidate* reproduction of GPT2 fast tokenizer metadata.

    Exact HF tokenizer parity remains unverified until separately executed
    against official Transformers/Tokenizers. Never label this an HF tokenizer.
    """

    PATTERN = regex.compile(
        r"'s|'t|'re|'ve|'m|'ll|'d| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+",
        regex.IGNORECASE,
    )
    DIGITS = regex.compile(r"(\p{N})")

    def __init__(self, directory: Path, *, expected_tokenizer_sha256: str):
        path = Path(directory) / "tokenizer.json"
        self.sha256 = check_file(path, max_bytes=8 * 1024 * 1024,
                                 expected_sha=expected_tokenizer_sha256)
        data = json.loads(path.read_bytes())
        if (data["model"]["type"] != "BPE"
                or data["pre_tokenizer"]["type"] != "Sequence"
                or [x["type"] for x in data["pre_tokenizer"]["pretokenizers"]]
                != ["Digits", "ByteLevel"]
                or data["pre_tokenizer"]["pretokenizers"][0].get("individual_digits") is not True
                or data["pre_tokenizer"]["pretokenizers"][1].get("add_prefix_space") is not False
                or data.get("normalizer") is not None):
            raise ValueError("unreviewed archived tokenizer configuration")
        self.vocab = data["model"]["vocab"]
        if len(self.vocab) != 49152:
            raise ValueError("unreviewed archived vocabulary")
        self.inverse_vocab = {value: key for key, value in self.vocab.items()}
        if len(self.inverse_vocab) != len(self.vocab):
            raise ValueError("duplicate vocabulary ids")
        self.bpe_ranks = {}
        for i, merge in enumerate(data["model"]["merges"]):
            pair = tuple(merge.split(" ", 1))
            if len(pair) != 2 or pair in self.bpe_ranks:
                raise ValueError("invalid BPE merge order")
            self.bpe_ranks[pair] = i
        self.special = {item["content"]: item["id"]
                        for item in data["added_tokens"] if item["special"]}
        if self.special.get("<|im_start|>") != 1 or self.special.get("<|im_end|>") != 2:
            raise ValueError("missing actual archived chat special tokens")
        tokens = sorted(self.special, key=len, reverse=True)
        self.special_pattern = regex.compile("(" + "|".join(regex.escape(t) for t in tokens) + ")")
        self.byte_encoder = bytes_to_unicode()
        self.byte_decoder = {v: k for k, v in self.byte_encoder.items()}

    @lru_cache(maxsize=30000)
    def _bpe(self, token: str):
        chars = tuple(token)
        while len(chars) > 1:
            pairs = [(self.bpe_ranks[(x, y)], i) for i, (x, y)
                     in enumerate(zip(chars, chars[1:])) if (x, y) in self.bpe_ranks]
            if not pairs:
                break
            _, best = min(pairs)
            chars = chars[:best] + (chars[best] + chars[best + 1],) + chars[best + 2:]
        return chars

    def encode(self, text: str, *, allow_special: bool = True):
        if not isinstance(text, str) or len(text.encode("utf-8")) > 500000:
            raise ValueError("tokenizer input size")
        parts = self.special_pattern.split(text) if allow_special else [text]
        ids = []
        for part in parts:
            if not part:
                continue
            if allow_special and part in self.special:
                ids.append(self.special[part])
                continue
            # Original Digits(individual_digits=True) occurs before ByteLevel.
            for fragment in self.DIGITS.split(part):
                if not fragment:
                    continue
                for chunk in self.PATTERN.findall(fragment):
                    transformed = "".join(self.byte_encoder[b] for b in chunk.encode("utf-8"))
                    for token in self._bpe(transformed):
                        if token not in self.vocab:
                            raise ValueError("BPE produced out-of-vocabulary token")
                        ids.append(self.vocab[token])
        return ids

    def decode(self, ids, *, skip_special: bool = True):
        token_bytes = bytearray()
        def flush():
            nonlocal token_bytes
            if not token_bytes:
                return ""
            chunk = token_bytes.decode("utf-8", errors="replace")
            token_bytes = bytearray()
            return chunk
        pieces = []
        for value in ids:
            if type(value) is not int or value not in self.inverse_vocab:
                raise ValueError("invalid original reader token")
            token = self.inverse_vocab[value]
            if token in self.special:
                pieces.append(flush())
                if not skip_special:
                    pieces.append(token)
            else:
                for char in token:
                    token_bytes.append(self.byte_decoder[char])
        pieces.append(flush())
        return "".join(pieces)


class ArchivedLlama:
    """Deterministic FP32 original BF16 Llama forward and greedy KV decoding.

    Not a replacement for official HF parity. Reuses **original** weights;
    no random, toy, fake, distilled or substituted pretrained tensors.
    """

    def __init__(self, directory: Path, *, expected_sha256=WEIGHT_SHA256):
        path = Path(directory) / "model.safetensors"
        check_file(path, max_bytes=400 * 1024 * 1024, expected_sha=expected_sha256)
        self.config = json.loads((Path(directory) / "config.json").read_bytes())
        c = self.config
        if not (c.get("model_type") == "llama"
                and c.get("num_hidden_layers") == 30
                and c.get("hidden_size") == 576
                and c.get("num_attention_heads") == 9
                and c.get("num_key_value_heads") == 3
                and c.get("tie_word_embeddings") is True
                and c.get("vocab_size") == 49152):
            raise ValueError("unreviewed model architecture")
        self.heads = c["num_attention_heads"]
        self.kv_heads = c["num_key_value_heads"]
        self.hidden = c["hidden_size"]
        self.head_dim = self.hidden // self.heads
        self.rope_theta = float(c["rope_theta"])
        self.rms_eps = float(c["rms_norm_eps"])
        # Checked original tensors are converted to FP32 for bounded reference.
        with safe_open(str(path), framework="pt", device="cpu") as f:
            original_keys = f.keys()
            if len(original_keys) != 272:
                raise ValueError("unexpected original model weight inventory")
            self.weights = {k: f.get_tensor(k).to(torch.float32) for k in original_keys}
        self.cache = None
        self.position = 0
        self.embed = self.weights["model.embed_tokens.weight"]

    def _rms(self, x, weight):
        return x * torch.rsqrt(x.square().mean(-1, keepdim=True) + self.rms_eps) * weight

    @staticmethod
    def _rotate(x):
        x1, x2 = x.chunk(2, dim=-1)
        return torch.cat((-x2, x1), dim=-1)

    def _rope(self, q, k, start, n):
        freqs = torch.outer(torch.arange(start, start + n, dtype=torch.float32),
                            self.rope_theta ** (
                                -torch.arange(0, self.head_dim, 2, dtype=torch.float32)
                                / self.head_dim))
        cos = torch.cat((freqs.cos(), freqs.cos()), dim=-1).unsqueeze(0)
        sin = torch.cat((freqs.sin(), freqs.sin()), dim=-1).unsqueeze(0)
        return q*cos + self._rotate(q)*sin, k*cos + self._rotate(k)*sin

    @torch.inference_mode()
    def forward(self, ids, *, reset=False):
        if reset:
            self.cache = [None] * 30
            self.position = 0
        if self.cache is None:
            raise ValueError("must start with reset=True")
        if not isinstance(ids, list) or not ids or any(type(i) is not int or i < 0 or i >= 49152 for i in ids):
            raise ValueError("unbounded or invalid model token batch")
        n = len(ids)
        if self.position + n > MAX_CONTEXT:
            raise ValueError("model context ceiling; refuse truncation")
        was = self.position
        x = self.embed[torch.tensor(ids)]
        h, kv, hd = self.heads, self.kv_heads, self.head_dim
        for i in range(30):
            prefix = f"model.layers.{i}."
            g = lambda name: self.weights[prefix + name]
            z = self._rms(x, g("input_layernorm.weight"))
            q = F.linear(z, g("self_attn.q_proj.weight")).reshape(n, h, hd).transpose(0, 1)
            k = F.linear(z, g("self_attn.k_proj.weight")).reshape(n, kv, hd).transpose(0, 1)
            v = F.linear(z, g("self_attn.v_proj.weight")).reshape(n, kv, hd).transpose(0, 1)
            q, k = self._rope(q, k, was, n)
            if self.cache[i] is not None:
                old_k, old_v = self.cache[i]
                k, v = torch.cat((old_k, k), dim=-2), torch.cat((old_v, v), dim=-2)
            self.cache[i] = (k, v)
            repeated_k = k.repeat_interleave(h // kv, dim=0)
            repeated_v = v.repeat_interleave(h // kv, dim=0)
            attn = q @ repeated_k.transpose(-1, -2) / math.sqrt(hd)
            # During prefill, block each current token from attending to
            # later tokens. Single-token KV decode sees the whole prior cache.
            if n > 1:
                from_pos = torch.arange(was, was+n).unsqueeze(1)
                to_pos = torch.arange(was+n).unsqueeze(0)
                attn = attn.masked_fill(to_pos > from_pos, float("-inf"))
            y = (attn.softmax(-1) @ repeated_v).transpose(0, 1).contiguous().reshape(n, h*hd)
            x = x + F.linear(y, g("self_attn.o_proj.weight"))
            z = self._rms(x, g("post_attention_layernorm.weight"))
            m = "mlp."
            x = x + F.linear(F.silu(F.linear(z, g(m+"gate_proj.weight")))
                             * F.linear(z, g(m+"up_proj.weight")),
                             g(m+"down_proj.weight"))
        self.position += n
        result = self._rms(x[-1], self.weights["model.norm.weight"])
        return F.linear(result, self.embed)

    @torch.inference_mode()
    def generate(self, input_ids: list[int], *, max_new_tokens: int):
        if type(max_new_tokens) is not int or not 1 <= max_new_tokens <= MAX_NEW_TOKENS:
            raise ValueError("unapproved generation length")
        if len(input_ids) + max_new_tokens > MAX_CONTEXT:
            raise ValueError("Reader input+output exceeds context; never truncate")
        logits = self.forward(input_ids, reset=True)
        generated = []
        for i in range(max_new_tokens):
            token = int(logits.argmax().item())
            generated.append(token)
            if token == 2:  # Original <|im_end|> is the model's eos.
                break
            if i + 1 != max_new_tokens:
                logits = self.forward([token])
        return generated


def format_archived_chat(question: str, evidence: list[str]):
    if not evidence or len(evidence) > 8:
        raise ValueError("bounded evidence required")
    if any(len(x.encode("utf-8")) > 640 for x in evidence):
        raise ValueError("evidence too large; no automatic truncation")
    system = "Answer only from the provided evidence. If insufficient evidence, say unknown. Cite [E1], [E2]."
    context = "\n".join(f"[E{i}] {passage}" for i, passage in enumerate(evidence, 1))
    return (f"<|im_start|>system\n{system}<|im_end|>\n"
            f"<|im_start|>user\n{context}\nQuestion: {question}<|im_end|>\n"
            "<|im_start|>assistant\n")
