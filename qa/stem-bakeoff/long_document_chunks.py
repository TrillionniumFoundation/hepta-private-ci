"""Native-token windows with complete source spans and overlap-corrected weights.

Tokens are sliced from one untruncated native encoding. They are not generated
by independently retokenizing fragments, which can change boundary tokenization.
Source spans include whitespace ignored by the native tokenizer; coverage of
those spans does not imply that normalization preserves every source character.
"""

from dataclasses import asdict, dataclass
import json
import re

from long_document_sources import canonical, sha


@dataclass(frozen=True)
class ChunkPolicy:
    max_tokens: int = 192
    overlap_tokens: int = 32
    max_source_bytes: int = 1024**2
    max_chunks_per_source: int = 512
    max_total_chunks: int = 32768

    def __post_init__(self):
        for value, low, high in ((self.max_tokens, 8, 512), (self.overlap_tokens, 0, 128),
                (self.max_source_bytes, 1, 1024**2), (self.max_chunks_per_source, 1, 512),
                (self.max_total_chunks, 1, 32768)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError("invalid bounded full-source chunk policy")
        if self.overlap_tokens >= self.max_tokens:
            raise ValueError("overlap must leave forward progress")


@dataclass(frozen=True)
class TextChunk:
    token_start: int
    token_end: int
    char_start: int
    char_end: int
    byte_start: int
    byte_end: int
    weight: float
    input_ids: tuple
    char_spans: tuple
    char_valid: tuple

    def manifest(self):
        return {"content_token_span": [self.token_start, self.token_end],
            "char_span": [self.char_start, self.char_end], "utf8_span": [self.byte_start, self.byte_end],
            "aggregation_weight": self.weight, "native_input_tokens": len(self.input_ids),
            "native_input_ids_sha256": sha(canonical(self.input_ids)),
            "token_character_spans_sha256": sha(canonical([self.char_spans, self.char_valid]))}


@dataclass(frozen=True)
class DocumentPlan:
    source_text: str
    tokenizer_sha256: str
    prefix: str
    policy: ChunkPolicy
    content_tokens: int
    prefix_tokens: int
    special_tokens: int
    chunks: tuple
    seal_sha256: str = ""

    def manifest(self):
        return {"source_utf8_sha256": sha(self.source_text.encode()),
            "source_utf8_bytes": len(self.source_text.encode()), "source_characters": len(self.source_text),
            "tokenizer_sha256": self.tokenizer_sha256, "prefix_sha256": sha(self.prefix.encode()),
            "policy": asdict(self.policy), "content_tokens": self.content_tokens,
            "prefix_tokens_per_chunk": self.prefix_tokens, "special_tokens_per_chunk": self.special_tokens,
            "chunks": [chunk.manifest() for chunk in self.chunks],
            "source_span_coverage": "complete", "native_content_tokens_dropped": 0,
            "native_normalization": "tokenizer may ignore or normalize source characters"}

    def verify(self):
        if sha(canonical(self.manifest())) != self.seal_sha256:
            raise ValueError("native document plan changed after sealing")


def tokenizer_fingerprint(tokenizer):
    if not getattr(tokenizer, "is_fast", False):
        raise ValueError("native fast-tokenizer offsets are required for full source spans")
    raw = json.loads(tokenizer.backend_tokenizer.to_str())
    raw.pop("truncation", None)
    raw.pop("padding", None)
    return sha(canonical(raw))


def plan_document(text, encoded, *, prefix, tokenizer_sha256, policy=ChunkPolicy()):
    if (type(text) is not str or not text or len(text.encode()) > policy.max_source_bytes
            or type(prefix) is not str or not isinstance(encoded, dict)
            or type(tokenizer_sha256) is not str or re.fullmatch(r"[a-f0-9]{64}", tokenizer_sha256) is None):
        raise ValueError("bounded complete source and native encoding required")
    ids = encoded["input_ids"]
    offsets, special = encoded["offset_mapping"], encoded["special_tokens_mask"]
    if (not ids or len(ids) != len(offsets) or len(ids) != len(special)
            or any(type(v) is not int or v < 0 for v in ids)
            or any(type(v) is not int or v not in (0, 1) for v in special)
            or any(len(pair) != 2 or any(type(v) is not int for v in pair)
                   or not 0 <= pair[0] <= pair[1] <= len(prefix) + len(text) for pair in offsets)):
        raise ValueError("malformed native token IDs, masks or source offsets")
    body = [i for i, flag in enumerate(special) if not flag]
    if not body or body != list(range(body[0], body[-1] + 1)):
        raise ValueError("only leading/trailing native special-token templates supported")
    first, last = body[0], body[-1] + 1
    prefix_end = first
    while prefix_end < last and offsets[prefix_end][1] <= len(prefix):
        prefix_end += 1
    content_ids = ids[prefix_end:last]
    source_offsets = tuple((max(0, a - len(prefix)), max(0, b - len(prefix)))
                           for a, b in offsets[prefix_end:last])
    if (not content_ids or any(a > len(text) or b > len(text) for a, b in source_offsets)
            or any(source_offsets[i][0] > source_offsets[i + 1][0]
                   for i in range(len(source_offsets) - 1))):
        raise ValueError("missing native content or nonmonotone source offsets")
    lead, tail = tuple(ids[:prefix_end]), tuple(ids[last:])
    capacity = policy.max_tokens - len(lead) - len(tail)
    if capacity <= policy.overlap_tokens:
        raise ValueError("actual prefix and special tokens exhaust the content window")
    ranges, start, count = [], 0, len(content_ids)
    while start < count:
        end = min(start + capacity, count)
        ranges.append((start, end))
        if len(ranges) > policy.max_chunks_per_source:
            raise ValueError("complete source exceeds chunk budget; no tail was accepted as complete")
        if end == count:
            break
        start = end - policy.overlap_tokens
    multiplicity = [0] * count
    for start, end in ranges:
        for i in range(start, end):
            multiplicity[i] += 1
    if not all(multiplicity):
        raise ValueError("native content tokens are uncovered")
    byte_offsets, total = [0], 0
    for char in text:
        total += len(char.encode())
        byte_offsets.append(total)
    chunks, covered_until = [], 0
    for start, end in ranges:
        char_start = 0 if start == 0 else source_offsets[start][0]
        char_end = len(text) if end == count else max(source_offsets[end - 1][1], source_offsets[end][0])
        if char_start > covered_until or char_end < char_start:
            raise ValueError("native windows leave an uncovered source character interval")
        covered_until = max(covered_until, char_end)
        local = source_offsets[start:end]
        valid = tuple(b > a for a, b in local)
        spans = ((0, 0),) * len(lead) + tuple(pair if ok else (0, 0)
                for pair, ok in zip(local, valid, strict=True)) + ((0, 0),) * len(tail)
        chunk = TextChunk(start, end, char_start, char_end, byte_offsets[char_start], byte_offsets[char_end],
            sum(1 / multiplicity[i] for i in range(start, end)), lead + tuple(content_ids[start:end]) + tail,
            spans, (False,) * len(lead) + valid + (False,) * len(tail))
        chunks.append(chunk)
    if covered_until != len(text) or abs(sum(chunk.weight for chunk in chunks) - count) > 1e-8:
        raise ValueError("incomplete source coverage or inconsistent overlap weights")
    plan = DocumentPlan(text, tokenizer_sha256, prefix, policy, count, prefix_end - first,
                        first + len(ids) - last, tuple(chunks))
    object.__setattr__(plan, "seal_sha256", sha(canonical(plan.manifest())))
    return plan


def tokenize_documents(tokenizer, texts, *, prefix, policy=ChunkPolicy()):
    if not isinstance(texts, (list, tuple)) or not 1 <= len(texts) <= 4096:
        raise ValueError("bounded document corpus required")
    fingerprint = tokenizer_fingerprint(tokenizer)
    plans, total = [], 0
    for begin in range(0, len(texts), 32):
        group = texts[begin:begin + 32]
        if any(type(text) is not str or not text or len(text.encode()) > policy.max_source_bytes for text in group):
            raise ValueError("complete source byte limit exceeded")
        encoded = tokenizer([prefix + text for text in group], add_special_tokens=True,
            truncation=False, padding=False, return_offsets_mapping=True, return_special_tokens_mask=True,
            return_attention_mask=False, return_token_type_ids=False)
        for row, text in enumerate(group):
            plan = plan_document(text, {key: encoded[key][row] for key in
                ("input_ids", "offset_mapping", "special_tokens_mask")}, prefix=prefix,
                tokenizer_sha256=fingerprint, policy=policy)
            total += len(plan.chunks)
            if total > policy.max_total_chunks:
                raise ValueError("complete corpus exceeds declared chunk budget")
            plans.append(plan)
    return tuple(plans)
