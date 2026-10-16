"""Source-local, provenance-complete CONTROLLED event reader.

Research-only typed parser over the exact authored event grammar. Not a language
model, general RAG engine, human sufficient-evidence oracle, or new Memory OS.
No search over withheld originals or target annotations. Missing hops, ambiguities,
withdrawals and untrusted bytes must abstain or reject before final delivery.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import re

SCHEMA = "hepta.memory.local-causal-reader.v1"
EVENT_SCHEMA = "hepta.controlled-event.v1"
ABSTAIN = "I do not have enough evidence."
QUERY = re.compile(
    r"For (service_[0-9a-f]{8}) at logical revision ([0-9]{1,5}), "
    r"what is (the location|the location of the assigned component|"
    r"the mode that actually succeeded for the assigned component)\?"
)
FIELDS = frozenset(("schema", "id", "entity", "attribute", "value", "revision", "supersedes"))
ID = re.compile(r"[A-Za-z0-9_-]{1,96}\Z")
ANSWER = re.compile(r"(?:site|mode)_[0-9a-f]{8}\Z")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def unique(items):
    row = {}
    for key, val in items:
        if key in row:
            raise ValueError("duplicate event source JSON key")
        row[key] = val
    return row


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("invalid observation timestamp")
    try:
        v = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("invalid observation timestamp") from None
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError("timezone-aware evidence time required")
    return v.astimezone(timezone.utc)


def interpret_query(text):
    """Use only publicly delivered question text, not private structured labels."""
    if not isinstance(text, str) or len(text.encode()) > 16384:
        raise ValueError("bounded question text required")
    prefix, separator, _ = text.partition(" Reply with only")
    if not separator:
        return None
    hit = QUERY.fullmatch(prefix)
    if not hit:
        return None
    entity, revision, phrase = hit.groups()
    cut = int(revision)
    if cut > 10000:
        return None
    paths = {
        "the location": ("location",),
        "the location of the assigned component": ("component", "location"),
        "the mode that actually succeeded for the assigned component": (
            "component", "successful_mode"
        ),
    }
    return entity, cut, paths[phrase]


def parse_event(doc, *, query_scope, query_time, revoked):
    """Allow exactly the source scope/time and original byte-level event identity."""
    if any(not isinstance(doc.get(f), str) for f in (
        "identity", "scope", "root", "session", "observed_at", "content"
    )):
        raise ValueError("original source document shape changed")
    if doc["scope"] != query_scope or doc["root"] in revoked:
        raise ValueError("source scope or revocation denial")
    if timestamp(doc["observed_at"]) > query_time:
        raise ValueError("future observation in delivered source")
    if not 1 <= len(doc["content"].encode("utf-8")) <= 4096:
        raise ValueError("source bytes out of bounds")
    row = json.loads(doc["content"], object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite source event")))
    if (
        not isinstance(row, dict) or set(row) != FIELDS
        or row["schema"] != EVENT_SCHEMA or row["id"] != doc["identity"]
        or any(not isinstance(row[k], str) or not ID.fullmatch(row[k]) for k in (
            "id", "entity", "attribute", "value"
        ))
        or type(row["revision"]) is not int
        or not 0 <= row["revision"] <= 10000
        or not isinstance(row["supersedes"], list)
        or len(row["supersedes"]) > 8
        or len(row["supersedes"]) != len(set(row["supersedes"]))
        or any(not isinstance(s, str) or not ID.fullmatch(s) for s in row["supersedes"])
    ):
        raise ValueError("invalid original controlled event")
    return row


def answer(query, selected, originals, *, revoked=()):
    """Resolve only delivered IDs; return explicit source trace or safe abstention."""
    if not isinstance(query, dict) or not all(k in query for k in (
        "identity", "scope", "content", "observed_at"
    )):
        raise ValueError("missing public query fields")
    if not isinstance(selected, (list, tuple)) or len(selected) > 8 or len(selected) != len(set(selected)):
        raise ValueError("duplicate or oversized delivered evidence")
    public = interpret_query(query["content"])
    if public is None:
        return dict(status="abstained", reason="unsupported_question_grammar", answer=ABSTAIN, trace=[], citations=[])
    entity, effective_revision, path = public
    observed = timestamp(query["observed_at"])
    seen = {}
    for index, sid in enumerate(selected, 1):
        if sid not in originals:
            raise ValueError("selected original source missing")
        event = parse_event(originals[sid], query_scope=query["scope"], query_time=observed, revoked=revoked)
        if event["revision"] <= effective_revision:
            seen[sid] = dict(event=event, label=f"E{index}", doc=originals[sid])
    superseded = set()
    for item in seen.values():
        newer = item["event"]
        for earlier_id in newer["supersedes"]:
            if earlier_id not in seen:
                continue  # A revised head can be independently delivered.
            older = seen[earlier_id]["event"]
            if (
                older["entity"] != newer["entity"]
                or older["attribute"] != newer["attribute"]
                or older["revision"] >= newer["revision"]
            ):
                raise ValueError("noncausal or cross-attribute supersedes")
            superseded.add(earlier_id)
    trace = []
    current = entity
    for attribute in path:
        matching = [
            (sid, item) for sid, item in seen.items()
            if sid not in superseded
            and item["event"]["entity"] == current
            and item["event"]["attribute"] == attribute
        ]
        values = {item["event"]["value"] for _, item in matching}
        if len(values) != 1:
            reason = "missing_causal_hop" if not matching else "unresolved_conflict"
            return dict(status="abstained", reason=reason, answer=ABSTAIN, trace=[], citations=[])
        current = next(iter(values))
        # Every traversed step must be cited, never a terminal-only shortcut.
        sid, item = next((sid, item) for sid, item in matching if item["event"]["value"] == current)
        trace.append(dict(
            original_id=sid, label=item["label"], entity=item["event"]["entity"],
            attribute=attribute, value=current, source_digest=hashlib.sha256(item["doc"]["content"].encode("utf-8")).hexdigest(),
            logical_revision=item["event"]["revision"],
        ))
    if not ANSWER.fullmatch(current):
        return dict(status="abstained", reason="untyped_terminal", answer=ABSTAIN, trace=[], citations=[])
    labels = [f"[{t['label']}]" for t in trace]
    return dict(status="answered", reason="complete_original_causal_chain", answer=" ".join([current, *labels]), trace=trace, citations=labels)
