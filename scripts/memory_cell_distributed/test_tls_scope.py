"""Actual TLS sockets, certificate/role isolation and remote source revisions."""

import base64
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS / "memory_cell_service"))

from authority_client import QuorumClient
from authority_replica import Replica
from distributed_test_support import LiveServer, certificates, membership
from source_evidence import SourceEvidence
from source_store import SourceStore
from tls_wire import Grant, RemoteError, call


class TlsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.certs = certificates(
            self.root / "certificates",
            dict(
                server="server", publisher="client", reader="client", unknown="client"
            ),
        )
        self.servers = []

    def tearDown(self):
        for server in reversed(self.servers):
            server.close()
        self.temporary.cleanup()

    def serve(self, application, grants):
        live = LiveServer(application, self.certs["server"]["credentials"], grants)
        self.servers.append(live)
        return live.address

    def grant(self, who, operations, scopes=("scope-a",), roots=()):
        return Grant(
            self.certs[who]["certificate_sha256"],
            frozenset(operations),
            frozenset(scopes),
            frozenset(roots),
        )

    def test_https_quorum_rejects_reader_mutation_scope_and_unknown_peer(self):
        members, writer, keys = membership()
        addresses = {}
        replicas = {}
        for name, key in keys.items():
            replicas[name] = Replica(
                self.root / name, name, members, key, creation="genesis"
            )
            addresses[name] = self.serve(
                replicas[name],
                [
                    self.grant(
                        "publisher", ("read", "prepare", "commit", "history", "pending")
                    ),
                    self.grant("reader", ("read",)),
                ],
            )
        publisher = QuorumClient(
            members, addresses, self.certs["publisher"]["credentials"], timeout=5
        )
        proposal = publisher.proposal(
            "scope-a", dict(scope="scope-a", epoch=0, revoked=[]), [], writer
        )
        publisher.publish(proposal)
        reader = QuorumClient(
            members, addresses, self.certs["reader"]["credentials"], timeout=5
        )
        self.assertEqual(reader.read("scope-a")["proposal"], proposal)
        with self.assertRaises(RemoteError):
            call(
                addresses["replica-0"],
                self.certs["reader"]["credentials"],
                dict(op="prepare", proposal=proposal),
            )
        with self.assertRaises(RemoteError):
            call(
                addresses["replica-0"],
                self.certs["reader"]["credentials"],
                dict(op="read", scope="scope-b"),
            )
        with self.assertRaises(RemoteError):
            call(
                addresses["replica-0"],
                self.certs["unknown"]["credentials"],
                dict(op="read", scope="scope-a"),
            )
        foreign = certificates(self.root / "foreign-ca", dict(client="client"))[
            "client"
        ]["credentials"]
        with self.assertRaises(RemoteError):
            call(
                addresses["replica-0"],
                foreign,
                dict(op="read", scope="scope-a"),
                timeout=5,
            )

    def test_remote_evidence_needs_exact_root_and_rejects_correction_and_withdrawal(
        self,
    ):
        source = SourceStore(self.root / "source.sqlite", "scope-a")
        first = source.write("incident", "build", "repair", "install-clippy")
        other = source.write("other", "other", "repair", "update-lock")
        application = SourceEvidence(source)
        address = self.serve(
            application,
            [self.grant("reader", ("evidence",), roots=[first.source_digest])],
        )
        epoch = source.snapshot()["epoch"]
        request = dict(
            op="evidence",
            scope="scope-a",
            source_root=first.source_digest,
            expected_epoch=epoch,
        )
        response = call(address, self.certs["reader"]["credentials"], request)
        self.assertIn(
            b"install-clippy",
            base64.b64decode(response["payload_base64"], validate=True),
        )
        self.assertEqual(
            (response["source_root"], response["origin"], response["parameter_output"]),
            (first.source_digest, "source_evidence", False),
        )
        with self.assertRaises(RemoteError):
            call(
                address,
                self.certs["reader"]["credentials"],
                dict(request, source_root=other.source_digest),
            )
        self.assertEqual(application.completed_reads, 1)
        source.correct("incident", "install-rustfmt", expected_revision=0)
        with self.assertRaises(RemoteError):
            call(address, self.certs["reader"]["credentials"], request)
        with self.assertRaises(RemoteError):
            call(
                address,
                self.certs["reader"]["credentials"],
                dict(request, expected_epoch=source.snapshot()["epoch"]),
            )
        source.revoke("incident", expected_revision=1)
        with self.assertRaises(RemoteError):
            call(
                address,
                self.certs["reader"]["credentials"],
                dict(request, expected_epoch=source.snapshot()["epoch"]),
            )
        self.assertEqual(application.completed_reads, 1)


if __name__ == "__main__":
    unittest.main()
