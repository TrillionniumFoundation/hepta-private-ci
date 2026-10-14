"""Research-only, explicit-SHA, single-host quarantine journal CLI.

The inputs/pins MUST come from independent CognitiveStore/Artifacts owners in
any real deployment. Reproducing a hash from the supplied file is NOT proof of
independent provenance. This executable cannot access production Runtime,
issue promotion receipts, sign records, or perform parameter unlearning.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path

from amcn_core import canonical, is_sha, require
from amcn_quarantine_ledger import ShadowQuarantineLedger
from amcn_revocation import CellGeneration, SourceWitness

LINEAGE_SCHEMA = "hepta.amcn.research-artifact-bundle.v1"
SOURCE_SCHEMA = "hepta.amcn.research-source-frontier.v1"
MAX_INPUT_BYTES = 4 * 1024 * 1024


def _duplicates(pairs):
    out = {}
    for k, value in pairs:
        require(k not in out, "duplicate source/lineage JSON key")
        out[k] = value
    return out


def _invalid_constant(_):
    require(False, "nonfinite input JSON")


def load_exact(path, expected):
    require(is_sha(expected), "independently supplied input SHA required")
    path = Path(path)
    require(path.is_file() and not path.is_symlink()
            and not any(p.is_symlink() for p in path.parents)
            and path.stat().st_size <= MAX_INPUT_BYTES,
            "missing/linked/oversize research input")
    raw = path.read_bytes()
    require(0 < len(raw) <= MAX_INPUT_BYTES
            and sha256(raw).hexdigest() == expected,
            "input material differs from external SHA")
    try:
        return json.loads(raw, object_pairs_hook=_duplicates,
                          parse_constant=_invalid_constant)
    except (TypeError, UnicodeError, ValueError) as error:
        raise ValueError("invalid external JSON material") from error


def _source(obj):
    expected = {"evidence_id", "source_root", "scope", "generation",
                "revision", "content_sha256", "revoked"}
    require(isinstance(obj, dict) and set(obj) == expected, "source witness schema")
    return SourceWitness(**obj)


def _artifact(obj):
    expected = {"artifact_id", "kind", "scope", "generation", "stem_sha256",
                "head_sha256", "parent_artifacts", "source_witnesses", "manifest_sha256"}
    require(isinstance(obj, dict) and set(obj) == expected, "Cell generation schema")
    require(isinstance(obj["parent_artifacts"], list)
            and isinstance(obj["source_witnesses"], list),
            "artifact parent/source arrays")
    return CellGeneration(**{**obj,
                             "parent_artifacts": tuple(obj["parent_artifacts"]),
                             "source_witnesses": tuple(map(_source, obj["source_witnesses"]))})


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("bootstrap", "update", "recover", "preflight"))
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--lineage", type=Path, required=True)
    parser.add_argument("--lineage-sha256", required=True)
    parser.add_argument("--current-sources", type=Path, required=True)
    parser.add_argument("--current-sources-sha256", required=True)
    parser.add_argument("--source-frontier-sha256", required=True)
    parser.add_argument("--expected-journal-head-sha256", required=True)
    parser.add_argument("--artifact-id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    require(not args.output.exists() and not args.output.is_symlink(),
            "never overwrite original immutable research receipt")
    require(args.output.parent.exists() and not args.output.parent.is_symlink(),
            "the receipt destination must already be an ordinary folder")
    require(is_sha(args.expected_journal_head_sha256)
            and is_sha(args.source_frontier_sha256),
            "missing original external journal/source pins")
    lineage = load_exact(args.lineage, args.lineage_sha256)
    sources = load_exact(args.current_sources, args.current_sources_sha256)
    require(isinstance(lineage, dict) and set(lineage) == {
        "schema", "scope", "generation", "artifacts"} and
        lineage["schema"] == LINEAGE_SCHEMA and
        isinstance(lineage["artifacts"], list), "invalid sealed lineage bundle")
    require(isinstance(sources, dict) and set(sources) == {
        "schema", "scope", "generation", "sources"} and
        sources["schema"] == SOURCE_SCHEMA and
        isinstance(sources["sources"], list), "invalid source-frontier bundle")
    scope, generation = lineage["scope"], lineage["generation"]
    require(scope == sources["scope"] and generation == sources["generation"],
            "source/artifact scope or generation drift")
    artifacts = tuple(map(_artifact, lineage["artifacts"]))
    witness = tuple(map(_source, sources["sources"]))
    owner = ShadowQuarantineLedger(args.journal)
    kw = dict(scope=scope, generation=generation,
              externally_pinned_frontier_sha256=args.source_frontier_sha256)
    if args.action == "bootstrap":
        require(args.artifact_id is None, "bootstrap cannot authorize specific artifact")
        result = owner.apply(artifacts, witness, expected_previous_sha256=
                             args.expected_journal_head_sha256, initialize=True, **kw)
    elif args.action == "update":
        require(args.artifact_id is None, "update cannot authorize specific artifact")
        result = owner.apply(artifacts, witness, expected_previous_sha256=
                             args.expected_journal_head_sha256, **kw)
    elif args.action == "recover":
        require(args.artifact_id is None, "recovery cannot authorize specific artifact")
        result = owner.recover(artifacts, witness, expected_previous_sha256=
                               args.expected_journal_head_sha256, **kw)
    else:
        require(is_sha(args.artifact_id), "preflight requires registered artifact digest")
        result = owner.preflight(
            args.artifact_id, artifacts, witness,
            expected_journal_head_sha256=args.expected_journal_head_sha256, **kw,
        )
    require(result["production_accepted"] is False,
            "research CLI cannot grant authority")
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as out:
            out.write(canonical(result) + b"\n")
            out.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)
    fd = os.open(args.output.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return result


if __name__ == "__main__":
    output = run()
    print(json.dumps(output["metrics"], sort_keys=True))
