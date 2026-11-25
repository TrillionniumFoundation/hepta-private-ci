"""Constructed-input contracts; never generate formal train/dev/test sources."""

from dataclasses import replace
import io
import unittest

import torch

from qualification.hcsn_smallnet_20261124.model import ModelConfig
from .boundary_fix import BoundaryControlHCSN, delivered_boundary, pack_state, unpack_state
from .communication import ControlSpec, control_step, initial_control
from .fast_kernel import FastSignedHCSN


class BoundaryFixTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1);torch.manual_seed(87102)
        self.c=ModelConfig(neurons=8,precision="mixed",backend="uniformized",message_mode="full")

    def model(self,channel="boundary_only",control="accumulate",message="centered"):
        return BoundaryControlHCSN(self.c,channel=channel,control_mode=control,boundary_mode=message)

    def test_raw_signed_matches_qualified_core_and_complete_gradients(self):
        base=FastSignedHCSN(replace(self.c,message_mode="flow"),scripted=True)
        model=self.model("signed_only","raw","raw")
        saved={k:v for k,v in base.state_dict().items()};saved["synaptic_mask"]=model.synaptic_mask.clone()
        saved["boundary_reference"]=model.boundary_reference.clone();model.load_state_dict(saved)
        x=torch.randn(12,2,6)*.3;out=[]
        for m in (base,model):
            inp=x.clone().requires_grad_();logits,features,state=m(inp,return_features=True)
            (logits.square().mean()+.001*features.square().mean()).backward()
            out.append((logits,features,state,{k:None if p.grad is None else p.grad.clone() for k,p in m.named_parameters()},inp.grad))
        for i in (0,1,4):torch.testing.assert_close(out[0][i],out[1][i],atol=0,rtol=0)
        for key in ("density","boundary","drift","cost","message"):
            torch.testing.assert_close(getattr(out[0][2],key),getattr(out[1][2],key),atol=0,rtol=0)
        for key,value in out[0][3].items():
            if value is None:self.assertIsNone(out[1][3][key])
            else:torch.testing.assert_close(value,out[1][3][key],atol=0,rtol=0)

    def test_nominal_transform_only_old_message_no_physical_change_without_edges(self):
        m=torch.randn(2,3,8,dtype=torch.float64);b=torch.linspace(-.5,.5,8,dtype=torch.float64)
        self.assertIs(delivered_boundary(m,b,"centered",0),m)
        transformed=delivered_boundary(m,b,"centered",1)
        torch.testing.assert_close(transformed[:,0],m[:,0]-b,atol=0,rtol=0)
        torch.testing.assert_close(transformed[:,1:],m[:,1:],atol=0,rtol=0)
        raw=self.model(message="raw");center=self.model(message="centered");center.load_state_dict(raw.state_dict())
        with torch.no_grad():raw.recurrent.weight.zero_();center.recurrent.weight.zero_()
        x=torch.randn(8,2,6)*.2
        a,fa,sa=raw(x,return_features=True);b,fb,sb=center(x,return_features=True)
        torch.testing.assert_close(a,b,atol=0,rtol=0);torch.testing.assert_close(fa,fb,atol=0,rtol=0)
        for key in ("density","boundary","drift","cost","message"):
            torch.testing.assert_close(getattr(sa,key),getattr(sb,key),atol=0,rtol=0)

    def test_accumulate_consumes_once_writer_raw_and_odd_cut_restores(self):
        frame=torch.zeros(2,6);s=initial_control(frame,ControlSpec("accumulate",2));emitted=[]
        for step in range(5):
            f=frame.clone();f[:,1]=step+1;c,s,due=control_step(f,s)
            if due:emitted.append(float(c[0,1]))
        self.assertEqual(emitted,[1.,5.,9.]);self.assertEqual(float(s.pending.abs().sum()),0.)
        model=self.model();x=torch.zeros(12,2,6);x[3,:,1]=.6;x[3,:,3]=1
        seen=[];hook=model.input_mark.register_forward_pre_hook(lambda module,args:seen.append(args[0].detach().clone()))
        whole,_,last=model(x,return_features=True);hook.remove()
        self.assertTrue(torch.equal(torch.stack(seen),x))
        first,_,cut=model(x[:4],return_features=True);self.assertEqual(float(cut.control.pending[0,1]),float(x[3,0,1]))
        archive=io.BytesIO();torch.save(pack_state(cut),archive);archive.seek(0)
        cold=unpack_state(torch.load(archive,weights_only=True));rest,_,final=model(x[4:],state=cold,return_features=True)
        torch.testing.assert_close(torch.cat((first,rest)),whole,atol=0,rtol=0)
        for key in ("density","boundary","drift","cost","message"):
            torch.testing.assert_close(getattr(final,key),getattr(last,key),atol=0,rtol=0)
        self.assertTrue(torch.equal(final.control.pending,last.control.pending))
        self.assertTrue(torch.equal(final.control.held,last.control.held));self.assertEqual(final.step,12)

    def test_odd_pulse_reaches_sender_next_slow_clock_and_bp_is_real(self):
        model=self.model();raw=self.model(control="raw");raw.load_state_dict(model.state_dict())
        with torch.no_grad():
            for m in (model,raw):
                m.input_drive.weight.zero_();m.input_drive.bias.zero_();m.input_drive.weight[:,1]=.7
                m.recurrent.weight.zero_();m.recurrent.weight[4:,:4]=.2
        x=torch.zeros(8,2,6);x[3,:,1]=.6;x[3,:,3]=1
        z=x.clone();z[3,:,1]=-.6
        for m,changed in ((model,True),(raw,False)):
            _,_,left=m(x[:5],return_features=True);_,_,right=m(z[:5],return_features=True)
            self.assertEqual(bool((left.boundary[:,:4]!=right.boundary[:,:4]).any()),changed)
        first=model(x);altered=x.clone();altered[6:,:,1]+=.8
        torch.testing.assert_close(model(altered)[:6],first[:6],atol=0,rtol=0)
        model.zero_grad(set_to_none=True)
        loss=torch.nn.functional.cross_entropy(first[-1],torch.tensor([0,1]));loss.backward()
        for p in (model.input_drive.weight,model.recurrent.weight,model.readout.weight):
            self.assertTrue(bool(torch.isfinite(p.grad).all()));self.assertGreater(float(p.grad.abs().max()),0.)
        self.assertEqual(float((model.recurrent.weight.grad*(1-model.synaptic_mask)).abs().max()),0.)
        old=model.readout.weight.detach().clone();torch.optim.SGD(model.parameters(),lr=.1).step()
        self.assertFalse(torch.equal(old,model.readout.weight))


if __name__ == "__main__":unittest.main()
