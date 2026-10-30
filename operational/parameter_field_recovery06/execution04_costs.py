"""Build cost facts from restored, externally pinned execution04 evidence."""
import hashlib
import json
from pathlib import Path

from operational.parameter_field_recovery06.ancestry import checked, canonical, require

BASE = Path("/workspace/scratch/178ced6a501f")
OPS = BASE / "fullstudy_execution04_ops"
RAW = BASE / "fullstudy_execution04_durable_raw"
PREREG = BASE / "execution06_preregistration_inputs"
FAILURE_MANIFEST = BASE / "executor_recovery_20261030T1152/downloads/hepta_execution04_terminal_failure_full_raw_20261030T0547_MANIFEST.json"
FAILURE_MANIFEST_SHA = "c2dc7004aed4b89281b735fdca0ac9cb38b1c169bb125dc3f3220f31bc659a9b"
A29_SHA = "eedb52e2cc05c5fdcc8ed295f27954952730038cdc2851ca4d7e110562f7e0ec"
OUTER_SHA = "1938e9d28ab7403a567f6359186afe25f9bd71024af71307cc293bacf89cea3d"


def descriptor(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "Expected original regular receipt")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest}


def build_cost_facts(import_receipt):
    checked(import_receipt)
    manifest = descriptor(FAILURE_MANIFEST)
    require(manifest["sha256"] == FAILURE_MANIFEST_SHA, "Terminal archive manifest differs")
    frozen = json.loads(FAILURE_MANIFEST.read_bytes())
    sources = {row["source"]["path"]: row["source"] for row in frozen["files"]}
    require(len(sources) == len(frozen["files"]), "Duplicate original file source")
    a29 = descriptor(RAW / "stage_A/seed-29/FAILED.json")
    outer = descriptor(OPS / "wait4_launcher/WAIT4_COMPLETE.json")
    require(a29["sha256"] == A29_SHA and outer["sha256"] == OUTER_SHA,
            "Execution04 failure identity differs")
    candidates = sorted((OPS / "root_steps").glob("*/WAIT4.json"))
    readbacks = BASE / "continuation_recovery_20261030/current_readiness_0253/root_archive_io/01_A-17/readback_steps"
    candidates += [readbacks / f"{index:03d}/WAIT4.json" for index in range(5)]
    require(len(candidates) == 32, "Known independent execution04 root-step population differs")
    rows, seen = [], set()
    for path in candidates:
        item = descriptor(path)
        require(item == sources.get(item["path"]), "Root cost was not in the restored failure archive")
        value = json.loads(path.read_bytes())
        require(value["schema"] == "hepta.execution04.root-engineering-wait4.1"
                and value["complete"] is True, "Root cost lacks a terminal wait4")
        identity = value["child"]["identity"]
        token = (identity["pid"], str(identity["start_ticks"]))
        require(token not in seen, "A waited process must not be charged twice")
        seen.add(token)
        rows.append({"receipt": item, "scope": "independent_root_step"})
    facts = {"schema": "hepta.execution06.execution04-cost-facts.1",
        "execution_episode": "execution04_durable_20261030",
        "accounted_in_execution_episode": "execution06_detached_20261030",
        "a29_failed": a29, "outer_envelope": outer, "import_receipt": import_receipt,
        "root_io": rows, "unknown_additional_work": True}
    path = PREREG / "EXECUTION04_COST_FACTS.json"
    with path.open("xb") as stream:
        stream.write(canonical(facts))
    item = descriptor(path)
    from operational.parameter_field_recovery06.historical_costs import execution04_cost_plan
    execution04_cost_plan(item, import_receipt)
    return item
