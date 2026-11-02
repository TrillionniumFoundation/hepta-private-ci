"""Full child-family process receipt; scientific timings are nested diagnostics."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--receipt',type=Path,required=True)
    parser.add_argument('--stdout',type=Path,required=True)
    parser.add_argument('--stderr',type=Path,required=True)
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    command=args.command[1:] if args.command[:1]==['--'] else args.command
    if not command or args.receipt.exists():raise ValueError('Fresh receipt and command required')
    start=time.monotonic()
    with args.stdout.open('xb') as out,args.stderr.open('xb') as err:
        child=subprocess.Popen(command,stdout=out,stderr=err)
        pid,status,usage=os.wait4(child.pid,0)
        child.returncode=os.waitstatus_to_exitcode(status)
    receipt=dict(command=command,pid=pid,exit_code=child.returncode,
                 user_cpu_seconds=usage.ru_utime,system_cpu_seconds=usage.ru_stime,
                 full_child_family_cpu_seconds=usage.ru_utime+usage.ru_stime,
                 wall_seconds=time.monotonic()-start,max_single_process_rss_kib=usage.ru_maxrss,
                 cost_scope='Full invoked child process and waited descendants, including interpreter imports/build/native calls/final serialization. Excludes this small wrapper and transport; nested inner timing must not be added.',
                 family_simultaneous_peak_rss_kib=None)
    print(json.dumps(receipt,sort_keys=True),flush=True)
    with args.receipt.open('x') as stream:json.dump(receipt,stream,indent=2,sort_keys=True);stream.write('\n')
    raise SystemExit(child.returncode)


if __name__=='__main__':main()
