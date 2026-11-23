"""Recompute one block of waiting on the registered TRAIN/DEV sensor panels."""
import argparse
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np

BINS = (.5, .6, .75, .9, 1.00000001)
POSTURES = ("sitting", "standing", "lying")

def mean_person(gain, group):
    return float(np.mean([gain[group == g].mean() for g in np.unique(group)]))

def run(folder):
    manifest = json.loads((folder/"archive_parts.json").read_text())
    parts = []
    for name, entry in sorted(manifest["parts"].items()):
        raw=(folder/name).read_bytes()
        assert len(raw)==entry["size"] and hashlib.sha256(raw).hexdigest()==entry["sha256"]
        parts.append(raw)
    archive=b"".join(parts)
    assert hashlib.sha256(archive).hexdigest()==manifest["zip_sha256"]
    sealed = json.loads((folder/"fit_seal.json").read_text())
    result={}
    with ZipFile(io.BytesIO(archive)) as z:
        def original(name):
            raw=z.read(name)
            assert hashlib.sha256(raw).hexdigest()==sealed["files"][name]
            return raw
        legacy=json.loads(original("development.json"))
        for split in ("train","dev"):
            with np.load(io.BytesIO(original(split+".npz")),allow_pickle=False) as data:
                scores=data["scores"]
                confidence=scores[:,0].max(1)
                people=data["group"]
                gold=data["target"]
                origin=data["posture"]
                hit=scores.argmax(-1)==gold[:,None]
                utility=(hit+2)*np.exp(-.2*.48*np.arange(6))-2
                change=utility[:,1]-utility[:,0]
                oracle=utility.max(1)-utility[:,0]
                assert np.allclose(utility[:,0],legacy[split]["fixed_exits"]["0-0"]["u"],atol=1.e-14,rtol=0)
                assert np.allclose(utility[:,1],legacy[split]["fixed_exits"]["0-1"]["u"],atol=1.e-14,rtol=0)
                assert np.isclose(mean_person(oracle,people),legacy[split]["opportunity"]["free_wait_over_immediate"])
                cells=[]
                for posture,label in enumerate(POSTURES):
                    for lo,hi in zip(BINS,BINS[1:]):
                        within=(origin==posture)&(lo<=confidence)&(confidence<hi)
                        ids=np.unique(people[within])
                        group_gain=np.array([change[within & (people==g)].mean() for g in ids])
                        decisions=np.where(within,change,0.)
                        cells.append({"initial_posture":label,"confidence":[lo,min(hi,1.)],"events":int(within.sum()),
                            "participants":len(ids),"rescues":int(sum(within&~hit[:,0]&hit[:,1])),
                            "harms":int(sum(within&hit[:,0]&~hit[:,1])),
                            "mean_person_net_change_inside_cell":float(group_gain.mean()) if len(ids) else None,
                            "participants_winning_inside_cell":int(sum(group_gain>0)),
                            "mean_person_net_change_entire_panel":mean_person(decisions,people),
                            "worst_person_change_entire_panel":min(float(decisions[people==g].mean()) for g in np.unique(people)),
                            "mean_person_hindsight_wait_opportunity_inside_cell":mean_person(oracle[within],people[within]) if len(ids) else None})
                assert sum(c["events"] for c in cells)==len(gold)
                result[split]={"events":len(gold),"participants":len(np.unique(people)),"cells":cells}
    return {"scope":"Retrospective TRAIN and DEV only. Fixed single 0.48 s unpaid wait versus stopping at onset; original annotated onset and starting posture.", "original_archive_sha256":manifest["zip_sha256"],"panels":result}

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wait_evidence",type=Path)
    print(json.dumps(run(parser.parse_args().wait_evidence),indent=2,sort_keys=True))
