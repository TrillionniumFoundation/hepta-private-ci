"""Seal the first four qualified sources, or retain a terminal panel refusal."""

import argparse
import json
from pathlib import Path
import sys
import time

import acquire_fresh as acquisition
import fresh_contract as c


def assemble(deployment):
    selection, excluded, publication, admissions, _ = acquisition.release(deployment)
    owner, audit, tasks = Path(selection["owner_root"]), [], []
    for index, project in enumerate(c.REPOSITORIES):
        entry = {"project_id": project, "attempts": []}
        audit.append(entry)
        if admissions[project] == "BEFORE_SCAN_REFUSAL":
            entry["status"] = "BEFORE_SCAN_REFUSAL"
            continue
        path = owner / "scans" / f"{index:02d}-{project.replace('/', '--')}" / "RESULT.json"
        entry["scan"] = {"path": str(path), "sha256": c.sha(path)}
        scanned = c.read_bound(entry["scan"])
        if scanned["status"] == "FAILED_NO_RETRY":
            entry["status"] = "SCAN_FAILED_NO_RETRY"
            continue
        entry["status"] = "NO_QUALIFIED_TASK"
        for ordinal, position in enumerate(c.ordered_potentials(scanned)):
            path = owner / "materials" / f"{index:02d}" / str(ordinal) / "FINAL.json"
            binding = {"path": str(path), "sha256": c.sha(path)}
            result = c.read_bound(binding)
            entry["attempts"].append({"position": list(position), "result": binding})
            c.require(result["status"] in ("QUALIFIED", "REFUSED", "FAILED_NO_RETRY"), "material terminal required before sealing")
            if result["status"] == "QUALIFIED":
                tasks.append(c.read_bound(result["task"]))
                entry["status"] = "SELECTED"
                break
        if len(tasks) == 4:
            break
    output = owner / "panel"
    output.mkdir(exist_ok=False)
    c.write_new(output / "SELECTION_AUDIT.json", {"repositories": audit})
    audit_binding = {"path": str(output / "SELECTION_AUDIT.json"), "sha256": c.sha(output / "SELECTION_AUDIT.json")}
    if len(tasks) < 4:
        result = {"status": "PANEL_REFUSED", "selection_digest": c.digest(selection), "qualified_sources": len(tasks),
                  "selection_audit": audit_binding, "replacement_sources": 0, "automatic_retry": False}
        c.write_new(owner / "PANEL_REFUSED.json", result)
        return result
    panel = {"schema": "hepta.current-student-fresh-panel.v1", "selection_digest": c.digest(selection),
             "tasks": tasks, "selection_audit": audit_binding}
    c.panel_guard(panel, selection, excluded, publication)
    c.write_new(output / "PANEL.json", panel)
    result = {"status": "PANEL_FROZEN", "selection_digest": c.digest(selection), "panel_digest": c.digest(panel),
              "panel": {"path": str(output / "PANEL.json"), "sha256": c.sha(output / "PANEL.json")},
              "created_at_ns": str(time.time_ns()), "generation_calls": 0, "publication_still_required": True}
    c.write_new(owner / "PANEL_FROZEN.json", result)
    return result


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment", required=True)
    parser.add_argument("--deployment-sha256", required=True)
    args = parser.parse_args()
    deployment = c.read_bound({"path": args.deployment, "sha256": args.deployment_sha256})
    with acquisition.source_owner(deployment):
        print(json.dumps(assemble(deployment)))
