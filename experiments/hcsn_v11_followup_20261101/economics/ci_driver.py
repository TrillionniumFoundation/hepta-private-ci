"""Run frozen V10 real cgroup qualification in a new, owned Linux CI parent."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import uuid


def identity(out, expected):
    git = ["git", "-c", f"safe.directory={Path.cwd().resolve()}"]
    head = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
    if head != expected:
        raise ValueError("Actual checkout HEAD differs from requested event head")
    sources = (list(Path("experiments/hcsn_v10_followup_20261101/economics").glob("*.py"))
               + list(Path(__file__).resolve().parent.glob("*.py"))
               + [Path("experiments/hcsn_v9_followup_20261101/economics/short_tree_probe.py"),
                  Path(".github/workflows/hcsn-v11-cgroup-economics.yml")])
    records = []
    snapshot = out / "sources"
    snapshot.mkdir()
    for source in sources:
        relative = source.resolve().relative_to(Path.cwd().resolve()).as_posix()
        git_blob = subprocess.check_output([*git, "rev-parse", f"HEAD:{relative}"], text=True).strip()
        actual_blob = subprocess.check_output([*git, "hash-object", str(source)], text=True).strip()
        if git_blob != actual_blob:
            raise ValueError("Tested source differs from committed blob: " + relative)
        target = snapshot / relative.replace("/", "__")
        shutil.copyfile(source, target)
        records.append({"path": relative, "git_blob": git_blob,
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "snapshot": str(target.relative_to(out))})
    binary = Path(sys.executable).resolve()
    return {"checkout_sha": head, "expected_head": expected, "sources": records,
            "python_binary": {"path": str(binary), "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                              "version": sys.version},
            "platform": platform.uname()._asdict(),
            "run_id": os.environ.get("GITHUB_RUN_ID"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--identity-only", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    result = {"status": "FAIL", "owned_parent_created": False, "parent_cleanup_verified": False,
              "hardware_charge_campaign_passed": False, "full_family_rss_qualified": False, "energy_qualified": False}
    parent = Path("/sys/fs/cgroup") / ("hcsn-ci-" + uuid.uuid4().hex)
    began = time.monotonic()
    try:
        (args.out / "IDENTITY.json").write_text(json.dumps(identity(args.out, args.expected_head), indent=2) + "\n")
        if args.identity_only:
            result["status"] = "IDENTITY_ONLY"
            return 0
        parent.mkdir(mode=0o700)
        result.update({"owned_parent_created": True, "parent": str(parent), "parent_inode": parent.stat().st_ino})
        if (parent / "cgroup.procs").read_text().strip():
            raise ValueError("Fresh owned CI parent unexpectedly contains tasks")
        available = (parent / "cgroup.controllers").read_text().split()
        if not {"cpu", "memory"}.issubset(available):
            raise ValueError("Root has not delegated cpu/memory; existing root/job groups will not be changed")
        (parent / "cgroup.subtree_control").write_text("+cpu +memory")
        enabled = (parent / "cgroup.subtree_control").read_text().split()
        if not {"cpu", "memory"}.issubset(enabled):
            raise ValueError("Owned parent controller enablement was not confirmed")
        result["owned_parent_controllers"] = enabled
        (parent / "memory.swap.max").write_text("0")
        swap_limit = (parent / "memory.swap.max").read_text().strip()
        if swap_limit != "0":
            raise ValueError("Owned-parent no-swap profile was not confirmed")
        profile = {"parent": str(parent), "inode": parent.stat().st_ino,
                   "enabled_controllers": enabled, "memory_swap_max": swap_limit,
                   "empty_before_admission": not (parent / "cgroup.procs").read_text().strip(),
                   "scope": "Hierarchical no-swap limit on this fresh owned parent only; root/job groups unchanged."}
        (args.out / "PARENT_PROFILE.json").write_text(json.dumps(profile, indent=2) + "\n")
        result["parent_profile_sha256"] = hashlib.sha256((args.out / "PARENT_PROFILE.json").read_bytes()).hexdigest()
        command = [sys.executable, "-m", "experiments.hcsn_v10_followup_20261101.economics.runner_campaign",
                   "--delegated-parent", str(parent), "--out", str(args.out / "campaign")]
        with (args.out / "CAMPAIGN.log").open("xb") as log:
            completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=90)
        result["campaign_exit_code"] = completed.returncode
        audit_command = [sys.executable, "-m", "experiments.hcsn_v11_followup_20261101.economics.audit_ci",
                         "--run", str(args.out)]
        with (args.out / "AUDIT.log").open("xb") as log:
            checked = subprocess.run(audit_command, stdout=log, stderr=subprocess.STDOUT, timeout=15)
        result["audit_exit_code"] = checked.returncode
        result["hardware_charge_campaign_passed"] = completed.returncode == 0 and checked.returncode == 0
    except Exception as error:
        result["failure"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        if result["owned_parent_created"]:
            try:
                if parent.stat().st_ino != result["parent_inode"]:
                    raise ValueError("Owned parent identity changed")
                (parent / "cgroup.kill").write_text("1")
                for child in parent.iterdir():
                    if child.is_dir():
                        deadline = time.monotonic() + 3
                        while "populated 1" in (child / "cgroup.events").read_text() and time.monotonic() < deadline:
                            time.sleep(0.01)
                        child.rmdir()
                if (parent / "cgroup.procs").read_text().strip():
                    raise ValueError("Owned parent still contains processes")
                parent.rmdir()
                result["parent_cleanup_verified"] = not parent.exists()
            except Exception as error:
                result["cleanup_failure"] = str(error)
        if result["hardware_charge_campaign_passed"] and result["parent_cleanup_verified"]:
            result["status"] = "PASS"
        result["wall_seconds"] = time.monotonic() - began
        (args.out / "CI_RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
