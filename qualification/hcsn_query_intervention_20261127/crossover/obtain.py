"""Cohort-exclusive acquisition uses the same version-aware NWB reader."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'voltage'))
from acquire_voltage import extract, roster, dump

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for flag in ('metadata','work','out'):parser.add_argument('--'+flag,type=Path,required=True)
    a=parser.parse_args();a.work.mkdir(exist_ok=True,parents=True);a.out.mkdir(exist_ok=True,parents=True)
    rows,order,pages=roster(a.metadata);past=set(json.loads((ROOT/'prior48.json').read_text()))
    order=[s for s in order if s not in past];dump(a.out/'metadata_pages.json',pages)
    eligible=[];attempts=[];idx=0
    with ThreadPoolExecutor(max_workers=4) as pool:
        while len(eligible)<48 and idx<160:
            batch=order[idx:idx+min(4,48-len(eligible))];idx+=len(batch)
            jobs=[pool.submit(extract,s,rows[s],a.work,a.out) for s in batch]
            for s,j in zip(batch,jobs):
                record=j.result();attempts.append(record)
                if record['admitted']:eligible.append(s)
                dump(a.out/'roster.json',dict(cells=eligible,attempts=attempts,candidate_count=len(order)))
                print(len(eligible),s,record.get('nwb_bytes'),record.get('error',''),flush=True)
    assert len(eligible)==48
