"""Executable research state contract; deliberately not the production Q24 journal."""

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from adapter import PreparedModel
from adapter import ROOT

SCHEMA = "hcsn-r13-research-distribution-checkpoint-v1"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def valid_digest(value):
    return isinstance(value,str) and len(value)==64 and all(c in "0123456789abcdef" for c in value) and value!="0"*64


def bindings():
    files=[ROOT/"runtime_adapter.py",ROOT/"adapter.py",ROOT/"evidence/build/libhcsn_prepared.so"]
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def bits(array):
    return np.asarray(array,dtype="<f8").tobytes().hex()


@dataclass(frozen=True)
class TickRequest:
    sequence: int
    dt: float
    model_identity: str
    model_version: int
    expected_checkpoint: str
    input_digest: str
    read: bool
    observation_identity: str


class ResearchDistributionRuntime:
    """Single-owner inference state; callers supply authenticated acquisition upstream.

    This research adapter checks bindings and causal READ/missing semantics, but
    it does not authenticate a real sensor nor implement production witness CAS.
    Events have a separate native exposure-checkpoint type and are not posterior
    entries. Model changes require identical grid/layout identity.
    """

    def __init__(self,q,prior,version,layout_identity,observation_identity):
        if not valid_digest(layout_identity) or not valid_digest(observation_identity):
            raise ValueError("Explicit layout and observation model digests are required")
        self.q=np.array(q,dtype=np.float64,order="C",copy=True)
        self.q.flags.writeable=False
        self._model=PreparedModel(self.q,version)
        self.posterior=self._model.propagate(np.asarray(prior,dtype=np.float64),0.)
        if self.posterior.ndim!=1:raise ValueError("One runtime owns one joint distribution")
        self.layout_identity,self.observation_identity=layout_identity,observation_identity
        self.clock,self.sequence=0.,0
        self.predecessor="0"*64
        self.last_input="0"*64
        self.source_bindings=bindings()

    def close(self):
        self._model.close()

    def state(self):
        return {"kind":"distribution","model_identity":self._model.identity,
            "model_version":self._model.version,"n":self._model.n,
            "layout_identity":self.layout_identity,"observation_identity":self.observation_identity,
            "posterior_f64_le_hex":bits(self.posterior),"clock_f64_le_hex":bits([self.clock]),
            "sequence":self.sequence,"predecessor":self.predecessor,"last_input":self.last_input}

    @property
    def checkpoint_digest(self):
        return digest({"schema":SCHEMA,"source_bindings":self.source_bindings,"state":self.state()})

    def tick(self,request,likelihood=None):
        if (type(request.sequence) is not int or request.sequence!=self.sequence+1 or request.model_identity!=self._model.identity
            or request.model_version!=self._model.version or request.expected_checkpoint!=self.checkpoint_digest
            or request.observation_identity!=self.observation_identity or not valid_digest(request.input_digest)
            or not np.isfinite(request.dt) or request.dt<0 or type(request.read) is not bool
            or request.read!=(likelihood is not None)):
            raise ValueError("Tick binding, clock, sequence or READ contract mismatch")
        clock=self.clock+float(request.dt)
        if not np.isfinite(clock):raise ValueError("Clock overflow")
        before=self.checkpoint_digest
        successor=self._model.propagate(self.posterior,request.dt)
        if request.read:successor=self._model.observe(successor,likelihood)
        self.posterior,self.clock,self.sequence=successor,clock,request.sequence
        self.predecessor,self.last_input=before,request.input_digest
        return {"checkpoint_before":before,"checkpoint_after":self.checkpoint_digest,
            "kind":"distribution","clock":self.clock,"sequence":self.sequence,
            "model_identity":self._model.identity,"model_version":self._model.version,
            "production_activation":False,"authority":"none"}

    def migrate(self,q,version,at,layout_identity,observation_identity,expected_checkpoint):
        if (layout_identity!=self.layout_identity or not valid_digest(observation_identity)
            or expected_checkpoint!=self.checkpoint_digest or not np.isfinite(at) or at<self.clock
            or version<=self._model.version):
            raise ValueError("Migration requires current checkpoint, forward time, same layout and newer model")
        candidate=PreparedModel(q,version)
        try:
            if candidate.n!=self._model.n:raise ValueError("State dimension changes require an explicit remapping")
            before=self.checkpoint_digest
            successor=self._model.propagate(self.posterior,float(at)-self.clock)
        except Exception:
            candidate.close()
            raise
        self._model.close();self._model=candidate;self.q=np.array(q,dtype=np.float64,copy=True)
        self.q.flags.writeable=False
        self.posterior,self.clock=successor,float(at)
        self.observation_identity=observation_identity
        self.sequence+=1;self.predecessor=before
        self.last_input=digest({"op":"migrate","model_identity":candidate.identity,"at":bits([at])})
        return self.checkpoint_digest

    def save(self,path):
        path=Path(path)
        body={"schema":SCHEMA,"source_bindings":self.source_bindings,"state":self.state(),
            "Q_f64_le_hex":bits(self.q),"state_digest":self.checkpoint_digest,
            "production_activation":False}
        payload=json.dumps({"body":body,"checksum":digest(body)},sort_keys=True,separators=(",", ":"))+"\n"
        temporary=path.with_suffix(path.suffix+f".tmp.{os.getpid()}")
        try:
            with temporary.open("x") as handle:
                handle.write(payload);handle.flush();os.fsync(handle.fileno())
            os.link(temporary,path)
            descriptor=os.open(str(path.parent),os.O_RDONLY)
            try:os.fsync(descriptor)
            finally:os.close(descriptor)
        finally:
            if temporary.exists():temporary.unlink()

    @classmethod
    def restore(cls,path,expected_model_identity,expected_version,expected_layout_identity,
                expected_observation_identity):
        payload=json.loads(Path(path).read_text());body=payload.get("body",{})
        if (body.get("schema")!=SCHEMA or payload.get("checksum")!=digest(body)
            or body.get("source_bindings")!=bindings()):
            raise ValueError("Unsupported/non-distribution checkpoint, source or checksum mismatch")
        state=body["state"]
        if (state["kind"]!="distribution" or state["model_identity"]!=expected_model_identity
            or state["model_version"]!=expected_version or state["layout_identity"]!=expected_layout_identity
            or state["observation_identity"]!=expected_observation_identity):
            raise ValueError("Checkpoint model/layout/observation binding mismatch")
        n=state["n"]
        q=np.frombuffer(bytes.fromhex(body["Q_f64_le_hex"]),dtype="<f8").reshape(n,n)
        posterior=np.frombuffer(bytes.fromhex(state["posterior_f64_le_hex"]),dtype="<f8").copy()
        value=cls(q,posterior,expected_version,expected_layout_identity,expected_observation_identity)
        try:
            clock=np.frombuffer(bytes.fromhex(state["clock_f64_le_hex"]),dtype="<f8")
            if (len(clock)!=1 or not np.isfinite(clock[0]) or clock[0]<0 or type(state["sequence"]) is not int
                or state["sequence"]<0 or value._model.identity!=expected_model_identity):
                raise ValueError("Invalid state clock, sequence or exact Q identity")
            value.clock=float(clock[0]);value.sequence=state["sequence"]
            value.predecessor=state["predecessor"];value.last_input=state["last_input"]
            if (value.sequence==0 and (value.predecessor!="0"*64 or value.last_input!="0"*64)
                or value.sequence>0 and (not valid_digest(value.predecessor) or not valid_digest(value.last_input))):
                raise ValueError("Invalid lineage metadata")
            if value.checkpoint_digest!=body["state_digest"]:raise ValueError("State digest mismatch")
            return value
        except Exception:
            value.close()
            raise


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("operation",choices=["init","resume"])
    parser.add_argument("input",type=Path);parser.add_argument("script",type=Path);parser.add_argument("output",type=Path)
    args=parser.parse_args();config=json.loads(args.input.read_text());script=json.loads(args.script.read_text())
    if args.operation=="init":runtime=ResearchDistributionRuntime(**config)
    else:runtime=ResearchDistributionRuntime.restore(**config)
    receipts=[]
    try:
        for command in script:
            if command["op"]=="tick":
                request=TickRequest(runtime.sequence+1,command["dt"],runtime._model.identity,
                    runtime._model.version,runtime.checkpoint_digest,command["input_digest"],
                    command["read"],runtime.observation_identity)
                receipts.append(runtime.tick(request,command.get("likelihood")))
            elif command["op"]=="migrate":
                receipts.append({"checkpoint_after":runtime.migrate(command["q"],command["version"],command["at"],
                    command["layout_identity"],command["observation_identity"],runtime.checkpoint_digest)})
            else:raise ValueError("Unknown operation")
        runtime.save(args.output)
        print(json.dumps({"pid":os.getpid(),"checkpoint_digest":runtime.checkpoint_digest,
            "clock":runtime.clock,"sequence":runtime.sequence,"model_identity":runtime._model.identity,
            "posterior":runtime.posterior.tolist(),"receipts":receipts,"production_activation":False}))
    finally:runtime.close()


if __name__=="__main__":main()
