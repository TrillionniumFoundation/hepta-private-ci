"""Cold-load one arm, read the public requests, return actions and network evidence."""
import argparse
import os
from pathlib import Path
import time

import cell


def net():
    stats={}
    for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
        interface, counters = line.split(":")
        cols = counters.split()
        stats[interface.strip()] = [int(cols[0]),int(cols[8])]
    if stats != {"lo":[0,0]}:
        raise RuntimeError("Research worker needs a fresh network namespace")
    return stats


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("arm", choices=cell.ARMS)
    parser.add_argument("model",type=Path)
    parser.add_argument("prompts",type=Path)
    parser.add_argument("commitment",type=Path)
    parser.add_argument("out",type=Path)
    a=parser.parse_args()
    before=net()
    commitment=cell.read(a.commitment)
    assert cell.file_sha(a.model)==commitment["model"]
    assert cell.file_sha(a.prompts)==commitment["prompts"]
    start=time.perf_counter_ns()
    model=cell.read(a.model)
    assert model["implementation_sha256"]==cell.file_sha(Path(cell.__file__))
    if a.arm in ("rule","no_donor"):
        model=None
    predictions={r["id"]:cell.propose(r["query"],model,a.arm) for r in cell.read(a.prompts)}
    elapsed=time.perf_counter_ns()-start
    cell.dump_new(a.out,dict(arm=a.arm,model=commitment["model"],prompts=commitment["prompts"],
                   pid=os.getpid(),net_before=before,net_after=net(),load_and_predict_ns=elapsed,
                   predictions=predictions))
