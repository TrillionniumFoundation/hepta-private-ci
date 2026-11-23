"""Recompute the final named Windows results from original Bazel test.log ZIPs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
REPO = "TrillionniumFoundation/hepta-private-ci"
REG = re.compile(r"^test (\S+) \.\.\. (ok|FAILED|ignored)\b", re.M)
RUNS = {
    "e327": (45130787598, 137546561430, 14799018890, "e3277e9677688be5c4c235a7a127f0b51e373399", "2f16bb0ab2f7a2826040335a356c4f5f760e6c985fa5144dda3038280fa0eb90"),
    "7005": (45110023804, 137481302886, 14790212814, "de4ef594bfefec05a64fc2ae3b717a640a57b263", "7dfe9d1bca9dc8d57fcd2d2b4d00c4ebfb1265e7cd2e190e05e2d0e2fc043aaa"),
    "7009": (45115542852, 137503935193, 14792963395, "de944cb80e0104c28383aee6ec55b9a43f23606b", "d41ee9736c1ab51afe5c0a642d7465962f6a7c11a626b187024fead3d88fec31"),
    "7013": (45120356546, 137513221713, 14794386164, "a4ff555f72833160e24217ecb57612d3943db2cd", "c92968abcd151078e1f996d128aa736d0b694376a557d5716690c9f02fe3f508"),
    "c6a": (45125165932, 137528575116, 14796846759, "c6a3ed9c36f88707d2f29630efe1e3ea4ee0e902", "ec9c6110c906f4ad69d5698b0b3ea47ab4890413e9420d9144a5f18f4c24ea15"),
}
FOUR = (
    "restricted_tokens_select_stable_routes_and_cleanup",
    "suite::windows_sandbox::windows_elevated_does_not_create_missing_workspace_metadata",
    "suite::windows_sandbox::windows_elevated_enforces_deny_read_and_protects_setup_marker",
    "suite::windows_sandbox::windows_elevated_unified_exec_enforces_managed_deny_reads",
)
EXTRA = ("exec_server_resumes_detached_session_without_killing_processes",
         "suite::remote_env::deferred_executor_spawn_agent_inherits_ready_step_environments::test_case_1_v1",
         "suite::cli_stream::integration_creates_and_checks_session_file",
         "suite::cli_stream::responses_mode_stream_cli_supports_openai_base_url_config_override",
         "suite::subagent_notifications::subagent_start_replaces_session_start_and_injects_context")
WITNESSES = {
    "private desktop required": "capability-only workspace tokens require a private desktop",
    "elevated filesystem unavailable": "elevated Windows sandbox isolation is unavailable",
    "websocket event deadline": "timed out waiting for exec-server websocket event",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def report(directory):
    result = {}
    for tag, (run, job, artifact, source, expected) in RUNS.items():
        archive = directory / (tag + ".zip")
        if digest(archive.read_bytes()) != expected:
            raise RuntimeError(f"Artifact {artifact} ZIP digest mismatch")
        files, outcome, failures = {}, {}, []
        with zipfile.ZipFile(archive) as z:
            if z.testzip() is not None:
                raise RuntimeError("ZIP CRC mismatch")
            for name in sorted(z.namelist()):
                if not name.endswith("/test.log"):
                    continue
                data = z.read(name)
                text = data.decode("utf-8", errors="strict")
                for test, status in REG.findall(text):
                    if status == "FAILED":
                        failures.append(test)
                    if test in FOUR + EXTRA:
                        if test in outcome:
                            raise RuntimeError(f"Repeated final record for {test}")
                        outcome[test] = {"status":status, "member":name}
                        files[name] = {
                            "sha256":digest(data), "bytes":len(data),
                            "diagnostic_categories":[key for key,value in WITNESSES.items() if value in text],
                        }
            count = len(z.namelist())
        required = set(FOUR) | ({EXTRA[0]} if tag=="c6a" else set())
        observed = set(failures)
        if observed != required or len(failures) != len(observed):
            raise RuntimeError(f"Unexpected complete roster of final failures on {tag}: {sorted(observed)}")
        for test in FOUR:
            category = "private desktop required" if test==FOUR[0] else "elevated filesystem unavailable"
            if category not in files[outcome[test]["member"]]["diagnostic_categories"]:
                raise RuntimeError(f"Missing original failure category for {test}")
        if tag=="c6a" and any(outcome[name]["status"]!="ok" for name in EXTRA[1:3]):
            raise RuntimeError("Unexpected final result in the c6a Windows test archive")
        if tag=="e327" and outcome[EXTRA[0]]["status"]!="ok":
            raise RuntimeError("Detached-session result differs from original e327 archive")
        result[tag] = dict(run=run,job=job,artifact=artifact,source=source,sha256=expected,
                           archive_entries=count,all_final_failed=sorted(failures),selected=outcome,members=files)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="folder containing 7005.zip, 7009.zip, 7013.zip, c6a.zip and e327.zip")
    parser.add_argument("--download", action="store_true", help="download missing ZIPs through an authenticated gh CLI")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.download:
        args.directory.mkdir(parents=True, exist_ok=True)
        for tag, (_, _, artifact, _, expected) in RUNS.items():
            dest = args.directory / (tag + ".zip")
            if dest.exists():
                continue
            data = subprocess.check_output(["gh", "api", f"repos/{REPO}/actions/artifacts/{artifact}/zip"])
            if digest(data) != expected:
                raise RuntimeError("Downloaded ZIP differs from recorded digest")
            dest.write_bytes(data)
    encoded = json.dumps(report(args.directory), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded, end="")


if __name__=="__main__":
    main()

