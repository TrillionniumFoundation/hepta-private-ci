"""Bounded, owner-scoped address resolution; aliases never grant authority."""

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import re
import unicodedata


OPERATIONS = ("current", "history", "semantic", "procedure", "change", "apply")
SHAPES = ("event", "attribute", "program", "result", "unsupported")
OP_SHAPE = ("event", "event", "attribute", "program", "result", "result")
MAX_TIME = 2**53 - 1


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def text(value, limit, field):
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode()) > limit
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("invalid " + field)
    return value


def integer(value, low, high, field):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("invalid " + field)
    return value


def normalize(value):
    return unicodedata.normalize("NFKC", value).casefold().strip()


@dataclass(frozen=True)
class ResolvedAddress:
    request: dict
    normalized_text: str
    registry_digest: str
    source_cut: str
    dates: tuple


class AddressError(ValueError):
    pass


class OwnerRegistry:
    """Snapshot supplied by an owner; the execution owner revalidates its cut.

    This object resolves names only. Neither its digest nor a client-supplied
    JSON document authenticates a principal or grants source access.
    """

    def __init__(self, value):
        if not isinstance(value, dict) or set(value) != {
            "schema",
            "scope",
            "source_cut",
            "entities",
        }:
            raise ValueError("invalid registry fields")
        if value["schema"] != "hepta.memory.v7.owner-registry.v1":
            raise ValueError("unsupported registry")
        self.scope = text(value["scope"], 128, "scope")
        self.source_cut = text(value["source_cut"], 64, "source cut")
        if re.fullmatch(r"[a-f0-9]{64}", self.source_cut) is None:
            raise ValueError("invalid source cut digest")
        if (
            not isinstance(value["entities"], list)
            or not 1 <= len(value["entities"]) <= 4096
        ):
            raise ValueError("invalid registry size")
        self.aliases, self.entities = {}, set()
        for entry in value["entities"]:
            if not isinstance(entry, dict) or set(entry) != {"entity", "aliases"}:
                raise ValueError("invalid registry entry")
            entity = text(entry["entity"], 128, "entity")
            if (
                entity in self.entities
                or not isinstance(entry["aliases"], list)
                or len(entry["aliases"]) > 32
            ):
                raise ValueError("invalid entity aliases")
            self.entities.add(entity)
            for name in (entity, *entry["aliases"]):
                alias = normalize(text(name, 128, "alias"))
                if not alias or alias in {
                    "entity",
                    "object",
                    "it",
                    "this",
                    "实体",
                    "对象",
                    "它",
                }:
                    raise ValueError("alias is an ambiguous generic reference")
                self.aliases.setdefault(alias, set()).add(entity)
        self.identity = digest(value)

    def resolve(self, request):
        allowed = {
            "query_id",
            "scope",
            "entity",
            "text",
            "at",
            "since",
            "max_hops",
            "max_cells",
            "source_cut",
        }
        required = {"query_id", "scope", "text", "at", "since", "max_hops", "max_cells"}
        if (
            not isinstance(request, dict)
            or not required <= set(request)
            or set(request) - allowed
        ):
            raise AddressError("invalid-request-fields")
        text(request["query_id"], 128, "query id")
        original = text(request["text"], 8192, "request text")
        if request["scope"] != self.scope:
            raise AddressError("scope-not-in-owner-registry")
        for field in ("at", "since"):
            integer(request[field], 0, MAX_TIME, field)
        if request["since"] > request["at"]:
            raise AddressError("historical-range-is-reversed")
        integer(request["max_hops"], 1, 8, "max hops")
        integer(request["max_cells"], 1, 8, "max cells")
        if "source_cut" in request:
            text(request["source_cut"], 64, "source cut")
            if request["source_cut"] != self.source_cut:
                raise AddressError("registry-cut-mismatch")
        normalized = normalize(original)
        spans = []
        for alias, identities in self.aliases.items():
            left = r"(?<![\w-])" if alias[0].isascii() and alias[0].isalnum() else ""
            right = r"(?![\w-])" if alias[-1].isascii() and alias[-1].isalnum() else ""
            for match in re.finditer(left + re.escape(alias) + right, normalized):
                spans.append((match.start(), match.end(), alias, identities))
        # Longest owner-listed alias wins inside overlapping spans. An alias
        # shared by multiple entities remains ambiguous even with a slot hint.
        selected = []
        for span in sorted(spans, key=lambda item: (-(item[1] - item[0]), item[0])):
            if not any(span[0] < old[1] and old[0] < span[1] for old in selected):
                selected.append(span)
        if any(len(span[3]) != 1 for span in selected):
            raise AddressError("ambiguous-entity-alias")
        mentioned = set().union(*(span[3] for span in selected)) if selected else set()
        if len(mentioned) > 1:
            raise AddressError("multiple-entities-not-supported")
        supplied = request.get("entity")
        if supplied is not None:
            supplied = text(supplied, 128, "entity")
            identities = self.aliases.get(normalize(supplied), set())
            if len(identities) != 1:
                raise AddressError("unknown-or-ambiguous-entity")
            entity = next(iter(identities))
            if mentioned and mentioned != {entity}:
                raise AddressError("text-entity-conflicts-with-slot")
        elif len(mentioned) == 1:
            entity = next(iter(mentioned))
        else:
            raise AddressError("entity-not-resolved")
        for start, end, _, _ in sorted(selected, reverse=True):
            normalized = normalized[:start] + " entity " + normalized[end:]
        dates = []

        def bind_date(match):
            parts = match.group().replace("-", "")
            try:
                parsed = date(int(parts[:4]), int(parts[4:6]), int(parts[6:]))
            except ValueError as error:
                raise AddressError("invalid-date-in-text") from error
            dates.append(int(parsed.strftime("%Y%m%d")))
            return " date "

        normalized = re.sub(
            r"(?<!\d)(?:\d{4}-\d{2}-\d{2}|\d{8})(?!\d)", bind_date, normalized
        )
        if len(set(dates)) > 1:
            raise AddressError("multiple-historical-cutoffs-not-supported")
        canonical_request = {
            key: value for key, value in request.items() if key != "source_cut"
        }
        canonical_request["entity"] = entity
        return ResolvedAddress(
            canonical_request,
            " ".join(normalized.split()),
            self.identity,
            self.source_cut,
            tuple(dates),
        )


def validate_operation(address, operation):
    if operation not in OPERATIONS:
        raise AddressError("unregistered-operation")
    request = address.request
    if address.dates:
        expected = (
            request["since"]
            if operation == "change"
            else request["at"]
            if operation == "history"
            else None
        )
        if expected is None or set(address.dates) != {expected}:
            raise AddressError("text-time-conflicts-with-operation-or-slot")
    cells = {
        "current": ["event"],
        "history": ["event"],
        "semantic": ["semantic"],
        "procedure": ["procedure"],
        "change": ["event"],
        "apply": ["event", "semantic", "procedure"],
    }[operation]
    hops = 2 if operation == "change" else len(cells)
    if len(cells) > request["max_cells"] or hops > request["max_hops"]:
        raise AddressError("typed-plan-exceeds-budget")
    return {
        "operation": operation,
        "required_cells": cells,
        "read_hops": hops,
        "source_cut": address.source_cut,
        "registry_digest": address.registry_digest,
    }
