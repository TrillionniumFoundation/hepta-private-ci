"""Explicit unpublished two-use worker wiring smoke; never a formal result."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent


def run():
    from . import campaign
    proto=dict(fits=[151101,151103,151107,151109,151113,151117,151119,151123],domains=["iid","ood"],
        world_theta=[.3,.018],uses_per_fit_domain=2,namespace=190811,resource_sample_every=1,raw_chunk_uses=1,
        compile_check_paths=[str((HERE/name).relative_to(campaign.ROOT)) for name in ("bounded.py","planner.py","execution.py","campaign.py")])
    campaign.OUT=HERE/"smoke_01"
    campaign.verify=lambda:(proto,dict(role="unpublished-development-smoke",readback_verified=False))
    for fit,domain in ((151101,"iid"),(151103,"ood")):
        campaign.worker(fit,domain)
    summaries=[json.loads(p.read_text()) for p in campaign.OUT.glob("summary*.json")]
    result=dict(role="development-only,2usesnot1000",actual_worlds=4,actual_executions=24,
        exact=all(x["exact_gate"] for x in summaries),
        source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob("*.py")})
    campaign.save(campaign.OUT/"SUMMARY.json",result)
    if not result["exact"]:raise SystemExit(1)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--worker",action="store_true");args=parser.parse_args()
    if args.worker:run()
    else:
        wall=time.perf_counter();child=subprocess.Popen([sys.executable,"-m",__spec__.name,"--worker"])
        _,status,usage=os.wait4(child.pid,0);child.returncode=os.waitstatus_to_exitcode(status)
        data=dict(exit_code=child.returncode,child_cpu_seconds=usage.ru_utime+usage.ru_stime,
            wall_seconds=time.perf_counter()-wall,scope="Fullunpublishedsmokechildimports,two-useworkerwiring,allarms/serialization/output; notformalreuse")
        with (HERE/"smoke_01/PROCESS_RECEIPT.json").open("x") as stream:json.dump(data,stream,sort_keys=True,indent=2)
        raise SystemExit(child.returncode)
