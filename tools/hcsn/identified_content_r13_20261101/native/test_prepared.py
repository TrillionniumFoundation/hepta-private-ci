"""Independent matrix-exponential parity, batch/handle/cache and refusal checks."""

import argparse
import ctypes
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from scipy.linalg import expm

from adapter import DOUBLE
from adapter import PreparedModel
from adapter import ROOT
from fixtures import save_fixtures


def run(destination):
    destination = Path(destination)
    models = save_fixtures(destination/"fixtures")
    checks, parity = [], []

    def check(name, condition, **details):
        checks.append({"name": name, "pass": bool(condition), **details})

    def refusal(name, call, out=None):
        before = None if out is None else out.copy()
        try:
            call()
            check(name, False, reason="accepted")
        except ValueError as error:
            check(name, out is None or np.array_equal(out, before), reason=str(error))

    rng = np.random.default_rng(20261101)
    for name in ["coarse", "default", "fine"]:
        q, prior = models[name]["Q"], models[name]["prior"]
        p = np.vstack([prior, rng.dirichlet(np.ones(len(prior)), size=6)])
        with PreparedModel(q, version=13) as model:
            fingerprint = hashlib.sha256(b"HCSN_R13_Q_VERSION_V1"+
                len(prior).to_bytes(8,"big")+(13).to_bytes(8,"big")+
                b"".join(np.float64(x).view(np.uint64).item().to_bytes(8,"big") for x in q.flat)).hexdigest()
            check(f"identity_{name}", model.identity == fingerprint)
            for dt in [0.0, 0.05, 0.45, 2.1, 29.4]:
                reference = p @ expm(q*dt)
                for mode in ["sparse", "dense"]:
                    result = model.propagate(p, dt, mode=mode)
                    error, mass = np.max(abs(result-reference)), np.max(abs(result.sum(-1)-1))
                    check(f"parity_{name}_{dt}_{mode}", error < 3e-11 and mass < 5e-10 and result.min() >= 0,
                          error=float(error), mass_error=float(mass))
                    parity.append({"fixture": name, "dt": dt, "mode": mode, "n":len(prior),
                                   "maximum_error": float(error), "mass_error": float(mass)})
            kernel = model.transition(.45)
            check(f"exported_kernel_{name}", np.max(abs(kernel-expm(q*.45)))<3e-11)
            joined = model.propagate(p,.75)
            split = model.propagate(model.propagate(p,.25),.5)
            check(f"semigroup_{name}", np.max(abs(joined-split))<3e-11)
            check(f"validate_once_{name}", model.cache_info()["generator_validations"] == 1)
    q = models["default"]["Q"].copy()
    p = np.tile(models["default"]["prior"], (24,1))
    with PreparedModel(q, version=13) as model:
        expected = model.propagate(p,.45)
        q[:] = np.nan
        check("model_copies_Q", np.array_equal(model.propagate(p,.45),expected))
        out = np.empty_like(p)
        check("output_reuse", model.propagate(p,.45,out=out) is out and np.array_equal(out, expected))
        alias = p.copy()
        model.propagate(alias,.45,out=alias)
        check("input_output_alias", np.array_equal(alias, expected))
        like = rng.uniform(.01,2.0,p.shape)
        reference = expected*like; reference /= reference.sum(-1,keepdims=True)
        posterior = model.observe(expected,like)
        check("batched_observation",np.max(abs(posterior-reference))<3e-14)
        huge = np.linspace(1e290,1e300,model.n)
        reference = expected*(huge/huge.max()); reference /= reference.sum(-1,keepdims=True)
        check("scaled_broadcast_observation",np.max(abs(model.observe(expected,huge)-reference))<3e-14)
        before = model.cache_info()["preparations"]
        model.prepare(.45); model.prepare(np.nextafter(.45,1.0))
        check("exact_dt_bit_cache",model.cache_info()["preparations"]==before+1)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:model.propagate(p,.45),range(8)))
        check("concurrent_handle",all(np.array_equal(x,expected) for x in results))
        guard=np.full_like(p,-12345.)
        bad=p.copy(); bad[-1,0]=-1
        refusal("bad_last_row_atomic",lambda:model.propagate(bad,.45,out=guard),guard)
        impossible=like.copy(); impossible[-1]=0
        refusal("impossible_last_observation_atomic",lambda:model.observe(expected,impossible,out=guard),guard)
        refusal("negative_time",lambda:model.propagate(p,-.1,out=guard),guard)
        refusal("nan_time",lambda:model.propagate(p,np.nan,out=guard),guard)
        refusal("work_limit",lambda:model.propagate(p,1e100,out=guard),guard)
        code=model.library.hcsn_propagate_batch(model.handle,14,.45,1,len(p),
            p.ctypes.data_as(DOUBLE),guard.ctypes.data_as(DOUBLE))
        check("wrong_version_atomic",code==10 and np.all(guard==-12345))
        model.clear_cache()
        for i in range(32): model.prepare(i/100)
        refusal("bounded_cache",lambda:model.prepare(.99))
        model.clear_cache(); model.prepare(.99)
        check("cache_clear_preserves_model",model.cache_info()["generator_validations"]==1)
        handle=model.handle
    code=model.library.hcsn_propagate_batch(handle,13,.45,1,len(p),
        p.ctypes.data_as(DOUBLE),guard.ctypes.data_as(DOUBLE))
    check("released_handle_atomic",code==9 and np.all(guard==-12345))
    q=models["default"]["Q"].copy()
    with PreparedModel(q,13) as a, PreparedModel(q,14) as b, PreparedModel(q*1.01,13) as c:
        check("Q_and_version_identity",len({a.identity,b.identity,c.identity})==3)
    bad=q.copy(); bad[0,0]=1
    refusal("invalid_generator",lambda:PreparedModel(bad,13))
    absorbing=np.zeros((6,6)); prior=np.array([1.,0,0,0,0,0])
    with PreparedModel(absorbing,13) as model:
        check("absorbing_generator",np.array_equal(model.propagate(prior,256),prior))
    report={"schema":"hcsn-r13-prepared-audit-v1", "checks":checks,
        "all_passed":all(x["pass"] for x in checks),"parity":parity,
        "maximum_error":max(x["maximum_error"] for x in parity),
        "maximum_mass_error":max(x["mass_error"] for x in parity),
        "library_sha256":hashlib.sha256((ROOT/"evidence/build/libhcsn_prepared.so").read_bytes()).hexdigest(),
        "source_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [*sorted(ROOT.glob("*.rs")),ROOT/"adapter.py",Path(__file__).resolve(),ROOT/"fixtures.py"]}}
    (destination/"RESULTS.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({k:report[k] for k in ["all_passed","maximum_error","maximum_mass_error"]}))
    if not report["all_passed"]:
        raise AssertionError([x for x in checks if not x["pass"]])
    return report


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=ROOT/"evidence/prepared_audit")
    run(parser.parse_args().output)
