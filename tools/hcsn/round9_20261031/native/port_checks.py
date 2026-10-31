"""Separate preregistered packet-length and irregular-dt FullHX parity probes."""
import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np

from qualify import Client, PARAMETERS, ZERO, logits, save, sha


def main(args):
    args.out.mkdir(parents=True, exist_ok=False)
    protocol = dict(lengths=[2,7,32,128], symbols=[0,1], random_seed=931031,
                    dt_log_range=[-3.,3.], maximum_logit_error=5e-5,
                    source_sha256=sha(Path(__file__)), binary_sha256=sha(args.binary))
    save(args.out/"PROTOCOL.json",protocol)
    source=args.hcsn_source/"task_value_factorial_20261030/task.py"
    spec=importlib.util.spec_from_file_location("content_port_reference",source)
    task=importlib.util.module_from_spec(spec); spec.loader.exec_module(task)
    adapter=task.ContentAdapter()
    rng=np.random.default_rng(protocol["random_seed"])
    root=args.out/"owner";root.mkdir()
    model=root/"model.json"
    save(model,dict(parameters=PARAMETERS,family="distribution",seed_hex="00000000000000ad",
        content_model=str(args.weights),content_model_sha256=sha(args.weights),subdivisions=1))
    client=Client(args.binary,model,root,ZERO)
    pair=ZERO;rows=[]
    try:
        for length in protocol["lengths"]:
            for symbol in protocol["symbols"]:
                packet=task.packet(symbol,int(rng.integers(0,2**63-1)),length)
                packet["dt"]=np.exp(rng.uniform(-3.,3.,length)).tolist()
                path=args.out/f"packet-{length}-{symbol}.json";save(path,packet)
                reference=adapter.read(path)
                response=client.step(dict(operation="interval",pair_before=pair,driver=.3,
                    duration_micros=2_000_007,horizon_micros=750_000,reset=False,
                    content=dict(path=str(path),sha256=sha(path))))
                if not response["ok"]:raise RuntimeError(response)
                receipt=response["receipt"];pair=receipt["pair_after"]
                output=receipt["content"]["last"]
                rows.append(dict(length=length,symbol=symbol,native=output,reference=reference,
                    observations_equal=output["observation"]==reference["observation"],
                    maximum_logit_error=max(abs(a-b) for a,b in zip(logits(output),reference["logits"]))))
    finally:
        client.close()
    passed=all(r["observations_equal"] and r["maximum_logit_error"]<5e-5 for r in rows)
    save(args.out/"REPORT.json",dict(protocol=protocol,rows=rows,passed=passed))
    print(json.dumps(dict(passed=passed,maximum_logit_error=max(r["maximum_logit_error"] for r in rows))))
    return passed


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("binary","weights","hcsn-source","out"):
        parser.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args()
    args.binary=args.binary.resolve();args.weights=args.weights.resolve();args.out=args.out.resolve()
    raise SystemExit(0 if main(args) else 1)
