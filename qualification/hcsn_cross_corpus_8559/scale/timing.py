"""Observe conservative bounds for the earliest worker lifetimes from filesystem event times."""
import argparse
import json
from pathlib import Path

from confirmation import ARMS,SEEDS,read,write


def mtime(path):
    return path.stat().st_mtime_ns/1e9


def run(w):
    order=[f'{ARMS[(i+j)%4]}-{seed}' for j in range(4) for i,seed in enumerate(SEEDS)]
    out={};previous=w/'data/data.json'
    for i,key in enumerate(order):
        base=w/'fits'/key
        if not (base/'progress.json').exists():break
        rec=read(base/'progress.json')
        if 30 not in rec['clock_done']:break
        event=next(e for e in rec['events'] if 30 in e['budgets'])
        end=base/f"s{event['step']}.pt"
        if 'process_startup_to_event_plus_previous_calls_s' not in event:
            if i+1==len(order) or not (w/'fits'/order[i+1]/'fit.lock').exists():break
            lower=mtime(end)-mtime(base/'fit.lock')
            upper=mtime(w/'fits'/order[i+1]/'fit.lock')-mtime(previous)
            assert 0<lower<=upper
            out[key]={'observed_lower_s':lower,'observed_upper_s':upper}
        previous=end
    write(w/'early-clock-brackets.json',out)
    print(json.dumps(out),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('work',type=Path);run(p.parse_args().work)
