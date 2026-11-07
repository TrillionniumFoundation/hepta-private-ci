"""Synthetic subprocess and SIGKILL checks; no scientific worlds are generated."""
import hashlib
import json
import os
from pathlib import Path
import selectors
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from guard import ARMS, FITS, Ledger, digest

ROOT = Path(__file__).resolve().parent
ENV = {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
PROTOCOL = digest("synthetic-finalize-protocol")
COHORT = digest("synthetic-candidates")
CHILD = r'''
import json, signal, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from guard import ARMS, FITS, Ledger, digest
phase, path = sys.argv[2], Path(sys.argv[3])
large = phase in ("complete", "uncommitted")
samples = [{"sha256": digest(["synthetic", fit, domain, i]), "fit": fit, "domain": domain}
           for fit in (FITS if large else FITS[:1])
           for domain in (("iid", "ood") if large else ("iid",))
           for i in range(32 if large else 1)]
ledger = Ledger(path)
protocol, cohort = digest("synthetic-finalize-protocol"), digest("synthetic-candidates")
ledger.freeze(protocol, cohort, [digest(["history", i]) for i in range(2896 if large else 2)])
ledger.reserve(protocol, cohort, samples)
if phase == "complete":
    for i, sample in enumerate(samples):
        for arm in ARMS:
            ledger.claim(protocol, sample["sha256"], sample["fit"], arm)
            ledger.record(protocol, sample["sha256"], sample["fit"], arm,
                          {"synthetic": i, "arm": arm}, .001, .002)
    print(json.dumps({"counts": ledger.counts(protocol), "finalization": ledger.close()}), flush=True)
else:
    sample = samples[0]
    if phase in ("claimed", "recorded"):
        ledger.claim(protocol, sample["sha256"], sample["fit"], "C")
    if phase == "recorded":
        ledger.record(protocol, sample["sha256"], sample["fit"], "C",
                      {"synthetic": 0, "arm": "C"}, .001, .002)
    if phase == "uncommitted":
        ledger.db.execute("PRAGMA cache_size=1")
        ledger.db.execute("BEGIN IMMEDIATE")
        ledger.db.execute("UPDATE attempts SET state='STARTED'")
    print(json.dumps({"ready": phase, "rows": len(samples) * len(ARMS),
        "rollback_journal_bytes": Path(str(path) + "-journal").stat().st_size
            if Path(str(path) + "-journal").exists() else 0}), flush=True)
    signal.pause()
'''
INSPECT = r'''
import json, sqlite3, sys
from pathlib import Path
path = Path(sys.argv[1]).resolve()
db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
try:
    print(json.dumps({"mode": db.execute("PRAGMA journal_mode").fetchall(),
        "integrity": db.execute("PRAGMA integrity_check").fetchall(),
        "rows": db.execute("SELECT sample,fit,domain,arm,state,result,cpu,wall FROM attempts ORDER BY sample,fit,arm").fetchall(),
        "runs": db.execute("SELECT protocol,candidates,state FROM runs").fetchall()}))
finally:
    db.close()
'''


class LedgerProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "ledger.sqlite"

    def tearDown(self):
        self.temp.cleanup()

    def inspect_fresh_process(self):
        process = subprocess.run([sys.executable, "-c", INSPECT, str(self.path)], env=ENV,
                                 text=True, capture_output=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result["mode"], [["delete"]])
        self.assertEqual(result["integrity"], [["ok"]])
        self.assertEqual(result["runs"], [[PROTOCOL, COHORT, "CONSUMED"]])
        return result

    def kill_after_acknowledged_boundary(self, phase):
        child = subprocess.Popen([sys.executable, "-c", CHILD, str(ROOT), phase, str(self.path)],
                                 env=ENV, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(timeout=30), "child did not reach its durable boundary")
                line = child.stdout.readline()
            self.assertTrue(line, "child exited before its boundary")
            marker = json.loads(line)
            self.assertEqual(marker["ready"], phase)
            child.kill()
            _stdout, stderr = child.communicate(timeout=10)
            self.assertEqual(child.returncode, -9, stderr)
            return marker
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)

    def test_320_worlds_nine_arms_survive_process_exit_and_fresh_readonly_open(self):
        child = subprocess.run([sys.executable, "-c", CHILD, str(ROOT), "complete", str(self.path)],
                               env=ENV, text=True, capture_output=True, timeout=120)
        self.assertEqual(child.returncode, 0, child.stderr)
        receipt = json.loads(child.stdout)
        self.assertEqual(receipt["counts"], {"COMPLETE": 2880})
        finalization = receipt["finalization"]
        self.assertTrue(finalization["normal_readonly_reopen_verified"])
        self.assertEqual(finalization["row_counts"], {"runs": 1, "samples": 3216, "attempts": 2880})
        self.assertEqual(finalization["database"]["sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        result = self.inspect_fresh_process()
        expected = []
        i = 0
        for fit in FITS:
            for domain in ("iid", "ood"):
                for index in range(32):
                    sample = digest(["synthetic", fit, domain, index])
                    expected.extend([sample, fit, domain, arm, "COMPLETE", digest({"synthetic": i, "arm": arm}), .001, .002]
                                    for arm in ARMS)
                    i += 1
        self.assertEqual(result["rows"], sorted(expected, key=lambda row: (row[0], row[1], row[3])))
        self.assertFalse(any(Path(str(self.path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")))

    def test_sigkill_after_reservation_keeps_every_denominator_and_refuses_reservation_retry(self):
        self.kill_after_acknowledged_boundary("reserved")
        result = self.inspect_fresh_process()
        self.assertEqual([row[4] for row in result["rows"]], ["RESERVED"] * len(ARMS))
        ledger = Ledger(self.path)
        try:
            with self.assertRaises(ValueError):
                ledger.reserve(PROTOCOL, COHORT, [{"sha256": digest(["synthetic", 11, "iid", 0]), "fit": 11, "domain": "iid"}])
        finally:
            ledger.close()

    def test_sigkill_after_claim_keeps_started_and_forbids_second_inference_claim(self):
        self.kill_after_acknowledged_boundary("claimed")
        result = self.inspect_fresh_process()
        self.assertEqual({row[3]: row[4] for row in result["rows"]}, {arm: "STARTED" if arm == "C" else "RESERVED" for arm in ARMS})
        ledger = Ledger(self.path)
        try:
            with self.assertRaises(ValueError):
                ledger.claim(PROTOCOL, digest(["synthetic", 11, "iid", 0]), 11, "C")
        finally:
            ledger.close()

    def test_sigkill_after_record_without_reply_preserves_result_and_forbids_retry(self):
        self.kill_after_acknowledged_boundary("recorded")
        result = self.inspect_fresh_process()
        expected = [row for row in result["rows"] if row[3] == "C"][0]
        self.assertEqual(expected[4:], ["COMPLETE", digest({"synthetic": 0, "arm": "C"}), .001, .002])
        ledger = Ledger(self.path)
        try:
            key = digest(["synthetic", 11, "iid", 0])
            with self.assertRaises(ValueError):
                ledger.claim(PROTOCOL, key, 11, "C")
            with self.assertRaises(ValueError):
                ledger.record(PROTOCOL, key, 11, "C", {"replacement": "forbidden"}, .1, .1)
        finally:
            ledger.close()

    def test_sigkill_with_spilled_uncommitted_pages_recovers_the_original_reservation(self):
        marker = self.kill_after_acknowledged_boundary("uncommitted")
        self.assertGreater(marker["rollback_journal_bytes"], 0)
        ledger = Ledger(self.path)  # SQLite performs its own hot rollback; no sidecar is removed by this test.
        try:
            self.assertEqual(ledger.counts(PROTOCOL), {"RESERVED": 2880})
        finally:
            ledger.close()
        result = self.inspect_fresh_process()
        self.assertEqual(len(result["rows"]), 2880)
        self.assertTrue(all(row[4] == "RESERVED" and row[5] is None for row in result["rows"]))

    def test_existing_wal_main_or_sidecars_are_refused_without_migration(self):
        for retain_connection in (True, False):
            with self.subTest(retain_connection=retain_connection), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "legacy.sqlite"
                connection = sqlite3.connect(path)
                connection.execute("PRAGMA journal_mode=WAL").fetchall()
                connection.execute("CREATE TABLE old_evidence (value TEXT)")
                connection.commit()
                if not retain_connection:
                    connection.close()
                before = {p.name: p.read_bytes() for p in path.parent.iterdir()}
                try:
                    with self.assertRaisesRegex(ValueError, "explicit offline recovery"):
                        Ledger(path)
                    self.assertEqual({p.name: p.read_bytes() for p in path.parent.iterdir()}, before)
                finally:
                    if retain_connection:
                        connection.close()


if __name__ == "__main__":
    unittest.main()
