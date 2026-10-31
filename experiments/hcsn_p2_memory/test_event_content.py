"""P2 trained memory, exact sampled event owner and checkpoint refusal tests."""
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

from .event_content import (ContentSession,TrainableEventContent,UnresolvedContent,
                            default_spec,example,make_batch,train_pilot,model_digest)


class EventContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.model,cls.report=train_pilot('mqar4',seed=1,steps=48,train_n=96,test_n=64)
        cls.model.eval()

    def test_learnt_state_gradients_and_multi_fire(self):
        r=self.report
        self.assertEqual(r['params'],5186)
        self.assertNotEqual(r['initial_model_sha256'],r['model_sha256'])
        self.assertGreater(r['id']['multi_fire_streams'],0)
        self.assertGreater(r['ood']['multi_fire_streams'],0)
        self.assertGreater(r['ood']['total_events'],r['ood']['multi_fire_streams'])
        self.assertFalse(r['production_activation'])
        self.assertFalse(r['all_scientific_blockers_closed'])
        data=make_batch('copy',n=8,length=16,seed=17)
        self.model.zero_grad(set_to_none=True)
        logits=self.model(data['x'],data['dt'],data['count'])
        loss=(logits*data['mask']).sum()
        loss.backward()
        self.assertTrue(torch.isfinite(logits).all())
        self.assertIsNotNone(self.model.log_decay.grad)
        self.assertIsNotNone(self.model.event.weight.grad)
        self.assertGreater(self.model.event.weight.grad.abs().sum().item(),0.)

    def test_causal_copy_and_four_key_mqar_labels_and_irregular_clocks(self):
        for task in ('copy','mqar4'):
            for length in (16,32):
                x,y,mask,dt,times=example(task,length=length,seed=904+length)
                self.assertTrue(all(s>0 for s in dt))
                self.assertTrue(all(a<b for a,b in zip(times,times[1:])))
                if task=='copy':
                    self.assertEqual(mask.sum(),1.)
                    idx=np.flatnonzero(x[:-1,5]==1.)
                    self.assertEqual(len(idx),1)
                    self.assertEqual(y[-1],float(x[int(idx[0]),4]>0))
                else:
                    self.assertEqual(mask.sum(),4.)
                    for j in range(length-4,length):
                        key=int(np.argmax(x[j,:4]))
                        writes=np.flatnonzero((x[:length-4,key]==1)&(x[:length-4,5]==1))
                        self.assertGreater(len(writes),0)
                        self.assertEqual(y[j],float(x[int(writes[-1]),4]>0))

    def test_complete_vs_partitioned_every_step_bitwise(self):
        x,_,_,_,times=example('mqar4',length=32,seed=141)
        p=default_spec()
        a=ContentSession(self.model,p,seed=501,stream_id='same')
        b=ContentSession(self.model,p,seed=501,stream_id='same')
        events_a=[]
        for i in range(len(times)):
            ev,pred=a.ingest(times[i],x[i]);events_a.extend(ev)
            if i==14:
                snap=b.checkpoint() if b.processed else None
        for i in range(15):b.ingest(times[i],x[i])
        raw=b.checkpoint()
        b=ContentSession.from_checkpoint(self.model,raw,expected_spec=p,expected_stream_id='same')
        events_b=[]
        for i in range(15,len(times)):
            ev,pred=b.ingest(times[i],x[i]);events_b.extend(ev)
        self.assertGreater(len(events_a),1)
        self.assertEqual(a.checkpoint(),b.checkpoint())
        self.assertEqual(a.spikes.checkpoint(),b.spikes.checkpoint())

    def test_transactional_rejection_and_digest_model_binding(self):
        p=default_spec();x,_,_,_,times=example('copy',length=16,seed=21)
        s=ContentSession(self.model,p,seed=1,stream_id='reject')
        before=s.checkpoint()
        with self.assertRaises(UnresolvedContent):
            s.ingest(times[-1],x[0],max_events=1)
        self.assertEqual(s.checkpoint(),before)
        for bad_time in (0.,-1.,float('nan'),float('inf')):
            with self.assertRaises(UnresolvedContent):s.ingest(bad_time,x[0])
        with self.assertRaises(UnresolvedContent):s.ingest(times[0],np.full(7,float('nan')))
        self.assertEqual(s.checkpoint(),before)
        s.ingest(times[0],x[0]); raw=s.checkpoint()
        with self.assertRaises(UnresolvedContent):s.ingest(times[0],x[0])
        broken=json.loads(raw);broken['content'][0]+=1
        with self.assertRaises(UnresolvedContent):
            ContentSession.from_checkpoint(self.model,json.dumps(broken))
        other=TrainableEventContent(hidden=32).eval()
        with self.assertRaises(UnresolvedContent):
            ContentSession.from_checkpoint(other,raw)
        with self.assertRaises(UnresolvedContent):
            ContentSession.from_checkpoint(self.model,raw,expected_stream_id='other')

    def test_trained_model_real_new_process_restore_bitwise(self):
        x,_,_,_,times=example('copy',length=16,seed=219)
        p=default_spec()
        full=ContentSession(self.model,p,seed=84,stream_id='child')
        for i in range(16):full.ingest(times[i],x[i])
        split=ContentSession(self.model,p,seed=84,stream_id='child')
        for i in range(7):split.ingest(times[i],x[i])
        snap=split.checkpoint()
        with tempfile.TemporaryDirectory() as d:
            weights=Path(d)/'weights.pt'
            torch.save(self.model.state_dict(),weights)
            code=('import sys,json,torch; '
                  'from experiments.hcsn_p2_memory.event_content import TrainableEventContent,ContentSession,default_spec; '
                  'torch.set_num_threads(1); '
                  'data=json.loads(sys.stdin.read()); '
                  'm=TrainableEventContent(32).eval(); '
                  'm.load_state_dict(torch.load(data["weights"],map_location="cpu",weights_only=True)); '
                  's=ContentSession.from_checkpoint(m,data["snapshot"],expected_spec=default_spec(),expected_stream_id="child"); '
                  '[s.ingest(float(t),obs) for t,obs in data["suffix"]]; '
                  'print(s.checkpoint())')
            pairs=[(times[i],x[i].tolist()) for i in range(7,16)]
            proc=subprocess.run([sys.executable,'-c',code],
                input=json.dumps({'weights':str(weights),'snapshot':snap,'suffix':pairs}),
                text=True,capture_output=True,check=True,timeout=40)
            self.assertEqual(proc.stdout.strip(),full.checkpoint())

    def test_invalid_type_and_model_training_guard(self):
        bad=TrainableEventContent(hidden=32)
        with self.assertRaises(UnresolvedContent):
            ContentSession(bad,default_spec(),seed=1,stream_id='bad')
        with self.assertRaises(UnresolvedContent):TrainableEventContent(hidden=1)
        with self.assertRaises(UnresolvedContent):example('bad',length=12,seed=1)

if __name__=='__main__':unittest.main()
