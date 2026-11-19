"""Run scoped ACT-1 gates in an isolated, staged native checkout."""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--phase", choices=["tests", "maintenance"], required=True)
    parser.add_argument("--filter")
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)

    def git(*argv):
        return subprocess.check_output(["git", "-C", str(source), *argv], text=True).strip()

    def identity():
        return {"head": git("rev-parse", "HEAD"), "tree": git("write-tree"),
                "unstaged": git("diff", "--name-only"),
                "status": git("status", "--porcelain", "--untracked-files=all")}

    record = {"schema": "hepta.act1.native-gate.v1", "base": args.base,
              "phase": args.phase, "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "steps": [], "success": False, "production_qualified": False,
              "learned_hierarchy_benefit_proved": False}
    try:
        before = identity()
        record["source_before"] = before
        if before["head"] != args.base or before["unstaged"]:
            raise ValueError("native source must be staged on the pinned base")
        if "??" in before["status"]:
            raise ValueError("untracked native source is not an exact candidate")
        record["rust_version"] = subprocess.check_output(["rustc", "--version"], text=True).strip()
        record["nextest_version"] = subprocess.check_output(["cargo", "nextest", "--version"], text=True).strip()
        if args.phase == "tests":
            command = ["just", "test", "--locked", "-p", "codex-hepta-automation",
                       "--lib", "--tests", "--test-threads", "2", "--success-output", "immediate"]
            if args.filter:
                command += ["-E", args.filter]
            commands = [("tests", command)]
        else:
            commands = [
                ("clippy", ["just", "fix", "--locked", "-p", "codex-hepta-automation", "--", "-D", "warnings"]),
                ("fmt", ["just", "fmt", "--base", args.base]),
            ]
        for name, command in commands:
            log = output / (name + ".log")
            started_ns = time.time_ns()
            with log.open("xb") as stream:
                proc = subprocess.run(command, cwd=source / "codex-rs", stdout=stream, stderr=subprocess.STDOUT)
            raw = log.read_bytes()
            step = {"name": name, "argv": command, "exit_code": proc.returncode,
                    "wall_seconds": (time.time_ns() - started_ns) / 1e9,
                    "log_sha256": hashlib.sha256(raw).hexdigest(), "log_bytes": len(raw)}
            if name == "tests":
                junit = source / "codex-rs/target/nextest/local/junit.xml"
                if junit.is_file() and junit.stat().st_mtime_ns >= started_ns:
                    xml_bytes = junit.read_bytes()
                    tree = ET.fromstring(xml_bytes)
                    match = re.search(r"Nextest run ID ([0-9a-f-]{36})", raw.decode(errors="replace"))
                    if not match or tree.attrib.get("uuid") != match.group(1):
                        raise ValueError("test log and JUnit do not bind the same run")
                    (output / "tests.xml").write_bytes(xml_bytes)
                    cases = tree.findall(".//testcase")
                    names = [(case.attrib.get("classname"), case.attrib.get("name")) for case in cases]
                    if not cases or len(names) != len(set(names)):
                        raise ValueError("missing or duplicated test cases")
                    failed = [case.attrib for case in cases if case.find("failure") is not None or case.find("error") is not None]
                    skipped = [case.attrib for case in cases if case.find("skipped") is not None]
                    step["junit"] = {"sha256": hashlib.sha256(xml_bytes).hexdigest(), "run_id": match.group(1),
                                     "tests": len(cases), "failed": failed, "skipped": skipped,
                                     "case_names": names}
                    if proc.returncode == 0 and failed:
                        raise ValueError("successful command contains failed test cases")
                elif proc.returncode == 0:
                    raise ValueError("successful command did not produce fresh JUnit")
            record["steps"].append(step)
            print(json.dumps({k: v for k, v in step.items() if k != "junit"}), flush=True)
            if proc.returncode:
                print(raw.decode(errors="replace")[-18000:], flush=True)
                break
        after = identity()
        record["source_after"] = after
        if args.phase == "tests" and after != before:
            raise ValueError("source changed during native tests")
        if args.phase == "maintenance":
            patch = subprocess.check_output(["git", "-C", str(source), "diff", "--binary", "HEAD"])
            (output / "maintenance.patch").write_bytes(patch)
            record["maintenance_patch_sha256"] = hashlib.sha256(patch).hexdigest()
        record["success"] = len(record["steps"]) == len(commands) and all(step["exit_code"] == 0 for step in record["steps"])
    except Exception as error:
        record["error"] = type(error).__name__ + ": " + str(error)
    finally:
        record["ended_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        raw = json.dumps(record, indent=2, sort_keys=True).encode() + b"\n"
        (output / "receipt.json").write_bytes(raw)
        summary = {k: v for k, v in record.items() if k != "steps"}
        summary["steps"] = [{**{k: v for k, v in step.items() if k != "junit"},
                             "test_counts": {k: v for k, v in step.get("junit", {}).items() if k in ["tests", "failed", "skipped", "run_id"]}}
                            for step in record["steps"]]
        summary["receipt_sha256"] = hashlib.sha256(raw).hexdigest()
        print(json.dumps(summary, sort_keys=True), flush=True)
    raise SystemExit(0 if record["success"] else 1)


if __name__ == "__main__":
    main()
