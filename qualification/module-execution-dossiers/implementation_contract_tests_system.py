"""Embodiment and disposable SQLite implementation-contract tests."""
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction as F
from pathlib import Path
import implementation_contracts as c

BASE=Path(__file__).resolve().parent
class EmbodimentTests(unittest.TestCase):
    def test_schedulable_controller(self): self.assertEqual(c.response_time(1000,200,10000,[(100,1000)]),1400)
    def test_deadline_miss(self):
        with self.assertRaises(c.Invalid): c.response_time(900,200,1000,[])
    def test_overloaded_task_set(self):
        with self.assertRaises(c.Invalid): c.response_time(1000,0,5000,[(1000,1000)])
    def test_cart_first_step(self): self.assertEqual(c.cart_step(F(1,2),F(0)),(F(1,2),F(-1,50),F(-2)))
    def test_zero_control_not_instant_stop(self):
        x,v,u=c.cart_step(F(-1,10),F(1,10)); self.assertEqual(u,0); self.assertEqual(v,F(1,10))
    def test_cart_profile_dt_drift(self):
        with self.assertRaises(c.Invalid): c.cart_step(0,0,F(1,10))
    def test_ideal_matrix_polynomial(self):
        tr=F(1)+F(96,100); det=F(96,100)+F(4,10000)
        self.assertEqual(tr,2*F(98,100)); self.assertEqual(det,F(98,100)**2)
    def test_cart_bounded_initial_trajectory(self):
        x,v=F(1,2),F(0)
        for _ in range(500):
            x,v,u=c.cart_step(x,v)
            self.assertLessEqual(abs(x),1); self.assertLessEqual(abs(v),1); self.assertLessEqual(abs(u),2)
        self.assertLess(abs(x),F(1,1000)); self.assertLess(abs(v),F(1,1000))

    def test_ideal_brake_stops_without_losing_position(self):
        x,v=F(0),F(1)
        for _ in range(50):
            x,v,u=c.cart_brake(x,v)
            self.assertLessEqual(abs(u),2)
        self.assertEqual(v,0)
        self.assertEqual(x,F(255,1000))
    def test_brake_outside_stopping_margin_rejects(self):
        with self.assertRaises(c.Invalid): c.cart_brake(F(9,10),F(1))
    def test_stationary_brake(self):
        self.assertEqual(c.cart_brake(F(1,2),F(0)),(F(1,2),F(0),F(0)))

class SqlFixtureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name)/'cognitive.sqlite'
        self.db=sqlite3.connect(self.path,isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript((BASE/'COGNITIVE_STORE.sql').read_text())
        self.db.execute('INSERT INTO frontier VALUES(?,?,?)',('s',0,b'0'*32))
    def tearDown(self): self.db.close(); self.tmp.cleanup()
    def add(self,sequence=1,kind='fact'):
        self.db.execute('INSERT INTO event VALUES(?,?,?,?,?,?,?,?)',('s',sequence,'r',sequence,kind,None,b'd'*32,b'payload'))
    def test_transaction_rollback(self):
        self.db.execute('BEGIN IMMEDIATE'); self.add(); self.db.execute('ROLLBACK')
        self.assertEqual(self.db.execute('SELECT count(*) FROM event').fetchone()[0],0)
    def test_commit_reopen(self):
        self.db.execute('BEGIN IMMEDIATE'); self.add(); self.db.execute('COMMIT')
        with sqlite3.connect(self.path) as other: self.assertEqual(other.execute('SELECT count(*) FROM event').fetchone()[0],1)
    def test_invalid_digest_type(self):
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('INSERT INTO frontier VALUES(?,?,?)',('bad',0,'x'*32))
    def test_current_foreign_key(self):
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('INSERT INTO current_record VALUES(?,?,?)',('s','r',99))
    def test_duplicate_revision(self):
        self.add()
        with self.assertRaises(sqlite3.IntegrityError): self.add()
    def test_two_writer_lock(self):
        self.db.execute('BEGIN IMMEDIATE')
        other=sqlite3.connect(self.path,timeout=0.01,isolation_level=None)
        try:
            with self.assertRaises(sqlite3.OperationalError): other.execute('BEGIN IMMEDIATE')
        finally: other.close(); self.db.execute('ROLLBACK')
    def test_revocation_overlay_query(self):
        self.add(); self.db.execute('INSERT INTO revocation VALUES(?,?,?,?,?)',('s',1,'r',1,b'x'*32))
        count=self.db.execute('SELECT count(*) FROM event e WHERE NOT EXISTS(SELECT 1 FROM revocation r WHERE r.scope=e.scope AND r.source_id=e.record_id AND r.cutoff_event_sequence>=e.sequence)').fetchone()[0]
        self.assertEqual(count,0)
    def test_wrong_record_pointer(self):
        self.add()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO current_record VALUES(?,?,?)",('s','other',1))
    def test_fractional_sequence(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE frontier SET sequence=1.5 WHERE scope='s'")
    def test_orphan_publication_intent(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO publication_intent VALUES(?,?,?,?,?)",('s','missing','kg',b'd'*32,'pending'))
    def test_publication_intent_requires_valid_disposition(self):
        self.add()
        self.db.execute("INSERT INTO mutation VALUES(?,?,?,?,?)",('s','op',b'd'*32,1,b'r'*32))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO publication_intent VALUES(?,?,?,?,?)",('s','op','kg',b'd'*32,'succeeded'))
    def abrupt(self,commit):
        code='import sqlite3,sys,os; d=sqlite3.connect(sys.argv[1],isolation_level=None); d.execute("PRAGMA synchronous=FULL"); d.execute("BEGIN IMMEDIATE"); d.execute("INSERT INTO event VALUES(?,?,?,?,?,?,?,?)",("s",1,"r",1,"fact",None,b"d"*32,b"p")); '+('d.execute("COMMIT"); ' if commit else '')+'os._exit(77)'
        p=subprocess.run([sys.executable,'-c',code,str(self.path)],timeout=10,check=False,capture_output=True)
        self.assertEqual(p.returncode,77,p.stderr.decode())
    def test_abrupt_exit_before_commit(self):
        self.abrupt(False); self.assertEqual(self.db.execute('SELECT count(*) FROM event').fetchone()[0],0)
    def test_abrupt_exit_after_commit(self):
        self.abrupt(True); self.assertEqual(self.db.execute('SELECT count(*) FROM event').fetchone()[0],1)
