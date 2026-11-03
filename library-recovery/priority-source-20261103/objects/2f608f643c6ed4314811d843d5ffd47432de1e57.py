"""Executable policy model and source-wiring checks; not native Rust evidence."""
from pathlib import Path
import asyncio
import unittest

ROOT=Path(__file__).resolve().parent
class Schedule:
    def __init__(self):self.next=0
    def reserve(self,n,limit):
        if not 1<=limit<=256 or n==0:raise ValueError('invalid schedule')
        start=self.next%n;self.next=(start+1)%n
        selected=min(n,limit)
        return start,[limit//selected+(i<limit%selected) for i in range(selected)]

class FairnessTests(unittest.TestCase):
    def test_every_reserved_observer_budget_is_bounded(self):
        schedule=Schedule()
        for n in list(range(1,301))+[2**64-1]:
            for limit in range(1,257):
                start,quotas=schedule.reserve(n,limit)
                self.assertLess(start,n)
                self.assertEqual(len(quotas),min(n,limit))
                self.assertEqual(sum(quotas),limit)
                self.assertTrue(all(q>0 for q in quotas))
    def test_unknown_prefix_and_terminal_tail(self):
        schedule=Schedule();seen=[]
        for _ in range(3):
            start,quotas=schedule.reserve(3,1)
            seen.extend((start+i)%3 for i,q in enumerate(quotas))
        self.assertEqual(seen,[0,1,2])
    def test_unavailable_does_not_expand_budget(self):
        start,quotas=Schedule().reserve(3,5)
        actual_observer_calls=0;settled=0
        for index,quota in enumerate(quotas):
            actual_observer_calls+=quota
            settled+=0 if index<2 else quota
        self.assertEqual(actual_observer_calls,5)
        self.assertEqual(settled,1)
    def test_error_retry_starts_at_unattempted_destination(self):
        schedule=Schedule();first=[]
        for _ in range(6):
            start,_=schedule.reserve(3,3);first.append(start)
        self.assertEqual(first,[0,1,2,0,1,2])
    def test_changed_snapshot_and_shared_clones(self):
        original=Schedule();clone=original
        self.assertEqual(original.reserve(2,1),(0,[1]))
        changed=Schedule()
        self.assertEqual(changed.reserve(3,1),(0,[1]))
        self.assertEqual(clone.reserve(2,1),(1,[1]))
    def test_invalid_does_not_advance(self):
        schedule=Schedule()
        for n,limit in [(3,0),(3,257),(0,1)]:
            with self.assertRaises(ValueError):schedule.reserve(n,limit)
        self.assertEqual(schedule.reserve(3,1),(0,[1]))
    def test_actual_host_and_runtime_wiring(self):
        host=(ROOT/'current/codex-rs/hepta-agentd/src/production_writer_host.rs').read_text()
        runtime=(ROOT/'base/codex-rs/hepta-agentd/src/runtime.rs').read_text()
        body=host.split('    pub async fn reconcile(',1)[1].split('    pub async fn dispatch(',1)[0]
        self.assertIn('.reserve(self.dispatchers.len(), limit)?',body)
        self.assertIn('.zip(plan.quotas)',body)
        self.assertNotIn('limit - total',body)
        self.assertNotIn('.dispatch(',body)
        self.assertIn('.await?',body)
        for name,end in [('attach_target','attach_additional_target'),('attach_additional_target','has_target')]:
            section=host.split(f'    pub fn {name}(',1)[1].split(f'    pub fn {end}(',1)[0]
            self.assertIn('self.reconciliation_schedule = Arc::default()',section)
        loop=runtime.split('async fn run_production_operation_reconciler(',1)[1].split('async fn monitor_runtime(',1)[0]
        self.assertIn('host: Arc<crate::AgentdProductionWriterHost>',loop)
        self.assertIn('host.reconcile(256).await?',loop)
        self.assertNotIn('::open',loop)
        self.assertNotIn('attach_target',loop)

class CancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancellation_keeps_reserved_progress(self):
        schedule=Schedule();entered=asyncio.Event()
        async def observer():
            self.assertEqual(schedule.reserve(3,1),(0,[1]));entered.set()
            await asyncio.Future()
        task=asyncio.create_task(observer());await entered.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(schedule.reserve(3,1),(1,[1]))

if __name__=='__main__':unittest.main(verbosity=2)
