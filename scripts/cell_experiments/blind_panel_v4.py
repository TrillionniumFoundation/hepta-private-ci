"""Admit the blinded B2 material after its learner weight-freeze handoff."""

import ast
import hashlib
from pathlib import Path

from . import data, repo_execution
from .protocol_v3 import require_prepared

CATALOG_SHA256 = "c3bdb9549bfde75416675609a068d22a7400dad43655afc287dd43cb1b6eb999"
RECORDS_SHA256 = "26b2e625c649a73a991c681bb1949cdaf91b995d8e4bc3402b924495797d42cb"
SOURCES_SHA256 = "2d56265cb5e3346cee347bd240236e66e6feec17829915eb61a0445af9acc2f7"


def _read_pinned(path, expected):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("blinded B2 material differs from its commitment")
    return raw


def load_panel(directory=None):
    """Verify sources, licenses, exact AST slices and prepared record bindings.

    Release timing is recorded by the independent construction handoff. This
    loader verifies artifact identity, not authenticated custody or user origin.
    """
    directory = (
        Path(directory)
        if directory
        else Path(__file__).resolve().parents[2]
        / "qualification/cell-blind-panel-b2-20261118"
    )
    retrieved = data._parse(
        _read_pinned(directory / "SOURCE_RETRIEVAL.json", SOURCES_SHA256)
    )
    sources = {}
    for pin in retrieved["sources"]:
        path = Path(pin["file"])
        if path.name != str(path) or path.name in sources:
            raise ValueError("blinded B2 source path conflicts")
        raw = _read_pinned(directory / "sources" / path, pin["sha256"])
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if len(raw) != pin["size"] or blob != pin["git_blob"]:
            raise ValueError("blinded B2 source differs from GitHub blob")
        sources[path.name] = (pin, raw)
    catalog = data._parse(_read_pinned(directory / "CATALOG.json", CATALOG_SHA256))
    records_path = directory / "prepared/records.jsonl"
    _read_pinned(records_path, RECORDS_SHA256)
    records = data.load_records(records_path)
    staged = {}
    for fixture in catalog["fixtures"]:
        source = fixture["source"]
        pin, original = sources[source["archive_name"]]
        if any(
            source[key] != pin[key]
            for key in ("repository", "revision", "path", "sha256", "git_blob", "url")
        ):
            raise ValueError("blinded B2 source identity differs")
        nodes = [
            node
            for node in ast.parse(original).body
            if isinstance(node, ast.FunctionDef) and node.name in fixture["nodes"]
        ]
        if len(nodes) != 1 or nodes[0].decorator_list:
            raise ValueError("blinded B2 function extraction is ambiguous")
        node = nodes[0]
        lines = original.decode().splitlines(keepends=True)
        exact = "".join(lines[node.lineno - 1 : node.end_lineno]).rstrip("\n") + "\n"
        if exact != fixture["subject_source"]:
            raise ValueError("blinded B2 executed source differs")
        identifier = fixture["fixture_id"]
        old = repo_execution._CATALOG.get(identifier)
        if identifier in staged or (old is not None and old != fixture):
            raise ValueError("blinded B2 fixture identity conflicts")
        staged[identifier] = fixture
    if len(staged) != len(records) or len(records) != 6:
        raise ValueError("complete six-task blinded B2 panel required")
    for record in records:
        require_prepared(record)
        parameters = record["task"]["verifier"]["parameters"]
        fixture = staged.get(parameters["fixture_id"])
        if (
            fixture is None
            or data.digest(fixture) != parameters["fixture_sha256"]
            or record["authorization"]["training_allowed"]
            or record["split"] != "confirmation"
            or record["origin_kind"] != "curated_development"
            or record["exposure"] != "development"
        ):
            raise ValueError("blinded B2 evaluation binding differs")
        if record["source"] != {
            key: fixture["source"][key]
            for key in ("repository", "revision", "path", "sha256")
        }:
            raise ValueError("blinded B2 record provenance differs")
    repo_execution._CATALOG.update(staged)
    return records
