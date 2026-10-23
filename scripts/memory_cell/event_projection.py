"""Read-only event projection for observed, controlled program events.

Not a new cognitive.store, natural-language extractor or production authority.
Every selected fact remains an exact original Document. A logical revision is a
sandbox state revision, NOT a calendar observation or independent snapshot.
"""

from dataclasses import dataclass
import json
import re

from native import digest

PROFILE = "hepta.controlled-event.v1"
MAX_EVENTS = 128
FIELDS = {"schema", "id", "entity", "attribute", "value", "revision", "supersedes"}


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,96}", value)


@dataclass(frozen=True)
class Lookup:
    entity: str
    path: tuple[str, ...]
    revision: int

    def validate(self):
        if (
            not identifier(self.entity)
            or not 1 <= len(self.path) <= 3
            or not all(identifier(p) for p in self.path)
            or type(self.revision) is not int
            or not 0 <= self.revision <= 10000
        ):
            raise ValueError("bounded public lookup required")


class EventProjection:
    def __init__(self, documents):
        if (
            not 1 <= len(documents) <= MAX_EVENTS
            or len({d.scope for d in documents}) != 1
            or len({d.identity for d in documents}) != len(documents)
        ):
            raise ValueError("unique bounded single-scope event view required")
        self.originals = {d.identity: d for d in documents}
        self.scope = documents[0].scope
        self.facts = {}

        def pairs(values):
            result = {}
            for k, v in values:
                if k in result:
                    raise ValueError("duplicate event JSON key")
                result[k] = v
            return result

        for doc in documents:
            if not 1 <= len(doc.content.encode()) <= 4096:
                raise ValueError("event byte bound")
            row = json.loads(doc.content, object_pairs_hook=pairs)
            if (
                set(row) != FIELDS
                or row["schema"] != PROFILE
                or row["id"] != doc.identity
                or any(
                    not identifier(row[k])
                    for k in ("id", "entity", "attribute", "value")
                )
                or type(row["revision"]) is not int
                or not 0 <= row["revision"] <= 10000
                or not isinstance(row["supersedes"], list)
                or len(row["supersedes"]) != len(set(row["supersedes"]))
                or len(row["supersedes"]) > 8
                or not all(identifier(v) for v in row["supersedes"])
            ):
                raise ValueError("invalid controlled event")
            self.facts[doc.identity] = row
        for row in self.facts.values():
            for old_id in row["supersedes"]:
                old = self.facts.get(old_id)
                if (
                    old is None
                    or (old["entity"], old["attribute"])
                    != (row["entity"], row["attribute"])
                    or old["revision"] >= row["revision"]
                ):
                    raise ValueError("unresolved or cross-key correction")
        self.frontier = digest([d.__dict__ for d in documents])
        self.source_bytes = sum(len(d.content.encode()) for d in documents)

    def select(self, lookup, candidates, *, mode, revoked, limit=4):
        """All modes see the SAME candidate pool; no target or oracle input.

        Entity/time filtering preserves alternatives. Correction-aware traversal
        retains conflicting heads rather than taking last-write-wins. A revision
        without an explicit supersedes edge does not silently invalidate history.
        """
        lookup.validate()
        if (
            mode not in ("hybrid", "entity_time", "organized")
            or type(limit) is not int
            or not 1 <= limit <= 8
            or not 1 <= len(candidates) <= MAX_EVENTS
            or len(set(candidates)) != len(candidates)
            or any(k not in self.facts for k in candidates)
            or any(d.root in revoked for d in self.originals.values())
        ):
            raise ValueError("invalid or withdrawn event selection")
        if mode == "hybrid":
            return tuple(candidates[:limit]), dict(
                inspected=0, conflicts=0, incomplete=False
            )
        visible = {
            k: self.facts[k]
            for k in candidates
            if self.facts[k]["revision"] <= lookup.revision
        }
        entities, selected, conflicts, incomplete = {lookup.entity}, [], 0, False
        for attribute in lookup.path:
            next_entities = set()
            for entity in sorted(entities):
                matches = [
                    k
                    for k in candidates
                    if k in visible
                    and (visible[k]["entity"], visible[k]["attribute"])
                    == (entity, attribute)
                ]
                if mode == "organized":
                    replaced = {p for k in matches for p in visible[k]["supersedes"]}
                    matches = [k for k in matches if k not in replaced]
                conflicts += int(len({visible[k]["value"] for k in matches}) > 1)
                if not matches or len(set(selected) | set(matches)) > limit:
                    incomplete = True
                    continue  # Never silently choose half of a conflicting group.
                for key in matches:
                    if key not in selected:
                        selected.append(key)
                    next_entities.add(visible[key]["value"])
            entities = next_entities
        return tuple(selected), dict(
            inspected=len(candidates), conflicts=conflicts, incomplete=incomplete
        )
