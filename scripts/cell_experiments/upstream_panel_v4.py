"""Load the reviewed external-source evaluation panel without opening old C."""

import ast
import hashlib
from pathlib import Path

from . import data, repo_execution
from .protocol_v3 import require_prepared

CATALOG_SHA256 = "7a1f4c3c1a18704345bec4c8cb83bc33def341cb08fab8747526b84ee63434f6"
RECORDS_SHA256 = "1ad685bb99ffafdbb9ed0cfa1dbdea3ea2e279fedc326f865da76a173519f8cb"


def load_panel(directory=None):
    """Check all source, fixture and record bytes before catalog registration."""
    directory = (
        Path(directory)
        if directory
        else Path(__file__).resolve().parents[2]
        / "qualification/cell-upstream-panel-20261118"
    )
    raw = (directory / "CATALOG.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != CATALOG_SHA256:
        raise ValueError("upstream reviewed catalog differs")
    catalog = data._parse(raw)
    records_path = directory / "prepared/records.jsonl"
    if hashlib.sha256(records_path.read_bytes()).hexdigest() != RECORDS_SHA256:
        raise ValueError("upstream frozen records differ")
    records = data.load_records(records_path)
    staged = {}
    for fixture in catalog["fixtures"]:
        original = (
            directory / "sources" / fixture["source"]["archive_name"]
        ).read_bytes()
        source = fixture["source"]
        if (
            hashlib.sha256(original).hexdigest() != source["sha256"]
            or hashlib.sha1(
                b"blob " + str(len(original)).encode() + b"\0" + original
            ).hexdigest()
            != source["git_blob"]
        ):
            raise ValueError("upstream source differs from GitHub blob")
        lines = original.decode().splitlines(keepends=True)
        nodes = [
            n
            for n in ast.parse(original).body
            if isinstance(n, ast.FunctionDef) and n.name in fixture["nodes"]
        ]
        if len(nodes) != 1 or nodes[0].decorator_list:
            raise ValueError("upstream function extraction is ambiguous")
        node = nodes[0]
        if (
            "".join(lines[node.lineno - 1 : node.end_lineno]).rstrip("\n") + "\n"
            != fixture["subject_source"]
        ):
            raise ValueError("upstream executed function differs from source")
        identifier = fixture["fixture_id"]
        old = repo_execution._CATALOG.get(identifier)
        if identifier in staged or (old is not None and old != fixture):
            raise ValueError("upstream fixture identity conflicts")
        staged[identifier] = fixture
    if len(staged) != len(records) or len(records) != 6:
        raise ValueError("complete six-task panel required")
    for record in records:
        require_prepared(record)
        parameters = record["task"]["verifier"]["parameters"]
        fixture = staged.get(parameters["fixture_id"])
        if (
            fixture is None
            or data.digest(fixture) != parameters["fixture_sha256"]
            or record["authorization"]["training_allowed"]
            or record["split"] != "selection"
        ):
            raise ValueError("upstream evaluation record binding differs")
        if record["source"] != {
            key: fixture["source"][key]
            for key in ("repository", "revision", "path", "sha256")
        }:
            raise ValueError("upstream task provenance differs")
    repo_execution._CATALOG.update(staged)
    return records
