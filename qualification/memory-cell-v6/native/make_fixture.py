"""Produce native bridge input from a real Python router and three-cell read."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from v6.contracts import MemoryRequest, canonical
from v6.encoder import MiniLMEncoder, normalize_request
from v6.router import Router
from v6.runtime import MemoryRuntime, train_snapshot
from v6.store import EventStore


def create(output, router_path, model_cache, router_manifest_sha256):
    started = time.perf_counter()
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    database, artifacts = output / "source.sqlite", output / "cells"
    store = EventStore(database)
    for index in range(4):
        entity = f"sensor:{index}"
        values = [("event", 5, 3 + index), ("event", 10, 41 + index), ("semantic", 1, {"factor": 7 + index, "label": f"public-fixture-{index}"}), ("procedure", 1, {"opcode": "affine", "bias": 3 + index, "limit": 1000})]
        for kind, at, value in values:
            store.append(scope="workspace:fixture", entity=entity, kind=kind, effective_at=at, value=value, origin_id=f"public:{index}:{kind}:{at}")
    store.close()
    training = train_snapshot(database, artifacts, scope="workspace:fixture", seed=1709, router_digest=router_manifest_sha256)
    encoder = MiniLMEncoder(model_cache)
    router = Router.load(router_path, encoder, router_manifest_sha256)
    request = MemoryRequest("query:native-fixture", "workspace:fixture", "sensor:0", "Apply the stored procedure to the latest value using the semantic parameter.", 10, 5)
    route = router.route(normalize_request(request.text, request.entity))
    runtime = MemoryRuntime(database, artifacts)
    try:
        readout = runtime.read(request, route["operation"], expected_digest=training["snapshot_digest"])
        if (route["operation"], readout["status"], readout["value"], readout["prediction_kind"]) != ("apply", "ok", 290, "mixed"):
            raise ValueError("actual router or three-cell execution failed public fixture")
        owner = dict(schema="hepta.memory.native-owner-fixture.v1", generation=readout["generation"], snapshot_digest=readout["snapshot_digest"], source_cut=runtime.source.cut, sources=[])
        for source, seq, scope, entity in runtime.source.db.execute("SELECT source_id,seq,scope,entity FROM records ORDER BY seq"):
            owner["sources"].append(dict(source_id=source, seq=seq, scope=scope, entity=entity, revoked=False))
        (output / "request.json").write_bytes(canonical(request.as_dict()) + b"\n")
        (output / "readout.json").write_bytes(canonical(readout) + b"\n")
        (output / "owner.json").write_bytes(canonical(owner) + b"\n")
        revoked = copy.deepcopy(owner)
        runtime.source.revoke(readout["source_ids"][0], "public qualification revocation")
        revoked["source_cut"] = runtime.source.cut
        for record in revoked["sources"]:
            record["revoked"] = bool(runtime.source.db.execute("SELECT 1 FROM revocations WHERE source_id=?", (record["source_id"],)).fetchone())
        (output / "owner-revoked.json").write_bytes(canonical(revoked) + b"\n")
        second = runtime.read(request, route["operation"], expected_digest=training["snapshot_digest"])
        if second["status"] != "stale" or second["value"] is not None:
            raise ValueError("Python owner did not fail closed after revocation")
        (output / "python-revocation.json").write_bytes(canonical(second) + b"\n")
    finally:
        runtime.close()
    receipt = dict(schema="hepta.memory.native-fixture.v1", route=route, readout=readout, training=training, actual_additional_cell_fits=2, router_manifest_sha256=router_manifest_sha256, encoder_digest=encoder.digest, wall_seconds=time.perf_counter() - started, held_read=False, limitation="public synthetic cross-language boundary fixture; not a linguistic quality benchmark or live source-owner adapter")
    receipt["files"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob("*.json")}
    (output / "FIXTURE.json").write_bytes(canonical(receipt) + b"\n")
    print(json.dumps({"status": readout["status"], "value": readout["value"], "prediction_kind": readout["prediction_kind"], "wall_seconds": receipt["wall_seconds"]}))
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--router-path", required=True, type=Path)
    parser.add_argument("--model-cache", required=True, type=Path)
    parser.add_argument("--router-manifest-sha256", required=True)
    args = parser.parse_args()
    create(args.output, args.router_path, args.model_cache, args.router_manifest_sha256)
