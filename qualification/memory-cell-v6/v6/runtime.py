"""Three typed cells composed through source, inference, and artifact owners."""

import time

from .artifacts import ArtifactOwner
from .contracts import MemoryReadout, MemoryRequest, OPERATIONS
from .store import EventStore, StaleSource
from .values import execute_program, validate_typed_value


class MemoryRuntime:
    def __init__(self, source_path, artifact_directory, *, reader_kind="parameter"):
        if reader_kind not in ("parameter", "exact"):
            raise ValueError("invalid reader kind")
        self.source = EventStore(source_path)
        self.artifacts = ArtifactOwner(artifact_directory)
        self.reader_kind = reader_kind
        self.loaded = {}

    def load(self, expected_digest=None):
        manifest, identity = self.artifacts.manifest(expected_digest)
        if manifest["source_cut"] != self.source.cut or manifest["source_frontier"] != self.source.frontier(
            manifest["scope"]
        ):
            raise StaleSource("source changed; retrain/rebind before serving")
        if self.reader_kind == "parameter":
            from .cells import AssociativeCell, key_digest

            for kind, reference in manifest["cells"].items():
                if reference["sha256"] not in self.loaded:
                    cell = AssociativeCell.from_bytes(self.artifacts.get(reference))
                    expected = {key_digest(key): [source] for key, source in manifest["supports"][kind].items()}
                    if cell.kind != kind or cell.supports != expected:
                        raise StaleSource("cell does not match typed bundle")
                    for value in cell.catalog:
                        validate_typed_value(kind, value)
                    self.loaded[reference["sha256"]] = cell
                cell = self.loaded[reference["sha256"]]
                self.source.validate_support(cell.lineage_sources, scope=manifest["scope"], cut=manifest["source_cut"])
            # Old immutable artifacts remain on disk, but serving arrays are bounded
            # to the single admitted bundle rather than accumulating per revision.
            admitted = {reference["sha256"] for reference in manifest["cells"].values()}
            self.loaded = {key: value for key, value in self.loaded.items() if key in admitted}
        return manifest, identity

    def read(self, request, operation, *, expected_digest=None, disabled=(), permute=False):
        if isinstance(request, dict):
            request = MemoryRequest.from_dict(request)
        if operation not in (*OPERATIONS, None):
            raise ValueError("unknown operation")
        started = time.perf_counter()
        generation, identity = self.artifacts.active()
        sources, models, calls = [], [], []

        def failure(status, reason):
            return MemoryReadout(
                request.query_id,
                operation,
                status,
                None,
                (),
                max(1, generation),
                identity or "0" * 64,
                "none",
                (),
                len(calls),
                time.perf_counter() - started,
                reason,
            ).as_dict()

        if operation is None:
            return failure("abstain", "semantic router rejected")
        try:
            manifest, identity = self.load(expected_digest)
            generation = manifest["generation"]
            if request.scope != manifest["scope"]:
                raise StaleSource("request scope differs from snapshot")

            def read_cell(kind, at):
                if kind in disabled:
                    raise StaleSource("required cell removed by ablation")
                if len(calls) >= request.max_hops or len(set(calls + [kind])) > request.max_cells:
                    raise OverflowError("cell/hop budget exceeded")
                calls.append(kind)
                # One source cut applies to every hop; no mixed topology/parameter epochs.
                if self.artifacts.active() != (generation, identity) or self.source.cut != manifest["source_cut"]:
                    raise StaleSource("generation changed during execution")
                if kind == "event" or self.reader_kind == "exact":
                    record = self.source.resolve(request.scope, request.entity, kind, at=at, cut=manifest["source_cut"])
                    sources.append(record["source_id"])
                    return record["value"]
                source_id = manifest["supports"][kind].get(request.entity)
                if source_id is None:
                    raise StaleSource("entity outside cell support")
                self.source.validate_support(
                    [source_id],
                    scope=request.scope,
                    cut=manifest["source_cut"],
                    expected_entity=request.entity,
                    expected_kind=kind,
                )
                reference = manifest["cells"][kind]
                cell = self.loaded[reference["sha256"]]
                key = request.entity
                if permute:
                    keys = sorted(manifest["supports"][kind])
                    key = keys[(keys.index(key) + 1) % len(keys)]
                prediction = cell.read(key)
                if prediction["abstain"]:
                    raise StaleSource("memory cell abstained")
                validate_typed_value(kind, prediction["value"])
                if not permute and prediction["support_ids"] != [source_id]:
                    raise StaleSource("prediction source differs from admitted source")
                # The shuffled diagnostic must expose its actual, wrong provenance.
                sources.extend(prediction["support_ids"])
                models.append(reference["sha256"])
                return prediction["value"]

            match operation:
                case "current":
                    value = read_cell("event", 2**53 - 1)
                case "history":
                    value = read_cell("event", request.at)
                case "semantic":
                    value = read_cell("semantic", 2**53 - 1)
                case "procedure":
                    value = read_cell("procedure", 2**53 - 1)
                case "change":
                    value = read_cell("event", 2**53 - 1) - read_cell("event", request.since)
                case "apply":
                    event = read_cell("event", 2**53 - 1)
                    semantic = read_cell("semantic", 2**53 - 1)
                    procedure = read_cell("procedure", 2**53 - 1)
                    value = execute_program(procedure, event, semantic)
                case _:
                    raise ValueError("unsupported operation")
            self.source.validate_support(sources, scope=request.scope, cut=manifest["source_cut"])
            if self.artifacts.active() != (generation, identity) or self.source.cut != manifest["source_cut"]:
                raise StaleSource("generation changed before result publication")
            kind = "mixed" if models and "event" in calls else "model_prediction" if models else "source_evidence"
            return MemoryReadout(
                request.query_id,
                operation,
                "ok",
                value,
                tuple(dict.fromkeys(sources)),
                generation,
                identity,
                kind,
                tuple(dict.fromkeys(models)),
                len(calls),
                time.perf_counter() - started,
            ).as_dict()
        except StaleSource as error:
            return failure("stale", str(error))
        except OverflowError as error:
            return failure("budget_exceeded", str(error))
        except (ValueError, TypeError, KeyError, OSError) as error:
            return failure("unavailable", "typed artifact/source failure: " + type(error).__name__)

    def close(self):
        self.source.close()
        self.artifacts.close()


def train_snapshot(
    source_path, artifact_directory, *, scope, seed, expected_generation=0, steps=600, hidden=48, router_digest="0" * 64
):
    """Train outside serving, then publish one model/source generation."""
    from .cells import AssociativeCell

    source, owner = EventStore(source_path), ArtifactOwner(artifact_directory)
    try:
        cut = source.cut
        cells, supports, receipts = {}, {}, {}
        for kind in ("semantic", "procedure"):
            rows = source.rows(scope, kind, cut=cut)
            if len(rows) < 2:
                raise ValueError("insufficient typed memory data")
            cell = AssociativeCell.fit(
                [row["entity"] for row in rows],
                [row["value"] for row in rows],
                seed=seed,
                support_ids=[row["source_id"] for row in rows],
                kind=kind,
                hidden=hidden,
                steps=steps,
            )
            cells[kind] = owner.put(cell.to_bytes())
            supports[kind] = {row["entity"]: row["source_id"] for row in rows}
            receipts[kind] = cell.training_receipt
        if source.cut != cut:
            raise StaleSource("source advanced during training")
        manifest = dict(
            schema="hepta.memory.bundle.v1",
            scope=scope,
            source_cut=cut,
            source_frontier=source.frontier(scope, cut),
            cells=cells,
            supports=supports,
            router_contract="hepta.memory.router.v1",
            router_digest=router_digest,
            primitives="typed-arithmetic-v1",
            training_receipts=receipts,
            seed=seed,
        )
        identity = owner.publish(manifest, expected_generation=expected_generation)
        return {"snapshot_digest": identity, "cells": cells, "training": receipts, "source_cut": cut}
    finally:
        source.close()
        owner.close()
