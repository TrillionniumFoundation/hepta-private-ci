"""Real process/TCP migration and live source-owner withdrawal observations."""

import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3

from network_client import NetworkClient
from network_test_support import ServiceProcess
from network_wire import call
from system_common import raw_signature, retain


class NetworkSession:
    def __init__(self, directory, model, source_root, scope):
        self.root = Path(directory)
        self.root.mkdir()
        self.scope, self.cell_id = scope, "memory"
        self.key = secrets.token_bytes(32)
        self.key_file = self.root / "transport.key"
        descriptor = os.open(self.key_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(self.key)
        self.processes = []
        try:
            self.authority = self.start(
                "authority", "authority", source_root=source_root, scope=scope
            )
            self.nodes = {
                name: self.start(
                    name,
                    "worker",
                    node_id=name,
                    authority=self.authority.address,
                    model=model,
                )
                for name in ("A", "B")
            }
            self.client = NetworkClient(
                self.authority.address,
                {name: node.address for name, node in self.nodes.items()},
                self.key,
            )
            retain(
                self.root / "processes.json",
                {
                    name: process.receipt
                    for name, process in [
                        ("authority", self.authority),
                        *self.nodes.items(),
                    ]
                },
            )
        except BaseException:
            self.close()
            raise

    def start(self, name, role, **options):
        process = ServiceProcess(self.root / name, role, self.key_file, **options)
        self.processes.append(process)
        return process

    def close(self):
        for process in reversed(self.processes):
            process.stop()
        self.key_file.unlink(missing_ok=True)

    def counts(self):
        return {
            name: call(node.address, self.key, {"op": "status"})["model_callbacks"]
            for name, node in self.nodes.items()
        }

    def observed_frontier(self, node):
        with sqlite3.connect(self.root / node / "fences.sqlite") as database:
            row = database.execute(
                "SELECT value FROM frontier WHERE scope=?", (self.scope,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def publish(self, active, previous=None, node="A"):
        staged = self.client.stage(
            node, active.directory, active.manifest_sha256, self.scope
        )
        candidate = dict(
            scope=self.scope,
            cell_id=self.cell_id,
            node_id=node,
            generation=previous["generation"] + 1 if previous else 0,
            manifest_sha256=active.manifest_sha256,
            roots=list(active.roots),
        )
        published = self.client.publish(
            candidate, previous["generation"] if previous else None
        )
        return {"stage": staged, "placement": published}

    def refused(self, node, questions):
        before = self.counts()
        try:
            call(
                self.nodes[node].address,
                self.key,
                dict(
                    op="read",
                    scope=self.scope,
                    cell_id=self.cell_id,
                    questions=questions,
                    control="adapter",
                ),
                timeout=600,
            )
        except (ValueError, RuntimeError, OSError) as error:
            return {
                "rejected": True,
                "error_type": type(error).__name__,
                "error": str(error),
                "before": before,
                "after": self.counts(),
                "observed_frontier": self.observed_frontier(node),
            }
        raise AssertionError("stale or withdrawn node served a model result")

    def migration(self, active, questions, expected_journal):
        publication = self.publish(active)
        before = self.client.read(self.scope, self.cell_id, questions)
        migration = self.client.migrate(publication["placement"], "B")
        after = self.client.read(self.scope, self.cell_id, questions)
        retry = self.client.migrate(publication["placement"], "B")
        stale = self.refused("A", questions)
        inventories = []
        for name in ("A", "B"):
            directory = self.root / name / "checkpoints" / active.manifest_sha256
            inventories.append(
                {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(directory.iterdir())
                    if path.is_file()
                }
            )
        result = {
            "publication": publication,
            "before": before,
            "migration": migration,
            "after": after,
            "retry": retry,
            "stale_node": stale,
            "checkpoint_byte_identities": inventories,
            "gates": {
                "independent_worker_pids": before["pid"] != after["pid"],
                "transferred_checkpoint_bytes_identical": inventories[0]
                == inventories[1],
                "fresh_and_network_generation_equal": raw_signature(expected_journal)
                == raw_signature(before["journal"])
                == raw_signature(after["journal"]),
                "old_node_rejected_without_callback": stale["before"] == stale["after"],
                "migration_retry_idempotent": retry["already_current"] is True,
            },
            "physical_hosts": 1,
            "transport": "authenticated loopback HTTP/TCP",
            "consensus_demonstrated": False,
        }
        retain(self.root / "migration.json", result)
        return result
