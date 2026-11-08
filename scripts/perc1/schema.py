"""Strict, finite, content-bound PERC-1 interchange types (stdlib only)."""
import base64
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType

ARMS = ("global_fixed", "dense_fixed", "global_active", "dense_active")
FAMILIES = ("missing_document", "blurred_screenshot", "asynchronous_state", "distractor_video")
PHASES = ("acquisition", "encoding", "communication", "decision", "planning", "inference", "wait", "training", "evaluation", "failure", "cancellation")
MAX_RAW = 4 * 1024 * 1024
MAX_BUNDLE = 8 * 1024 * 1024


class Invalid(ValueError):
    """An input failed an explicit contract, never a scientific rejection."""


def require(condition, message):
    if not condition:
        raise Invalid(message)


def exact(obj, keys):
    require(type(obj) is dict and set(obj) == set(keys.split()), "unknown or missing fields: " + keys)
    return obj


def integer(value, minimum=0):
    require(type(value) is int and minimum <= value <= 2**63 - 1, "invalid integer")
    return value


def real(value, minimum=-math.inf, maximum=math.inf):
    require(type(value) in (int, float) and -1.7976931348623157e308 <= value <= 1.7976931348623157e308 and math.isfinite(value) and minimum <= value <= maximum, "invalid finite number")
    return value


def string(value):
    require(type(value) is str and 0 < len(value) <= 65536, "invalid string")
    return value


def identifier(value):
    require(len(string(value)) <= 256, "identifier exceeds 256 characters")
    return value


def digest(value):
    require(type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None, "invalid SHA-256")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def load(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def invalid_constant(value):
        raise Invalid("nonfinite JSON constant: " + value)
    require(Path(path).stat().st_size <= 128 * 1024 * 1024, "JSON input exceeds 128 MiB; shard the dataset")
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=invalid_constant)


def freeze(value):
    if type(value) is dict:
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    return tuple(freeze(v) for v in value) if type(value) is list else value


def thaw(value):
    if isinstance(value, (dict, MappingProxyType)):
        return {k: thaw(v) for k, v in value.items()}
    return [thaw(v) for v in value] if isinstance(value, (list, tuple)) else value


def locator(value):
    require(type(value) is dict, "locator must be an object")
    kind = value.get("kind")
    common = "kind origin_sha256 "
    if kind == "bytes":
        exact(value, common + "start end total")
        require(integer(value["start"]) < integer(value["end"]) <= integer(value["total"], 1), "invalid byte span")
    elif kind in ("image", "video"):
        fields = "x0 y0 x1 y1 width height"
        if kind == "video":
            fields += " start_ns end_ns duration_ns first_frame last_frame frame_count"
        exact(value, common + fields)
        for lo, hi, bound in (("x0", "x1", "width"), ("y0", "y1", "height")):
            require(integer(value[lo]) < integer(value[hi]) <= integer(value[bound], 1), "invalid image region")
        if kind == "video":
            for lo, hi, bound in (("start_ns", "end_ns", "duration_ns"), ("first_frame", "last_frame", "frame_count")):
                require(integer(value[lo]) < integer(value[hi]) <= integer(value[bound], 1), "invalid video interval")
    elif kind == "state":
        exact(value, common + "pointer version event_ns")
        pointer = value["pointer"]
        require(type(pointer) is str and len(pointer) <= 1024 and (pointer == "" or pointer.startswith("/")) and re.search(r"~(?![01])", pointer) is None, "invalid JSON pointer")
        identifier(value["version"])
        integer(value["event_ns"])
    else:
        raise Invalid("unknown locator kind")
    digest(value["origin_sha256"])
    return value


def within(child, parent):
    locator(child)
    require(child["kind"] == parent["kind"] and child["origin_sha256"] == parent["origin_sha256"], "token origin mismatch")
    bounds = {"bytes": (("start", "end", "total"),), "image": (("x0", "x1", "width"), ("y0", "y1", "height")),
              "video": (("x0", "x1", "width"), ("y0", "y1", "height"), ("start_ns", "end_ns", "duration_ns"), ("first_frame", "last_frame", "frame_count"))}
    if child["kind"] == "state":
        require(child == parent, "state token scope mismatch")
    for lo, hi, bound in bounds.get(child["kind"], ()):
        require(parent[lo] <= child[lo] < child[hi] <= parent[hi] and child[bound] == parent[bound], "token escapes source scope")


@dataclass(frozen=True)
class Cost:
    acquisition: int = 0
    encoding: int = 0
    communication: int = 0
    decision: int = 0
    planning: int = 0
    inference: int = 0
    wait: int = 0
    training: int = 0
    evaluation: int = 0
    failure: int = 0
    cancellation: int = 0

    def __post_init__(self):
        for value in asdict(self).values():
            integer(value)
        integer(sum(asdict(self).values()))

    @classmethod
    def parse(cls, value):
        return cls(**exact(value, " ".join(PHASES)))

    @property
    def total(self):
        return sum(asdict(self).values())


@dataclass(frozen=True)
class Proposal:
    source_id: str
    operation: str
    reason: str
    estimated_gain: float

    @classmethod
    def parse(cls, value, catalog):
        exact(value, "source_id operation reason estimated_gain")
        require(value["source_id"] in catalog and value["operation"] in ("acquire", "poll", "inspect"), "unavailable proposal")
        string(value["reason"])
        real(value["estimated_gain"])
        return cls(**value)


@dataclass(frozen=True)
class ActorObservation:
    source_id: str
    raw_sha256: str
    raw_base64: str
    locator: dict
    encoder_sha256: str
    tokens: list
    observed_ns: int

    def __post_init__(self):
        object.__setattr__(self, "locator", freeze(self.locator))
        object.__setattr__(self, "tokens", freeze(self.tokens))

    def to_dict(self):
        return {key: thaw(value) for key, value in vars(self).items()}

    @classmethod
    def parse(cls, value, source, raw, encoder, arm):
        exact(value, "source_id raw_sha256 raw_base64 locator encoder_sha256 tokens observed_ns")
        require(type(value["raw_base64"]) is str and len(value["raw_base64"]) <= MAX_RAW * 4 // 3 + 4, "raw evidence exceeds bound")
        require(value["source_id"] == source["id"] and value["locator"] == source["locator"], "evidence source mismatch")
        try:
            decoded = base64.b64decode(value["raw_base64"], validate=True)
        except (ValueError, TypeError) as error:
            raise Invalid("invalid raw evidence encoding") from error
        require(decoded == raw and digest(value["raw_sha256"]) == sha(raw), "raw evidence was altered")
        require(digest(value["encoder_sha256"]) == encoder["checkpoint_sha256"], "encoder identity mismatch")
        require(integer(value["observed_ns"]) >= source["available_ns"], "observation predates availability")
        tokens = value["tokens"]
        require(type(tokens) is list and 0 < len(tokens) <= 4096, "empty or excessive tokens")
        require(len(tokens) * encoder["dimension"] <= 65536, "representation scalar budget exceeded")
        require(not arm.startswith("global") or len(tokens) == 1, "global arm must contain one token")
        for token in tokens:
            exact(token, "locator values")
            within(token["locator"], source["locator"])
            require(type(token["values"]) is list and len(token["values"]) == encoder["dimension"], "representation dimension mismatch")
            for item in token["values"]:
                real(item)
        require(len(canonical(value)) <= MAX_BUNDLE, "observation payload exceeds bound")
        return cls(**value)


class Dataset:
    def __init__(self, value, root):
        exact(value, "schema sources episodes")
        require(value["schema"] == "perc1.dataset.v1", "dataset schema mismatch")
        require(type(value["sources"]) is list and type(value["episodes"]) is list, "dataset arrays required")
        self.value, self.root, self.sources, self.episodes = value, Path(root).resolve(), {}, {}
        for source in value["sources"]:
            exact(source, "id episode_id group split description uri path sha256 byte_length locator available_ns")
            for key in ("id", "episode_id", "group", "description", "uri", "path"):
                string(source[key])
            for key in ("id", "episode_id", "group"):
                identifier(source[key])
            require(source["id"] not in self.sources and source["split"] in ("train", "dev", "confirmation"), "duplicate source or invalid split")
            digest(source["sha256"])
            locator(source["locator"])
            integer(source["available_ns"])
            require(integer(source["byte_length"], 1) <= MAX_RAW, "invalid captured view byte length")
            require(not Path(source["path"]).is_absolute() and (self.root / source["path"]).resolve().is_relative_to(self.root), "source path escapes dataset root")
            self.sources[source["id"]] = source
        for episode in value["episodes"]:
            exact(episode, "id group split family task source_ids initial_ids")
            for key in ("id", "group", "task"):
                string(episode[key])
            identifier(episode["id"])
            identifier(episode["group"])
            require(episode["id"] not in self.episodes and episode["family"] in FAMILIES, "duplicate episode or unknown family")
            ids, initial = episode["source_ids"], episode["initial_ids"]
            require(type(ids) is list and len(ids) == len(set(ids)) > 0 and type(initial) is list and len(initial) == len(set(initial)) > 0 and set(initial) <= set(ids), "invalid source catalog")
            for item in ids:
                source = self.sources.get(item)
                require(source is not None and (source["episode_id"], source["group"], source["split"]) == (episode["id"], episode["group"], episode["split"]), "source crosses episode/group/split")
            self.episodes[episode["id"]] = episode
        require(set(self.sources) == {s for e in self.episodes.values() for s in e["source_ids"]}, "orphan source")

    def read(self, source_id):
        source = self.sources[source_id]
        path = (self.root / source["path"]).resolve()
        require(path.is_relative_to(self.root) and not Path(source["path"]).is_absolute(), "source path escapes dataset root")
        require(path.stat().st_size <= MAX_RAW, "source view exceeds 4 MiB; register smaller views")
        raw = path.read_bytes()
        require(sha(raw) == source["sha256"] and len(raw) == source["byte_length"], "source SHA-256/length mismatch")
        loc = source["locator"]
        if loc["kind"] == "bytes":
            require(len(raw) == loc["end"] - loc["start"], "captured byte span length mismatch")
        return raw


def manifest(value, dataset):
    exact(value, "schema dataset_sha256 encoder controller evaluator teacher_sha256 budget splits thresholds")
    require(value["schema"] == "perc1.manifest.v1" and digest(value["dataset_sha256"]) == sha(dataset.value), "manifest/dataset mismatch")
    encoder = exact(value["encoder"], "kind checkpoint_sha256 preprocessor_sha256 dimension")
    require(encoder["kind"] in ("diagnostic_fixture", "external_artifact"), "unknown encoder kind")
    digest(encoder["checkpoint_sha256"])
    digest(encoder["preprocessor_sha256"])
    require(integer(encoder["dimension"], 1) <= 65536, "excessive representation dimension")
    controller = exact(value["controller"], "sha256 training_runs")
    digest(controller["sha256"])
    require(type(controller["training_runs"]) is list and len(controller["training_runs"]) > 0, "missing training runs")
    seeds, receipts = set(), set()
    for run in controller["training_runs"]:
        exact(run, "seed receipt_sha256 cost")
        require(integer(run["seed"]) not in seeds and digest(run["receipt_sha256"]) not in receipts, "training seeds/receipts are not distinct")
        seeds.add(run["seed"])
        receipts.add(run["receipt_sha256"])
        require(Cost.parse(run["cost"]).training > 0, "missing training/teacher cost receipt")
    budget = exact(value["budget"], "unit cap tariff")
    require(budget["unit"] == "microcredits_v1", "unknown budget unit")
    integer(budget["cap"], 1)
    tariff = Cost.parse(budget["tariff"])
    require(all(v > 0 for v in asdict(tariff).values()), "all cost phases require positive tariffs")
    splits = exact(value["splits"], "train dev confirmation")
    seen = set()
    for name, groups in splits.items():
        require(type(groups) is list and len(groups) == len(set(groups)) > 0 and not seen.intersection(groups), "split leakage or empty split")
        seen.update(groups)
        require(set(groups) == {e["group"] for e in dataset.episodes.values() if e["split"] == name}, "split registry mismatch")
    origins = {}
    for source in dataset.sources.values():
        for identity in (source["sha256"], source["locator"]["origin_sha256"]):
            require(identity not in origins or origins[identity] == source["split"], "source bytes/origin crosses splits")
            origins[identity] = source["split"]
    for identity in exact(value["evaluator"], "identity_sha256 rubric_sha256 targets_sha256 canaries_sha256").values():
        digest(identity)
    if value["teacher_sha256"] is not None:
        digest(value["teacher_sha256"])
    if value["thresholds"] is not None:
        limits = exact(value["thresholds"], "minimum_task_gain maximum_field_regression minimum_training_seeds")
        real(limits["minimum_task_gain"], 0, 1)
        real(limits["maximum_field_regression"], 0, 1)
        integer(limits["minimum_training_seeds"], 2)
    return value
