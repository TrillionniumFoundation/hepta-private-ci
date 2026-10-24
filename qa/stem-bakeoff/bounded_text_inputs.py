"""Label-blind prefix/head-tail inputs with identical native token budgets.

This is a research preprocessing policy, not an assumption that preserving a
tail improves a task. Every retained source position is recorded. The selected
IDs go directly to the model; decoding and re-tokenizing could change budgets.
"""

from dataclasses import asdict, dataclass
import hashlib
import json


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode()


@dataclass(frozen=True)
class TokenSelection:
    policy: str
    source_tokens: int
    source_positions: tuple
    source_token_ids: tuple
    tokenizer_special_tokens: int
    max_tokens: int

    @property
    def retained_source_tokens(self):
        return len(self.source_positions)

    @property
    def truncated(self):
        return self.retained_source_tokens < self.source_tokens

    def receipt(self):
        data = asdict(self)
        data.pop("source_token_ids")
        data["retained_source_tokens"] = self.retained_source_tokens
        data["truncated"] = self.truncated
        data["selected_ids_sha256"] = hashlib.sha256(canonical(self.source_token_ids)).hexdigest()
        return data


def select_source_tokens(token_ids, *, max_tokens, special_tokens, policy):
    if policy not in {"prefix", "head_tail"}:
        raise ValueError("unknown fixed input policy")
    if (type(max_tokens) is not int or not 8 <= max_tokens <= 4096
            or type(special_tokens) is not int or not 0 <= special_tokens < max_tokens):
        raise ValueError("invalid bounded native token allocation")
    if not isinstance(token_ids, (list, tuple)) or not token_ids:
        raise ValueError("nonempty tokenized source required")
    if any(type(token) is not int or token < 0 for token in token_ids):
        raise ValueError("native integer token IDs required")
    keep = min(len(token_ids), max_tokens - special_tokens)
    if policy == "prefix" or keep == len(token_ids):
        positions = tuple(range(keep))
    else:
        head = (keep + 1) // 2
        tail = keep - head
        positions = tuple(range(head)) + tuple(range(len(token_ids) - tail, len(token_ids)))
    return TokenSelection(policy, len(token_ids), positions,
                          tuple(token_ids[index] for index in positions),
                          special_tokens, max_tokens)


def predictor_row(row):
    # No labels, gold patches, hints, or other metadata enter preprocessing.
    fields = ("source_id", "source_version", "text")
    if not isinstance(row, dict) or any(type(row.get(key)) is not str or not row[key] for key in fields):
        raise ValueError("nonempty source identity, revision, and text required")
    public = {key: row[key] for key in fields}
    if len(public["text"].encode()) > 1024 * 1024:
        raise ValueError("source exceeds fixed one-MiB preprocessing bound")
    return public


def prepare_row(tokenizer, row, *, max_tokens=192, policy="prefix"):
    public = predictor_row(row)
    native = tokenizer(public["text"], add_special_tokens=True, truncation=False,
                       return_special_tokens_mask=True,
                       return_attention_mask=False, return_token_type_ids=False)
    special = tokenizer.num_special_tokens_to_add(pair=False)
    ids, mask = native["input_ids"], native["special_tokens_mask"]
    if len(ids) != len(mask) or any(flag not in (0, 1) for flag in mask) or sum(mask) != special:
        raise ValueError("tokenizer special-token contract differs from its declared count")
    body = [i for i, flag in enumerate(mask) if flag == 0]
    if not body or body != list(range(body[0], body[-1] + 1)):
        raise ValueError("only one contiguous native source sequence is supported")
    selected = select_source_tokens(ids[body[0]:body[-1] + 1], max_tokens=max_tokens,
                                    special_tokens=special, policy=policy)
    # Preserve the actual native postprocessor's prefix and suffix. Generic fast
    # tokenizer prepare_for_model may not implement its backend postprocessor.
    prepared_ids = ids[:body[0]] + list(selected.source_token_ids) + ids[body[-1] + 1:]
    prepared = {"input_ids": prepared_ids, "attention_mask": [1] * len(prepared_ids)}
    if len(prepared_ids) != selected.retained_source_tokens + special or len(prepared_ids) > max_tokens:
        raise ValueError("tokenizer special-token contract differs from its declared count")
    receipt = {**selected.receipt(), "source_id": public["source_id"],
               "source_version": public["source_version"],
               "source_text_sha256": hashlib.sha256(public["text"].encode()).hexdigest(),
               "input_ids_sha256": hashlib.sha256(canonical(prepared_ids)).hexdigest(),
               "effective_model_tokens": len(prepared_ids),
               "position_semantics": "zero-based positions in full source tokenization; discontinuous spans concatenate"}
    return prepared, receipt


def matched_inputs(tokenizer, rows, *, max_tokens=192):
    if not rows or len(rows) > 4096:
        raise ValueError("bounded nonempty corpus required")
    result = {policy: [] for policy in ("prefix", "head_tail")}
    identities = set()
    for row in rows:
        public = predictor_row(row)
        if public["source_id"] in identities:
            raise ValueError("duplicate source identity")
        identities.add(public["source_id"])
        for policy in result:
            result[policy].append(prepare_row(tokenizer, public, max_tokens=max_tokens, policy=policy))
        first, second = (result[policy][-1] for policy in result)
        if len(first[0]["input_ids"]) != len(second[0]["input_ids"]):
            raise ValueError("paired native token budgets differ")
    return result
