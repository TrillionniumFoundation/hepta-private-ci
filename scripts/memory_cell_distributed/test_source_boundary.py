"""Live source cuts fence stale authority replicas before a model callback."""

from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
for name in ("memory_cell", "memory_cell_service", "memory_cell_network"):
    sys.path.insert(0, str(SCRIPTS / name))

from authority_client import QuorumClient, QuorumUnavailable
from authority_replica import Replica
from distributed_test_support import LiveServer, certificates, membership
from network_checkpoints import pack
from network_worker import Worker
from source_bound_authority import SourceBoundAuthority
from source_evidence import SourceEvidence
from source_store import SourceStore
from test_parametric_owner import checkpoint
from tls_wire import Grant, RemoteError
import tls_wire


class SourceBoundaryTests(unittest.TestCase):
    def test_live_correction_and_source_partition_fence_current_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = SourceStore(root / "source.sqlite", "scope-a")
            fact = source.write("incident", "build", "repair", "install-clippy")
            certs = certificates(root / "certs", dict(server="server", worker="client"))
            grant = Grant(
                certs["worker"]["certificate_sha256"],
                frozenset(["source_frontier"]),
                frozenset(["scope-a"]),
            )
            server = LiveServer(
                SourceEvidence(source), certs["server"]["credentials"], [grant]
            )
            self.addCleanup(server.close)
            members, writer, keys = membership()
            replicas = {
                name: Replica(root / name, name, members, key, creation="genesis")
                for name, key in keys.items()
            }
            addresses = {name: f"https://{name}:443" for name in replicas}
            online = set(replicas)

            def rpc(address, credentials, request, *, timeout):
                name = next(
                    name for name, value in addresses.items() if value == address
                )
                if name not in online:
                    raise OSError("controlled authority partition")
                return replicas[name].dispatch(request)

            quorum = QuorumClient(members, addresses, None, rpc=rpc)
            bound = SourceBoundAuthority(
                quorum, server.address, certs["worker"]["credentials"], timeout=1
            )
            candidate = root / "candidate"
            pin = checkpoint(candidate, [fact.source_digest])
            placement = dict(
                scope="scope-a",
                cell_id="memory",
                node_id="worker-a",
                generation=0,
                manifest_sha256=pin,
                roots=[fact.source_digest],
            )
            bound.publish(placement, None, writer)
            calls = []

            def callback(*_args):
                calls.append("entered")
                return dict(structural_test_callback=True, model_execution=False)

            worker = Worker(
                root / "worker",
                "worker-a",
                next(iter(addresses.values())),
                certs["worker"]["credentials"],
                root / "no-model",
                reader=callback,
                transport=tls_wire,
                authority_snapshot=bound.snapshot,
            )
            worker.dispatch(
                dict(
                    op="stage",
                    package=pack(candidate, pin, "scope-a"),
                    retained_manifest_sha256=pin,
                )
            )
            self.assertTrue(
                worker.read("scope-a", "memory", ["query"], "adapter")["journal"][
                    "structural_test_callback"
                ]
            )
            online.remove("replica-2")
            self.assertIsNotNone(worker.read("scope-a", "memory", ["query"], "adapter"))
            online.remove("replica-1")
            with self.assertRaises(QuorumUnavailable):
                worker.read("scope-a", "memory", ["query"], "adapter")
            self.assertEqual(len(calls), 2)
            online.add("replica-1")
            source.correct("incident", "install-rustfmt", 0)
            # No follow-up write to any replica: source liveness alone fences it.
            with self.assertRaisesRegex(ValueError, "frontier differ"):
                worker.read("scope-a", "memory", ["query"], "adapter")
            self.assertEqual(len(calls), 2)
            live = bound.live("scope-a")
            quorum.publish(
                quorum.proposal("scope-a", live["frontier"], [placement], writer)
            )
            with self.assertRaisesRegex(ValueError, "noncurrent"):
                worker.read("scope-a", "memory", ["query"], "adapter")
            self.assertEqual(len(calls), 2)
            bound.source_endpoint = "https://127.0.0.1:1"
            with self.assertRaises(RemoteError):
                worker.read("scope-a", "memory", ["query"], "adapter")
            self.assertEqual(len(calls), 2)

    def test_inflight_source_change_suppresses_callback_output(self):
        # The same live check is used by ParametricOwner before and after calls.
        # This isolates that owner composition from inference accuracy.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = SourceStore(root / "source.sqlite", "scope-a")
            fact = source.write("incident", "build", "repair", "install-clippy")
            candidate = root / "candidate"
            pin = checkpoint(candidate, [fact.source_digest])
            placement = dict(
                scope="scope-a",
                cell_id="memory",
                node_id="worker-a",
                generation=0,
                manifest_sha256=pin,
                roots=[fact.source_digest],
            )

            class Cut:
                def snapshot(self, scope, cell):
                    return dict(
                        frontier=dict(scope=scope, epoch=1, revoked=[]),
                        placement=placement,
                    )

            endpoint = SourceEvidence(source)
            bound = SourceBoundAuthority(
                Cut(),
                "https://source:443",
                None,
                rpc=lambda address, credentials, request, timeout: endpoint.dispatch(
                    request
                ),
            )

            def callback(*_args):
                source.revoke("incident", 0)
                return dict(must_not_escape=True)

            worker = Worker(
                root / "worker",
                "worker-a",
                "https://authority:443",
                None,
                root / "no-model",
                reader=callback,
                transport=tls_wire,
                authority_snapshot=bound.snapshot,
            )
            worker.dispatch(
                dict(
                    op="stage",
                    package=pack(candidate, pin, "scope-a"),
                    retained_manifest_sha256=pin,
                )
            )
            with self.assertRaisesRegex(ValueError, "frontier differ"):
                worker.read("scope-a", "memory", ["query"], "adapter")
            self.assertEqual(worker.fences.calls(), 1)


if __name__ == "__main__":
    unittest.main()
