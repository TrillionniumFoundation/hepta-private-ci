"""The durable handler receives this actual frame's original deadline."""
from pathlib import Path
import tempfile
import tomllib
import unittest

import test_historical_task_read_source_closure as route

ROOT, PROOF = route.ROOT, route.PROOF
PEER = "codex-rs/hepta-contracts/src/authority_host_peer.rs"


class PublicationFrameDeadlineSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def mutate(self, path, change):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            changed = change(source)
            self.assertNotEqual(source, changed)
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    reject = route.HistoricalTaskReadSourceTests.reject
    check = route.HistoricalTaskReadSourceTests.check

    def test_original_api_delegates_without_a_second_timeout(self):
        self.reject(PEER, "exchange", "self.exchange_with_original_deadline(|bytes, _deadline| handle(bytes))")
        self.check(PEER, "exchange_with_original_deadline", (
            "self.stream.take().ok_or(HostIssuerTransportError::Closed)?",
            "self.exchange_inner(&mut stream, handle)",
            "self.stream = Some(stream)", "stream.shutdown(Shutdown::Both)"))

    def test_handler_cannot_receive_a_renewed_or_unrelated_deadline(self):
        self.reject(PEER, "exchange_inner", "let response = handle(&bytes, deadline)?")
        self.mutate(PEER, lambda source: source.replace(
            "handle(&bytes, deadline)?", "handle(&bytes, self.owner.deadline(self.policy.timeout))?", 1))

    def test_all_original_frame_io_and_owner_checks_keep_the_same_end(self):
        self.check(PEER, "exchange_inner", (
            "self.owner.read_until(stream, &mut length[1..], deadline)?",
            "self.owner.read_until(stream, &mut bytes, deadline)?",
            "write_until(stream, &(response.len() as u32).to_be_bytes(), deadline)?",
            "self.owner.write_until(stream, &response, deadline)?"))
        for occurrence in range(3):
            self.reject(PEER, "exchange_inner", "self.owner.check(deadline)?", occurrence)


if __name__ == "__main__":
    unittest.main()
