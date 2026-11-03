import unittest
import numpy as np
from recurrent_factorial_pilot import make_dataset,run_pilot

class RegenerationResearchTask(unittest.TestCase):
    def test_three_resets_and_last_epoch_causality(self):
        for length in (24,48,64):
            x,y=make_dataset(length,32,seed=109,task='regeneration')
            a=x.numpy();b=y.numpy()
            self.assertEqual(a.shape,(32,length,6))
            for i in range(32):
                self.assertEqual(int(a[i,:-1,3].sum()),3)
                self.assertTrue(np.all(a[i,:-1,:5].sum(axis=1)==1))
                self.assertTrue(np.all(a[i,:,5]>0))
                memory=0
                for t in range(length-1):
                    if a[i,t,3]:memory=0
                    elif a[i,t,1]:memory=0
                    elif a[i,t,2]:memory=1
                self.assertEqual(memory,int(b[i]))

    def test_across_holdout_seeds(self):
        x,y=make_dataset(24,192,seed=151,task='regeneration')
        xx,yy=make_dataset(48,192,seed=100151,task='regeneration')
        self.assertFalse(np.array_equal(x.numpy().tobytes(),xx.numpy().tobytes()))
        self.assertTrue(0<float(y.float().mean())<1.)
        self.assertTrue(0<float(yy.float().mean())<1.)

    def test_train_run_is_always_research_only(self):
        r=run_pilot(seeds=(11,),training_steps=2,task='regeneration')
        self.assertEqual(len(r['rows']),8)
        self.assertTrue(r['matched_parameter_data_step_constraints'])
        self.assertFalse(r['full_training_flops_equal'])
        self.assertFalse(r['production_evidence_accepted'])

if __name__=='__main__':unittest.main()
