"""Exact typed readers over real documents; address learning lives elsewhere.

Procedures execute a bounded checklist simulator, never external effects. Event
traces are constructed ingestion/correction/revocation scenarios, not production
history. Every missing specialist has a capable generic implementation.
"""

import hashlib
import json
import re
import time

import numpy as np

from learned import canonical


FIELD_PATTERNS = {"owner": r"(?:The primary owner |\*\*Owner:\*\*\s*)`([^`]+)`",
                  "deputy": r"(?:The deputy |\*\*Deputy:\*\*\s*)`([^`]+)`"}
TYPES = frozenset(("event", "semantic", "procedure", "meta"))


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def build_typed_corpus(repo):
    """Add actual front-matter/identity spans excluded by the address-only corpus."""
    from corpus import _documents, build_corpus
    result = build_corpus(repo)
    result["address_corpus_sha256"] = result["corpus_sha256"]
    by_path = {row["path"]: row for row in result["records"]}
    for path, text, source_id in _documents(repo):
        base = by_path[path]
        stop = re.search(r"(?m)^## 2[.]", text).start()
        excerpt = text[:stop]
        heading = "Identity, mission and ownership"
        result["records"].append(dict(id=sha([source_id, "front-matter-and-identity", excerpt]),
            source_id=source_id, module=base["module"], path=path, version=1, kind="semantic",
            available_phase=base["available_phase"], heading=heading, dependencies=[],
            text=base["module"] + "\n" + heading + "\n" + excerpt,
            document_span=dict(start=0, end=stop, raw=excerpt)))
    result.pop("corpus_sha256")
    result["corpus_sha256"] = sha(result)
    return result


def declarations(text):
    return {field: match.group(1) for field, pattern in FIELD_PATTERNS.items()
            if (match := re.search(pattern, text))}


def procedures(text):
    """Preserve exact source spans and only accept contiguous numbered blocks."""
    blocks = []
    for match in re.finditer(r"(?m)^1[.)] [^\n]+(?:\n(?!\s*$|#{1,6}\s)[^\n]+)*", text):
        raw = match.group()
        rows = list(re.finditer(r"(?m)^(\d+)[.)]\s+", raw))
        if len(rows) < 3 or [int(row.group(1)) for row in rows] != list(range(1, len(rows) + 1)):
            continue
        steps = [re.sub(r"\s+", " ", raw[row.end():rows[i + 1].start() if i + 1 < len(rows) else len(raw)]).strip()
                 for i, row in enumerate(rows)]
        blocks.append(dict(start=match.start(), end=match.end(), raw=raw, steps=steps))
    return blocks


def replay(record, entries, cut):
    current = dict(revision=1, text=record["text"], revoked=False)
    visited = 0
    for row in entries:
        visited += 1
        if row["sequence"] <= cut:
            if row["text_sha256"] != sha(row["text"]):
                raise ValueError("event content changed")
            current = dict(revision=row["revision"], text=row["text"], revoked=row["revoked"])
    return current, visited


def execute_checklist(steps, cursor, advance):
    if not (type(cursor) is int and 0 <= cursor <= len(steps)
            and type(advance) is int and 0 <= advance <= 4):
        return None
    position, actions = cursor, []
    for _ in range(advance):
        if position == len(steps):
            break
        actions.append(steps[position])
        position += 1
    return dict(before=cursor, after=position, actions=actions,
                next_action=steps[position] if position < len(steps) else None,
                remaining=steps[position:], complete=position == len(steps))


class TypedMemory:
    def __init__(self, records, events, enabled=TYPES, active=None):
        started = time.perf_counter()
        self.records, self.events, self.enabled = records, events, frozenset(enabled)
        self.active = np.ones(len(records), bool) if active is None else np.asarray(active, dtype=bool)
        if not self.enabled.issubset(TYPES):
            raise ValueError("unknown cell type")
        self.event_cache, self.semantic_cache, self.procedure_cache = {}, {}, {}
        for i, record in enumerate(records):
            if not self.active[i]:
                continue
            for cut in (0, 1, 2):
                state, _ = replay(record, events.get(record["id"], []), cut)
                key = (record["id"], state["revision"])
                if "event" in self.enabled:
                    self.event_cache[(record["id"], cut)] = state
                if not state["revoked"] and "semantic" in self.enabled and key not in self.semantic_cache:
                    self.semantic_cache[key] = declarations(state["text"])
                if not state["revoked"] and "procedure" in self.enabled and key not in self.procedure_cache:
                    self.procedure_cache[key] = procedures(state["text"])
        caches = [list(cache.items()) for cache in (self.event_cache, self.semantic_cache, self.procedure_cache)]
        self.costs = dict(prepare_wall_seconds=time.perf_counter() - started,
                          cache_serialized_bytes=len(canonical(caches)),
                          source_text_bytes=sum(len(row["text"].encode()) for i, row in enumerate(records) if self.active[i]),
                          shared_event_bytes=len(canonical({row["id"]: events.get(row["id"], [])
                                                           for i, row in enumerate(records) if self.active[i]})))

    def solve(self, task, scores, threshold=0., evidence_limit=2):
        started = time.perf_counter()
        receipt = dict(evidence_reads=0, read_bytes=0, parse_calls=0, parse_bytes=0,
                       event_rows_examined=0, evidence=[], addressed=[], operators=[])
        order = np.argsort(-np.asarray(scores), kind="stable")
        selected = [int(i) for i in order if self.active[i] and scores[i] > 0][:evidence_limit]
        if selected and scores[selected[0]] < threshold:
            selected = []
        need_semantic = task["operation"] in ("lookup", "compose")
        need_procedure = task["operation"] in ("checklist", "compose")
        if not need_semantic and not need_procedure:
            raise ValueError("unknown task operation")
        result = {}
        for index in selected:
            record = self.records[index]
            receipt["addressed"].append(record["id"])
            if "event" in self.enabled:
                state = self.event_cache[(record["id"], task["cut"])]
                receipt["operators"].append("event_snapshot")
            else:
                state, visited = replay(record, self.events.get(record["id"], []), task["cut"])
                receipt["event_rows_examined"] += visited
                receipt["operators"].append("generic_event_replay")
            if state["revoked"]:
                continue
            receipt["evidence_reads"] += 1
            receipt["read_bytes"] += len(state["text"].encode())
            receipt["evidence"].append(record["id"])
            key = (record["id"], state["revision"])
            identity = dict(module=record["module"], source_id=record["id"], revision=state["revision"])
            if need_semantic and "declaration" not in result:
                if "semantic" in self.enabled:
                    facts = self.semantic_cache[key]
                    receipt["operators"].append("semantic_cache")
                else:
                    facts = declarations(state["text"])
                    receipt["parse_calls"] += 1
                    receipt["parse_bytes"] += len(state["text"].encode())
                    receipt["operators"].append("generic_declaration_parse")
                if task["field"] in facts:
                    result["declaration"] = identity | dict(field=task["field"], value=facts[task["field"]])
            if need_procedure and "execution" not in result:
                if "procedure" in self.enabled:
                    plans = self.procedure_cache[key]
                    receipt["operators"].append("procedure_cache")
                else:
                    plans = procedures(state["text"])
                    receipt["parse_calls"] += 1
                    receipt["parse_bytes"] += len(state["text"].encode())
                    receipt["operators"].append("generic_procedure_parse")
                if plans:
                    execution = execute_checklist(plans[0]["steps"], task["cursor"], task["advance"])
                    if execution is not None:
                        result["execution"] = identity | execution
        complete = ((not need_semantic or "declaration" in result)
                    and (not need_procedure or "execution" in result))
        if complete and len(result) == 2:
            complete = result["declaration"]["module"] == result["execution"]["module"]
        receipt["wall_seconds"] = time.perf_counter() - started
        return result if complete else None, receipt


def build_tasks(corpus):
    records = corpus["records"]
    identities = {row["module"]: row for row in records if row["heading"] == "Identity, mission and ownership"}
    metadata = {row["module"]: row["fields"] for row in corpus["metadata"]}
    programs = [(row, procedures(row["text"])[0]) for row in records if procedures(row["text"])]
    events, source_spans, tasks = {}, [], []
    for record, plan in programs:
        # The first version is a deliberately incomplete ingestion of authentic
        # source lines. This is not asserted to be a historical document version.
        prefix = record["module"] + "\n" + record["heading"] + "\n" + "\n".join(
            f"{i + 1}. {step}" for i, step in enumerate(plan["steps"][:3]))
        events[record["id"]] = [dict(sequence=sequence, revision=sequence + 1, revoked=sequence == 2,
                                     text=text, text_sha256=sha(text))
                                 for sequence, text in enumerate((prefix, record["text"], ""))]
        source_spans.append(dict(source_id=record["id"], module=record["module"], path=record["path"],
                                 document_sha256=record["source_id"], heading=record["heading"],
                                 **plan))
    templates = {"train": ("For {module}, find {topic}.",),
                 "calibration": ("In {module}, locate the contract about {topic}.",),
                 "test": ("Which {module} passage specifies {topic}?", "Use {module}'s documented {topic}.")}

    def add(record, operation, topic, target_ids, expected, *, field="owner", cut=1, cursor=2, advance=1):
        for split, prompts in templates.items():
            for prompt in prompts:
                row = dict(text=prompt.format(module=record["module"].replace(".", " "), topic=topic),
                           operation=operation, field=field, cut=cut, cursor=cursor, advance=advance,
                           phase=record["available_phase"], split=split, target_ids=target_ids,
                           expected=expected)
                row["id"] = sha(row)
                tasks.append(row)

    for module, record in identities.items():
        for field in FIELD_PATTERNS:
            expected = dict(declaration=dict(module=module, source_id=record["id"], revision=1,
                                             field=field, value=metadata[module][field]))
            add(record, "lookup", f"identity, mission and ownership; report the {field}", [record["id"]], expected, field=field)
        add(record, "lookup", "identity and ownership; report the personal telephone number",
            [record["id"]], None, field="personal_telephone")
    for record, plan in programs:
        identity = identities[record["module"]]
        for cut in (0, 1, 2):
            steps = plan["steps"][:3] if cut == 0 else plan["steps"]
            # Independent oracle uses direct slices; runtime executes a cursor loop.
            position = min(4, len(steps))
            execution = dict(module=record["module"], source_id=record["id"], revision=cut + 1,
                             before=2, after=position, actions=steps[2:position],
                             next_action=steps[position] if position < len(steps) else None,
                             remaining=steps[position:], complete=position == len(steps))
            for operation in ("checklist", "compose"):
                expected = None if cut == 2 else dict(execution=execution)
                targets = [record["id"]]
                topic = record["heading"].lower() + "; advance two checklist steps after the first two"
                if operation == "compose":
                    targets.append(identity["id"])
                    topic += "; also report the primary owner from identity and ownership"
                    if expected is not None:
                        expected["declaration"] = dict(module=record["module"], source_id=identity["id"],
                            revision=1, field="owner", value=metadata[record["module"]]["owner"])
                add(record, operation, topic, targets, expected, cut=cut, advance=2)
    phantom = dict(module="stellar.gardening.scheduler", available_phase=2)
    add(phantom, "lookup", "identity and ownership", [], None)
    return dict(tasks=tasks, events=events, procedure_source_spans=source_spans,
                corpus_sha256=corpus["corpus_sha256"], schema="hepta.memory.typed-tasks.v12",
                limitations=["authored document tasks, not production logs", "only actually numbered source procedures",
                    "bounded checklist simulation, not execution of real-world effects",
                    "event scenarios are partial ingestion, full-source correction, and withdrawal",
                    "semantic/procedure/event readers are exact typed caches, not trained generative models"])
