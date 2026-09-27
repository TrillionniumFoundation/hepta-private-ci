#!/usr/bin/env python3
"""Offline, artifact-bound byte-pair tokenizer for the context owner.

The vocabulary artifact fixes ranks, pre-tokenization, special tokens and the
provider's input serialization. It is an operator input, not guessed from a model
name. No downloaded encodings, character estimates or provider usage fallback.
A provider template still needs independent semantic/golden qualification.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import heapq
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import regex

SCHEMA = "hepta.context-byte-bpe.v1"
REGEX_VERSION = "2026.5.9"
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_REQUEST_BYTES = 32 * 1024 * 1024
MAX_PIECE_BYTES = 1024 * 1024
MAX_VOCABULARY = 1_000_000
MAX_TOKENS = 1_000_000
MAX_ITEMS = 4096


class Rejected(ValueError):
    """Only a bounded reason code is exposed; never include input text."""


def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise Rejected("duplicate_json_key")
        result[key] = value
    return result


def read_json(raw: bytes) -> Any:
    def nonfinite(_: str) -> None:
        raise Rejected("nonfinite_json")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=object_pairs,
                           parse_constant=nonfinite)
        pending = [value]
        visited = 0
        while pending:
            entry = pending.pop()
            visited += 1
            if visited > 1_000_000:
                raise Rejected("json_node_limit")
            if isinstance(entry, dict):
                pending.extend(entry.values())
            elif isinstance(entry, list):
                pending.extend(entry)
            elif type(entry) is float and not math.isfinite(entry):
                raise Rejected("nonfinite_json")
        return value
    except (UnicodeError, ValueError, RecursionError) as error:
        if isinstance(error, Rejected):
            raise
        raise Rejected("invalid_json") from None


def keys(value: Any, required: set[str], optional: set[str] = frozenset()) -> dict[str, Any]:
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - optional:
        raise Rejected("schema_fields")
    return value


def text(value: Any, limit: int = MAX_REQUEST_BYTES) -> str:
    if not isinstance(value, str):
        raise Rejected("expected_text")
    try:
        if len(value.encode("utf-8")) > limit:
            raise Rejected("text_limit")
    except UnicodeError:
        raise Rejected("invalid_unicode") from None
    return value


def integer(value: Any) -> int:
    if type(value) is not int or not 0 <= value < (1 << 32):
        raise Rejected("invalid_token_id")
    return value


@dataclass(frozen=True)
class Encoding:
    ranks: dict[bytes, int]
    specials: dict[str, int]
    pattern: Any
    framing: dict[str, Any]
    provider: str
    model: str
    version: str
    normalization: str
    artifact_sha256: str

    @classmethod
    def from_bytes(cls, raw: bytes) -> "Encoding":
        if not raw or len(raw) > MAX_ARTIFACT_BYTES:
            raise Rejected("artifact_limit")
        value = keys(read_json(raw), {"schema", "provider", "model", "version", "normalization",
                                     "pattern", "mergeable_ranks", "special_tokens", "framing"})
        if value["schema"] != SCHEMA or value["normalization"] != "none":
            raise Rejected("unsupported_artifact")
        ranks: dict[bytes, int] = {}
        token_ids: set[int] = set()
        entries = value["mergeable_ranks"]
        if not isinstance(entries, list) or not 256 <= len(entries) <= MAX_VOCABULARY:
            raise Rejected("vocabulary_limit")
        for entry in entries:
            keys(entry, {"bytes_base64", "rank"})
            try:
                piece = base64.b64decode(text(entry["bytes_base64"], 4 * MAX_PIECE_BYTES), validate=True)
            except (ValueError, binascii.Error):
                raise Rejected("invalid_vocabulary_bytes") from None
            rank = integer(entry["rank"])
            if not piece or len(piece) > MAX_PIECE_BYTES or piece in ranks or rank in token_ids:
                raise Rejected("duplicate_or_invalid_vocabulary")
            ranks[piece] = rank
            token_ids.add(rank)
        if any(bytes([value]) not in ranks for value in range(256)):
            raise Rejected("incomplete_byte_vocabulary")
        specials = value["special_tokens"]
        if not isinstance(specials, dict) or len(specials) > 4096:
            raise Rejected("special_token_limit")
        for name, token in specials.items():
            if not text(name, 4096) or integer(token) in token_ids:
                raise Rejected("invalid_special_token")
            token_ids.add(token)
        pattern_text = text(value["pattern"], 16_384)
        if regex.__version__ != REGEX_VERSION:
            raise Rejected("regex_runtime_version_mismatch")
        try:
            pattern = regex.compile(pattern_text)
        except regex.error:
            raise Rejected("invalid_pattern") from None
        framing = keys(value["framing"], {"request_prefix", "request_suffix", "roles", "instructions_role", "ignored_fields"},
                       {"tools", "structured_items"})
        if not isinstance(framing["roles"], dict) or not framing["roles"]:
            raise Rejected("missing_role_framing")
        for role, rule in framing["roles"].items():
            if role not in {"system", "developer", "user", "assistant"}:
                raise Rejected("unsupported_role")
            keys(rule, {"prefix", "suffix"})
        if framing["instructions_role"] not in framing["roles"]:
            raise Rejected("invalid_instructions_role")
        ignored = framing["ignored_fields"]
        if not isinstance(ignored, list) or any(
            type(key) is not str or key in {"model", "input", "instructions", "tools"} for key in ignored
        ) or len(ignored) != len(set(ignored)):
            raise Rejected("invalid_ignored_fields")
        encoding = cls(ranks, specials, pattern, framing,
                       text(value["provider"], 512), text(value["model"], 512),
                       text(value["version"], 256), "none", hashlib.sha256(raw).hexdigest())
        if not encoding.provider or not encoding.model or not encoding.version:
            raise Rejected("empty_identity")
        # Eagerly validate framing atoms before any input is counted.
        encoding.atoms(framing["request_prefix"])
        encoding.atoms(framing["request_suffix"])
        for rule in framing["roles"].values():
            encoding.atoms(rule["prefix"])
            encoding.atoms(rule["suffix"])
        if "tools" in framing:
            rule = keys(framing["tools"], {"prefix", "suffix"})
            encoding.atoms(rule["prefix"])
            encoding.atoms(rule["suffix"])
        if "structured_items" in framing:
            rules = framing["structured_items"]
            if not isinstance(rules, dict) or len(rules) > 64:
                raise Rejected("structured_item_limit")
            for kind, rule in rules.items():
                if not text(kind, 256) or kind == "message":
                    raise Rejected("invalid_structured_kind")
                keys(rule, {"fields", "prefix", "suffix"})
                fields = rule["fields"]
                if not isinstance(fields, list) or not fields or any(type(key) is not str for key in fields):
                    raise Rejected("invalid_structured_fields")
                if len(fields) != len(set(fields)) or "type" in fields:
                    raise Rejected("invalid_structured_fields")
                encoding.atoms(rule["prefix"])
                encoding.atoms(rule["suffix"])
        return encoding

    def atoms(self, values: Any) -> list[str | int]:
        if not isinstance(values, list) or len(values) > MAX_ITEMS:
            raise Rejected("framing_limit")
        result: list[str | int] = []
        for value in values:
            if not isinstance(value, dict) or len(value) != 1:
                raise Rejected("invalid_framing_atom")
            if "text" in value:
                result.append(text(value["text"]))
            elif "special" in value and value["special"] in self.specials:
                result.append(self.specials[value["special"]])
            else:
                raise Rejected("unknown_special_token")
        return result

    def piece_tokens(self, piece: bytes) -> list[int]:
        if len(piece) > MAX_PIECE_BYTES:
            raise Rejected("piece_limit")
        if piece in self.ranks:
            return [self.ranks[piece]]
        # Ranked adjacent merges with stale-heap invalidation. Ordinary user text
        # never gains special-token meaning even when it spells a special label.
        parts = [bytes([value]) for value in piece]
        count = len(parts)
        previous = [index - 1 for index in range(count)]
        following = [index + 1 if index + 1 < count else -1 for index in range(count)]
        alive = [True] * count
        versions = [0] * count
        heap: list[tuple[int, int, int, int, int]] = []

        def add(left: int) -> None:
            if left < 0 or not alive[left]:
                return
            right = following[left]
            if right < 0:
                return
            rank = self.ranks.get(parts[left] + parts[right])
            if rank is not None:
                heapq.heappush(heap, (rank, left, right, versions[left], versions[right]))

        for index in range(count):
            add(index)
        while heap:
            _, left, right, left_version, right_version = heapq.heappop(heap)
            if not alive[left] or not alive[right] or following[left] != right or (
                versions[left] != left_version or versions[right] != right_version
            ):
                continue
            parts[left] += parts[right]
            alive[right] = False
            versions[left] += 1
            following[left] = following[right]
            if following[right] >= 0:
                previous[following[right]] = left
            add(previous[left])
            add(left)
        return [self.ranks[part] for index, part in enumerate(parts) if alive[index]]

    def ordinary_tokens(self, value: str) -> list[int]:
        text(value)
        result: list[int] = []
        cursor = 0
        try:
            for match in self.pattern.finditer(value, timeout=5):
                if match.start() != cursor or match.end() <= cursor:
                    raise Rejected("pattern_incomplete_coverage")
                result.extend(self.piece_tokens(match.group().encode("utf-8")))
                if len(result) > MAX_TOKENS:
                    raise Rejected("token_limit")
                cursor = match.end()
        except TimeoutError:
            raise Rejected("pattern_timeout") from None
        if cursor != len(value):
            raise Rejected("pattern_incomplete_coverage")
        return result

    def count_atoms(self, atoms: list[str | int]) -> int:
        # Join adjacent ordinary text BEFORE tokenization: BPE is not additive
        # across template/content boundaries. A special token is an actual cut.
        pending: list[str] = []
        count = 0
        bytes_seen = 0
        for atom in [*atoms, -1]:
            if type(atom) is str:
                bytes_seen += len(atom.encode("utf-8"))
                if bytes_seen > MAX_REQUEST_BYTES:
                    raise Rejected("serialized_input_limit")
                pending.append(atom)
                continue
            count += len(self.ordinary_tokens("".join(pending)))
            pending.clear()
            if atom != -1:
                count += 1
            if count > MAX_TOKENS:
                raise Rejected("token_limit")
        return count

    def provider_tokens(self, raw: bytes) -> int:
        if not raw or len(raw) > MAX_REQUEST_BYTES:
            raise Rejected("request_limit")
        request = keys(read_json(raw), {"model", "input"},
                       {"instructions", "tools", *self.framing["ignored_fields"]})
        if request["model"] != self.model:
            raise Rejected("model_mismatch")
        atoms = self.atoms(self.framing["request_prefix"])

        def message(role: str, content: str) -> None:
            rule = self.framing["roles"].get(text(role, 256))
            if rule is None:
                raise Rejected("unqualified_role")
            atoms.extend(self.atoms(rule["prefix"]))
            atoms.append(text(content))
            atoms.extend(self.atoms(rule["suffix"]))

        if request.get("instructions") is not None:
            message(self.framing["instructions_role"], request["instructions"])
        if request.get("tools"):
            if "tools" not in self.framing or not isinstance(request["tools"], list):
                raise Rejected("unqualified_tool_schema")
            if len(request["tools"]) > MAX_ITEMS:
                raise Rejected("tool_limit")
            rule = self.framing["tools"]
            atoms.extend(self.atoms(rule["prefix"]))
            atoms.append(json.dumps(request["tools"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
            atoms.extend(self.atoms(rule["suffix"]))
        inputs = request["input"]
        if isinstance(inputs, str):
            message("user", inputs)
        elif isinstance(inputs, list) and len(inputs) <= MAX_ITEMS:
            for item in inputs:
                if not isinstance(item, dict):
                    raise Rejected("invalid_input_item")
                kind = text(item.get("type", "message"), 256)
                if kind == "message":
                    keys(item, {"role", "content"}, {"type"})
                    content = item["content"]
                    if isinstance(content, str):
                        message(item["role"], content)
                    elif isinstance(content, list) and len(content) <= MAX_ITEMS:
                        pieces: list[str] = []
                        for part in content:
                            keys(part, {"type", "text"})
                            expected = "output_text" if item["role"] == "assistant" else "input_text"
                            if part["type"] != expected:
                                raise Rejected("unqualified_content_type")
                            pieces.append(text(part["text"]))
                        message(item["role"], "".join(pieces))
                    else:
                        raise Rejected("invalid_message_content")
                else:
                    rule = self.framing.get("structured_items", {}).get(kind)
                    if rule is None:
                        raise Rejected("unqualified_structured_item")
                    keys(item, {"type", *rule["fields"]})
                    atoms.extend(self.atoms(rule["prefix"]))
                    atoms.append(json.dumps({key: item[key] for key in rule["fields"]}, ensure_ascii=False,
                                            sort_keys=True, separators=(",", ":"), allow_nan=False))
                    atoms.extend(self.atoms(rule["suffix"]))
        else:
            raise Rejected("input_limit_or_type")
        atoms.extend(self.atoms(self.framing["request_suffix"]))
        count = self.count_atoms(atoms)
        if count == 0:
            raise Rejected("empty_model_input")
        return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--vocabulary", required=True, type=Path)
    parser.add_argument("--normalization", required=True)
    parser.add_argument("--mode", choices=("provider-request", "text"), default="provider-request")
    args = parser.parse_args()
    try:
        with args.vocabulary.open("rb") as stream:
            encoding = Encoding.from_bytes(stream.read(MAX_ARTIFACT_BYTES + 1))
        if (args.provider, args.model, args.version, args.normalization) != (
            encoding.provider, encoding.model, encoding.version, encoding.normalization
        ):
            raise Rejected("artifact_identity_mismatch")
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if not raw or len(raw) > MAX_REQUEST_BYTES:
            raise Rejected("request_limit")
        count = encoding.provider_tokens(raw) if args.mode == "provider-request" else len(encoding.ordinary_tokens(raw.decode("utf-8")))
        if count <= 0:
            raise Rejected("empty_model_input")
        print(count)
        return 0
    except Rejected as error:
        print(f"context_tokenizer_{error}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, RecursionError):
        print("context_tokenizer_invalid_input", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
