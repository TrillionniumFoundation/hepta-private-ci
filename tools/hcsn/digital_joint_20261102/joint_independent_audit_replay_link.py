"""Exact deterministic semantics link from main value arms to raw/slim replay."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time


def read(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def main():
    p = argparse.ArgumentParser(); p.add_argument("--confirmation",type=Path,required=True)
    p.add_argument("--benchmark",type=Path,required=True); p.add_argument("--out",type=Path,required=True)
    a = p.parse_args(); cpu,wall = time.process_time(),time.perf_counter(); pairs,inputs = 0,{}
    def load(path):
        inputs[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        return read(path)
    def semantic(e):
        return dict(world=e["world"],actions=[d["action"] for d in e["decisions"]],
                    scores=[d["scores"] for d in e["decisions"]],final_state=e["final_state"],utility=e["outcome"]["utility"])
    for fit in (11,23,37,53,71):
        for split in ("iid","ood"):
            for family in ("renewal","full_markov","affine_markov","gru"):
                original = load(a.confirmation/f"fit_{fit}_{split}_{family}_value.json.gz")["episodes"]
                for fmt in ("raw","slim"):
                    replay = load(a.benchmark/f"fit_{fit}_{split}_{fmt}_{family}.json.gz")["episodes"]
                    assert len(original) == len(replay) == 40
                    for left,right in zip(original,replay):
                        assert json.dumps(semantic(left),sort_keys=True,allow_nan=False) == json.dumps(semantic(right),sort_keys=True,allow_nan=False)
                        pairs += 1
    assert pairs == 3200
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in inputs.items())
    result = dict(passed=True,exact_links=pairs,original_value_episodes=1600,raw_slim_replays=3200,
        input_sha256=inputs,audit_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        audit_cpu_window_seconds=time.process_time()-cpu,audit_wall_window_seconds=time.perf_counter()-wall,
        scope="Actions/scores/final state/utility exact; excludes teacher diagnostics/timings. Reused worlds are not new independent efficacy observations; cost window excludes imports/final write/exit.")
    with a.out.open("x") as stream:
        json.dump(result,stream,indent=2,sort_keys=True); stream.write("\n")
    print(json.dumps({k:v for k,v in result.items() if k != "input_sha256"},sort_keys=True))


if __name__ == "__main__": main()
