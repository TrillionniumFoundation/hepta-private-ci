"""Measured Linux wait4 descendant inclusion, before formal worker accounting."""

import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent


def burn(seconds):
    start=time.process_time();value=1
    while time.process_time()-start<seconds:value=(value*17+3)%1_000_003


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--nested",action="store_true");parser.add_argument("--leaf",action="store_true");args=parser.parse_args()
    if args.leaf:burn(.05);return
    path=HERE/"development_03/METER_NESTED.json"
    if args.nested:
        burn(.03);child=subprocess.Popen([sys.executable,"-m",__spec__.name,"--leaf"])
        _,status,usage=os.wait4(child.pid,0);child.returncode=os.waitstatus_to_exitcode(status)
        own=resource.getrusage(resource.RUSAGE_SELF)
        with path.open("x") as stream:json.dump(dict(own_cpu=own.ru_utime+own.ru_stime,leaf_cpu=usage.ru_utime+usage.ru_stime,exit_code=child.returncode),stream)
        return
    child=subprocess.Popen([sys.executable,"-m",__spec__.name,"--nested"])
    _,status,usage=os.wait4(child.pid,0);child.returncode=os.waitstatus_to_exitcode(status)
    nested=json.loads(path.read_text());inclusive=usage.ru_utime+usage.ru_stime
    own=resource.getrusage(resource.RUSAGE_SELF)
    result=dict(nested=nested,inclusive_nested_wait4_cpu=inclusive,outer_own_cpu=own.ru_utime+own.ru_stime,
        complete_known_cpu_lower_bound=inclusive+own.ru_utime+own.ru_stime,
        descendant_inclusion_verified=inclusive>=nested["own_cpu"]+nested["leaf_cpu"]-.002,
        exit_code=child.returncode,scope="Developmentmeterfixture: inclusivechildalreadyincludeswaiteddescendant; donotadditsleafCPUagain. OuterCPUthroughreceiptconstruction, write/exitnotincluded.")
    with (HERE/"development_03/METER_SANITY.json").open("x") as stream:json.dump(result,stream,sort_keys=True,indent=2)
    if not result["descendant_inclusion_verified"] or child.returncode:raise SystemExit(1)
    print(json.dumps(result))


if __name__=="__main__":main()
