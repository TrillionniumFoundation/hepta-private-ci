"""Explicit CPU reference for the two pinned historical snapshots only.

NOT a fallback for five_causal_native, NOT HF parity certification, and NOT a
production model loader. Uses actual safetensors, with exact original inventory
pins. Equations follow the HF v4.57.1 BERT/Llama definitions (Apache-2.0); this
small independent implementation is limited to the archived configs. No network,
pickle, remote code, trainer state, selected-weight mutation or implicit models.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import shutil
import unicodedata

import regex
from jinja2.sandbox import ImmutableSandboxedEnvironment
import torch
from torch.nn import functional as F
from safetensors.torch import load_file

PROFILE = "hepta.archived-torch-reference.v1"
INVENTORIES = {
    "encoder": "5afecdd6098fec07380bc10a30fd8debcffcd147274b3ffd18143f1fa86dc12a",
    "reader": "afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c",
}


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha_file(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def inventory(root):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("ordinary model directory required")
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise ValueError("symlink rejected, including excluded metadata")
        if p.is_file() and ".cache" not in p.relative_to(root).parts:
            out[p.relative_to(root).as_posix()] = {"sha256": sha_file(p), "bytes": p.stat().st_size}
    return out


def verify(root, kind):
    if kind not in INVENTORIES:
        raise ValueError("unknown archived profile")
    out = inventory(root)
    if hashlib.sha256(canonical(out)).hexdigest() != INVENTORIES[kind]:
        raise ValueError("original weight/tokenizer inventory differs")
    return out


def stage_clean(source, destination, kind):
    """Preserve source archive; COPY verified assets, account excluded metadata.

    The original artifact deliberately contains Hub cache metadata. That is not
    model input; never delete it or silently weaken the strict clean loader.
    """
    source, destination = Path(source), Path(destination)
    original = verify(source, kind)
    destination.mkdir(parents=True, exist_ok=False)
    excluded = []
    for p in sorted(source.rglob("*")):
        if p.is_file() and ".cache" in p.relative_to(source).parts:
            excluded.append({"path": p.relative_to(source).as_posix(), "sha256": sha_file(p), "bytes": p.stat().st_size})
    for name in original:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with (source / name).open("rb") as src, target.open("xb") as dst:
            shutil.copyfileobj(src, dst)
    if verify(destination, kind) != original or verify(source, kind) != original:
        raise ValueError("source or clean copy changed")
    return {"kind": kind, "original_inventory_sha256": INVENTORIES[kind],
            "copied_files": original, "excluded_metadata": excluded,
            "source_preserved": True, "independent_attestation": False}


class ArchivedTokenizer:
    """Pure Python interpreter of the PINNED tokenizer.json profiles.

    In particular the Reader has Digits(individual_digits=True) BEFORE ByteLevel;
    it is not the stock slow GPT2 regex alone. Hosted fast-tokenizer parity is
    required before claiming bit equivalence on arbitrary text.
    """
    def __init__(self, root, kind):
        root = Path(root)
        verify(root, kind)
        self.kind = kind
        self.spec = json.loads((root / "tokenizer.json").read_text())
        self.config = json.loads((root / "tokenizer_config.json").read_text())
        self.vocab = self.spec["model"]["vocab"]
        self.inverse = {v: k for k, v in self.vocab.items()}
        self.added = {x["content"]: x["id"] for x in self.spec["added_tokens"]}
        for text, index in self.added.items():
            self.inverse[index] = text
        self.special = {x["id"] for x in self.spec["added_tokens"] if x["special"]}
        self.special_pattern = re.compile("(" + "|".join(re.escape(x) for x in sorted(self.added, key=len, reverse=True)) + ")")
        if kind == "reader":
            expected = {"type": "Sequence", "pretokenizers": [{"type": "Digits", "individual_digits": True}, {"type": "ByteLevel", "add_prefix_space": False, "trim_offsets": True, "use_regex": True}]}
            if self.spec["pre_tokenizer"] != expected or self.spec["normalizer"] is not None:
                raise ValueError("unqualified tokenizer semantics")
            bs = list(range(33, 127)) + list(range(161, 173)) + list(range(174, 256))
            chars = bs[:]; n = 0
            for b in range(256):
                if b not in bs:
                    bs.append(b); chars.append(256+n); n += 1
            self.byte_encoder = dict(zip(bs, map(chr, chars)))
            self.byte_decoder = {v:k for k,v in self.byte_encoder.items()}
            merges = self.spec["model"]["merges"]
            self.ranks = {tuple(pair.split(" ") if isinstance(pair, str) else pair): i for i, pair in enumerate(merges)}
            self.pat = regex.compile(r"'s|'t|'re|'ve|'m|'ll|'d| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+")
            self.digits = regex.compile(r"\p{N}|[^\p{N}]+")
            self.template = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True).from_string(self.config["chat_template"])

    @lru_cache(maxsize=32768)
    def bpe(self, word):
        parts = tuple(word)
        while len(parts) > 1:
            pair = min(zip(parts, parts[1:]), key=lambda p: self.ranks.get(p, float("inf")))
            if pair not in self.ranks:
                break
            result = []; i = 0
            while i < len(parts):
                if i+1 < len(parts) and (parts[i], parts[i+1]) == pair:
                    result.append(parts[i]+parts[i+1]); i += 2
                else:
                    result.append(parts[i]); i += 1
            parts = tuple(result)
        return [self.vocab[x] for x in parts]

    def encode(self, text):
        if not isinstance(text, str) or len(text.encode()) > 262144:
            raise ValueError("bounded text required")
        result = []
        for part in self.special_pattern.split(text):
            if not part:
                continue
            if part in self.added:
                result.append(self.added[part]); continue
            if self.kind == "reader":
                for piece in self.digits.findall(part):
                    for word in self.pat.findall(piece):
                        result.extend(self.bpe("".join(self.byte_encoder[b] for b in word.encode("utf-8"))))
            else:
                # BERT clean text, CJK isolation, lower-case, NFD accent strip.
                clean = []
                for ch in part:
                    code = ord(ch); category = unicodedata.category(ch)
                    if code in (0, 0xfffd) or (category.startswith("C") and ch not in "\t\n\r"):
                        continue
                    cjk = any(lo <= code <= hi for lo, hi in ((0x4e00,0x9fff),(0x3400,0x4dbf),(0x20000,0x2a6df),(0x2a700,0x2b73f),(0x2b740,0x2b81f),(0x2b820,0x2ceaf),(0xf900,0xfaff),(0x2f800,0x2fa1f)))
                    if ch.isspace(): clean.append(" ")
                    elif cjk: clean.extend((" ",ch," "))
                    else: clean.append(ch)
                lower = "".join(ch for ch in unicodedata.normalize("NFD", "".join(clean).lower()) if unicodedata.category(ch) != "Mn")
                tokens = []
                current = ""
                for ch in lower:
                    punct = unicodedata.category(ch).startswith("P") or (33 <= ord(ch) <= 47 or 58 <= ord(ch) <= 64 or 91 <= ord(ch) <= 96 or 123 <= ord(ch) <= 126)
                    if ch.isspace() or punct:
                        if current: tokens.append(current); current = ""
                        if punct: tokens.append(ch)
                    else: current += ch
                if current: tokens.append(current)
                for word in tokens:
                    if len(word) > 100:
                        result.append(self.vocab["[UNK]"]); continue
                    pieces = []; start = 0
                    while start < len(word):
                        end = len(word)
                        while end > start:
                            piece = ("##" if start else "") + word[start:end]
                            if piece in self.vocab: break
                            end -= 1
                        if end == start:
                            pieces = [self.vocab["[UNK]"]]; break
                        pieces.append(self.vocab[piece]); start = end
                    result.extend(pieces)
        return ([self.vocab["[CLS]"]] + result + [self.vocab["[SEP]"]]) if self.kind == "encoder" else result

    def decode(self, ids, skip_special=True):
        words = [self.inverse[int(i)] for i in ids if not skip_special or int(i) not in self.special]
        if self.kind == "reader":
            return bytes(self.byte_decoder[ch] for ch in "".join(words)).decode("utf-8", errors="replace")
        return " ".join(words).replace(" ##", "")

    def chat(self, system, user):
        return self.encode(self.template.render(messages=[{"role":"system","content":system},{"role":"user","content":user}], add_generation_prompt=True))


class ArchivedModel:
    def __init__(self, root, kind):
        self.root, self.kind = Path(root), kind
        self.source = verify(root, kind)
        self.config = json.loads((self.root / "config.json").read_text())
        self.tokenizer = ArchivedTokenizer(root, kind)
        self.weights = {k:v.float() for k,v in load_file(str(self.root / "model.safetensors"), device="cpu").items()}
        self.forward_calls = 0
        if any(not bool(torch.isfinite(v).all()) for v in self.weights.values()):
            raise ValueError("nonfinite archived weights")

    def linear(self, x, key):
        return F.linear(x, self.weights[key+".weight"], self.weights.get(key+".bias"))

    def rms(self, x, key):
        return x * torch.rsqrt(x.square().mean(-1, keepdim=True)+self.config["rms_norm_eps"]) * self.weights[key+".weight"]

    def ln(self, x, key):
        return F.layer_norm(x, (self.config["hidden_size"],), self.weights[key+".weight"], self.weights[key+".bias"], self.config["layer_norm_eps"])

    def valid_ids(self, ids):
        if (not isinstance(ids, (list, tuple)) or not ids
                or any(type(i) is not int or not 0 <= i < self.config["vocab_size"] for i in ids)):
            raise ValueError("invalid token ids")

    @torch.no_grad()
    def bert(self, ids):
        self.valid_ids(ids)
        if self.kind != "encoder" or len(ids) > 512:
            raise ValueError("archived BERT length/profile")
        self.forward_calls += 1
        x = self.weights["embeddings.word_embeddings.weight"][ids][None]
        x = self.ln(x + self.weights["embeddings.position_embeddings.weight"][:len(ids)] + self.weights["embeddings.token_type_embeddings.weight"][0], "embeddings.LayerNorm")
        for i in range(6):
            p = f"encoder.layer.{i}"
            q,k,v = [self.linear(x,p+".attention.self."+n).reshape(1,len(ids),12,32).transpose(1,2) for n in ("query","key","value")]
            attention = (q @ k.transpose(-1,-2) / (32**.5)).softmax(-1) @ v
            x = self.ln(x + self.linear(attention.transpose(1,2).reshape(1,len(ids),384), p+".attention.output.dense"),p+".attention.output.LayerNorm")
            x = self.ln(x + self.linear(F.gelu(self.linear(x,p+".intermediate.dense")),p+".output.dense"),p+".output.LayerNorm")
        return x

    @torch.no_grad()
    def encode(self, texts):
        # One true forward per item, no silently padded or truncated evidence.
        return torch.cat([self.bert(self.tokenizer.encode(s)).mean(1) for s in texts])

    @torch.no_grad()
    def llama(self, ids, cache=None, *, attention="eager"):
        self.valid_ids(ids)
        if self.kind != "reader" or attention not in ("eager","sdpa"):
            raise ValueError("archived Llama profile")
        offset = 0 if cache is None else cache[0][0].shape[-2]
        if offset + len(ids) > 8192:
            raise ValueError("positional capacity")
        self.forward_calls += 1
        x = self.weights["model.embed_tokens.weight"][ids][None]
        pos = torch.arange(offset, offset+len(ids), dtype=torch.float32)
        inv = 1 / (100000 ** (torch.arange(0,64,2,dtype=torch.float32)/64))
        angle = torch.outer(pos, inv); angle = torch.cat((angle,angle),-1)[None,None]
        cos,sin = angle.cos(),angle.sin()
        def rotate(v): return torch.cat((-v[...,32:],v[...,:32]),-1)
        updated = []
        for i in range(30):
            p = f"model.layers.{i}"
            norm = self.rms(x,p+".input_layernorm")
            q = self.linear(norm,p+".self_attn.q_proj").reshape(1,len(ids),9,64).transpose(1,2)
            k = self.linear(norm,p+".self_attn.k_proj").reshape(1,len(ids),3,64).transpose(1,2)
            v = self.linear(norm,p+".self_attn.v_proj").reshape(1,len(ids),3,64).transpose(1,2)
            q,k = q*cos+rotate(q)*sin, k*cos+rotate(k)*sin
            if cache is not None:
                k,v = torch.cat((cache[i][0],k),-2),torch.cat((cache[i][1],v),-2)
            updated.append((k,v))
            k,v = k.repeat_interleave(3,1),v.repeat_interleave(3,1)
            mask = torch.arange(k.shape[-2])[None,:] <= torch.arange(offset,offset+len(ids))[:,None]
            if attention == "eager":
                probs = (q @ k.transpose(-1,-2) * .125).masked_fill(~mask,torch.finfo(torch.float32).min).softmax(-1)
                out = probs @ v
            else:
                out = F.scaled_dot_product_attention(q,k,v,attn_mask=mask,dropout_p=0.0)
            x = x + self.linear(out.transpose(1,2).reshape(1,len(ids),576),p+".self_attn.o_proj")
            norm = self.rms(x,p+".post_attention_layernorm")
            x = x + self.linear(F.silu(self.linear(norm,p+".mlp.gate_proj"))*self.linear(norm,p+".mlp.up_proj"),p+".mlp.down_proj")
        x = self.rms(x,"model.norm")
        return F.linear(x[:,-1], self.weights["model.embed_tokens.weight"]),updated

    @torch.no_grad()
    def generate(self, system, user, maximum=64):
        if type(maximum) is not int or not 1 <= maximum <= 64:
            raise ValueError("fixed diagnostic output budget")
        ids = self.tokenizer.chat(system,user)
        if len(ids) + maximum > 8192:
            raise ValueError("no truncation permitted")
        new,cache = [],None
        prompt = ids
        for _ in range(maximum):
            logits,cache = self.llama(prompt,cache)
            next_id = int(logits[0].argmax());new.append(next_id)
            if next_id == 2: break
            prompt = [next_id]
        return {"answer": self.tokenizer.decode(new), "input_ids": ids, "output_ids": new,
                "input_tokens": len(ids), "generated_tokens": len(new),
                "profile": PROFILE, "upstream_hf_parity_established": False}

    def close(self):
        if verify(self.root,self.kind) != self.source:
            raise ValueError("original disk weights changed")
