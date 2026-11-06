"""Audit retained GitHub evidence without replaying any native command."""

import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import stat
import zipfile


ROOT = Path("/workspace/scratch/3f6a885bb83c")
EVIDENCE = ROOT / "round3_core_ci/evidence/selected_5114_terminal"
OUTPUT = ROOT / "round3_core_ci/selected_5114_failure_appendix_v1"
HEAD = "9847916393fbd4b67f961a2398229ede0bbd0b91"
TREE = "8e7689e974ee5e299d4fb6b2b60e064fcebb2c4e"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def identity(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest(),
    }


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def main():
    require(not OUTPUT.exists(), "appendix destination already exists")
    log = (EVIDENCE / "job_128091426260.log").read_bytes()
    require(
        identity(log)["sha256"]
        == "c429227119b7f01a72887cba59527b926ca0a7a1560276684bd65ad4af71e34e",
        "job log identity mismatch",
    )
    archive = (EVIDENCE / "artifact.zip").read_bytes()
    require(
        len(archive) == 1498
        and identity(archive)["sha256"]
        == "63a69674b2c243af5dbf88655039f5ad0d61a47995492b1e0dcf70aec7f64440",
        "official artifact identity mismatch",
    )
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        require(source.namelist() == ["evidence-manifest.json"], "unexpected members")
        member = source.getinfo("evidence-manifest.json")
        require(stat.S_ISREG(member.external_attr >> 16), "non-regular member")
        manifest_raw = source.read(member)
    require(
        manifest_raw
        == (EVIDENCE / "artifact_members/evidence-manifest.json").read_bytes(),
        "extracted manifest mismatch",
    )
    receipt = json.loads(manifest_raw)
    require(receipt["validated"] is False, "unexpected qualification")
    require(receipt["raw_logs_uploaded"] is False, "unexpected raw upload")
    require("junit.xml" not in receipt["original_files"], "unexpected JUnit identity")
    require(
        {name: value["rejection_code"] for name, value in receipt["scanner_rejections"].items()}
        == {
            "logs/list.stderr.log": "URI_UNRECOGNIZED_FRAGMENT",
            "logs/run.stderr.log": "URI_UNRECOGNIZED_FRAGMENT",
        },
        "unexpected scanner rejection",
    )
    text = log.decode("utf-8", "strict")
    require(
        re.search(r"^\S+ " + HEAD + r"$", text, re.M) is not None,
        "exact checkout not emitted",
    )
    stages = []
    pattern = re.compile(
        r"^(\S+) CORE_SELECTED_DIAGNOSTIC (\w+) (START|PASS|FAIL) (\w+) EXIT=(null|-?\d+)$"
    )
    for number, line in enumerate(text.splitlines(), 1):
        match = pattern.fullmatch(line)
        if match:
            timestamp, stage, status, code, exit_status = match.groups()
            stages.append({
                "line": number,
                "timestamp": timestamp,
                "stage": stage,
                "status": status,
                "code": code,
                "exit_code": None if exit_status == "null" else int(exit_status),
            })
    final = {item["stage"]: item for item in stages if item["status"] != "START"}
    require(final["list"]["exit_code"] == 0, "list exit differs")
    require(final["run"]["exit_code"] == 100, "run exit differs")
    require(final["source_after"]["status"] == "PASS", "source-after differs")
    require(final["collect"]["code"] == "EVIDENCE_REJECTED", "collection differs")
    proposal = ROOT / "round3_core_ci/native_selected_proposal"
    spec_path = proposal / "units/22b2_selected_native_executor_bound/candidate/.github/scripts/hepta-core-selected-spec.json"
    source_path = proposal / "inputs/published_22b2_commit_api.json"
    spec = json.loads(spec_path.read_bytes())
    commit = json.loads(source_path.read_bytes())
    require(commit["sha"] == HEAD and commit["tree"]["sha"] == TREE, "source mismatch")
    require(len(spec["cases"]) == 7, "case selection mismatch")
    OUTPUT.mkdir()
    originals = OUTPUT / "originals"
    originals.mkdir()
    for name in ("job_128091426260.log", "artifact.zip", "artifacts_api.json", "artifact_inventory.json"):
        shutil.copyfile(EVIDENCE / name, originals / name)
    (originals / "evidence-manifest.json").write_bytes(manifest_raw)
    shutil.copyfile(
        ROOT / "round3_core_ci/evidence/selected_5114_jobs_snapshot_v4.json",
        originals / "terminal_job_state.json",
    )
    shutil.copyfile(Path(__file__), OUTPUT / "audit.py")
    audit = {
        "scope": "Read-only audit of retained original GitHub log and artifact; no native replay.",
        "source": {"head": HEAD, "tree": TREE, "parent": commit["parents"][0]["sha"]},
        "run_id": 42275718905,
        "job_id": 128091426260,
        "artifact_id": 13533454938,
        "job_conclusion": "failure",
        "stages": stages,
        "exact_product_case_results_available": False,
        "qualified_passes_from_this_run": 0,
        "actual_case_execution_count": None,
        "junit_in_retained_artifact": False,
        "junit_identity_in_original_files": False,
        "artifact_is_rejection_manifest_only": True,
        "scanner_rejections": receipt["scanner_rejections"],
        "original_source_receipts_have_equal_reported_identity": (
            receipt["original_files"]["source-before.json"]
            == receipt["original_files"]["source-after.json"]
        ),
        "unavailable_raw_source_receipts_independently_revalidated": False,
        "case_results": [{"case": case, "status": "UNDETERMINED", "actual_attempts": None} for case in spec["cases"]],
        "external_frozen_references": {
            str(spec_path.relative_to(ROOT)): identity(spec_path.read_bytes()),
            str(source_path.relative_to(ROOT)): identity(source_path.read_bytes()),
        },
        "limits": [
            "List exit zero and the later run stage establish a successful build/list phase, not per-case runtime success.",
            "Run exit 100 does not identify a failed case or establish how many selected cases executed.",
            "The manifest gives rejected stream identities but no URI contents; the rejecting URI is undetermined.",
            "Absence of a collected JUnit file does not establish whether nextest generated one elsewhere.",
            "No rejected bytes were recovered, encoded, re-uploaded, or used to relax the scanner.",
            "The frozen 219-file Core 21/22 checkpoint remains unchanged and records its earlier pending state.",
        ],
    }
    write_json(OUTPUT / "AUDIT.json", audit)
    (OUTPUT / "CASE_STATUS.tsv").write_text(
        "case\tstatus\tactual_attempts\n"
        + "".join(case + "\tUNDETERMINED\tunknown\n" for case in spec["cases"])
    )
    (OUTPUT / "README.md").write_text(
        "# Selected Core attempt 5114: retained failure evidence\n\n"
        "The exact side source completed build and test listing, then the original just test command returned 100. "
        "Source checks and scanner readiness passed. The final qualification gate failed.\n\n"
        "The official artifact contains only its original rejection manifest. Both list.stderr and run.stderr "
        "were rejected with URI_UNRECOGNIZED_FRAGMENT. The unchanged collector therefore uploaded no raw "
        "command streams, source receipts, or result.json. It did not record a JUnit file in original_files.\n\n"
        "All seven per-case outcomes and attempt counts remain undetermined. This attempt qualifies zero "
        "per-case passes; that statement does not assert that zero tests passed or ran. The source of the "
        "URI rejection and the actual runtime failure are not recoverable from this artifact.\n\n"
        "AUDIT.json binds the full original GitHub log, official artifact, emitted finite stages, and frozen "
        "source references. CASE_STATUS.tsv records the seven unresolved outcomes. originals contains the "
        "unaltered retrieved evidence. audit.py is the audit source; it performs no native execution.\n\n"
        "This is an additive failure appendix. The earlier 219-file checkpoint is frozen at its original "
        "pending status and has not been edited. No compiler output, rejected stream, or JUnit report is "
        "fabricated or reconstructed. Further source diagnosis and any future attempt require separate evidence.\n"
    )
    files = {}
    for path in sorted(OUTPUT.rglob("*")):
        if path.is_file():
            files[path.relative_to(OUTPUT).as_posix()] = {
                **identity(path.read_bytes()), "mode": oct(stat.S_IMODE(path.stat().st_mode))
            }
    write_json(OUTPUT / "MANIFEST.json", {"files": files, "file_count": len(files), "total_bytes": sum(item["bytes"] for item in files.values())})
    print(json.dumps({"output": str(OUTPUT), "files": len(files), "manifest": identity((OUTPUT / "MANIFEST.json").read_bytes())}, indent=2))


if __name__ == "__main__":
    main()
