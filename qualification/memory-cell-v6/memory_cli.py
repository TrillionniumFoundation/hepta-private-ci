#!/usr/bin/env python3
"""Write, train, read, revoke and inspect private typed arithmetic memories.

Read requests use the existing six-operation router. The selected router and
encoder must already exist locally; this entry point never downloads models.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

from v6.artifacts import ArtifactOwner
from v6.contracts import MemoryRequest, bounded_text, integer, valid_digest
from v6.encoder import normalize_request
from v6.runtime import MemoryRuntime, train_snapshot
from v6.store import EventStore, StaleSource
from v6.values import validate_typed_value


def load_json(path, maximum_bytes=1_048_576):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > maximum_bytes:
        raise ValueError("JSON file is missing or exceeds its byte limit")
    return json.loads(path.read_bytes())


def load_selected_router(selected, encoder_path):
    from v6.encoder import MiniLMEncoder
    from v6.router import Router

    selected = Path(selected)
    manifest = load_json(selected / "manifest.json", 4_000_000)
    identity = hashlib.sha256((selected / "manifest.json").read_bytes()).hexdigest()
    lexical = manifest["kind"].removesuffix("_split") == "lexical"
    if not lexical and encoder_path is None:
        raise ValueError("--encoder-path is required for this selected router")
    encoder = None if lexical else MiniLMEncoder(encoder_path)
    return Router.load(selected, encoder, expected_manifest_sha256=identity), identity


def write_records(args):
    rows = load_json(args.input)
    rows = rows if isinstance(rows, list) else [rows]
    if not 1 <= len(rows) <= 256:
        raise ValueError("write accepts 1..256 typed records")
    required = {"entity", "kind", "effective_at", "value", "origin_id"}
    for row in rows:
        if not isinstance(row, dict) or not required <= set(row) or set(row) - required - {"predecessor"}:
            raise ValueError("record requires entity, kind, effective_at, value, origin_id and optional predecessor")
        if not all(bounded_text(row[key]) for key in ("entity", "origin_id")) or not integer(
            row["effective_at"], 0, 2**53 - 1
        ):
            raise ValueError("invalid record identity/time")
        if row.get("predecessor") is not None and not valid_digest(row["predecessor"]):
            raise ValueError("invalid predecessor source digest")
        validate_typed_value(row["kind"], row["value"])
    source = EventStore(args.source)
    try:
        written = []
        for row in rows:
            identity = source.append(scope=args.scope, **row)
            written.append(
                {
                    "source_id": identity,
                    "entity": row["entity"],
                    "kind": row["kind"],
                    "effective_at": row["effective_at"],
                }
            )
        return {"written": written, "source_cut": source.cut, "clean_train_required": True}
    finally:
        source.close()


def train(args, router_loader):
    if not Path(args.source).is_file():
        raise ValueError("source database does not exist")
    _, router_digest = router_loader(args.selected, args.encoder_path)
    owner = ArtifactOwner(args.artifacts)
    try:
        current, _ = owner.active()
    finally:
        owner.close()
    expected = current if args.expected_generation is None else args.expected_generation
    if expected != current:
        raise StaleSource("expected generation is not active")
    result = train_snapshot(
        args.source,
        args.artifacts,
        scope=args.scope,
        seed=args.seed,
        expected_generation=expected,
        steps=args.steps,
        hidden=args.hidden,
        router_digest=router_digest,
    )
    return {
        **result,
        "generation": expected + 1,
        "router_digest": router_digest,
        "clean_rebuild": True,
        "serialized_parameter_cell_bytes": sum(value["bytes"] for value in result["cells"].values()),
    }


def read(args, router_loader):
    if not Path(args.source).is_file() or not (Path(args.artifacts) / "owner.sqlite").is_file():
        raise ValueError("source database and a trained artifact owner are required")
    payload = load_json(args.request, 131_072)
    if not isinstance(payload, dict) or payload.get("scope", args.scope) != args.scope:
        raise ValueError("request scope differs from --scope")
    request = MemoryRequest.from_dict({"scope": args.scope, **payload})
    router, router_digest = router_loader(args.selected, args.encoder_path)
    normalized = normalize_request(request.text, request.entity, request.at, request.since)
    decision = router.route(normalized)
    runtime = MemoryRuntime(args.source, args.artifacts)
    try:
        manifest, snapshot = runtime.artifacts.manifest()
        if manifest["scope"] != args.scope or manifest["router_digest"] != router_digest:
            raise StaleSource("selected router/scope differs from the trained snapshot; clean train required")
        result = runtime.read(request, decision["operation"], expected_digest=snapshot)
        return {**result, "router_decision": decision, "router_digest": router_digest}
    finally:
        runtime.close()


def revoke(args):
    if not Path(args.source).is_file():
        raise ValueError("source database does not exist")
    source = EventStore(args.source)
    try:
        if source.record(args.source_id)["scope"] != args.scope:
            raise ValueError("source identity belongs to a different scope")
        cut = source.revoke(args.source_id, args.reason)
        return {"revoked": args.source_id, "source_cut": cut, "clean_train_required": True}
    finally:
        source.close()


def inspect(args):
    if not Path(args.source).is_file() or not (Path(args.artifacts) / "owner.sqlite").is_file():
        raise ValueError("source database and artifact owner must already exist")
    source, owner = EventStore(args.source), ArtifactOwner(args.artifacts)
    try:
        generation, identity = owner.active()
        manifest = None if identity is None else owner.manifest()[0]
        if manifest is not None and manifest["scope"] != args.scope:
            raise ValueError("active snapshot belongs to a different scope")
        return {
            "generation": generation,
            "snapshot_digest": identity,
            "router_digest": None if manifest is None else manifest["router_digest"],
            "source_digest": source.frontier(args.scope),
            "source_cut": source.cut,
            "cost": {
                "source_database_bytes": Path(args.source).stat().st_size,
                "source_journal_bytes": sum(
                    path.stat().st_size
                    for suffix in ("-wal", "-shm")
                    if (path := Path(str(args.source) + suffix)).is_file()
                ),
                "artifact_directory_bytes": sum(
                    path.stat().st_size for path in Path(args.artifacts).rglob("*") if path.is_file()
                ),
                "current_cell_bytes": 0
                if manifest is None
                else sum(ref["bytes"] for ref in manifest["cells"].values()),
                "current_training_cpu_seconds": 0
                if manifest is None
                else sum(row["cpu_seconds"] for row in manifest["training_receipts"].values()),
            },
        }
    finally:
        source.close()
        owner.close()


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("write", "train", "read", "revoke", "inspect"):
        command = commands.add_parser(name)
        command.add_argument("--source", required=True, help="SQLite source owner path")
        command.add_argument("--scope", required=True, help="Exact source ownership scope")
        if name in {"train", "read", "inspect"}:
            command.add_argument("--artifacts", required=True, help="Parameter snapshot/owner directory")
        if name in {"train", "read"}:
            command.add_argument(
                "--selected",
                required=True,
                help="Existing selected router directory with manifest.json and weights.npz",
            )
            command.add_argument(
                "--encoder-path",
                help="Existing pinned encoder directory; required for semantic/hybrid selected routers",
            )
        if name == "write":
            command.add_argument(
                "--input", required=True, help="JSON typed record or array; each append is an immutable transaction"
            )
        elif name == "train":
            command.add_argument("--seed", type=int, default=0)
            command.add_argument("--steps", type=int, default=600)
            command.add_argument("--hidden", type=int, default=48)
            command.add_argument("--expected-generation", type=int)
            command.description = "Cleanly rebuild both parameter cells from surviving sources; requires at least two live semantic and two procedure records."
        elif name == "read":
            command.add_argument(
                "--request",
                required=True,
                help="MemoryRequest JSON: query_id, entity, text, at, since; optional scope/budgets/schema",
            )
        elif name == "revoke":
            command.add_argument("--source-id", required=True)
            command.add_argument("--reason", required=True)
    return result


def main(argv=None, *, router_loader=None):
    args = parser().parse_args(argv)
    try:
        if not bounded_text(args.scope):
            raise ValueError("invalid source scope")
        loader = load_selected_router if router_loader is None else router_loader
        result = (
            (train if args.command == "train" else read)(args, loader)
            if args.command in {"train", "read"}
            else {"write": write_records, "revoke": revoke, "inspect": inspect}[args.command](args)
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 0
    except (ValueError, TypeError, KeyError, OSError) as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
