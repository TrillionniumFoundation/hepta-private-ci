"""Frozen MEM6 joint allocation and execution on the retained ai395 resources.

Reserve disjoint source groups before either campaign observes an actor outcome.
The released cohorts are development evidence, not sealed confirmation.
"""

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile


ROOT = Path("/home/qq/mem6-attribution-20261110-484c")
SOURCE = ROOT / "source-8cf848ba"
SOURCE_COMMIT = "8cf848babdd897e9f38642d5faf3ba0f72a1303c"
ARCHIVE_SHA256 = "45b737c45ad1d29de5b58bced568fa7f8469963c8845fd18bac3fedf95064b81"
OLD = Path("/home/qq/mem5-selection-20261110-4b3362")


def pin(path, relative=None):
    raw = path.read_bytes()
    return {"path": str(path if relative is None else path.relative_to(relative)),
            "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def prepare():
    archive = ROOT / "mem6-source-8cf848ba.zip"
    if pin(archive)["sha256"] != ARCHIVE_SHA256:
        raise ValueError("source archive differs from published bytes")
    SOURCE.mkdir(exist_ok=False)
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise ValueError("unsafe source member")
        bundle.extractall(SOURCE)
    manifest = json.loads((SOURCE / "SOURCE_MANIFEST.json").read_bytes())
    if manifest["source_commit"] != SOURCE_COMMIT:
        raise ValueError("source commit differs")
    for item in manifest["files"]:
        if pin(SOURCE / item["path"], SOURCE) != {
            k: item[k] for k in ("path", "bytes", "sha256")
        }:
            raise ValueError("extracted source bytes differ")
    base = json.loads((OLD / "request-5fa0d0e462cd.json").read_bytes())
    old_source = base["config"]["repository_root"]
    base["config"].update(repository_root=str(SOURCE), scripts_root=str(SOURCE / "scripts"))
    base["config"]["runtime_roots"] = [str(SOURCE) if p == old_source else p
                                         for p in base["config"]["runtime_roots"]]
    sys.path[:0] = [str(SOURCE), str(SOURCE / "scripts"), base["config"]["pillow_path"]]
    from ndu_real_runtime import run_candidate_retention as legacy
    from ndu_real_runtime import candidate_retention_public_plan as retention
    from ndu_real_runtime import candidate_selection_plan as selection
    from ndu_real_runtime.objective import canonical_sha

    base["source_commit"] = SOURCE_COMMIT
    paths = legacy.required_source_paths() | {
        "qualification/memory-cell-mem6/" + name
        for name in ("PROTOCOL.md", "ACCEPTANCE.json", "CONTRACT.md")}
    base["source_pins"] = [pin(SOURCE / path, SOURCE) for path in sorted(paths)]
    base["prior_episode_plan_pins"].append(pin(OLD / "run-001-5fa0d0e462cd/PLAN.json"))
    base["max_workers"] = 2
    request = copy.deepcopy(base)
    request.update(schema=retention.SCHEMA, experiment_id="mem6-retention-484c-v1",
                   selection_salt=retention.SELECTION_SALT,
                   groups_per_role={"development": 16, "retention_validation": 4})
    request["sampling_profile_sha256"] = canonical_sha(retention.sampling_profile(request))
    write(ROOT / "retention-request.json", request)
    retained = ROOT / "freeze-retention"
    retained.mkdir()
    plan, _ = retention.freeze(request, retained)
    reserved = sorted({row["source_group_id"] for row in plan["episodes"]})
    ledger = ROOT / "reserved-retention-exposure.json"
    write(ledger, {"schema": "ndu.real.researcher-exposure.v1",
                   "registry_sha256": base["registry_sha256"],
                   "quarantined_source_groups": reserved,
                   "basis_plan": pin(retained / "PLAN.json"),
                   "basis": "prospective reservation before any new actor outcomes",
                   "provider_authenticated": False})
    request = copy.deepcopy(base)
    request.update(schema=selection.SCHEMA, experiment_id="mem6-selector-484c-v1",
                   selection_salt=selection.SELECTION_SALT,
                   groups_per_role={"development": 10, "retention_validation": 4})
    request["exposure_ledgers"].append(pin(ledger))
    write(ROOT / "selector-request.json", request)
    compared = ROOT / "freeze-selector"
    compared.mkdir()
    selector_plan, _ = selection.freeze(request, compared)
    selector_sources = sorted({r["source_group_id"] for r in selector_plan["episodes"]})
    if set(reserved) & set(selector_sources):
        raise ValueError("joint cohorts overlap")
    (ROOT / "tmp").mkdir(exist_ok=False)
    write(ROOT / "PREPARE_RECEIPT.json", {
        "schema": "hepta.mem6.joint-prefreeze.v1", "source_commit": SOURCE_COMMIT,
        "launcher": pin(Path(__file__)), "source_archive": pin(archive),
        "source_manifest": pin(SOURCE / "SOURCE_MANIFEST.json"),
        "retention_plan": pin(retained / "PLAN.json"),
        "selector_plan": pin(compared / "PLAN.json"),
        "retention_sources": reserved, "selector_sources": selector_sources,
        "retention_episodes": len(plan["episodes"]),
        "selector_episodes": len(selector_plan["episodes"]),
        "source_overlap": [], "actor_outcomes_read": False,
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "scientific_acceptance": "HOLD", "production_adoption": False})
    print(json.dumps({"prepared": True, "retention_episodes": len(plan["episodes"]),
                      "selector_episodes": len(selector_plan["episodes"])}), flush=True)


def execute():
    preflight = json.loads((ROOT / "PREPARE_RECEIPT.json").read_bytes())
    if preflight["launcher"] != pin(Path(__file__)):
        raise ValueError("launcher changed after joint allocation")
    write(ROOT / "RUN_STARTED.json", {
        "source_commit": SOURCE_COMMIT, "launcher": pin(Path(__file__)),
        "started_at": datetime.now(timezone.utc).isoformat()})
    original = json.loads((ROOT / "retention-request.json").read_bytes())
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "OMP_NUM_THREADS": "1",
           "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "TMPDIR": str(ROOT / "tmp"),
           "PYTHONPATH": os.pathsep.join([str(SOURCE), str(SOURCE / "scripts"),
                                         original["config"]["pillow_path"]])}
    records = []
    for kind, module in (("retention", "run_candidate_retention_public"),
                         ("selector", "run_candidate_selection")):
        before = time.perf_counter()
        with (ROOT / (kind + ".stdout.log")).open("xb") as out, \
             (ROOT / (kind + ".stderr.log")).open("xb") as error:
            run = subprocess.run([sys.executable, "-B", "-m", "ndu_real_runtime." + module,
                                  "--request", str(ROOT / (kind + "-request.json")),
                                  "--output", str(ROOT / (kind + "-run-001")),
                                  "--independent-report"], cwd=SOURCE, env=env,
                                 stdout=out, stderr=error, timeout=1800, check=False)
        actual = ROOT / (kind + "-run-001/PLAN.json")
        row = {"campaign": kind, "returncode": run.returncode,
               "wall_seconds": time.perf_counter() - before,
               "plan_matches_prefreeze": actual.is_file() and pin(actual)["sha256"]
               == preflight[kind + "_plan"]["sha256"]}
        records.append(row)
        write(ROOT / (kind + "-launch-receipt.json"), row)
        print(json.dumps(row), flush=True)
    with (ROOT / "mechanism.stdout.log").open("xb") as out, \
         (ROOT / "mechanism.stderr.log").open("xb") as error:
        run = subprocess.run([sys.executable, "-B", "-m",
                              "ndu_real_runtime.run_episodic_qualification",
                              "--output", str(ROOT / "mechanism-run-001"),
                              "--source-commit", SOURCE_COMMIT], cwd=SOURCE, env=env,
                             stdout=out, stderr=error, timeout=120, check=False)
    write(ROOT / "EXECUTION_RECEIPT.json", {
        "source_commit": SOURCE_COMMIT, "campaigns": records,
        "mechanism_returncode": run.returncode,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "scientific_acceptance": "HOLD", "production_adoption": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "execute"))
    args = parser.parse_args()
    prepare() if args.phase == "prepare" else execute()
