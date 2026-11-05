"""New hard-budget experiment option: journal, scoring and provenance without a model."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import experiment as ex
from generation import COMPONENTS


class FakeHardPool:
    calls=[]
    def __init__(self,*args,**kwargs):
        self.initializations=[{'worker_pid':4321,'load_seconds':.8,'slot':0}]
    def __enter__(self): return self
    def __exit__(self,*args):return False
    def run(self,jobs,budget):
        self.calls.append(len(jobs))
        for index,job in enumerate(jobs):
            obs,method,seed,risk,partner,cap=job
            receipt={'status':'hard_timeout' if index==0 else 'completed',
                     'measured_wall_seconds':.12 if index==0 else .02,
                     'resident':self.initializations[0],
                     'internal_call_counts_complete':index!=0}
            if index==0:
                yield index,None,receipt
            else:
                yield index,{'task_id':obs['task_id'],'method':method,'seed':seed,'risk_weight':risk,
                             'budget_cap':cap,'budget_unit':'wall_seconds','actual_wall_seconds':.02,
                             'resident_initialization':self.initializations[0],
                             'checkpoint_identities':{'cells.pt':ex.sha(Path(self.work)/'training/cells.pt')},
                             'costs':[{'component':c,'calls':0,'wall_seconds':.02 if c=='controller' else 0.}
                                      for c in COMPONENTS],
                             'controls':[],'failures':[],'termination':'completed'},receipt


class HardBudgetExperimentTests(unittest.TestCase):
    def test_new_mode_is_scored_and_resumable_without_touching_v1_protocol(self):
        with TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'training').mkdir()
            (root/'training/cells.pt').write_bytes(b'cells')
            (root/'manifest.json').write_text('{}')
            pairs=[]
            for i in range(2):
                obs={'task_id':f'task-{i}','image_path':'unused','image_sha256':'f'*64,
                     'prompt':'category','target_category':'cat'}
                ref={'task_id':f'task-{i}','source_id':f'task-{i}'}
                pairs.append((obs,ref))
            args=SimpleNamespace(model='fake',cohort=directory,work=directory,budget=.1,workers=1,hard_budget=True)
            def simple_score(ep,ref):
                failed=ep['termination']!='completed'
                return {'quality':float(not failed),'loss':float(failed),'severe':float(failed)}
            FakeHardPool.calls.clear(); FakeHardPool.work=directory
            with patch.object(ex,'iter_pairs',side_effect=lambda *args: iter(pairs)), \
                 patch.object(ex,'HardBudgetPool',FakeHardPool), \
                 patch.object(ex,'score_episode',side_effect=simple_score):
                rows,_=ex.execute(args,'collect','train',[('explore',23,.5)])
                self.assertEqual([row['score']['quality'] for row in rows],[0.,1.])
                self.assertTrue(rows[0]['internal_model_calls_complete'] is False)
                identity=json.loads((root/'collect.run.json').read_text())['identity']
                self.assertIn('hard_budget.py',identity['implementation_sha256'])
                self.assertEqual(identity['supervision'],'externally-killed-resident-v2')
                self.assertEqual(FakeHardPool.calls,[2])
                rows_again,_=ex.execute(args,'collect','train',[('explore',23,.5)])
                self.assertEqual(rows_again,rows)
                self.assertEqual(FakeHardPool.calls,[2,0])
            with self.assertRaisesRegex(ValueError,'resume identity changed'):
                args.hard_budget=False
                with patch.object(ex,'iter_pairs',side_effect=lambda *args: iter(pairs)):
                    ex.execute(args,'collect','train',[('explore',23,.5)])


if __name__=='__main__':unittest.main()
