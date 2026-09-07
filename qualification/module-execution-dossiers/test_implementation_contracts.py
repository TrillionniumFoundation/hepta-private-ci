"""Qualification-only tests: analytic rules and a disposable SQLite DDL fixture."""
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction as F
from pathlib import Path
import implementation_contracts as c

BASE=Path(__file__).resolve().parent
class NumericTests(unittest.TestCase):
    def test_signed_half_ties(self):
        self.assertEqual([c.rescale(v,2,1) for v in (5,7,-5,-7)],[2,4,-2,-4])
    def test_toward_zero_is_not_nearest(self):
        self.assertEqual(c.rescale(-7,2,1,'toward_zero'),-3)
    def test_overflow_rejects(self):
        with self.assertRaises(c.Invalid): c.rescale((1<<63)-1,1,2)
    def test_unknown_rounding_rejects(self):
        with self.assertRaises(c.Invalid): c.rescale(1,1,1,'ambient')
    def test_boolean_is_not_counter(self):
        with self.assertRaises(c.Invalid): c.next_sequence(True)
    def test_exhaustion_before_mutation(self):
        state={'sequence':7,'record':'old'}
        with self.assertRaises(c.Invalid): state['sequence']=c.next_sequence(state['sequence'],7)
        self.assertEqual(state,{'sequence':7,'record':'old'})
    def test_advance_sequence(self): self.assertEqual(c.next_sequence(8),9)
    def test_correlated_covariance(self): self.assertEqual(c.covariance_2d((2,1,2),(5,1)),(3,-1))
    def test_identity_covariance(self): self.assertEqual(c.covariance_2d((1,0,1),(3,-1)),(3,-1))
    def test_singular_covariance(self):
        with self.assertRaises(c.Invalid): c.covariance_2d((1,1,1),(2,2))
    def test_indefinite_covariance(self):
        with self.assertRaises(c.Invalid): c.covariance_2d((1,2,1),(2,2))
    def test_nonzero_mean_centered(self): self.assertEqual(c.centered_scalar([(1,8),(2,11),(3,14)]),3)
    def test_constant_driver_unsupported(self):
        with self.assertRaises(c.Invalid): c.centered_scalar([(1,2),(1,3)])
    def test_scaled_driver(self): self.assertEqual(c.covariance_2d((2,0,2),(6,0)),(3,0))
    def test_joint_ess_floor(self): self.assertEqual(c.ess_floor(5000,[200]),500)
    def test_minimum_ess(self): self.assertEqual(c.ess_floor(1000,[200]),400)
    def test_stricter_ess(self): self.assertEqual(c.ess_floor(1000,[900]),900)
    def test_threshold_intersection(self):
        a={'unit':'m','estimand':'single','scope':'pilot','lower':0,'upper':2}
        b=dict(a,lower=1,upper=3)
        self.assertEqual(c.threshold_intersection([a,b]),(1,2))
    def test_threshold_unit_mismatch(self):
        a={'unit':'m','estimand':'single','scope':'pilot','lower':0,'upper':2}
        with self.assertRaises(c.Invalid): c.threshold_intersection([a,dict(a,unit='seconds')])
    def test_threshold_empty_intersection(self):
        a={'unit':'m','estimand':'single','scope':'pilot','lower':0,'upper':1}
        with self.assertRaises(c.Invalid): c.threshold_intersection([a,dict(a,lower=2,upper=3)])
    def test_sequential_dr(self):
        rows=[dict(v=F(1,4),q=F(1,4),reward=F(1,5),behavior=F(1),evaluation=F(1,2),discount=F(9,10)),dict(v=F(1,2),q=F(1,2),reward=F(1),behavior=F(1,2),evaluation=F(1),discount=F(1))]
        self.assertEqual(c.sequential_dr(rows),F(9,10))
    def test_zero_propensity(self):
        with self.assertRaises(c.Invalid): c.sequential_dr([dict(v=0,q=0,reward=1,behavior=0,evaluation=1,discount=1)])
    def test_terminal_not_double_counted(self):
        self.assertEqual(c.sequential_dr([dict(v=0,q=0,reward=1,behavior=1,evaluation=1,discount=1)],F(0)),1)
    def test_duplicate_json_keys(self):
        with self.assertRaises(c.Invalid): json.loads('{"x":1,"x":2}',object_pairs_hook=c.pairs)

class GraphAndEvolutionTests(unittest.TestCase):
    def test_stable_topology(self): self.assertEqual(c.topo(['b','a','c'],[('a','c'),('b','c')]),['a','b','c'])
    def test_cycle_rejects(self):
        with self.assertRaises(c.Invalid): c.topo(['a','b'],[('a','b'),('b','a')])
    def test_unknown_edge(self):
        with self.assertRaises(c.Invalid): c.topo(['a'],[('a','x')])
    def test_duplicate_edge(self):
        with self.assertRaises(c.Invalid): c.topo(['a','b'],[('a','b'),('a','b')])
    def test_total_disjoint_split(self): c.partition(['a','b','c'],{'left':['a'],'right':['b','c']})
    def test_duplicate_writer_partition(self):
        with self.assertRaises(c.Invalid): c.partition(['a','b'],{'left':['a'],'right':['a','b']})
    def test_omitted_fact_partition(self):
        with self.assertRaises(c.Invalid): c.partition(['a','b'],{'left':['a']})
    def test_all_handoff_phases(self):
        for i,phase in enumerate(c.PHASES): c.handoff(phase,i<3,i>=7,i==0,i>=8,4,5)
    def test_two_valid_writers(self):
        with self.assertRaises(c.Invalid): c.handoff('new_writer_fenced',True,True,False,False,4,5)
    def test_new_admission_before_route(self):
        with self.assertRaises(c.Invalid): c.handoff('new_writer_fenced',False,True,False,True,4,5)
    def test_stale_fence(self):
        with self.assertRaises(c.Invalid): c.handoff('prepared',True,False,True,False,4,4)
    def test_unknown_effect_blocks_cutover(self):
        with self.assertRaises(c.Invalid): c.handoff('old_writer_fenced',False,False,False,False,4,5,1)
    def test_rollback_preserves_delta(self): c.rollback_required_delta(3,3,True,False)
    def test_rollback_old_snapshot_loses_delta(self):
        with self.assertRaises(c.Invalid): c.rollback_required_delta(3,0,True,False)
    def test_revoked_rollback_rejects(self):
        with self.assertRaises(c.Invalid): c.rollback_required_delta(0,0,True,True)
    def test_current_epoch_admission(self): c.admit(4,4,'a'*64,'a'*64)
    def test_revoke_blocks_later_admission(self):
        with self.assertRaises(c.Invalid): c.admit(4,5,'a'*64,'a'*64)
    def test_clamp_requires_new_binding(self):
        with self.assertRaises(c.Invalid): c.admit(4,4,'a'*64,'b'*64)
    def test_path_escape_rejects(self):
        with self.assertRaises(c.Invalid): c.inside(BASE,'../../escape')

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

if __name__=='__main__': unittest.main()
