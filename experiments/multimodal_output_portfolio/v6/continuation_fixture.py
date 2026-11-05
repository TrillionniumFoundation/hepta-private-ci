"""Retain one actual Torch/media/native engineering fixture; never efficacy data."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

import numpy as np
import torch

from .continuation_differential import compare_native
from .continuation_head import ContinuationHead
from .continuation_head_tests import ContinuationContractTests


def run(output, binary):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    case = ContinuationContractTests()
    case.setUp()
    started = time.process_time(), time.perf_counter()
    try:
        records, states = case.collect(gamma=2.)
        head = ContinuationHead.fit(case.base, records)
        checkpoint = output / "continuation.json"
        head_sha = head.save(checkpoint)
        case.base.save(output / "generator.pt")
        np.savez(output / "public_input.npz", pixels=case.observation.pixels.numpy(),
                 mask=case.observation.mask.numpy(), tokens=case.observation.text_tokens.numpy())
        expected = [head.predict(case.backend, state, case.context,
                                 cost_profile_digest=case.tariff).tolist() for state in states]
        parity = compare_native(binary, head.to_record(), [r["features"] for r in records], expected)
        shutil.copytree(case.directory.name, output / "actual_media")
        (output / "paired_records.json").write_text(json.dumps(records, indent=2, allow_nan=False))
        restore = '''import json,sys,numpy as np,torch
from pathlib import Path
from experiments.multimodal_output_portfolio.v6.conditioned import ConditionedSnapshot
from experiments.multimodal_output_portfolio.v6.continuation_head import ContinuationHead,DecisionContext,encoder_only
from experiments.multimodal_output_portfolio.v6.data import Observation
from experiments.multimodal_output_portfolio.v6.forecast import ForecastBackend,ForecastBundle,RidgeHead
torch.set_num_threads(1)
p=Path(sys.argv[1]);base=ConditionedSnapshot.load(p/'generator.pt')
with np.load(p/'public_input.npz') as d:
 observation=Observation(torch.from_numpy(d['pixels']),torch.from_numpy(d['mask']),torch.from_numpy(d['tokens']))
_,state=encoder_only(base,observation)
head=ContinuationHead.load(p/'continuation.json',expected_file_sha256=sys.argv[2])
forecast=ForecastBundle(RidgeHead(64,1),RidgeHead(64,4),torch.zeros(2),base.fingerprint,())
backend=ForecastBackend(base,forecast,'continuation-contract-fixture')
print(json.dumps(head.infer(backend,state,DecisionContext(16.,4.,0,3),cost_profile_digest=sys.argv[3])))
'''
        process = subprocess.run([sys.executable, "-c", restore, str(output.resolve()), head_sha, case.tariff],
                                 capture_output=True, text=True, check=True, timeout=30)
        restored = json.loads(process.stdout)
        original = head.infer(case.backend, states[0], case.context, cost_profile_digest=case.tariff)
        if restored != original:
            raise ValueError("Fresh-process restored inference differs")
        files = {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(output.rglob("*")) if p.is_file()}
        report = {"scope": "direct-host engineering fixture; synthetic random pixels and untrained observer",
                  "runtime": {"python": platform.python_version(), "torch": str(torch.__version__),
                              "numpy": np.__version__, "torch_cuda": torch.cuda.is_available()},
                  "fit_sources": 2, "executed_output_bundles": 10,
                  "paired_sources_are_not_independent_efficacy_evidence": True,
                  "native": parity, "fresh_process_restore_exact": True,
                  "head_sha256": head_sha, "files": files,
                  "parent_cpu_seconds": time.process_time() - started[0],
                  "wall_seconds_including_fresh_process": time.perf_counter() - started[1],
                  "decision": "no-update", "scientific_confirmation_executed": False,
                  "codex_cloud_execution": False, "production_activated": False}
        (output / "RESULT.json").write_text(json.dumps(report, indent=2, allow_nan=False))
        print(json.dumps(report, allow_nan=False))
        return report
    finally:
        case.doCleanups()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native-binary", type=Path, required=True)
    args = parser.parse_args()
    run(args.output, args.native_binary)
