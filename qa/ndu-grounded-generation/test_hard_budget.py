"""Exercise real externally preempted subprocesses (no model download)."""
import time
import os
import unittest
from hard_budget import HardBudgetPool


def init():
    pass


def work(job):
    if isinstance(job,(int,float)):
        time.sleep(job)
        return {'duration':job}
    if job=='crash':
        os._exit(19)
    if job=='error':
        raise ValueError('deliberate worker exception')
    raise ValueError('unknown job')


class HardBudgetTests(unittest.TestCase):
    def test_timeout_kills_native_or_blocking_work_and_worker_restarts(self):
        with HardBudgetPool(init,(),work,workers=1,init_timeout=5) as pool:
            results=list(pool.run([0.25,0.001],budget=0.08))
            self.assertEqual([r[2]['status'] for r in results],['hard_timeout','completed'])
            self.assertTrue(results[0][2]['worker_restarted'])
            self.assertNotEqual(results[0][2]['resident']['worker_pid'],results[1][2]['resident']['worker_pid'])
            self.assertIsNone(results[0][1]);self.assertEqual(results[1][1],{'duration':0.001})
            self.assertEqual(len(pool.initializations),2)

    def test_concurrency_safely_retains_all_items(self):
        pool=HardBudgetPool(init,(),work,workers=2,init_timeout=5)
        results=list(pool.run([0.01,0.02,0.001,0.003],budget=1))
        self.assertEqual(set(x[0] for x in results),set(range(4)))
        self.assertEqual(sum(x[2]['status']=='completed' for x in results),4)
        self.assertEqual(len(pool.initializations),2)

    def test_timeout_on_one_worker_does_not_delay_active_peer(self):
        pool=HardBudgetPool(init,(),work,workers=2,init_timeout=5)
        results=list(pool.run([0.30,0.02,0.02,0.02,0.02],budget=0.08))
        status={i:r['status'] for i,_,r in results}
        self.assertEqual(status[0],'hard_timeout')
        self.assertEqual([status[i] for i in range(1,5)],['completed']*4)
        self.assertEqual(len(status),5)

    def test_failed_job_does_not_crash_pool_or_count_as_success(self):
        pool=HardBudgetPool(init,(),work,workers=1,init_timeout=5)
        results=list(pool.run(['error',0.001],budget=1))
        self.assertEqual([x[2]['status'] for x in results],['worker_failed','completed'])
        self.assertIsNone(results[0][1])

    def test_abrupt_worker_exit_is_counted_and_recovered(self):
        pool=HardBudgetPool(init,(),work,workers=1,init_timeout=5)
        results=list(pool.run(['crash',0.001],budget=.5))
        self.assertEqual([x[2]['status'] for x in results],['worker_crashed','completed'])
        self.assertEqual(len(pool.initializations),2)
        self.assertIsNone(results[0][1])

    def test_bad_budget_rejected_and_context_exits(self):
        pool=HardBudgetPool(init,(),work,workers=1,init_timeout=5)
        for budget in (0,-1,float('inf'),float('nan')):
            with self.assertRaises(ValueError): list(pool.run([0.01],budget))
        pool.close()


class InterruptedReceiptTests(unittest.TestCase):
    def test_hard_timeout_retains_denominator_and_measured_cost(self):
        from hard_budget import interrupted_episode
        from evaluate import score_episode
        observation={'task_id':'sample','image_sha256':'a'*64,'target_category':'cat'}
        job=(observation,'ndu',23,.5,observation,0.1)
        receipt={'status':'hard_timeout','measured_wall_seconds':.11,
                 'resident':{'worker_pid':33,'load_seconds':1.0},
                 'internal_call_counts_complete':False}
        row=interrupted_episode(job,receipt,{'policies.pt':'sha'},'frozen')
        reference={'task_id':'sample','source_id':'sample','image_size':[8,8],
                   'boxes':[[.1,.1,.8,.8]],'label':'cat','count':1,'largest_side':'left'}
        score=score_episode(row,reference)
        self.assertEqual(score['quality'],0.0)
        self.assertEqual(score['coverage'],0.0)
        self.assertEqual(score['severe'],1.0)
        self.assertTrue(score['budget_exceeded'])
        self.assertAlmostEqual(score['wall_seconds'],.11)
        self.assertIsNone(row['generated_tokens'])
        self.assertFalse(row['internal_model_calls_complete'])

    def test_failed_record_requires_nonzero_measured_wall(self):
        from hard_budget import interrupted_episode
        observation={'task_id':'x','image_sha256':'a'*64,'target_category':'cat'}
        job=(observation,'ndu',1,.5,observation,1)
        for receipt in ({'status':'completed','measured_wall_seconds':.3},
                        {'status':'hard_timeout','measured_wall_seconds':0}):
            with self.assertRaises(ValueError):
                interrupted_episode(job,receipt,{},'frozen')


if __name__=='__main__':unittest.main()
