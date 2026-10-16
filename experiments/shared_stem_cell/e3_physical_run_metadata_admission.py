"""Independent E3 original physical GitHub Actions receipt metadata admission.

The input files MUST come from the original authenticated GH Actions run,
jobs and artifacts API (not fixtures for real claims). This pure-stdlib
auditor verifies exact SOURCE ID, genuine push job/step completion, no
skips, and required output artifact inventory. It DOES NOT inspect the
artifact ZIP *bytes*, label truth, model publisher signatures, internal
Transformer forwards or production grant authority.

A green workflow alone can hide skipped OCR/native inference; fail closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

SCHEMA = "hepta.e3-original-five-arm-gh-job-metadata-audit.v1"
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
WORKFLOW = "Hepta E3 original same-source physical OCR + Gemma2 native (DENY_ALL)"
BRANCH = "research/e3-five-arm-byte-mutation-audit-20261016"
REQUIRED = {
    "schema-and-security-contract": (
        "Require exact source SHA and pristine original source checkout",
        "Verify 196 byte-bound original model input entries and mutation re-snapshot",
        "Check original 196-byte-source workflow graph and independent-owner ordering",
        "Strict native tokenizer source and conservative image preflight",
    ),
    "physical-ocr-granite": (
        "Original pinned ScienceQA cohort, no prediction labels",
        "Validate no-TEST-target source tree BEFORE OCR/Granite97 inference",
        "Physically OCR all 192 sources and encode with original Granite97",
        "Independently recheck source tree AFTER OCR/Granite97 inference",
    ),
    "physical-native-gemma2": (
        "Prove two genuinely trained same-architecture 769-Head controls",
        "Stage the SAME original ScienceQA sources and fit-only labels",
        "Validate no-TEST-target source tree BEFORE native Gemma2 inference",
        "Download and verify reviewed native Google model snapshot",
        "Actually encode same natural images jointly with text and train 769 Head",
        "Independently recheck source tree AFTER native Gemma2 inference",
    ),
    "independent-original-ocr-heldout": (
        "Fetch original completed byte-pinned source predictions before targets",
        "Only now re-stage original heldout labels in separate reviewer",
        "Independently score genuine frozen Granite text against OCR",
    ),
    "independent-five-arm-review": (
        "Obtain three original source-matched REAL prediction artifacts",
        "Independently verify both physical model jobs excluded TEST label bytes before source scoring",
        "Seal exactly all five source-matched arms before opening heldout labels",
        "Independently restage ORIGINAL 64 TEST labels after predictions are sealed",
        "Independently score actual five-arm results; no selection",
        "Independently score matched Gemma2 text-only vs native joint Heads",
    ),
}
ARTIFACTS = (
    "hepta-e3-same-original-ocr",
    "hepta-e3-same-original-native",
    "hepta-e3-original-ocr-independent-outcome",
    "hepta-e3-five-arm-source-sealed-historical",
)

class MissingPhysicalReceipt(ValueError):
    pass

def need(ok, reason):
    if not ok:
        raise MissingPhysicalReceipt(reason)

def is_sha(v, length=64):
    return type(v) is str and len(v)==length and all(c in "0123456789abcdef" for c in v)

def unique(items):
    seen={}
    for k,v in items:
        need(k not in seen, "duplicate original REST JSON field")
        seen[k]=v
    return seen

def parse(raw):
    def bad_constant(x): raise MissingPhysicalReceipt("nonfinite JSON "+x)
    def finite_float(value):
        number=float(value)
        need(math.isfinite(number), "nonfinite JSON exponent")
        return number
    value=json.loads(raw,object_pairs_hook=unique,parse_constant=bad_constant,
                     parse_float=finite_float)
    need(type(value) is dict, "REST response object missing")
    return value

def read(path):
    p=Path(path)
    need(p.is_file() and not p.is_symlink() and 0 < p.stat().st_size <= 10*1024*1024,
         "missing/oversized/symlinked GH API response")
    return parse(p.read_bytes())

def audited(run, jobs, artifacts, expected_sha):
    need(is_sha(expected_sha,40), "invalid expected source commit SHA")
    need(type(run) is dict and type(jobs) is dict and type(artifacts) is dict,
         "three complete original GH REST response envelopes required")
    repo=run.get("repository")
    need(type(repo) is dict and repo.get("full_name")==REPOSITORY,
         "wrong original GitHub repository")
    need(run.get("name")==WORKFLOW and run.get("head_branch")==BRANCH and
         run.get("head_sha")==expected_sha and run.get("event")=="push" and
         run.get("status")=="completed" and run.get("conclusion")=="success",
         "PR/queued/skipped/foreign branch workflow is not physical execution")
    runid=run.get("id")
    attempt=run.get("run_attempt")
    need(type(runid) is int and runid > 0 and type(attempt) is int and attempt>=1,
         "missing exact original run and attempt")
    raw_jobs=jobs.get("jobs")
    need(type(raw_jobs) is list and len(raw_jobs)==len(REQUIRED),
         "missing, duplicate or surplus physical workflow jobs")
    seen={}
    for job in raw_jobs:
        need(type(job) is dict and type(job.get("name")) is str and
             job["name"] not in seen and job["name"] in REQUIRED,
             "unknown or duplicate original Job owner")
        seen[job["name"]]=job
        need(job.get("run_id")==runid and job.get("status")=="completed" and
             job.get("conclusion")=="success" and
             type(job.get("id")) is int and job["id"]>0,
             "physical job skipped, queued, failed or from another run")
        steps=job.get("steps")
        need(type(steps) is list and bool(steps), "missing original job step receipt")
        real_steps={}
        for step in steps:
            need(type(step) is dict and
                 type(step.get("name")) is str and
                 step["name"] not in real_steps,
                 "missing or duplicated original job step")
            real_steps[step["name"]]=step
            need(step.get("status")=="completed" and
                 step.get("conclusion")=="success",
                 "skipped or non-success step in supposedly completed Job")
        for name in REQUIRED[job["name"]]:
            need(name in real_steps, "required real physical step not executed: "+name)
        order=[next(i for i,s in enumerate(steps) if s["name"]==name)
               for name in REQUIRED[job["name"]]]
        need(order==sorted(order), "original source/model/independent label steps reordered")
    need(set(seen)==set(REQUIRED), "incomplete exact physical and independent reviewer jobs")
    raw_art=artifacts.get("artifacts")
    need(type(raw_art) is list and bool(raw_art), "no original numeric archived receipts")
    seen_art={}
    for obj in raw_art:
        need(type(obj) is dict and type(obj.get("name")) is str and
             obj["name"] not in seen_art,"duplicate/invalid output artifact name")
        seen_art[obj["name"]]=obj
    for name in ARTIFACTS:
        need(name in seen_art, "original physical/reviewer artifact missing: "+name)
        entry=seen_art[name]
        need(entry.get("expired") is False and
             type(entry.get("size_in_bytes")) is int and entry["size_in_bytes"]>0 and
             type(entry.get("id")) is int and entry["id"]>0 and
             type(entry.get("digest")) is str and
             entry["digest"].startswith("sha256:") and
             is_sha(entry["digest"][7:]),
             "missing original archived numeric receipt or SHA-256")
        origin=entry.get("workflow_run")
        need(type(origin) is dict and origin.get("id")==runid,
             "output artifact not created by original physical workflow")
    return {
        "schema":SCHEMA,
        "repository":REPOSITORY,
        "workflow":WORKFLOW,
        "run_id":runid,"run_attempt":attempt,"head_sha":expected_sha,
        "required_original_job_count":len(REQUIRED),
        "required_original_step_count":sum(map(len,REQUIRED.values())),
        "original_job_steps_all_success":True,
        "required_numeric_artifacts":{name:seen_art[name]["digest"] for name in ARTIFACTS},
        "original_artifact_zip_bytes_independently_verified":False,
        "prepost_input_tree_artifact_contents_verified":False,
        "original_test_labels_independently_authenticated":False,
        "model_publisher_signatures_authenticated":False,
        "causal_visual_necessity_adjudicated":False,
        "resource_cost_matched":False,
        "original_hosted_execution_metadata_complete":True,
        "admission_scope":"REST_METADATA_ONLY_NOT_SCIENTIFIC_SELECTION",
        "stem_winner":None,"production_accepted":False,"authority":"DENY_ALL",
    }

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ("run","jobs","artifacts","expected_sha","output"):
        ap.add_argument("--"+arg.replace("_","-"),required=True)
    a=ap.parse_args()
    value=audited(read(a.run),read(a.jobs),read(a.artifacts),a.expected_sha)
    p=Path(a.output)
    need(not p.exists() and not p.is_symlink(), "cannot replace original admission report")
    with p.open("x",encoding="utf-8") as file:
        file.write(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n")
        file.flush()
        os.fsync(file.fileno())
    print("E3_PHYSICAL_REST_METADATA_COMPLETE / SCIENTIFIC_ADMISSION_DENY_ALL")

if __name__=="__main__":
    main()
