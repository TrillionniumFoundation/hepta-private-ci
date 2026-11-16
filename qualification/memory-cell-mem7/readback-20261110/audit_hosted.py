"""Verify the original MEM7 hosted ZIPs and their test/campaign receipts."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

from audit_retained import SOURCE, require, sha


ARCHIVES = {
    "mem7-integrity-42836074869.zip": "0ce0b24972d6072435f4eaa17605d29fc3d713a889b74b1ca366ae2fa0999c1a",
    "mem-python-42836074869.zip": "137977b52b0c62bcba6987285a519a344a4c6c2769bc3316ec095dca937c720c",
}


def audit(root, repository):
    archives, suites, identifiers = [], [], []
    for name, expected in ARCHIVES.items():
        path = root / name
        require(sha(path.read_bytes()) == expected, "original_archive_sha256")
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            require(
                len(entries) == len({entry.filename for entry in entries}),
                "duplicate_zip_member",
            )
            require(
                sum(entry.file_size for entry in entries) < 1024 * 1024,
                "zip_expansion_bound",
            )
            content = {}
            for entry in entries:
                relative = Path(entry.filename)
                require(
                    not relative.is_absolute() and ".." not in relative.parts,
                    "unsafe_zip_path",
                )
                require(entry.file_size <= 512000, "zip_member_bound")
                content[entry.filename] = archive.read(entry)
            local_names = set()
            for filename, raw in content.items():
                if not filename.endswith(".json") or "/" in filename:
                    continue
                receipt = json.loads(raw)
                if "observed_passed_tests" not in receipt:
                    continue
                require(
                    receipt["source_sha"] == receipt["tested_sha"] == SOURCE,
                    "hosted_source",
                )
                require(
                    receipt["before"] == receipt["after"]
                    and not receipt["before"]["dirty"],
                    "hosted_clean_tree",
                )
                require(receipt["before"]["commit"] == SOURCE, "hosted_checkout")
                tree = subprocess.check_output(
                    ["git", "rev-parse", f"{SOURCE}^{{tree}}"],
                    cwd=repository,
                    text=True,
                ).strip()
                require(receipt["before"]["tree"] == tree, "hosted_tree_identity")
                log = content[Path(receipt["log_file"]).name]
                require(
                    sha(log) == receipt["log_sha256"]
                    and len(log) == receipt["log_bytes"],
                    "hosted_log_pin",
                )
                names = re.findall(rb"^test_\w+ \(([^\n)]+)\)", log, re.M)
                count = receipt["observed_passed_tests"]
                require(
                    len(names) == len(set(names)) == count, "hosted_test_identifiers"
                )
                require(
                    len(re.findall(rb"(?:^| \.\.\. )ok$", log, re.M)) == count,
                    "hosted_test_ok_count",
                )
                require(
                    re.search(
                        rb"\nRan "
                        + str(count).encode()
                        + rb" tests in [\d.]+s\n\nOK\n",
                        log,
                    )
                    is not None,
                    "hosted_test_summary",
                )
                require(
                    receipt["status"] == "passed"
                    and receipt["observed_failed_tests"] == 0,
                    "hosted_failed_tests",
                )
                require(
                    receipt["exit_code"] == receipt["returncode"] == 0
                    and not receipt["timed_out"]
                    and not receipt["output_limit_exceeded"],
                    "hosted_terminal",
                )
                require(not local_names & set(names), "duplicate_tests_within_job")
                local_names.update(names)
                suites.append(
                    {
                        "artifact": name,
                        "receipt": filename,
                        "passed": count,
                        "log_sha256": receipt["log_sha256"],
                    }
                )
            identifiers.append(local_names)
            archives.append(
                {
                    "path": name,
                    "bytes": path.stat().st_size,
                    "sha256": expected,
                    "members": len(entries),
                    "uncompressed_bytes": sum(entry.file_size for entry in entries),
                }
            )
            if "campaign/PLAN.json" in content:
                plan = json.loads(content["campaign/PLAN.json"])
                require(plan["source_commit"] == SOURCE, "hosted_campaign_source")
                for pin in plan["source_pins"]:
                    source = subprocess.check_output(
                        ["git", "show", f"{SOURCE}:{pin['path']}"], cwd=repository
                    )
                    require(
                        len(source) == pin["bytes"] and sha(source) == pin["sha256"],
                        "hosted_campaign_source_pin",
                    )
                    require(
                        sha((repository / pin["path"]).read_bytes()) == pin["sha256"],
                        "local_verifier_source_pin",
                    )
                sys.path.insert(0, str(repository / "scripts"))
                from ndu_real_runtime.episodic_receipt import verify_read_receipt

                campaign = json.loads(content["campaign/REPORT.json"])
                require(
                    [row["scenario"] for row in campaign["rows"]] == plan["scenarios"],
                    "hosted_campaign_roster",
                )
                for row in campaign["rows"]:
                    process = row["process"]
                    raw = content["campaign/" + process["stdout"]["path"]]
                    require(
                        sha(raw) == process["stdout"]["sha256"]
                        and len(raw) == process["stdout"]["bytes"],
                        "hosted_campaign_output_pin",
                    )
                    result = json.loads(raw)
                    require(
                        verify_read_receipt(result)
                        and result["receipt"] == row["receipt"],
                        "hosted_campaign_receipt",
                    )
                    require(
                        process["returncode"] == 0
                        and row["passed"]
                        and row["request_bound"],
                        "hosted_campaign_row",
                    )
                require(
                    campaign["passed_scenarios"] == campaign["planned_scenarios"] == 14
                    and campaign["status"] == "PASS",
                    "hosted_campaign_count",
                )
                require(
                    all(campaign["invariants"].values())
                    and campaign["model_calls"] == 0,
                    "hosted_campaign_scope",
                )
    return {
        "schema": "hepta.mem7.hosted-evidence-readback.v1",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_ORIGINAL_HOSTED_ARTIFACTS",
        "source_sha": SOURCE,
        "run_id": 42836074869,
        "run_url": "https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42836074869",
        "original_archives": archives,
        "suites": suites,
        "test_invocations_by_job": [len(group) for group in identifiers],
        "overlapping_test_identifiers_between_jobs": len(
            identifiers[0] & identifiers[1]
        ),
        "unique_test_identifiers": len(set.union(*identifiers)),
        "hosted_revocation_scenarios": 14,
        "counts_are_independent_real_tasks": False,
        "this_audit_started_hosted_jobs": False,
        "current_evidence_commit_hosted_ci_pass_claimed": False,
        "full_repository_ci_qualified": False,
        "common_p0_candidate_qualified": False,
        "scientific_acceptance": "HOLD",
        "adoption_action": "NoUpdate",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.root, args.repository), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
