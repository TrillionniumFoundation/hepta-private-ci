"""Bounds and pinned reference code for content verification, not adoption."""

from dataclasses import dataclass, fields
from functools import lru_cache
import ast
import hashlib
import json
from pathlib import Path
import re

from closure_io import ClosureError as ClosureError
from closure_io import read_capped as read_capped


REFERENCE_COMMIT = "aeedeee98a5f7472f11b88ef7b869fc5a6d3d8e1"
REFERENCE_HASHES = {
    "adapter.py": "f4c3b03dd22c4a5e7a27459348ba673842060624c6f983e9211112a49bfccba9",
    "backend.py": "47b18cca113cf50ee47bb67032083abb39c44fe151410be792888d3abea55a53",
    "lifecycle.py": "0cb9ce6a732f5fa3156ebc5c28776e3eb241153f7ade3286938965317b9c50eb",
    "download_model.py": "fd0a7e1ba831c4f2929ee8d29d22495c61ecfdbf7ceee3daec9f5110ff09c0f7",
}


@dataclass(frozen=True)
class ClosureLimits:
    max_checkpoint_bytes: int = 64 * 1024 * 1024
    max_dataset_bytes: int = 128 * 1024 * 1024
    max_zip_uncompressed_bytes: int = 128 * 1024 * 1024
    max_array_bytes: int = 64 * 1024 * 1024
    max_metadata_bytes: int = 128 * 1024
    max_npy_header_bytes: int = 4096
    max_examples: int = 131072
    max_dimension: int = 4096
    max_parameter_elements: int = 4 * 1024 * 1024
    max_dataset_elements: int = 4 * 1024 * 1024
    max_encoder_file_bytes: int = 128 * 1024 * 1024
    max_encoder_total_bytes: int = 256 * 1024 * 1024
    max_source_bytes: int = 2 * 1024 * 1024
    max_source_records: int = 256
    max_source_body_bytes: int = 65536

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or not 1 <= value <= field.default:
                raise ClosureError(f"Invalid or enlarged resource bound: {field.name}")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def object_keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ClosureError(f"Missing or unexpected {label} fields")


def integer(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ClosureError(f"Invalid {label}")
    return value


def text(value, maximum, label):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ClosureError(f"Invalid {label}")
    try:
        if len(value.encode("utf-8")) > maximum:
            raise ClosureError(f"Invalid {label}")
    except UnicodeError as error:
        raise ClosureError(f"Invalid {label} encoding") from error
    return value


def digest_text(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ClosureError(f"Invalid {label} digest")
    return value


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ClosureError("Duplicate JSON member")
            value[key] = item
        return value

    def nonfinite(_value):
        raise ClosureError("Non-finite JSON number")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ClosureError("Invalid bounded JSON") from error


@lru_cache(maxsize=1)
def reference():
    """Load only the hash-checked original Adapter; never import the encoder."""
    directory = Path(__file__).resolve().parent
    provenance = strict_json(read_capped(directory / "PROVENANCE.json", 65536))
    if provenance.get("source_commit") != REFERENCE_COMMIT:
        raise ClosureError("Reference source commit changed")
    records = provenance.get("files", [])
    if len(records) != len(REFERENCE_HASHES):
        raise ClosureError("Reference source inventory changed")
    sources = {}
    for record in records:
        name = Path(record["source_path"]).name
        if name not in REFERENCE_HASHES or name in sources or record["modifications"]:
            raise ClosureError("Reference source inventory or modifications changed")
        relative = f"reference/{name}.source"
        if (
            record["vendored_path"] != relative
            or record["source_commit"] != REFERENCE_COMMIT
            or record["source_path"] != f"qualification/memory-cell-v13/{name}"
        ):
            raise ClosureError("Reference source path changed")
        raw = read_capped(directory / relative, 32768)
        blob = hashlib.sha1(
            f"blob {len(raw)}\0".encode() + raw, usedforsecurity=False
        ).hexdigest()
        if (
            len(raw) != record["bytes"]
            or sha(raw) != REFERENCE_HASHES[name]
            or sha(raw) != record["sha256"]
            or blob != record["git_blob"]
        ):
            raise ClosureError("Reference source bytes changed")
        sources[name] = raw
    pins = {}
    for statement in ast.parse(sources["download_model.py"]).body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id in {"MODEL_ID", "REVISION", "FILES"}
        ):
            pins[statement.targets[0].id] = ast.literal_eval(statement.value)
    if json.loads(canonical(pins)) != provenance["encoder_pins"]:
        raise ClosureError("Pinned encoder source disagrees with provenance")
    namespace = {
        "__name__": "hepta_v13_pinned_adapter",
        "__file__": str(directory / "reference/adapter.py.source"),
    }
    exec(compile(sources["adapter.py"], namespace["__file__"], "exec"), namespace)
    return namespace["Adapter"], provenance, pins
