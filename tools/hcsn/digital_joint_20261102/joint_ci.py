"""CPU semantic/mathematical CI fixtures; never formal fitting/confirmation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODULE = "tools.hcsn.digital_joint_20261102"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+"\n")


def packed_export(out):
    import numpy as np
    import torch
    from . import joint_campaign, joint_deploy, joint_model
    from .joint_independent_audit_training import engineering_rows
    torch.set_num_threads(1); out.mkdir(parents=True, exist_ok=False)
    rows, confusion = engineering_rows(json.loads((HERE/"joint_protocol.json").read_bytes()))
    results = []
    for family in joint_model.FAMILIES:
        model = joint_model.Policy(family, 37, confusion)
        artifact = model.export([.25, .5, .75, 1., 1.5])
        info = joint_campaign.write(out/(family+".json.gz"), artifact)
        restored = joint_campaign.read(out/(family+".json.gz")); assert restored == artifact
        policy, maximum = joint_deploy.NumpyPolicy(restored), 0.
        for row in rows:
            with torch.no_grad():
                expected = model.forward_row(row["public"], row["state"])
            actual = policy.predict(row["public"], row["state"])
            maximum = max(maximum, max(float(np.max(abs(np.asarray(actual[k])-v.detach().numpy()))) for k, v in expected.items()))
        assert maximum < 1e-10
        results.append(dict(family=family, packed=info, rows=len(rows), maximum_error=maximum))
    save(out/"SUMMARY.json", dict(passed=True, families=results, formal_fits=0,
         scope="initialized engineering models, actual campaign gzip reader and NumPy inference; not frozen-weight bit reproduction"))


def run_case(name, argv, stage, out):
    folder = out/name; folder.mkdir(); wall = time.perf_counter()
    with (folder/"stdout.log").open("x") as stdout, (folder/"stderr.log").open("x") as stderr:
        child = subprocess.Popen(argv, cwd=stage, stdout=stdout, stderr=stderr)
        _, status, usage = os.wait4(child.pid, 0); child.returncode = os.waitstatus_to_exitcode(status)
    result = dict(name=name, command=argv, returncode=child.returncode,
                  wall_seconds=time.perf_counter()-wall, user_cpu_seconds=usage.ru_utime,
                  system_cpu_seconds=usage.ru_stime, maximum_resident_kib=usage.ru_maxrss)
    save(folder/"PROCESS.json", result)
    return result


def run(out, source_freeze):
    import numpy as np
    import scipy
    import torch
    out = out.resolve(); out.mkdir(parents=True, exist_ok=False)
    source_freeze = source_freeze.resolve()
    frozen = json.loads(source_freeze.read_bytes())["sources"]
    if not frozen:
        raise ValueError("explicit nonempty registered source map required")
    before = {p: sha(ROOT/p) for p in frozen}
    environment = dict(python=sys.version, torch=torch.__version__, numpy=np.__version__, scipy=scipy.__version__,
                       torch_git_version=torch.version.git_version, torch_cuda_build=torch.version.cuda,
                       expected_ci_torch="2.9.1+cpu", declared_training_torch="2.15.0+cpu", weight_bit_reproduction=False)
    save(out/"STARTED.json", dict(environment=environment, frozen_sources=before,
         ci_source_sha256=sha(__file__), source_freeze_path=str(source_freeze.relative_to(ROOT)), source_freeze_sha256=sha(source_freeze)))
    if before != frozen:
        save(out/"SUMMARY.json", dict(passed=False, reason="formal source identity mismatch"))
        raise RuntimeError("formal source identity mismatch")
    # All fixed-output audit CLIs run in a fresh copied tree, never in the source.
    stage = out/"isolated_repo"; stage.mkdir(); paths = set(frozen)
    paths |= {str(p.relative_to(ROOT)) for p in HERE.glob("joint_*.py")}
    paths |= {str((HERE/n).relative_to(ROOT)) for n in ("joint_kernel_protocol.json", "joint_ci_PRIMARY_SOURCES.json")}
    paths.add(str(source_freeze.relative_to(ROOT)))
    for name in sorted(paths):
        target = stage/name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, target)
    save(out/"STAGED_SOURCES.json", {name: sha(stage/name) for name in sorted(paths)})
    command = lambda module, *args: [sys.executable, "-m", MODULE+"."+module, *map(str, args)]
    cases = [
        ("task_semantics", command("joint_task_audit")),
        ("budget", command("joint_budget_profile", "--out", out/"budget_fixture")),
        ("kernel_math", command("joint_independent_audit", "--kernel", "--out", out/"kernel_math.json")),
        ("actual_loss_fd", command("joint_independent_audit_training", "--out", out/"actual_loss_fd.json")),
        ("compiled_dp", command("joint_compiled_dp_validate", "--out", out/"compiled_dp_fixture")),
        ("packed_export", command("joint_ci", "--export-only", "--out", out/"packed_export_fixture")),
    ]
    results = [run_case(name, argv, stage, out) for name, argv in cases]
    after = {p: sha(ROOT/p) for p in frozen}
    passed = all(r["returncode"] == 0 for r in results) and before == after == frozen
    save(out/"SUMMARY.json", dict(schema="joint-cpu-ci-v1", passed=passed, cases=results, environment=environment,
         formal_sources_unchanged=before == after == frozen, formal_source_count=len(frozen),
         formal_fits=0, confirmation_cohorts=0, native_ci_executed=False,
         scope="CPU fixture semantic/math/source/packed-reader replay; no GPU, energy, full native qualification or frozen-weight regeneration claim"))
    print(json.dumps(dict(passed=passed, cases={r["name"]: r["returncode"] for r in results}, environment=environment)))
    if not passed:
        raise RuntimeError("CPU CI fixture lane failed; preserve all case output")


def main():
    p = argparse.ArgumentParser(); p.add_argument("--out", type=Path, required=True); p.add_argument("--export-only", action="store_true")
    p.add_argument("--source-freeze", type=Path, default=HERE/"FORMAL_SOURCE_FREEZE_ATTEMPT2.json"); a = p.parse_args()
    if a.export_only:
        packed_export(a.out)
    else:
        run(a.out, a.source_freeze)


if __name__ == "__main__":
    main()
