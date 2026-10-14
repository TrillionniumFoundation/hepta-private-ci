"""Real SQLite roundtrips, fail-closed writes, scope/anchor and receipt replay."""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
import shutil
import sqlite3
from contextlib import closing
import tempfile
import threading
import unittest
from unittest.mock import patch
from four_gate_common import digest
from fbsde_rule_checkpoint import RuleCheckpoint, CheckpointError
from fbsde_durable_rule import DurableRuleSlot
from fbsde_checkpoint_audit import validate_rows
from fbsde_transfer import TransferProblem, TransferTable, OPS
from fbsde_rule_lifecycle import UseTicket
from test_fbsde_rule_lifecycle import PUBLIC, CONTEXT, source, begin


def create(root, *, limit=5, fault=None):
    problem = TransferProblem.build(PUBLIC,CONTEXT)
    history = tuple((s,problem.table[1][s]) for s in range(6))
    table = TransferTable.from_support(problem,history,dict(binding=problem.binding,**CONTEXT))
    store = RuleCheckpoint(root,create=True,fault=fault)
    return DurableRuleSlot(store,PUBLIC,CONTEXT,history,table.snapshot(),recovery_limit=limit)


class DurableRuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.live = None
    def tearDown(self):
        if self.live is not None:self.live.close()
        self.temp.cleanup()
    def make(self, **kwargs): self.live = create(self.root,**kwargs); return self.live
    def reopen(self, anchor, context=CONTEXT):
        store=RuleCheckpoint(self.root,anchor=anchor)
        try:self.live=DurableRuleSlot.reopen(store,context)
        except BaseException:store.close();raise
        return self.live

    def test_restart_never_restores_active_capability(self):
        s=self.make(); ticket=begin(s); floor=s.checkpoint_anchor();s.close()
        s=self.reopen(floor)
        self.assertEqual(s.status()['state'],'quarantined')
        with self.assertRaises(ValueError):s.finish(ticket)
        with self.assertRaises(ValueError):s.finish(UseTicket(**ticket.__dict__))
        with self.assertRaises(ValueError):begin(s)
        self.assertTrue(s.relearn(source(1)))
        t=begin(s);self.assertEqual(s.finish(t),(0,2,1));validate_rows(s._store.rows())

    def test_failed_attempts_survive_multiple_restarts_and_generation(self):
        s=self.make(limit=2);s.advance_generation(2)
        def unavailable(_):raise OSError('source down')
        for _ in range(2):
            self.assertFalse(s.relearn(unavailable));floor=s.checkpoint_anchor();s.close()
            s=self.reopen(floor,dict(CONTEXT,generation=2))
        self.assertEqual(s.status()['recovery_attempts'],2)
        s.advance_generation(3)
        self.assertFalse(s.relearn(lambda _:self.fail('refilled attempt budget')))
        validate_rows(s._store.rows())

    def test_committed_receipt_before_history_update_replays_once(self):
        armed=[False]
        def fault(phase,event):
            if armed[0] and event=='recovery_receipt' and phase=='after_commit':raise OSError('lost response')
        s=self.make(fault=fault);s.advance_generation(2);floor=s.checkpoint_anchor();armed[0]=True
        with self.assertRaises(CheckpointError):s.relearn(source(7))
        s.close();s=self.reopen(floor,dict(CONTEXT,generation=2))
        self.assertEqual(len(s._history),1);self.assertEqual(s.status()['recovery_attempts'],1)
        self.assertTrue(s.relearn(source(7)))
        self.assertEqual(s.status()['recovery_attempts'],3)
        self.assertEqual(len(s._history),3)
        validate_rows(s._store.rows())

    def test_precommit_failure_cannot_publish_or_enter_source(self):
        def fault(phase,event):
            if event=='verification_intent' and phase=='before_commit':raise OSError('disk full')
        s=self.make(fault=fault);ticket=begin(s);calls=[]
        with self.assertRaises(Exception):s.verify(ticket,source(1,calls))
        self.assertEqual(calls,[])
        with self.assertRaises(ValueError):s.finish(ticket)

    def test_generation_and_anchor_rollback_reject(self):
        s=self.make();old=(self.root/'rule.sqlite3').read_bytes();s.advance_generation(2)
        floor=s.checkpoint_anchor();s.close()
        with self.assertRaisesRegex(ValueError,'rollback'):self.reopen(floor,CONTEXT)
        (self.root/'rule.sqlite3').write_bytes(old)
        with self.assertRaisesRegex(ValueError,'rollback'):RuleCheckpoint(self.root,anchor=floor)

    def test_missing_database_is_not_initialized(self):
        s=self.make();floor=s.checkpoint_anchor();s.close();(self.root/'rule.sqlite3').unlink()
        with self.assertRaises(FileNotFoundError):RuleCheckpoint(self.root,anchor=floor)
        self.assertFalse((self.root/'rule.sqlite3').exists())

    def test_corruption_and_second_owner_refuse(self):
        s=self.make();floor=s.checkpoint_anchor()
        with self.assertRaises(BlockingIOError):RuleCheckpoint(self.root,anchor=floor)
        s.close();(self.root/'rule.sqlite3').write_bytes(b'bad database')
        with self.assertRaises(sqlite3.DatabaseError):RuleCheckpoint(self.root,anchor=floor)

    def test_foreign_anchor_and_environment_reject(self):
        s=self.make();floor=s.checkpoint_anchor();s.close()
        with self.assertRaisesRegex(ValueError,'foreign'):RuleCheckpoint(self.root,anchor=dict(floor,database_id='x'*32))
        with self.assertRaisesRegex(ValueError,'foreign'):self.reopen(floor,dict(CONTEXT,environment='elsewhere'))

    def test_error_after_commit_requires_reopen_not_memory_retry(self):
        def fault(phase,event):
            if event=='finish' and phase=='after_commit':raise OSError('commit outcome unavailable')
        s=self.make(fault=fault);ticket=begin(s);floor=s.checkpoint_anchor()
        with self.assertRaises(CheckpointError):s.finish(ticket)
        with self.assertRaises(ValueError):s.finish(ticket)
        s.close();s=self.reopen(floor)
        self.assertIn('finish',[e['event'] for e in s.records()])
        self.assertEqual(s.status()['state'],'quarantined')

    def test_late_thread_receipt_cannot_reactivate_committed_revocation(self):
        s=self.make();ticket=begin(s);entered=threading.Event();release=threading.Event();out=[]
        def reveal(r):entered.set();release.wait(2);return source(1)(r)
        thread=threading.Thread(target=lambda:out.append(s.verify(ticket,reveal)))
        thread.start();self.assertTrue(entered.wait(2));s.advance_generation(2);release.set();thread.join(2)
        self.assertEqual(out,[False]);validate_rows(s._store.rows())
        floor=s.checkpoint_anchor();s.close();s=self.reopen(floor,dict(CONTEXT,generation=2))
        with self.assertRaises(ValueError):s.finish(ticket)

    def test_refusal_survives_reopen(self):
        s=self.make();s.advance_generation(2)
        self.assertFalse(s.relearn(lambda r:dict(request_sha256=digest(r),effect=(0,0,1))))
        floor=s.checkpoint_anchor();s.close();s=self.reopen(floor,dict(CONTEXT,generation=2))
        self.assertEqual(s.status()['state'],'refused')
        self.assertFalse(s.relearn(lambda _:self.fail('refused source called')))
        validate_rows(s._store.rows())

    def test_forged_budget_and_active_state_fail_semantic_replay(self):
        s=self.make();s.advance_generation(2)
        def error(_):raise OSError('pause')
        s.relearn(error);rows=s._store.rows()
        bad=copy.deepcopy(rows);bad[-1]['snapshot']['attempts']=0
        with self.assertRaisesRegex(ValueError,'accounting'):validate_rows(bad)
        bad=copy.deepcopy(rows);bad[-1]['snapshot']['state']='active'
        with self.assertRaisesRegex(ValueError,'accounting'):validate_rows(bad)

    def test_reopen_keeps_name_permutation_semantics(self):
        s=self.make();names=['Nolan','Mira','Orla'];t=s.begin(PUBLIC['event'],names,(0,1,2));s.finish(t)
        floor=s.checkpoint_anchor();validate_rows(s._store.rows());s.close();self.reopen(floor)

    def test_committed_unsupported_receipt_is_refused_on_restart(self):
        armed=[False]
        def fault(phase,event):
            if armed[0] and phase=='after_commit' and event=='recovery_receipt':raise OSError('crash boundary')
        s=self.make(fault=fault);s.advance_generation(2);floor=s.checkpoint_anchor();armed[0]=True
        with self.assertRaises(CheckpointError):
            s.relearn(lambda r:dict(request_sha256=digest(r),effect=(0,0,1)))
        s.close();s=self.reopen(floor,dict(CONTEXT,generation=2))
        self.assertEqual(s.status()['state'],'refused');validate_rows(s._store.rows())

    def test_snapshot_tampering_with_fresh_hash_still_rejects(self):
        from fbsde_rule_checkpoint import SCHEMA, encode
        s=self.make();floor=s.checkpoint_anchor();s.advance_generation(2)
        def fail(_):raise OSError('unavailable')
        s.relearn(fail);s.close()
        with closing(sqlite3.connect(self.root/'rule.sqlite3')) as db:
            seq,prev,event,snapshot,_=db.execute('SELECT * FROM checkpoint ORDER BY seq DESC LIMIT 1').fetchone()
            event=json.loads(event);snapshot=json.loads(snapshot);snapshot['attempts']=0
            identity=digest([SCHEMA,floor['database_id'],seq,prev,event,snapshot])
            db.execute('UPDATE checkpoint SET snapshot=?,digest=? WHERE seq=?',(encode(snapshot),identity,seq))
            db.commit()
        with self.assertRaisesRegex(ValueError,'accounting'):self.reopen(floor,dict(CONTEXT,generation=2))

    def test_second_process_cannot_open_live_owner(self):
        s=self.make();floor=s.checkpoint_anchor()
        code="from fbsde_rule_checkpoint import RuleCheckpoint; import json,sys; RuleCheckpoint(sys.argv[1],anchor=json.loads(sys.argv[2]))"
        p=subprocess.run([sys.executable,'-c',code,str(self.root),json.dumps(floor)],capture_output=True,timeout=10)
        self.assertNotEqual(p.returncode,0);self.assertIn(b'BlockingIOError',p.stderr)
        t=begin(s);s.finish(t)

    def test_symlink_database_and_lock_are_rejected(self):
        s=self.make();floor=s.checkpoint_anchor();s.close()
        path=self.root/'rule.sqlite3';path.rename(self.root/'elsewhere');path.symlink_to(self.root/'elsewhere')
        with self.assertRaises(ValueError):RuleCheckpoint(self.root,anchor=floor)
        path.unlink();(self.root/'writer.lock').unlink();(self.root/'writer.lock').symlink_to(self.root/'elsewhere')
        with self.assertRaises(OSError):RuleCheckpoint(self.root,anchor=floor)

    def test_capacity_failure_never_returns_result(self):
        with patch('fbsde_rule_checkpoint.MAX_ROWS',2):
            s=self.make();t=begin(s)
            with self.assertRaisesRegex(ValueError,'capacity'):s.finish(t)
            self.assertEqual(s.status()['state'],'quarantined')
            with self.assertRaises(ValueError):begin(s)

    def test_initial_persistence_failure_releases_owner(self):
        def fault(phase,event):raise OSError('disk unavailable')
        with self.assertRaises(CheckpointError):create(self.root,fault=fault)
        import fcntl
        fd=os.open(self.root/'writer.lock',os.O_RDWR)
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        finally:os.close(fd)

    def test_failed_restore_releases_database_owner(self):
        s=self.make();floor=s.checkpoint_anchor();s.close()
        store=RuleCheckpoint(self.root,anchor=floor)
        with self.assertRaisesRegex(ValueError,'foreign'):
            DurableRuleSlot.reopen(store,dict(CONTEXT,environment='foreign'))
        # Caller does not close the failed store: ownership was consumed by reopen.
        with RuleCheckpoint(self.root,anchor=floor) as fresh:
            self.assertEqual(fresh.anchor(),floor)

    def test_sql_page_exhaustion_closes_slot_before_output(self):
        s=self.make();db=s._store._db
        pages=db.execute('PRAGMA page_count').fetchone()[0]
        db.execute(f'PRAGMA max_page_count={pages}')
        with self.assertRaises(CheckpointError):
            for _ in range(32):begin(s)
        with self.assertRaises(ValueError):begin(s)
        self.assertEqual(s.status()['state'],'quarantined')

    def test_anchor_required_and_create_never_overwrites(self):
        s=self.make();s.close()
        with self.assertRaises(ValueError):RuleCheckpoint(self.root)
        with self.assertRaises(FileExistsError):RuleCheckpoint(self.root,create=True)


if __name__=='__main__':unittest.main()
