"""Measured single-writer releases, explicit replica delivery and node recovery.

This local qualification uses controlled operations, not a language-routing
score. Replica source updates are explicitly replayed by the experiment; no
automatic distributed revocation or multiwriter agreement is claimed.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from .artifacts import ArtifactOwner, durable_bytes
from .cells import AssociativeCell
from .contracts import MemoryRequest, canonical, digest, integer
from .network import MetaNetwork, NodeClient, NodeProcess
from .runtime import MemoryRuntime, train_snapshot
from .store import EventStore, StaleSource
from .study_data import AT, LATEST, SINCE, create_sources, expected


def _child_cpu():
    try:
        import resource
    except ImportError:
        return None
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def _copy_bundle(source, target):
    """Copy a stopped-writer bundle into new files, charging every payload byte."""
    source, target = Path(source), Path(target)
    if target.exists() or source.is_symlink():
        raise ValueError("migration requires an unused target and a concrete source")
    started = time.perf_counter()
    target.mkdir(parents=True)
    inventory = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError("migration refuses symlinked bundle members")
        if not path.is_file():
            continue
        relative, raw = path.relative_to(source), path.read_bytes()
        destination = target / relative
        durable_bytes(destination, raw)
        identity = hashlib.sha256(raw).hexdigest()
        if hashlib.sha256(destination.read_bytes()).hexdigest() != identity:
            raise ValueError("copied bundle failed integrity verification")
        independent = (path.stat().st_dev, path.stat().st_ino) != (destination.stat().st_dev, destination.stat().st_ino)
        if not independent:
            raise ValueError("migration reused an inode")
        inventory.append(dict(path=relative.as_posix(), bytes=len(raw), sha256=identity, independent_inode=independent))
    # Bind newly created directory entries as well as each file replacement.
    if os.name != "nt":
        directories = [path for path in target.rglob("*") if path.is_dir()] + [target, target.parent]
        for directory in directories:
            handle = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(handle)
            finally:
                os.close(handle)
    return dict(
        source=str(source),
        target=str(target),
        files=inventory,
        copied_bytes=sum(row["bytes"] for row in inventory),
        manifest_sha256=digest(inventory),
        wall_seconds=time.perf_counter() - started,
        accounting="application bytes copied; file and directory fsync; excludes filesystem metadata I/O",
    )


def _snapshot(directory):
    owner = ArtifactOwner(Path(directory) / "artifacts")
    try:
        manifest, identity = owner.manifest()
        lineage = {}
        for kind, reference in manifest["cells"].items():
            cell = AssociativeCell.from_bytes(owner.get(reference))
            lineage[kind] = sorted(cell.lineage_sources)
        return dict(
            generation=manifest["generation"],
            snapshot_digest=identity,
            source_cut=manifest["source_cut"],
            source_frontier=manifest["source_frontier"],
            lineage_sources=lineage,
            supports=manifest["supports"],
            cells=manifest["cells"],
            transitions=[
                list(row)
                for row in owner.db.execute(
                    "SELECT generation,predecessor,successor FROM transitions ORDER BY generation"
                )
            ],
        )
    finally:
        owner.close()


def _replay_updates(source_path, updates):
    source = EventStore(source_path)
    try:
        ids = [source.append(**update) for update in updates]
        return dict(source_ids=ids, source_cut=source.cut, source_frontier=source.frontier(updates[0]["scope"]))
    finally:
        source.close()


def run_lifecycle_study(seed, output_dir):
    """Run one bounded real lifecycle study and persist successes and failures.

    Four cell fits occur: semantic/procedure for the initial source and for its
    corrected, extended successor. A failed phase returns a failed receipt with
    all completed work and costs retained, and cleans up every started process.
    """
    if not integer(seed, 0, 2**32 - 1):
        raise ValueError("invalid lifecycle seed")
    output = Path(output_dir).absolute()
    output.mkdir(parents=True, exist_ok=False)
    started, cpu_started, child_started = time.perf_counter(), time.process_time(), _child_cpu()
    receipt = dict(
        schema="hepta.memory.lifecycle-study.v1",
        seed=seed,
        status="running",
        checks=[],
        trials=[],
        migrations=[],
        source_deliveries=[],
        processes=[],
        training=[],
        publication={},
        limits=[
            "one machine, loopback HTTP, independent files; not separate physical disks or hosts",
            "single-writer SQLite CAS; no multiwriter consensus claim",
            "explicit coordinator source replay and full bundle distribution; no automatic revocation propagation",
            "controlled operations bypass language routing; language quality is evaluated separately",
            "RPC bytes are attempted JSON request plus received response bodies, excluding HTTP/TCP overhead",
        ],
    )
    all_nodes, nodes, paths = [], [], []
    base = output / "writer"
    base.mkdir()

    def check(name, observed, wanted):
        passed = observed == wanted
        receipt["checks"].append(dict(name=name, passed=passed, observed=observed, expected=wanted))
        if not passed:
            raise RuntimeError("lifecycle check failed: " + name)

    def start(path, name):
        begin = time.perf_counter()
        receipt["process_start_attempts"] = receipt.get("process_start_attempts", 0) + 1
        node = NodeProcess(path / "source.sqlite", path / "artifacts", "parameter", log_path=output / (name + ".log"))
        all_nodes.append(node)
        receipt["processes"].append(
            dict(name=name, directory=str(path), ready=node.ready, startup_wall_seconds=time.perf_counter() - begin)
        )
        active = sum(item.process.poll() is None for item in all_nodes)
        receipt["peak_live_processes"] = max(receipt.get("peak_live_processes", 0), active)
        return node

    def request(name, entity):
        return MemoryRequest(
            f"lifecycle.{seed}.{name}",
            fixture["scope"],
            entity,
            "Execute the stored procedure on the event and semantic memories.",
            AT,
            SINCE,
        )

    def read(network, name, entity, *, wanted_status="ok", wanted_value=None, wanted_sources=None):
        result = network.read(request(name, entity), "apply")
        receipt["trials"].append(dict(name=name, readout=result))
        check(name + ".status", result["status"], wanted_status)
        if wanted_status == "ok":
            check(name + ".value", result["value"], wanted_value)
            if wanted_sources is not None:
                check(name + ".sources", sorted(result["source_ids"]), sorted(wanted_sources))
        else:
            check(
                name + ".no_partial_answer",
                [result["value"], list(result["source_ids"]), list(result["cell_digests"])],
                [None, [], []],
            )
        return result

    def expect_stale(client, name, entity):
        before, begin = client.counters(), time.perf_counter()
        try:
            returned = client.read(request(name, entity), "current")
            result = dict(rejected=False, returned=returned)
        except StaleSource as error:
            result = dict(rejected=True, error=str(error), error_type=type(error).__name__)
        result.update(
            name=name,
            wall_seconds=time.perf_counter() - begin,
            counters={key: client.counters()[key] - value for key, value in before.items()},
        )
        receipt["trials"].append(result)
        check(name + ".rejected", result["rejected"], True)

    extra_clients = []
    try:
        fixture = create_sources(base / "source.sqlite", seed=seed, domain="lifecycle", count=12)
        durable_bytes(output / "SOURCE-ORACLE.json", canonical(fixture))
        receipt["training_attempts"] = 1
        training = train_snapshot(base / "source.sqlite", base / "artifacts", scope=fixture["scope"], seed=seed)
        receipt["training"].append(training)
        initial = _snapshot(base)
        receipt["initial_snapshot"] = initial
        chosen = next(record for record in fixture["entities"].values() if record["procedure"]["opcode"] == "affine")
        entity = chosen["entity"]
        old_value, old_sources = expected(chosen, "apply")

        owner = ArtifactOwner(base / "artifacts")
        try:
            manifest, old_digest = owner.manifest()
            before = owner.active()
            try:
                owner.publish(manifest, expected_generation=1, fail_before_commit=True)
            except RuntimeError as error:
                receipt["publication"]["injected_failure"] = str(error)
            else:
                raise RuntimeError("publication failpoint did not fail")
            check("failpoint.active_pointer", list(owner.active()), list(before))
        finally:
            owner.close()
        reopened = ArtifactOwner(base / "artifacts")
        contender = ArtifactOwner(base / "artifacts")
        try:
            check("failpoint.reopen_old_version", list(reopened.active()), [1, old_digest])
            expected_generation = contender.active()[0]
            next_digest = reopened.publish(manifest, expected_generation=1)
            try:
                contender.publish(manifest, expected_generation=expected_generation)
            except StaleSource as error:
                receipt["publication"]["stale_cas_error"] = str(error)
            else:
                raise RuntimeError("stale publication CAS unexpectedly succeeded")
            check("cas.one_committed_successor", list(contender.active()), [2, next_digest])
            receipt["publication"].update(
                initial_digest=old_digest,
                published_digest=next_digest,
                expected_generation=expected_generation,
                failpoint_kind="injected exception after durable snapshot file and before SQLite pointer commit; not power-loss simulation",
                staged_snapshot_bytes=(base / "artifacts/snapshots" / (next_digest + ".json")).stat().st_size,
            )
        finally:
            contender.close()
            reopened.close()
        # A separate runtime reopened from disk consumes the committed pointer.
        local = MemoryRuntime(base / "source.sqlite", base / "artifacts")
        try:
            result = local.read(request("reopened-publication", entity), "apply", expected_digest=next_digest)
            receipt["publication"]["reopened_read"] = result
            check("cas.reopened_read", [result["status"], result["generation"], result["value"]], ["ok", 2, old_value])
        finally:
            local.close()

        for index in range(3):
            path = output / f"replica-{index}"
            receipt["migrations"].append(_copy_bundle(base, path))
            paths.append(path)
            nodes.append(start(path, f"node-{index}"))
        check("replicas.independent_processes", len({node.process.pid for node in nodes}), 3)
        check("replicas.independent_source_files", len({(path / "source.sqlite").stat().st_ino for path in paths}), 3)
        network = MetaNetwork(*(node.client for node in nodes))
        first = read(network, "three-node", entity, wanted_value=old_value, wanted_sources=old_sources)
        two = read(
            MetaNetwork(nodes[0].client, nodes[1].client, nodes[1].client),
            "two-node",
            entity,
            wanted_value=old_value,
            wanted_sources=old_sources,
        )
        check(
            "three-node.rpc_counts",
            [first["transport"]["rpc_attempts"], first["transport"]["validation_attempts"]],
            [6, 3],
        )
        check(
            "two-node.rpc_counts", [two["transport"]["rpc_attempts"], two["transport"]["validation_attempts"]], [5, 2]
        )

        killed_pid, failure_begin = nodes[1].process.pid, time.perf_counter()
        nodes[1].stop(crash=True)
        read(network, "killed-node", entity, wanted_status="unavailable")
        nodes[1] = start(paths[1], "node-restarted")
        network = MetaNetwork(*(node.client for node in nodes))
        read(network, "restart-recovered", entity, wanted_value=old_value, wanted_sources=old_sources)
        receipt["recovery"] = dict(
            killed_pid=killed_pid,
            replacement_pid=nodes[1].process.pid,
            kill_to_success_wall_seconds=time.perf_counter() - failure_begin,
        )
        check("recovery.new_process", killed_pid != nodes[1].process.pid, True)

        nodes[1].stop()
        checkpoint = EventStore(paths[1] / "source.sqlite")
        checkpoint.close()
        migrated = output / "migrated-semantic-node"
        receipt["migrations"].append(_copy_bundle(paths[1], migrated))
        paths[1] = migrated
        nodes[1] = start(migrated, "node-migrated")
        network = MetaNetwork(*(node.client for node in nodes))
        read(network, "migration-recovered", entity, wanted_value=old_value, wanted_sources=old_sources)
        check("migration.full_snapshot", _snapshot(migrated), _snapshot(base))

        new_entity = "fresh-" + digest([seed, "new-after-publication"])[:12]
        updates = [
            dict(
                scope=fixture["scope"],
                entity=entity,
                kind="semantic",
                effective_at=20240101,
                value={"factor": 31, "label": "corrected-after-publication"},
                origin_id=f"correction.{seed}",
                predecessor=chosen["sources"]["semantic"],
            ),
            dict(
                scope=fixture["scope"],
                entity=entity,
                kind="event",
                effective_at=LATEST + 1,
                value=149,
                origin_id=f"latest.{seed}",
            ),
            dict(
                scope=fixture["scope"],
                entity=new_entity,
                kind="event",
                effective_at=LATEST + 1,
                value=19,
                origin_id=f"new-event.{seed}",
            ),
            dict(
                scope=fixture["scope"],
                entity=new_entity,
                kind="semantic",
                effective_at=20240101,
                value={"factor": 11, "label": "new-after-publication"},
                origin_id=f"new-semantic.{seed}",
            ),
            dict(
                scope=fixture["scope"],
                entity=new_entity,
                kind="procedure",
                effective_at=20240101,
                value={"opcode": "affine", "bias": 7, "limit": 1000},
                origin_id=f"new-procedure.{seed}",
            ),
        ]
        written = _replay_updates(base / "source.sqlite", updates)
        receipt["source_update"] = dict(updates=updates, writer=written, payload_bytes=len(canonical(updates)))
        # Deliberately measure the observation gap, instead of pretending that
        # disconnected replicas learn about a writer change automatically.
        read(network, "before-explicit-source-delivery", entity, wanted_value=old_value, wanted_sources=old_sources)
        receipt["source_update"]["unobserved_writer_change_can_serve_old_value"] = True
        for index, path in enumerate(paths):
            begin = time.perf_counter()
            delivered = _replay_updates(path / "source.sqlite", updates)
            receipt["source_deliveries"].append(
                dict(
                    target=str(path),
                    method="explicit coordinator SQLite replay; not an automatic network protocol",
                    payload_bytes=len(canonical(updates)),
                    wall_seconds=time.perf_counter() - begin,
                    result=delivered,
                )
            )
            check(f"source-delivery-{index}.coherent_cut", delivered, written)
            expect_stale(nodes[index].client, f"old-node-{index}-invalidated", entity)
        read(network, "all-old-bundles-invalidated", entity, wanted_status="stale")

        receipt["training_attempts"] += 1
        training = train_snapshot(
            base / "source.sqlite", base / "artifacts", scope=fixture["scope"], seed=seed ^ 0xA53, expected_generation=2
        )
        receipt["training"].append(training)
        successor = _snapshot(base)
        receipt["successor_snapshot"] = successor
        check("successor.source_cut", successor["source_cut"], written["source_cut"])
        check("successor.source_frontier", successor["source_frontier"], written["source_frontier"])
        for kind in ("semantic", "procedure"):
            check(
                "successor.complete_lineage." + kind,
                successor["lineage_sources"][kind],
                sorted(successor["supports"][kind].values()),
            )
        check(
            "successor.clean_correction_lineage",
            chosen["sources"]["semantic"] in successor["lineage_sources"]["semantic"],
            False,
        )

        for index in range(3):
            nodes[index].stop()
            path = output / f"successor-replica-{index}"
            receipt["migrations"].append(_copy_bundle(base, path))
            paths[index] = path
            nodes[index] = start(path, f"successor-node-{index}")
            if index == 0:
                begin = time.perf_counter()
                try:
                    MetaNetwork(*(node.client for node in nodes))
                except StaleSource as error:
                    receipt["mixed_release"] = dict(
                        rejected=True, error=str(error), wall_seconds=time.perf_counter() - begin
                    )
                else:
                    raise RuntimeError("mixed release unexpectedly composed")
        network = MetaNetwork(*(node.client for node in nodes))
        ids = written["source_ids"]
        corrected = read(
            network,
            "corrected-after-release",
            entity,
            wanted_value=149 * 31 + chosen["procedure"]["bias"],
            wanted_sources=[ids[1], ids[0], chosen["sources"]["procedure"]],
        )
        check(
            "successor.version_binding",
            [corrected["generation"], corrected["snapshot_digest"]],
            [3, successor["snapshot_digest"]],
        )
        read(network, "new-entity-after-release", new_entity, wanted_value=19 * 11 + 7, wanted_sources=ids[2:])
        for index, node in enumerate(nodes):
            stale_client = NodeClient(node.client.url, next_digest, generation=2)
            extra_clients.append(stale_client)
            expect_stale(stale_client, f"old-client-pin-{index}", entity)
            check(f"successor-replica-{index}.full_snapshot", _snapshot(paths[index]), successor)
        check("process_budget.maximum_three", receipt["peak_live_processes"] <= 3, True)
        receipt["status"] = "passed"
    except Exception as error:
        receipt["status"] = "failed"
        receipt["error"] = dict(type=type(error).__name__, message=str(error))
    finally:
        for node in all_nodes:
            node.stop(crash=True)
        for process, node in zip(receipt["processes"], all_nodes):
            process.update(exit_code=node.process.returncode, final_counters=node.client.counters())
        clients = [node.client for node in all_nodes] + extra_clients
        counters = {
            key: sum(client.counters()[key] for client in clients)
            for key in ("sent_bytes", "received_bytes", "calls", "read_attempts", "validation_attempts")
        }
        child_finished = _child_cpu()
        receipt["cost"] = dict(
            wall_seconds=time.perf_counter() - started,
            parent_cpu_seconds=time.process_time() - cpu_started,
            reaped_child_cpu_seconds=None if child_started is None else child_finished - child_started,
            actual_cell_fits=2 * len(receipt["training"])
            if len(receipt["training"]) == receipt.get("training_attempts", 0)
            else None,
            completed_snapshot_cell_fits=2 * len(receipt["training"]),
            attempted_snapshot_trainings=receipt.get("training_attempts", 0),
            process_starts=receipt.get("process_start_attempts", 0),
            ready_processes=len(all_nodes),
            application_bundle_copied_bytes=sum(row["copied_bytes"] for row in receipt["migrations"]),
            explicit_source_replay_payload_bytes=sum(row["payload_bytes"] for row in receipt["source_deliveries"]),
            rpc=counters,
            rpc_body_bytes=counters["sent_bytes"] + counters["received_bytes"],
            directory_bytes_before_receipt=sum(path.stat().st_size for path in output.rglob("*") if path.is_file()),
        )
        receipt["all_child_processes_reaped"] = all(node.process.poll() is not None for node in all_nodes)
        receipt["checks_passed"] = sum(row["passed"] for row in receipt["checks"])
        receipt["source_files"] = {
            str(path.relative_to(Path(__file__).parent)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                Path(__file__),
                *(
                    Path(__file__).with_name(name)
                    for name in ("network.py", "runtime.py", "artifacts.py", "store.py", "cells.py", "study_data.py")
                ),
            )
        }
        receipt = json.loads(canonical(receipt))
        durable_bytes(output / "LIFECYCLE.json", canonical(receipt) + b"\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    result = run_lifecycle_study(arguments.seed, arguments.output)
    print(json.dumps({"status": result["status"], "checks_passed": result["checks_passed"], "cost": result["cost"]}))
    raise SystemExit(0 if result["status"] == "passed" else 1)
