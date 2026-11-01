"""Post-freeze witness: cache exhaustion refuses without advancing actor state."""

import hashlib
import json
from pathlib import Path

import numpy as np

from adapter import ROOT
from runtime_adapter import ResearchDistributionRuntime
from runtime_adapter import TickRequest
from runtime_adapter import digest


def run():
    with np.load(ROOT/"evidence/prepared_audit/fixtures/default.npz") as f:
        q,prior,edges=f["Q"],f["prior"],f["edges"]
    layout=hashlib.sha256(edges.tobytes()).hexdigest();observation=digest("cache-witness-observation")
    runtime=ResearchDistributionRuntime(q,prior,13,layout,observation)
    for i in range(1,32):
        request=TickRequest(runtime.sequence+1,i/1000,runtime._model.identity,13,
            runtime.checkpoint_digest,digest(["wait",i]),False,observation)
        runtime.tick(request)
    before={"digest":runtime.checkpoint_digest,"clock":runtime.clock,"sequence":runtime.sequence,
            "posterior_hex":runtime.posterior.tobytes().hex(),"cache":runtime._model.cache_info()}
    request=TickRequest(runtime.sequence+1,.032,runtime._model.identity,13,
        runtime.checkpoint_digest,digest(["wait",32]),False,observation)
    error=None
    try:runtime.tick(request)
    except ValueError as failure:error=str(failure)
    unchanged=(runtime.checkpoint_digest==before["digest"] and runtime.clock==before["clock"] and
        runtime.sequence==before["sequence"] and runtime.posterior.tobytes().hex()==before["posterior_hex"])
    # The single owner clears an execution cache, not its model or posterior.
    runtime._model.clear_cache()
    clear_preserves_state=runtime.checkpoint_digest==before["digest"]
    receipt=runtime.tick(request)
    result={"schema":"hcsn-r13-cache-exhaustion-witness-v1","error":error,
        "failure_state_unchanged":unchanged,"clear_preserves_state":clear_preserves_state,
        "same_request_after_clear_succeeds":runtime.sequence==before["sequence"]+1,
        "before":before,"after":{"receipt":receipt,"cache":runtime._model.cache_info()},
        "source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "runtime_source_sha256":hashlib.sha256((ROOT/"runtime_adapter.py").read_bytes()).hexdigest(),
        "all_passed":error is not None and "cache_limit" in error and unchanged and clear_preserves_state
            and runtime.sequence==before["sequence"]+1}
    runtime.close();output=ROOT/"evidence/CACHE_LIMIT_WITNESS.json"
    if output.exists():raise FileExistsError(output)
    output.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"all_passed":result["all_passed"],"error":error}))
    if not result["all_passed"]:raise AssertionError("Cache witness failed")


if __name__=="__main__":run()
