"""P2 event-timestamp ordering, gradient, rollback and cold-restoration tests."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import torch

from .event_content import TrainableEventContent, default_spec, example
from .timed_fire_content import (TimedFireSession,timed_content_step,
                                 UnresolvedContent,INITIAL_EVENT_DIGEST)


class TimedFIRETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        torch.manual_seed(20261031)
        cls.model=TrainableEventContent(32).eval()

    def test_actual_event_timestamp_changes_state_at_fixed_event_count(self):
        obs=torch.zeros(1,7)
        old=torch.ones(1,32)*.7
        # Same events, same total interval, different precise event timing.
        a,_=timed_content_step(self.model,obs,0.,1.6,(.02,.5,1.2),old)
        b,_=timed_content_step(self.model,obs,0.,1.6,(.2,.8,1.4),old)
        self.assertGreater(float((a-b).detach().abs().max()),1e-6)
        # The old observation-count-only path cannot distinguish these trains.
        x,_=self.model.step(obs,torch.tensor([[1.6]]),torch.tensor([[3.]]),old)
        y,_=self.model.step(obs,torch.tensor([[1.6]]),torch.tensor([[3.]]),old)
        self.assertTrue(torch.equal(x,y))

    def test_event_gradients_and_physical_time_decay(self):
        torch.manual_seed(33)
        model=TrainableEventContent(32)
        model.zero_grad(set_to_none=True)
        state,logit=timed_content_step(model,torch.randn(1,7)*.1,
                                      0.,1.6,(0.,.21,.83,1.2),torch.ones(1,32)*.1)
        logit.sum().backward()
        self.assertTrue(torch.isfinite(state).all())
        self.assertIsNotNone(model.event.weight.grad)
        self.assertGreater(float(model.event.weight.grad.abs().sum()),1e-7)
        self.assertGreater(abs(float(model.log_decay.grad)),1e-7)

    def test_partition_causal_prefix_and_same_process_checkpoint(self):
        x,_,_,_,times=example('mqar4',length=32,seed=131)
        p=default_spec()
        full=TimedFireSession(self.model,p,seed=508,stream_id='timed-prefix')
        split=TimedFireSession(self.model,p,seed=508,stream_id='timed-prefix')
        for i in range(len(times)):
            full.ingest(times[i],x[i])
            if i<17: split.ingest(times[i],x[i])
        snap=split.checkpoint()
        split=TimedFireSession.from_checkpoint(self.model,snap,
                  expected_spec=p,expected_stream_id='timed-prefix')
        for i in range(17,len(times)):split.ingest(times[i],x[i])
        self.assertGreater(full.event_count,1)
        self.assertEqual(full.event_count,full.spikes.events)
        self.assertEqual(full.checkpoint(),split.checkpoint())
        self.assertNotEqual(full.event_digest,INITIAL_EVENT_DIGEST)

    def test_real_new_python_process_model_and_event_recovery(self):
        x,_,_,_,times=example('copy',length=16,seed=337)
        p=default_spec()
        full=TimedFireSession(self.model,p,seed=777,stream_id='timed-child')
        split=TimedFireSession(self.model,p,seed=777,stream_id='timed-child')
        for i in range(16):
            full.ingest(times[i],x[i])
            if i<7:split.ingest(times[i],x[i])
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/'weights.pt'
            torch.save(self.model.state_dict(),file)
            script=('import json,sys,torch; '
                    'from experiments.hcsn_p2_memory.event_content import TrainableEventContent,default_spec; '
                    'from experiments.hcsn_p2_memory.timed_fire_content import TimedFireSession; '
                    'torch.set_num_threads(1); '
                    'req=json.loads(sys.stdin.read()); '
                    'model=TrainableEventContent(32).eval(); '
                    'model.load_state_dict(torch.load(req["weights"],map_location="cpu",weights_only=True)); '
                    'owner=TimedFireSession.from_checkpoint(model,req["checkpoint"],'
                    'expected_spec=default_spec(),expected_stream_id="timed-child"); '
                    '[owner.ingest(t,x) for t,x in req["suffix"]]; '
                    'print(owner.checkpoint())')
            job=dict(weights=str(file),checkpoint=split.checkpoint(),
                     suffix=[(float(times[i]),x[i].tolist()) for i in range(7,16)])
            proc=subprocess.run([sys.executable,'-c',script],input=json.dumps(job),
                        text=True,capture_output=True,timeout=45,check=True)
            self.assertEqual(proc.stdout.strip(),full.checkpoint())

    def test_invalid_event_budget_time_and_checkpoint_do_not_mutate(self):
        x,_,_,_,times=example('copy',length=16,seed=909)
        s=TimedFireSession(self.model,default_spec(),seed=1,stream_id='reject-timed')
        before=s.checkpoint()
        with self.assertRaises(UnresolvedContent):s.ingest(times[-1],x[0],max_events=1)
        self.assertEqual(s.checkpoint(),before)
        for timestamp in (0.,-1.,float('nan'),float('inf')):
            with self.assertRaises(UnresolvedContent):s.ingest(timestamp,x[0])
        with self.assertRaises(UnresolvedContent):s.ingest(times[0],np.ones(7)*float('nan'))
        self.assertEqual(s.checkpoint(),before)
        s.ingest(times[0],x[0])
        raw=s.checkpoint()
        with self.assertRaises(UnresolvedContent):s.ingest(times[0],x[0])
        bad=json.loads(raw);bad['event_count']+=1
        with self.assertRaises(UnresolvedContent):TimedFireSession.from_checkpoint(self.model,json.dumps(bad))
        bad=json.loads(raw);bad['event_digest']='0'*64
        with self.assertRaises(UnresolvedContent):TimedFireSession.from_checkpoint(self.model,json.dumps(bad))
        with self.assertRaises(UnresolvedContent):TimedFireSession.from_checkpoint(self.model,raw,expected_stream_id='not-this-stream')
        wrong=TrainableEventContent(32).eval()
        with self.assertRaises(UnresolvedContent):TimedFireSession.from_checkpoint(wrong,raw)

    def test_invalid_manual_event_order_or_horizon_refused(self):
        obs=torch.zeros(1,7);h=torch.zeros(1,32)
        for events in ((1.4,1.2),(-.1,),(.4,1.8),(.2,.2),(float('nan'),)):
            with self.subTest(events=events),self.assertRaises(UnresolvedContent):
                timed_content_step(self.model,obs,0.,1.6,events,h)


if __name__=='__main__': unittest.main()
