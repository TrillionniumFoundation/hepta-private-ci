"""Design experiment, NOT native production validation.

Uses the exact current uncertain-dispatch table shape and independent proposed
rowid-epoch reads. It never edits source evidence to achieve fairness.
"""
import sqlite3
import unittest
from dataclasses import dataclass

SCHEMA = '''
CREATE TABLE automation_tasks(task_id TEXT PRIMARY KEY, owner_agent_id TEXT NOT NULL);
CREATE TABLE automation_runs(task_id TEXT NOT NULL, occurrence INTEGER NOT NULL,
 scheduled_for_ms INTEGER NOT NULL, PRIMARY KEY(task_id, occurrence));
CREATE TABLE automation_dispatch_outcomes (
 task_id TEXT NOT NULL, occurrence INTEGER NOT NULL,
 client_user_message_id TEXT NOT NULL UNIQUE, queued_submission_id TEXT UNIQUE,
 outcome TEXT NOT NULL CHECK (outcome IN ('uncertain', 'submitted')),
 observed_at_ms INTEGER NOT NULL, submitted_at_ms INTEGER,
 PRIMARY KEY(task_id, occurrence));
CREATE INDEX automation_dispatch_outcome_state_idx
 ON automation_dispatch_outcomes(outcome, observed_at_ms, task_id, occurrence);
'''
from pathlib import Path
import re
SOURCE = (Path(__file__).resolve().parents[1] / 'cursor-candidate/codex-rs/hepta-automation/src/uncertain_dispatch_scan.rs').read_text()
FIRST = re.search(r'"(SELECT rowid FROM automation_dispatch_outcomes ORDER BY rowid LIMIT 1)"',SOURCE).group(1)
HIGH = re.search(r'"(SELECT rowid FROM automation_dispatch_outcomes ORDER BY rowid DESC LIMIT 1)"',SOURCE).group(1)
NEXT = re.search(r'"(SELECT o\.\*, t\.owner_agent_id, r\.scheduled_for_ms FROM \(.*?)",',SOURCE,re.S).group(1)

@dataclass
class Cursor:
 owner: str
 identity: object
 after: int=0
 through: int|None=None

class Experiment:
 def __init__(self):
  self.db=sqlite3.connect(':memory:');self.db.executescript(SCHEMA);self.identity=object()
 def cursor(self,owner):return Cursor(owner,self.identity)
 def add(self,i,owner='a',observed=None):
  task=f'{owner}-{i:06}';self.db.execute('INSERT INTO automation_tasks VALUES (?,?)',(task,owner))
  self.db.execute('INSERT INTO automation_runs VALUES (?,1,100)',(task,))
  self.db.execute('INSERT INTO automation_dispatch_outcomes VALUES (?,1,?,NULL,\'uncertain\',?,NULL)',(task,f'client-{task}',i if observed is None else observed));self.db.commit()
 def select(self,cursor,owner):
  if cursor.owner != owner or cursor.identity is not self.identity:raise ValueError('cross-store cursor')
  if cursor.through is None:
   first=self.db.execute(FIRST).fetchone()
   if first is not None and first[0] <= 0:raise ValueError('nonpositive rowid')
   high=self.db.execute(HIGH).fetchone()
   cursor.after=0;cursor.through=high[0] if high else None
   if cursor.through is None:return None
  rows=self.db.execute(NEXT,(cursor.after,cursor.through)).fetchall()
  assert len(rows)<=64
  last=cursor.after;result=None
  for row in rows:
   assert last<row[0]<=cursor.through
   last=row[0]
   if row[5]=='uncertain' and row[6]==owner:
    result=row[:5];break
  if not rows or last==cursor.through:
   cursor.after=0;cursor.through=None
  else:cursor.after=last
  return result
 def snapshot(self):return tuple(self.db.iterdump())

class FairnessDesignTests(unittest.TestCase):
 def test_oldest_failure_does_not_starve_row_1025(self):
  e=Experiment()
  for i in range(1025):e.add(i)
  before=e.snapshot();c=e.cursor('a')
  seen=[e.select(c,'a')[1] for _ in range(1025)]
  self.assertEqual(len(set(seen)),1025);self.assertEqual(before,e.snapshot())
  self.assertEqual(e.select(c,'a')[1],'a-000000')
 def test_continuous_arrivals_do_not_extend_epoch(self):
  e=Experiment();e.add(0);e.add(1);e.add(2);c=e.cursor('a')
  self.assertEqual(e.select(c,'a')[1],'a-000000')
  for expected in [1,2]:
   e.add(expected+2)
   self.assertEqual(e.select(c,'a')[1],f'a-{expected:06}')
  self.assertEqual(e.select(c,'a')[1],'a-000000')
 def test_mutable_observation_timestamp_does_not_move_anchor(self):
  e=Experiment();e.add(0);e.add(1);c=e.cursor('a')
  self.assertEqual(e.select(c,'a')[1],'a-000000')
  e.db.execute('UPDATE automation_dispatch_outcomes SET observed_at_ms=999999 WHERE task_id=\'a-000000\'');e.db.commit()
  self.assertEqual(e.select(c,'a')[1],'a-000001')
  self.assertEqual(e.select(c,'a')[1],'a-000000')
 def test_removed_high_water_wraps_without_unbounded_rescan(self):
  e=Experiment()
  for i in range(3):e.add(i)
  c=e.cursor('a');e.select(c,'a')
  e.db.execute("DELETE FROM automation_dispatch_outcomes WHERE task_id='a-000002'");e.db.commit()
  self.assertEqual(e.select(c,'a')[1],'a-000001');self.assertIsNone(e.select(c,'a'))
  self.assertEqual(e.select(c,'a')[1],'a-000000')
 def test_owner_scope_and_submitted_rows(self):
  e=Experiment();e.add(0);e.add(1,'b');e.add(2)
  e.db.execute("UPDATE automation_dispatch_outcomes SET outcome='submitted' WHERE task_id='a-000000'");e.db.commit()
  c=e.cursor('a');self.assertEqual(e.select(c,'a')[1],'a-000002')
  with self.assertRaises(ValueError):e.select(c,'b')
 def test_no_observation_never_implies_provider_absence(self):
  e=Experiment();e.add(0);before=e.snapshot();c=e.cursor('a')
  for _ in range(30):e.select(c,'a')
  self.assertEqual(before,e.snapshot())
 def test_restart_only_resets_scheduling_not_effect_identity(self):
  e=Experiment();e.add(0);e.add(1);old=e.cursor('a');first=e.select(old,'a');before=e.snapshot()
  new=e.cursor('a');self.assertEqual(e.select(new,'a')[1:],first[1:]);self.assertEqual(e.snapshot(),before)

 def test_distinct_open_same_owner_is_rejected_and_clone_can_continue(self):
  e=Experiment();e.add(0);e.add(1);c=e.cursor('a');clone=e
  self.assertEqual(clone.select(c,'a')[1],'a-000000')
  other=Experiment();other.add(0)
  with self.assertRaises(ValueError):other.select(c,'a')
  self.assertEqual(e.select(c,'a')[1],'a-000001')
 def test_explicit_rowid_reuse_is_seen_next_epoch_as_current_identity(self):
  e=Experiment()
  for i in range(3):e.add(i)
  c=e.cursor('a');self.assertEqual(e.select(c,'a')[1],'a-000000')
  e.db.execute("DELETE FROM automation_dispatch_outcomes WHERE rowid=1");e.db.commit()
  e.add(3);e.db.execute("UPDATE automation_dispatch_outcomes SET rowid=1 WHERE task_id='a-000003'");e.db.commit()
  self.assertEqual(e.select(c,'a')[1],'a-000001');self.assertEqual(e.select(c,'a')[1],'a-000002')
  self.assertEqual(e.select(c,'a')[1],'a-000003')
 def test_rollback_below_cursor_resets_finitely_without_settlement(self):
  e=Experiment();e.add(0);e.add(1)
  older=sqlite3.connect(':memory:');e.db.backup(older)
  for i in range(2,6):e.add(i)
  c=e.cursor('a')
  for _ in range(4):e.select(c,'a')
  older.backup(e.db);before=e.snapshot()
  self.assertIsNone(e.select(c,'a'))
  self.assertEqual(e.select(c,'a')[1],'a-000000');self.assertEqual(e.snapshot(),before)
 def test_cancelled_observation_loses_no_uncertain_work(self):
  e=Experiment();e.add(0);e.add(1);before=e.snapshot();c=e.cursor('a')
  first=e.select(c,'a') # cancellation after selection means no settlement
  self.assertEqual(e.select(c,'a')[1],'a-000001')
  self.assertEqual(e.select(c,'a')[1:],first[1:]);self.assertEqual(e.snapshot(),before)
 def test_nonpositive_corrupt_rowid_is_not_silently_hidden(self):
  e=Experiment();e.add(0);e.add(1)
  e.db.execute("UPDATE automation_dispatch_outcomes SET rowid=-2 WHERE task_id='a-000000'");e.db.commit()
  with self.assertRaises(ValueError):e.select(e.cursor('a'),'a')

 def test_physical_window_bounds_settled_holes(self):
  e=Experiment()
  for i in range(130):e.add(i)
  e.db.execute("UPDATE automation_dispatch_outcomes SET outcome='submitted' WHERE rowid<130");e.db.commit()
  c=e.cursor('a');self.assertIsNone(e.select(c,'a'));self.assertEqual(c.after,64)
  self.assertIsNone(e.select(c,'a'));self.assertEqual(c.after,128)
  self.assertEqual(e.select(c,'a')[1],'a-000129');self.assertIsNone(c.through)
 def test_actual_query_cost_is_independent_of_total_frontier(self):
  costs=[];settled_costs=[]
  for count in [100,1000,10000]:
   e=Experiment()
   for i in range(count):e.add(i)
   def measure(query,args=()):
    instructions=0
    def progress():
     nonlocal instructions
     instructions+=1;return 0
    e.db.set_progress_handler(progress,1)
    rows=e.db.execute(query,args).fetchall()
    e.db.set_progress_handler(None,0)
    return instructions,len(rows)
   low=measure(FIRST);high=measure(HIGH);page=measure(NEXT,(0,count))
   self.assertEqual(page[1],64);costs.append((low[0],high[0],page[0]))
   e.db.execute("UPDATE automation_dispatch_outcomes SET outcome='submitted' WHERE rowid<?",(count,));e.db.commit()
   settled_costs.append(measure(NEXT,(0,count))[0])
   print('EXACT SQL',count,'rows; endpoint/page VM steps',costs[-1],'settled-page VM steps',settled_costs[-1])
   if count==100:
    print('PLAN',e.db.execute('EXPLAIN QUERY PLAN '+NEXT,(0,count)).fetchall())
  self.assertEqual(len(set(costs)),1)
  self.assertEqual(len(set(settled_costs)),1)

if __name__=='__main__':unittest.main(verbosity=2)
