"""Pinned real-source tasks and executable, explicitly supplied typed composition.

Three task families share one repository. Seeds change partitions and generated
procedure inputs, not the underlying real observations. This is not a general
memory or independent-domain qualification. No network access occurs here.
"""

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import random


BASELINE = "f8c9419df6ddeb36ff8b522a50219981fb8d9345"
SOURCE_HASHES = {
    "MODULES.json": "be10ee569a0a12c94631e0d5f25e5ee627b337369e8bccf5b75f236c98d444a5",
    "config.schema.json": "f946f00a381b86f64452320c2999a39bd1d49ad13204e64e98fddbd7c9cdb2b1",
    "github-history.json": "176238bbc41e923ed08c44331cb925467c5232b9119716a23da729db132c9272",
    "LICENSE": "d17f227e4df5da1600391338865ce0f3055211760a36688f816941d58232d8dc",
    "NOTICE": "9d71575ecfd9a843fc1677b0efb08053c6ba9fd686a0de1a6f5382fd3c220915",
}


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


@dataclass(frozen=True)
class WriteEvent:
    event_id: str
    cell_type: str
    key: str
    value: object
    revision: int
    timestamp: str
    source_id: str
    source_pointer: str
    deleted: bool = False


@dataclass(frozen=True)
class ReadQuery:
    query_id: str
    task: str
    cell_type: str
    key: str
    text: str
    inputs: dict
    as_of: str | None
    split: str
    target: object
    episode_id: str

    def public_input(self):
        """The target, episode labels and split are unavailable to a candidate."""
        return {
            name: getattr(self, name)
            for name in ("task", "cell_type", "key", "text", "inputs", "as_of")
        }


@dataclass(frozen=True)
class TypedEdge:
    source_node: str
    output_type: str
    target_node: str
    input_port: str


@dataclass(frozen=True)
class TaskBundle:
    events: tuple[WriteEvent, ...]
    train: tuple[ReadQuery, ...]
    selection: tuple[ReadQuery, ...]
    test: tuple[ReadQuery, ...]
    sources: tuple[dict, ...]
    metadata: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def load_sources(directory=None):
    directory = Path(directory or Path(__file__).resolve().parents[1] / "sources")
    payloads, sources = {}, []
    for name, expected in SOURCE_HASHES.items():
        raw = (directory / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"pinned source mismatch: {name}")
        source_path = {
            "MODULES.json": "docs/modules/MODULES.json",
            "config.schema.json": "codex-rs/core/config.schema.json",
        }.get(name, name)
        sources.append(
            {
                "source_id": name,
                "sha256": expected,
                "bytes": len(raw),
                "license": "Apache-2.0",
                "baseline_commit": BASELINE,
                "source_path": source_path,
                "source_kind": "normalized_api_snapshot"
                if name == "github-history.json"
                else "git_blob",
                "git_blob_sha": None
                if name == "github-history.json"
                else hashlib.sha1(
                    b"blob " + str(len(raw)).encode() + b"\0" + raw
                ).hexdigest(),
            }
        )
        if name.endswith(".json"):
            payloads[name] = json.loads(raw)
    return payloads, tuple(sources)


def _time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("source/query timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def read_store(events, cell_type, key, as_of=None):
    """Strong exact baseline; latest revision within the declared sampled cut."""
    eligible = [
        e
        for e in events
        if e.cell_type == cell_type
        and e.key == key
        and (as_of is None or _time(e.timestamp) <= _time(as_of))
    ]
    if not eligible:
        return None
    latest = max(eligible, key=lambda e: (e.revision, e.event_id))
    return None if latest.deleted else latest.value


def execute_rule(rule, value):
    """Execute a strict primitive-schema program, never a stored example answer.

    Supports standalone integer bounds and string enums only. JSON Schema integer
    includes finite integral floats and excludes booleans. Annotation formats
    such as uint64 are deliberately not interpreted as additional constraints.
    """
    if not isinstance(rule, dict) or set(rule) - {"type", "minimum", "maximum", "enum"}:
        raise ValueError("unsupported primitive schema")
    if rule.get("type") == "integer" and "enum" not in rule:
        bounds = [rule[key] for key in ("minimum", "maximum") if key in rule]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds):
            raise ValueError("integer bounds must be finite numbers")
        if rule.get("minimum", -math.inf) > rule.get("maximum", math.inf):
            raise ValueError("integer interval is empty")
        if type(value) is not int and (
            type(value) is not float
            or not math.isfinite(value)
            or not value.is_integer()
        ):
            return False
        return value >= rule.get("minimum", -math.inf) and value <= rule.get(
            "maximum", math.inf
        )
    if (
        rule.get("type") == "string"
        and set(rule) == {"type", "enum"}
        and isinstance(rule["enum"], list)
        and all(type(v) is str for v in rule["enum"])
    ):
        return type(value) is str and value in rule["enum"]
    raise ValueError("unsupported primitive schema")


def reference_valid(fragment, value):
    """Separate direct oracle for the admitted original schema fragments."""
    if fragment["type"] == "string":
        return isinstance(value, str) and any(
            value == member for member in fragment["enum"]
        )
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, float) and (not math.isfinite(value) or value % 1 != 0):
        return False
    if "minimum" in fragment and value < fragment["minimum"]:
        return False
    if "maximum" in fragment and value > fragment["maximum"]:
        return False
    return True


def schema_rules(schema):
    """Extract complete primitive fragments; union branches are not whole fields."""
    found = {}

    def walk(node, pointer):
        if not isinstance(node, dict):
            return
        if "/oneOf/" not in pointer and "/anyOf/" not in pointer:
            numeric = node.get("type") == "integer" and any(
                k in node for k in ("minimum", "maximum")
            )
            enum = node.get("type") == "string" and len(node.get("enum", [])) >= 2
            if numeric or enum:
                allowed = {
                    "type",
                    "minimum",
                    "maximum",
                    "enum",
                    "description",
                    "title",
                    "default",
                    "examples",
                    "format",
                    "deprecated",
                    "readOnly",
                    "writeOnly",
                }
                if set(node) - allowed:
                    raise ValueError(
                        "primitive extraction would drop a schema assertion"
                    )
                found[pointer] = {
                    k: v
                    for k, v in node.items()
                    if k in {"type", "minimum", "maximum", "enum"}
                }
        for name, child in node.items():
            escaped = name.replace("~", "~0").replace("/", "~1")
            if isinstance(child, dict):
                walk(child, pointer + "/" + escaped)
            elif isinstance(child, list):
                for index, item in enumerate(child):
                    walk(item, pointer + "/" + escaped + "/" + str(index))

    walk(schema, "")
    return found


def _partition(keys, seed):
    ordered = sorted(set(keys), key=lambda key: digest([seed, key]))
    return {
        key: "selection" if index % 2 == 0 else "test"
        for index, key in enumerate(ordered)
    }


def _query(task, kind, key, split, target, *, inputs=None, as_of=None, index=0):
    inputs = {} if inputs is None else inputs
    identity = digest([task, key, split, inputs, as_of, index])
    verb = {"train": "Read", "selection": "Retrieve", "test": "Consult"}[split]
    return ReadQuery(
        identity,
        task,
        kind,
        key,
        f"{verb} {task} for {key}.",
        inputs,
        as_of,
        split,
        target,
        digest([task, key]),
    )


def _bundle(events, queries, sources, seed, **metadata):
    notes = {
        "partition_seed": seed,
        "source_independence": "three task families share one repository",
        "seed_changes_real_source_observations": False,
        "selection_test_keys_disjoint": True,
        "general_memory_established": False,
    }
    notes.update(metadata)
    return TaskBundle(
        tuple(events),
        *(
            tuple(q for q in queries if q.split == split)
            for split in ("train", "selection", "test")
        ),
        sources,
        notes,
    )


def _semantic(modules, sources, seed, stamp):
    events, queries = [], []
    for index, module in enumerate(modules):
        for name in ("owner", "plane", "kind"):
            key = f"module.{name}:{module['id']}"
            events.append(
                WriteEvent(
                    key,
                    "semantic",
                    key,
                    module[name],
                    1,
                    stamp,
                    "MODULES.json",
                    f"/modules/{index}/{name}",
                )
            )
    partition = _partition((e.key for e in events), seed)
    for event in events:
        for split in ("train", partition[event.key]):
            queries.append(
                _query("module_attribute", "semantic", event.key, split, event.value)
            )
    return _bundle(
        events,
        queries,
        sources,
        seed,
        scope="written module metadata; no unseen-entity inference",
    )


def _episodic(history, sources, seed):
    commits = sorted(
        history["frozen_commits"], key=lambda c: (_time(c["timestamp"]), c["sha"])
    )
    counts = Counter(path for c in commits for path in c["changed_paths"])
    paths = sorted(path for path, count in counts.items() if count >= 2)[:64]
    partition, revisions = _partition(paths, seed), Counter()
    events, queries = [], []
    for index, commit in enumerate(commits):
        for path in commit["changed_paths"]:
            if path not in partition:
                continue
            revisions[path] += 1
            events.append(
                WriteEvent(
                    f"{commit['sha']}:{path}",
                    "episodic",
                    path,
                    commit["sha"],
                    revisions[path],
                    commit["timestamp"],
                    "github-history.json",
                    "/frozen_commits/" + str(history["frozen_commits"].index(commit)),
                )
            )
    for event in events:
        observed = _time(event.timestamp)
        later = [
            _time(other.timestamp)
            for other in events
            if other.key == event.key and _time(other.timestamp) > observed
        ]
        hidden_cut = observed + (
            (min(later) - observed) / 2 if later else timedelta(days=1)
        )
        for split, cut in (("train", observed), (partition[event.key], hidden_cut)):
            stamp = cut.isoformat()
            target = read_store(events, "episodic", event.key, stamp)
            queries.append(
                _query(
                    "latest_sampled_change",
                    "episodic",
                    event.key,
                    split,
                    target,
                    as_of=stamp,
                    index=event.revision,
                )
            )
    return _bundle(
        events,
        queries,
        sources,
        seed,
        scope="as-of latest file-touch in this frozen commit sample; not complete repository history",
        path_selection="first 64 sorted paths with at least two sampled touches",
        hidden_cut_policy="midpoint to next distinct timestamp for the same path; last event plus one day",
        simultaneous_event_policy="timestamp then SHA lexical order; no asserted ancestry",
    )


def _program_inputs(rule, rng):
    if rule["type"] == "string":
        members = list(rule["enum"])
        rng.shuffle(members)
        suffix = str(rng.getrandbits(64))
        return [members[0], "invalid-train-" + suffix], [
            members[1],
            "invalid-held-" + suffix,
        ]
    low = int(rule.get("minimum", -1000))
    high = int(rule.get("maximum", low + 100000))
    if high - low < 6:
        raise ValueError(
            "admitted integer rule lacks enough distinct valid probe inputs"
        )
    good = rng.sample(range(low, high + 1), 6)
    bad = [
        low - rng.randrange(1, 1000),
        low - rng.randrange(1000, 2000),
        high + rng.randrange(1, 1000) if "maximum" in rule else low - 2001,
    ]
    return good[:3] + [bad[0], True, "integer-required"], good[3:] + [
        bad[1],
        bad[2],
        0.25,
    ]


def _procedural(schema, sources, seed, stamp):
    rules = schema_rules(schema)
    partition = _partition(rules, seed)
    events, queries = [], []
    for key, rule in sorted(rules.items()):
        events.append(
            WriteEvent(
                key, "procedural", key, rule, 1, stamp, "config.schema.json", key
            )
        )
        rng = random.Random(int(digest([seed, key]), 16))
        train, held = _program_inputs(rule, rng)
        for split, values in (("train", train), (partition[key], held)):
            for index, value in enumerate(values):
                queries.append(
                    _query(
                        "schema_execution",
                        "procedural",
                        key,
                        split,
                        reference_valid(rule, value),
                        inputs={"value": value},
                        index=index,
                    )
                )
    return _bundle(
        events,
        queries,
        sources,
        seed,
        scope="standalone primitive schema execution",
        unsupported="objects, arrays, refs, unions, formats and full product config validation",
        held_inputs="per-rule JSON values disjoint from training; selection/test rule keys disjoint",
        execution_engine="supplied primitive interpreter; not learned code synthesis",
        rule_payload_bytes=len(canonical(rules)),
    )


def _alias(pointer):
    parts = pointer.strip("/").split("/")
    return ".".join(part for part in parts if part not in {"definitions", "properties"})


def _composition(modules, history, procedural, sources, seed, stamp):
    events, queries = list(procedural.events), []
    aliases = {e.key: "config.field:" + _alias(e.key) for e in procedural.events}
    if len(set(aliases.values())) != len(aliases):
        raise ValueError("schema alias collision")
    for event in procedural.events:
        key = aliases[event.key]
        events.append(
            WriteEvent(
                key,
                "semantic",
                key,
                event.key,
                1,
                stamp,
                "config.schema.json",
                event.source_pointer,
            )
        )
    for query in procedural.train + procedural.selection + procedural.test:
        queries.append(
            _query(
                "schema_chain",
                "composition",
                aliases[query.key],
                query.split,
                query.target,
                inputs=query.inputs,
                index=int(query.query_id[:8], 16),
            )
        )
    roots = []
    for index, module in enumerate(modules):
        key = "module.owner:" + module["id"]
        events.append(
            WriteEvent(
                key,
                "semantic",
                key,
                module["owner"],
                1,
                stamp,
                "MODULES.json",
                f"/modules/{index}/owner",
            )
        )
        roots += [
            (binding["path"].rstrip("/"), module["id"])
            for binding in module["rootBindings"]
        ]
    linked = []
    for index, commit in enumerate(history["frozen_commits"]):
        matches = sorted(
            {
                module
                for root, module in roots
                for path in commit["changed_paths"]
                if path == root or path.startswith(root + "/")
            }
        )
        if matches:
            key = "commit.module:" + commit["sha"]
            linked.append(
                WriteEvent(
                    key,
                    "episodic",
                    key,
                    matches[0],
                    1,
                    commit["timestamp"],
                    "github-history.json",
                    f"/frozen_commits/{index}",
                )
            )
    events += linked
    partition = _partition((e.key for e in linked), seed)
    for event in linked:
        owner = read_store(events, "semantic", "module.owner:" + event.value)
        for split in ("train", partition[event.key]):
            queries.append(
                _query("commit_owner_chain", "composition", event.key, split, owner)
            )
    edges = (
        TypedEdge("schema_address", "schema_pointer", "schema_executor", "key"),
        TypedEdge("commit_event", "module_id", "module_owner", "key"),
    )
    return _bundle(
        events,
        queries,
        sources,
        seed,
        edges=[asdict(edge) for edge in edges],
        scope="two supplied cross-type chains: semantic-to-procedural and episodic-to-semantic",
        graph_learned=False,
        program_inputs_copied_from_query=True,
        commit_projection="lexically first registered module touched by a sampled commit; prefix matching scaffold",
        registry_snapshot_for_owner=BASELINE,
        historical_owner_at_commit_claim=False,
        edge_payload_policy="only type/port identifiers in edges; values travel at runtime",
    )


def compose(query, read, edge_transform=None):
    """Run typed calls; read(kind, key, as_of) must never receive query.target.

    An ablation may supply an edge_transform(value, declared_type). Returning
    None removes an edge; a permutation must act on IDs rather than final answers.
    """
    transform = (
        (lambda value, kind: value) if edge_transform is None else edge_transform
    )
    if query.task == "schema_chain":
        pointer = transform(read("semantic", query.key, None), "schema_pointer")
        if not isinstance(pointer, str):
            return None
        rule = read("procedural", pointer, None)
        if rule is None:
            return None
        try:
            return execute_rule(rule, query.inputs["value"])
        except ValueError:
            return None
    if query.task == "commit_owner_chain":
        module = transform(read("episodic", query.key, None), "module_id")
        return (
            read("semantic", "module.owner:" + module, None)
            if isinstance(module, str)
            else None
        )
    raise ValueError("unknown composition task")


def exact_predict(bundle, queries=None, *, edge_transform=None):
    """Strong exact/chained source baseline, including actual held-input execution."""
    queries = bundle.test if queries is None else queries

    def read(kind, key, cut):
        return read_store(bundle.events, kind, key, cut)

    result = []
    for query in queries:
        if query.cell_type == "composition":
            value = compose(query, read, edge_transform)
        else:
            value = read(query.cell_type, query.key, query.as_of)
            if query.cell_type == "procedural" and value is not None:
                value = execute_rule(value, query.inputs["value"])
        result.append(value)
    return result


def build_real_tasks(repo=None, source_dir=None, development_seed=8001):
    """Build source tasks without training or selecting a model.

    repo is accepted for runner compatibility; immutable snapshots are always
    loaded from source_dir, never silently replaced by the current worktree.
    """
    del repo
    if not isinstance(development_seed, int) or development_seed < 0:
        raise ValueError("partition seed must be a nonnegative integer")
    data, sources = load_sources(source_dir)
    modules, history = data["MODULES.json"]["modules"], data["github-history.json"]
    stamp = next(
        c["timestamp"] for c in history["frozen_commits"] if c["sha"] == BASELINE
    )
    procedural = _procedural(
        data["config.schema.json"], sources, development_seed, stamp
    )
    return {
        "semantic": _semantic(modules, sources, development_seed, stamp),
        "episodic": _episodic(history, sources, development_seed),
        "procedural": procedural,
        "composition": _composition(
            modules, history, procedural, sources, development_seed, stamp
        ),
    }
