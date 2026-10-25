"""Bind every data role to its prospective registration and complete census."""

import json
from pathlib import Path

import numpy as np

from ...abc_recovery.training_run import file_sha
from .collect import segments
from .forecast import INPUT_DIM, Q


def check_sources(protocol):
    spec=json.loads(protocol.read_text())
    for name,digest in spec["source_pins"].items():
        if file_sha(Path(__file__).parent/name)!=digest:
            raise ValueError("Frozen implementation changed: "+name)
    return spec


def verified_data(directory, protocol, role):
    spec=check_sources(protocol)
    access=json.loads((directory/"access-registration.json").read_text())
    if access["role"]!=role:
        raise ValueError("Collected role does not match requested analysis role")
    expected_protocol=(spec["development_collection_protocol_sha256"] if role=="development" else file_sha(protocol))
    expected_allocation=(spec["development_collection_allocation_sha256"] if role=="development" else spec["allocation_sha256"])
    if access["protocol_sha256"]!=expected_protocol or access["allocation_sha256"]!=expected_allocation:
        raise ValueError("Collected protocol/allocation binding mismatch")
    expected=[list(row) for row in segments(role,spec)]
    if access["segments"]!=expected:
        raise ValueError("Collected source ranges differ from frozen census")
    cost=json.loads((directory/"cost.json").read_text())
    if (cost["role"]!=role or cost["data_sha256"]!=file_sha(directory/"data.npz")
            or cost["rows_sha256"]!=file_sha(directory/"rows.jsonl.gz")):
        raise ValueError("Collected artifact identity changed")
    with np.load(directory/"data.npz",allow_pickle=False) as source:
        data={key:source[key] for key in source.files}
    assignments={}
    for group,_,view,offset,count in expected:
        for pair in range(offset,offset+count):
            if pair in assignments:raise ValueError("Overlapping collected source ranges")
            assignments[pair]=(group,view=="both_missing")
    n=2*len(assignments)
    shapes={"x_q24":(n,INPUT_DIM),"past_q24":(n,32),"future_q24":(n,32),"future_tokens":(n,8),
            **{name:(n,) for name in ("pair","action","group","ood","y")}}
    if set(data)!=set(shapes) or any(data[key].shape!=shape for key,shape in shapes.items()):
        raise ValueError("Collected array schema/census mismatch")
    actual=set()
    for pair,action,group,ood in zip(data["pair"],data["action"],data["group"],data["ood"]):
        pair,action=int(pair),int(action)
        if (pair,action) in actual or action not in (0,1) or assignments.get(pair)!=(group,bool(ood)):
            raise ValueError("Duplicate, missing or mislabeled source/action")
        actual.add((pair,action))
    if actual!={(pair,action) for pair in assignments for action in (0,1)}:
        raise ValueError("Incomplete actual source/action census")
    if not np.isin(data["y"],(0,1)).all() or not np.isin(data["future_tokens"],np.arange(24)).all():
        raise ValueError("Invalid observed outcomes or token domain")
    for name,bound in (("x_q24",8*Q),("past_q24",Q),("future_q24",Q)):
        if not np.issubdtype(data[name].dtype,np.integer) or (np.abs(data[name])>bound).any():
            raise ValueError("Observed feature bound violation")
    if cost["source_pairs"]!=len(assignments) or cost["future_rows"]!=n:
        raise ValueError("Collected cost census mismatch")
    return data
