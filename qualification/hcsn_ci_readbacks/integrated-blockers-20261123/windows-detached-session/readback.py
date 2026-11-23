"""Original dated Windows archive reads plus detached-session observation readback."""

import argparse
import hashlib
import json
import re
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

ROSTER = {
    "exec_server_dedupes_retried_process_write_ids",
    "exec_server_defaults_omitted_pipe_stdin_to_closed_stdin",
    "exec_server_keeps_control_requests_live_during_long_reads_and_queued_requests",
    "exec_server_resumes_detached_session_without_killing_processes",
    "exec_server_runs_ordinary_requests_serially_by_default",
    "exec_server_starts_process_over_websocket",
}
DETACHED = "exec_server_resumes_detached_session_without_killing_processes"
ARCHIVES = {
    "7005": [
        137481302886,
        14790212814,
        "7dfe9d1bca9dc8d57fcd2d2b4d00c4ebfb1265e7cd2e190e05e2d0e2fc043aaa",
        "6a302bc17e7871daaa03c3cacd230bd9e77db22909deea7029ecefa4ab0f5341"
    ],
    "7009": [
        137503935193,
        14792963395,
        "d41ee9736c1ab51afe5c0a642d7465962f6a7c11a626b187024fead3d88fec31",
        "e312adf3d338fb5ef58b7f3c2b187f6302522984f25233d08cf28b3c8ff380ed"
    ],
    "7013": [
        137513221713,
        14794386164,
        "c92968abcd151078e1f996d128aa736d0b694376a557d5716690c9f02fe3f508",
        "0d26731454f31376d0235b0e89516fe54fea5b9b210c5156f788c84cfad1086a"
    ],
    "c6a": [
        137528575116,
        14796846759,
        "ec9c6110c906f4ad69d5698b0b3ea47ab4890413e9420d9144a5f18f4c24ea15",
        "e5d8030375cbc54f814a5af7cd8dac6d634cc17dfb76389d22aae8841e22caf3"
    ]
}



def sha(data):
    return hashlib.sha256(data).hexdigest()


def parse(data):
    text = data.decode()
    lines = text.splitlines()
    found = re.findall(r"^test ([\w:]+) \.\.\. (ok|FAILED|ignored)$", "\n".join(lines), re.M)
    if len(found) != len(ROSTER) or {name for name, _ in found} != ROSTER:
        raise ValueError("original six-case roster differs")
    summary, = [line for line in lines if line.startswith("test result:")]
    return {
        "cases": dict(found), "log_sha256": sha(data), "target_summary": summary,
        "errors": [line for line in lines if line.startswith("Error:") or "WRESUME" in line],
    }


def read(earlier_dir, observed):
    result = {"historical": {}, "observations": {}}
    for label, (job, artifact, archive_sha, log_sha) in ARCHIVES.items():
        if earlier_dir.is_dir():
            path = earlier_dir / (label + ".zip")
            if sha(path.read_bytes()) != archive_sha:
                raise ValueError(f"original source archive differs for {label}")
            with ZipFile(path) as z:
                member, = [n for n in z.namelist() if n.endswith("exec-server-process-test/test.log")]
                data = z.read(member)
        else:
            with ZipFile(earlier_dir) as z:
                data = z.read(label + ".log")
        record = parse(data)
        if record["log_sha256"] != log_sha:
            raise ValueError(f"original target log differs for {label}")
        record.update(job=job, artifact=artifact, zip_sha256=archive_sha)
        result["historical"][label] = record
    if observed is None:
        return result
    result["observation_zip_sha256"] = sha(observed.read_bytes())
    if result["observation_zip_sha256"] != "1bc6894eff455ee2c4e8ce0f89b8833a5e6b0d07f1f261714e0357fc252c2d3f":
        raise ValueError("observation archive differs from the hosted artifact")
    with ZipFile(observed) as z:
        for lane in ["original", "contextual"]:
            for repeat in range(1, 4):
                key = f"{lane}-{repeat}"
                data = z.read(f"{key}/test.log")
                contents = parse(data)
                metadata = json.loads(z.read(f"{key}/observation.json"))
                xml = z.read(f"{key}/test.xml")
                aggregate, = ElementTree.fromstring(xml).iter("testsuite")
                bad = sum(int(aggregate.get(v, "0")) for v in ["errors", "failures"])
                failed = any(status != "ok" for status in contents["cases"].values())
                if int(aggregate.get("tests")) != 1 or bool(bad) != failed:
                    raise ValueError("Bazel executable XML outcome disagrees with original case listing")
                if (int(metadata["bazel_exit"]) != 0) != failed:
                    raise ValueError("Bazel exit disagrees with original cases")
                if metadata["log_sha256"] != sha(data) or metadata["xml_sha256"] != sha(xml):
                    raise ValueError("per-invocation hash discrepancy")
                if metadata["cases"] != contents["cases"] or metadata["lane"] != lane or metadata["repeat"] != repeat:
                    raise ValueError("observer disagrees with original cases or directory")
                contents.update(xml_sha256=sha(xml), bazel_exit=metadata["bazel_exit"])
                result["observations"][key] = contents
        patch = z.read("contextual.diff").decode()
        additions = [line for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++")]
        deletions = [line for line in patch.splitlines() if line.startswith("-") and not line.startswith("---")]
        if patch.count('diff --git a/') != 1 or 'a/codex-rs/exec-server/tests/process.rs' not in patch:
            raise ValueError("scope of diagnostic source diff differs")
        if deletions != ["-        .await?;"] * 5:
            raise ValueError("original test source beyond the five error-context lines changed")
        if sum("WRESUME wait=" in line for line in additions) != 10:
            raise ValueError("incomplete context labels")
        result["context_diff_sha256"] = sha(z.read("contextual.diff"))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("historical_directory", type=Path, nargs="?", default=Path(__file__).with_name("historical-target-logs.zip"))
    parser.add_argument("observer_zip", type=Path, nargs="?", default=Path(__file__).with_name("observed.zip"))
    args = parser.parse_args()
    print(json.dumps(read(args.historical_directory, args.observer_zip), indent=2, sort_keys=True))
