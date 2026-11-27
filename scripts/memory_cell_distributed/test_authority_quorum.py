"""Behavior tests for real SQLite replica state and cryptographic certificates."""

import copy
from pathlib import Path
import shutil
import tempfile
import unittest

from authority_client import QuorumClient, QuorumUnavailable
from authority_replica import Replica
from distributed_test_support import membership


class ReplicaTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.members, self.writer, self.keys = membership()
        self.replicas = {
            name: Replica(self.root / name, name, self.members, key, creation="genesis")
            for name, key in self.keys.items()
        }
        self.addresses = {name: f"https://{name}:443" for name in self.replicas}
        self.online = set(self.replicas)

        def dispatch(address, _credentials, request, *, timeout):
            name = next(
                name for name, value in self.addresses.items() if value == address
            )
            if name not in self.online:
                raise OSError("partitioned replica")
            return self.replicas[name].dispatch(request)

        self.client = QuorumClient(self.members, self.addresses, None, rpc=dispatch)
        self.placement = dict(
            scope="scope-a",
            cell_id="cell",
            node_id="worker-a",
            generation=0,
            manifest_sha256="a" * 64,
            roots=["b" * 64],
        )

    def tearDown(self):
        self.temporary.cleanup()

    def proposal(self, epoch=0, revoked=None, placements=None):
        return self.client.proposal(
            "scope-a",
            dict(scope="scope-a", epoch=epoch, revoked=revoked or []),
            placements if placements is not None else [self.placement],
            self.writer,
        )

    def test_committed_majority_restart_and_monotonic_withdrawal(self):
        first = self.client.publish(self.proposal())
        self.assertEqual(first["acknowledged"], sorted(self.replicas))
        self.client.publish(self.proposal(epoch=1, revoked=["b" * 64]))
        self.assertEqual(
            self.client.snapshot("scope-a", "cell"),
            dict(
                frontier=dict(scope="scope-a", epoch=1, revoked=["b" * 64]),
                placement=self.placement,
            ),
        )
        for name, key in self.keys.items():
            self.replicas[name] = Replica(self.root / name, name, self.members, key)
        self.assertEqual(
            self.client.read("scope-a")["proposal"]["state"]["sequence"], 2
        )
        with self.assertRaises(QuorumUnavailable):
            self.client.publish(self.proposal(epoch=0))

    def test_one_partition_reads_latest_and_two_partitions_fail_closed(self):
        self.client.publish(self.proposal())
        self.online.remove("replica-2")
        self.client.publish(self.proposal(epoch=1, revoked=["b" * 64]))
        self.online = {"replica-1", "replica-2"}
        self.assertEqual(
            self.client.snapshot("scope-a", "cell")["frontier"]["epoch"], 1
        )
        self.online = {"replica-2"}
        with self.assertRaises(QuorumUnavailable):
            self.client.snapshot("scope-a", "cell")

    def test_prepared_writer_failure_recovers_without_new_signature(self):
        proposal = self.proposal()
        for name in ("replica-0", "replica-1"):
            self.replicas[name].prepare(proposal)
        self.assertIsNone(self.client.read("scope-a"))
        recovered = self.client.recover_pending("scope-a")
        self.assertEqual(recovered["certificate"]["proposal"], proposal)
        self.assertEqual(self.client.read("scope-a")["proposal"], proposal)

    def test_one_vote_per_sequence_prevents_two_valid_forks(self):
        proposal_a = self.proposal()
        proposal_b = self.proposal(
            placements=[dict(self.placement, node_id="worker-b")]
        )
        vote_a = self.replicas["replica-0"].prepare(proposal_a)
        with self.assertRaises(ValueError):
            self.replicas["replica-0"].prepare(proposal_b)
        other_a = self.replicas["replica-1"].prepare(proposal_a)
        vote_b = self.replicas["replica-2"].prepare(proposal_b)
        with self.assertRaises(ValueError):
            self.members.certificate(proposal_b, [vote_a, vote_b])
        self.client.finish(self.members.certificate(proposal_a, [vote_a, other_a]))
        self.assertEqual(
            self.replicas["replica-2"].read("scope-a")["certificate"]["proposal"],
            proposal_a,
        )

    def test_lagging_replica_replays_certified_chain(self):
        self.client.publish(self.proposal())
        self.online.remove("replica-2")
        self.client.publish(self.proposal(epoch=1))
        self.client.publish(self.proposal(epoch=2, revoked=["b" * 64]))
        self.online.add("replica-2")
        repaired = self.client.repair("scope-a", "replica-2")
        self.assertEqual((repaired["sequence"], len(repaired["transferred"])), (3, 2))
        self.assertEqual(
            self.replicas["replica-2"].read("scope-a")["certificate"],
            self.client.read("scope-a"),
        )

    def test_database_loss_and_restore_rollback_are_not_empty_genesis(self):
        self.client.publish(self.proposal())
        replica = self.replicas["replica-0"]
        backup = self.root / "old.sqlite"
        shutil.copyfile(replica.database, backup)
        self.client.publish(self.proposal(epoch=1))
        shutil.copyfile(backup, replica.database)
        with self.assertRaises(ValueError):
            replica.read("scope-a")
        with self.assertRaises(ValueError):
            Replica(replica.root, "replica-0", self.members, self.keys["replica-0"])
        replica.database.unlink()
        with self.assertRaises(ValueError):
            Replica(
                replica.root,
                "replica-0",
                self.members,
                self.keys["replica-0"],
                creation="genesis",
            )

    def test_forged_duplicate_or_wrong_membership_certificates_rejected(self):
        proposal = self.proposal()
        vote = self.replicas["replica-0"].prepare(proposal)
        with self.assertRaises(ValueError):
            self.members.certificate(proposal, [vote, vote])
        forged = copy.deepcopy(proposal)
        forged["state"]["frontier"]["epoch"] = 7
        with self.assertRaises(ValueError):
            self.replicas["replica-1"].prepare(forged)
        wrong = copy.deepcopy(proposal["state"])
        wrong["membership_sha256"] = "c" * 64
        with self.assertRaises(ValueError):
            self.members.propose(wrong, self.writer)


if __name__ == "__main__":
    unittest.main()
