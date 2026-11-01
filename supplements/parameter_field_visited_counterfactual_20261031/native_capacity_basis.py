"""Revalidate the actual outcome-free capacity artifact, source and owned cost."""

import hashlib
import os
from pathlib import Path
import time
import urllib.request
import zipfile

from . import counterfactual as k
from . import native_common as n
from . import native_environment as environment
from . import native_receipts as receipts

ROOT = Path("/work/native_capacity")
EPISODE = "visited_counterfactual_capacity_20261031"
ARCHIVE = Path("/work/native_binding/capacity-evidence.zip")
MEMBERS = ("COMPLETE.json", "PLAN.json", "SOURCE_BEFORE.json", "SOURCE_AFTER.json", "INPUT_CONTRACT.json", "RUNTIME.json",
           *("measurement/" + name for name in receipts.MEASUREMENT_NAMES.values()))


def archive_members(value, *, restore=False):
    from . import native_provider as provider

    archive_item = value["artifact_archive"]
    actual = n.descriptor(archive_item["path"])
    expected = provider.entry(value["actual_provider_artifact"])
    k.need(actual == archive_item and all(actual[key] == expected[key] for key in ("bytes", "sha256")),
           "Capacity ZIP differs from the immutable provider artifact")
    files = {item["path"]: item for item in value["evidence_files"]}
    mapping = value["evidence_members"]
    k.need(len(files) == len(value["evidence_files"]) == len(MEMBERS)
           and set(files) == set(mapping) == {str(ROOT / name) for name in MEMBERS}
           and len(set(mapping.values())) == len(mapping), "Capacity evidence mapping is not the complete fixed population")
    with zipfile.ZipFile(archive_item["path"]) as archive:
        members = provider.zip_members(archive, 16 * 1024**2, 512)
        for original, member in sorted(mapping.items()):
            k.need(member in members, "Required capacity literal is absent from the actual provider ZIP")
            target = Path(original)
            provider.extract_checked(archive, members[member], target, files[original], existing=not restore)
    return archive_item


def acquire(value, health):
    from . import native_provider as provider

    p = provider.provider()
    k.need(value["artifact_archive"]["path"] == str(ARCHIVE) and not ARCHIVE.exists() and not ROOT.exists(),
           "Capacity history must be newly acquired into its canonical isolated scope")
    expected = provider.entry(value["actual_provider_artifact"])
    k.need(0 < expected["bytes"] <= 16 * 1024**2, "Unexpected capacity artifact size")
    token = os.environ.get("GITHUB_TOKEN")
    k.need(bool(token), "Actual provider metadata authorization is required")
    opener = urllib.request.build_opener(p.NoRedirect())
    job = value["actual_provider_job"]
    run = p.api_json(opener, "/actions/runs/" + str(job["run_id"]) + "/attempts/" + str(job["run_attempt"]), token)
    provider.validate_run(run, job["run_id"], job["head_sha"])
    metadata = p.api_json(opener, "/actions/artifacts/" + str(expected["id"]), token)
    provider.validate_artifact(metadata, expected, job, run)
    health(0)
    downloaded = p.download(opener, expected, ARCHIVE, token, time.monotonic() + 300)
    health(0)
    item = archive_members(value, restore=True)
    return {"archive": item, "download": downloaded, "current_inode_is_original_inode_claim": False,
            "scope": "New capacity ZIP acquisition is inside this preparation owner's actual wait4; old costs remain separate."}


def check(value, resources):
    from . import native_provider as provider

    k.need(value.get("schema") == "hepta.visited-counterfactual.capacity-basis.1"
           and value.get("execution_episode") == n.EPISODE and value.get("resources") == resources
           and value.get("scientific_outcomes_used") is False
           and value.get("full_completion_within_deadline_guaranteed") is False,
           "Capacity basis is missing or claims a scientific/deadline guarantee")
    n.resources_checked(resources)
    archive_members(value)
    files = {Path(item["path"]).relative_to(ROOT).as_posix(): item for item in value["evidence_files"]}
    k.need(set(files) == set(MEMBERS), "Incomplete capacity evidence population")
    for item in files.values():
        n.checked(item)
    complete, plan, target, before, after = (n.read(files[name]) for name in
        ("COMPLETE.json", "PLAN.json", "INPUT_CONTRACT.json", "SOURCE_BEFORE.json", "SOURCE_AFTER.json"))
    job, artifact = value["actual_provider_job"], value["actual_provider_artifact"]
    producer = {"repository": "TrillionniumFoundation/hepta-private-ci", "run_id": str(job["run_id"]),
                "run_attempt": str(job["run_attempt"]), "head_sha": job["head_sha"], "job": "capacity"}
    k.need(job.get("name") == "capacity" and job.get("status") == "completed" and job.get("conclusion") == "success"
           and complete.get("schema") == "hepta.visited-counterfactual.capacity-complete.1"
           and complete.get("execution_episode") == EPISODE and complete.get("complete") is True
           and complete.get("current_producer") == plan.get("current_producer") == producer
           and complete.get("source_commit") == job["head_sha"] and before == after
           and complete.get("finite_cgroup_memory_bytes") == 8 * 1024**3
           and complete.get("scientific_inputs_requested") is False
           and complete.get("scientific_models_created") is False and complete.get("scientific_values_decoded") is False
           and complete.get("scientific_training_microsteps") == 0
           and complete.get("full_completion_within_deadline_guaranteed") is False,
           "Capacity owner, source or no-science scope differs")
    expected_binding = {
        "execution_episode": EPISODE, "phase": "capacity",
        "component_schema_is_implementation_version_not_execution_episode": True,
        "source_commit": job["head_sha"], "owned_core_sha256": receipts.CORE_SHA,
        "input_contract": files["INPUT_CONTRACT.json"],
        "measurement_program": before["operational/parameter_field_native_capacity_20261031/measure.py"],
    }
    measurements = {key: files["measurement/" + name] for key, name in receipts.MEASUREMENT_NAMES.items()}
    k.need(complete.get("engineering_expected_binding") == plan.get("binding") == expected_binding
           and complete.get("engineering_measurement") == measurements
           and complete.get("engineering_receipt") == files["RUNTIME.json"]
           and complete.get("input_contract") == files["INPUT_CONTRACT.json"], "Capacity binding differs from literal source and measurements")
    checked = receipts.verify_wait4(measurements, receipts.Literals(), expected_binding,
        argv=["/opt/runtime/venv/bin/python", "-B", "/work/source/tools/parameter_field_executor/diagnose.py",
              "--output", "/work/native_capacity/RUNTIME.json"], pinned_core=True)
    actual = complete["actual_result"]
    k.need(all(actual.get(key) == checked["wait4"].get(key)
               for key in ("pid", "exit_code", "cpu_seconds", "wall_seconds", "peak_rss_bytes"))
           and actual.get("wait4_receipt") == measurements["wait4"]
           and actual.get("ownership_closure") == measurements["closure"], "Capacity actual wait4 summary differs")
    k.need(environment.assess_runtime(n.read(files["RUNTIME.json"]), target) is None,
           "Capacity basis did not observe the original exact runtime and three actual samples")
    c, _, _ = n.portable()
    original = target["source_files"]
    k.need(len(original) == 167 and set(original) <= set(before), "Capacity source closure lacks all original scientific files")
    for relative, item in before.items():
        k.need(item["path"] == str(n.SOURCE / relative) and not Path(relative).is_absolute() and ".." not in Path(relative).parts,
               "Capacity source closure path differs")
        raw = c.git(n.ADDON, "show", job["head_sha"] + ":" + relative)
        raw = raw.encode() if isinstance(raw, str) else raw
        k.need(len(raw) == item["bytes"] and hashlib.sha256(raw).hexdigest() == item["sha256"],
               "Capacity source file does not match its actual immutable producer commit")
        if relative in original:
            k.need(item["sha256"] == original[relative], "Original scientific source pin differs")
    raw = c.git(n.ADDON, "show", job["head_sha"] + ":operational/parameter_field_recovery07/INPUT_CONTRACT.json")
    raw = raw.encode() if isinstance(raw, str) else raw
    k.need(len(raw) == files["INPUT_CONTRACT.json"]["bytes"]
           and hashlib.sha256(raw).hexdigest() == files["INPUT_CONTRACT.json"]["sha256"],
           "Capacity historical input contract differs from the actual capacity source")
    token = os.environ.get("GITHUB_TOKEN")
    k.need(bool(token), "Live provider revalidation is required for the historical capacity basis")
    p = provider.provider()
    opener = urllib.request.build_opener(p.NoRedirect())
    actual_job = p.api_json(opener, "/actions/jobs/" + str(job["id"]), token)
    k.need(all(actual_job.get(key) == job.get(key) for key in
               ("id", "run_id", "run_attempt", "head_sha", "name", "status", "conclusion", "started_at", "completed_at")),
           "Capacity provider job identity or conclusion changed")
    run = p.api_json(opener, "/actions/runs/" + str(job["run_id"]) + "/attempts/" + str(job["run_attempt"]), token)
    provider.validate_run(run, job["run_id"], job["head_sha"])
    metadata = p.api_json(opener, "/actions/artifacts/" + str(artifact["id"]), token)
    provider.validate_artifact(metadata, provider.entry(artifact), job, run)
    return {"completion": files["COMPLETE.json"], "measurement": measurements, "wait4": checked["wait4"],
            "capacity_is_not_deadline_guarantee": True, "historical_inodes_reproduced_claim": False}
