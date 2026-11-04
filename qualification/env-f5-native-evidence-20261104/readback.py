#!/usr/bin/env python3
"""Read one immutable successful Env rejection artifact. Never execute artifact content."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

REPO = "TrillionniumFoundation/hepta-private-ci"
SOURCE = "f5bddc124052837befca7735b9e5a46ab708e5a5"
TREE = "d1440d79ec6cf406185a6b709c472b3557db524a"
RUN = 41782882626
JOB = 126419485455
ARTIFACT = 13299399930
ZIP_BYTES = 4437
ZIP_SHA256 = "c9529e6341df86f4cc8c408390de337cada0f605fa116978899c5266d3bc855a"
EXPECTED = {"mutant-command.log", "mutant-test.log", "mutant-test.xml",
            "receipt.json", "restored-worktree.stdout", "restored-worktree.stderr"}
CASES = {
    "git_process::tests::timed_out_git_wrapper_does_not_leave_child_process_running",
    "git_process::tests::timed_out_exited_git_wrapper_does_not_leave_child_process_running",
}
INPUTS = {
    "qualification/windows-process-fixtures-current/native-helper/run_negative.py":
        "09fcbb0b49b5a69e0cdfd439db72e1d4f809acd4",
    "codex-rs/git-utils/src/git_process.rs": "3ce0431434d0c0e4bbde65eb68bce27cc572d9c6",
    "codex-rs/git-utils/src/git_process_tests.rs": "01fd218228d447b6c0094e73030da0361e4d0693",
}
API = "https://api.github.com/repos/" + REPO
OUT_LIMIT = 128 * 1024

class Rejected(Exception):
    pass

def require(condition, code):
    if not condition:
        raise Rejected(code)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()

def bounded(stream, maximum):
    raw = stream.read(maximum + 1)
    require(len(raw) <= maximum, "READ_LIMIT")
    return raw

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class HttpsRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 3
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        require(parsed.scheme == "https" and parsed.hostname and not parsed.username
                and not parsed.password, "REDIRECT_SCHEME")
        require(not req.has_header("Authorization"), "REDIRECT_AUTHORIZATION")
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def api(path, maximum=2 * 1024 * 1024):
    require(path.startswith("/") and not path.startswith("//"), "API_PATH")
    req = urllib.request.Request(API + path, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + os.environ["GH_TOKEN"],
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "immutable-env-negative-readback",
    })
    with urllib.request.build_opener(NoRedirect).open(req, timeout=60) as response:
        return json.loads(bounded(response, maximum))

def download():
    req = urllib.request.Request(API + "/actions/artifacts/" + str(ARTIFACT) + "/zip",
        headers={"Accept": "application/vnd.github+json",
                 "Authorization": "Bearer " + os.environ["GH_TOKEN"],
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": "immutable-env-negative-readback"})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=60) as response:
            raw = bounded(response, ZIP_BYTES)
    except urllib.error.HTTPError as error:
        require(error.code in (301, 302, 303, 307, 308), "DOWNLOAD_STATUS")
        location = error.headers.get("Location", "")
        parsed = urllib.parse.urlsplit(location)
        require(parsed.scheme == "https" and parsed.hostname and not parsed.username
                and not parsed.password, "DOWNLOAD_LOCATION")
        # The signed archive request and every following redirect carry no API token.
        archive_req = urllib.request.Request(location, headers={
            "User-Agent": "immutable-env-negative-readback"})
        with urllib.request.build_opener(HttpsRedirect).open(archive_req, timeout=60) as response:
            raw = bounded(response, ZIP_BYTES)
    require(len(raw) == ZIP_BYTES and sha(raw) == ZIP_SHA256, "ARCHIVE_IDENTITY")
    return raw

def members(raw):
    result = {}
    returned = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        require(len(infos) == 6 and {item.filename for item in infos} == EXPECTED,
                "MEMBER_SET")
        for info in infos:
            mode = info.external_attr >> 16
            require(not info.is_dir() and not info.flag_bits & 1
                    and stat.S_IFMT(mode) in (0, stat.S_IFREG), "MEMBER_KIND")
            require(info.file_size <= 128 * 1024 and returned + info.file_size <= 512 * 1024,
                    "DECODE_LIMIT")
            with archive.open(info) as stream:
                value = bounded(stream, min(128 * 1024, 512 * 1024 - returned))
            returned += len(value)
            require(len(value) == info.file_size, "MEMBER_SIZE")
            # Reading each entire member also verifies its original ZIP CRC.
            result[info.filename] = value
    return result

def safe_exact(raw):
    text = raw.decode("utf-8-sig")
    forbidden = (r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
                 r"\bgh[pousr]_[A-Za-z0-9]{20,}", r"\bgithub_pat_[A-Za-z0-9_]{20,}",
                 r"\bAKIA[A-Z0-9]{16}\b", r"\bsk-[A-Za-z0-9_-]{20,}",
                 r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}")
    require(not any(re.search(pattern, text) for pattern in forbidden), "OUTPUT_SECRET")
    require(len(raw) <= 128 * 1024, "EXACT_OUTPUT_LIMIT")
    return base64.b64encode(raw).decode("ascii")

def raw_rejection(raw):
    text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    summaries = re.findall(
        r"^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; "
        r"(\d+) measured; (\d+) filtered out;", text, re.M)
    rows = re.findall(r"^test ([^\r\n]+?) \.\.\. (ok|FAILED|ignored)$", text, re.M)
    pids = re.findall(r"^Git wrapper child process (\d+) survived timeout cleanup$", text, re.M)
    require(summaries == [("FAILED", "0", "2", "0", "0", "31")], "RAW_COUNTS")
    require(len(rows) == 2 and {name for name, _ in rows} == CASES
            and all(status == "FAILED" for _, status in rows), "RAW_CASES")
    require(len(pids) == 2 and len(set(pids)) == 2
            and all(0 < int(pid) < 2**32 for pid in pids), "RAW_SURVIVORS")
    require("skipping test:" not in text.lower(), "RAW_SKIP")
    return {"failed_cases": sorted(CASES), "passed": 0, "failed": 2,
            "filtered": 31, "distinct_survivor_pids": 2}

def xml_shape(raw, log):
    require(b"<!DOCTYPE" not in raw.upper() and b"<!ENTITY" not in raw.upper(), "XML_DTD")
    root = ET.fromstring(raw)
    allowed = {"testsuites", "testsuite", "testcase", "error", "failure", "skipped",
               "system-out", "system-err", "properties", "property"}
    nodes = list(root.iter())
    require(len(nodes) <= 64 and all(node.tag in allowed for node in nodes), "XML_TAGS")
    normalized_log = log.decode("utf-8-sig").replace("\r\n", "\n").strip()
    rows = []
    for node in nodes:
        attrs = {}
        for key, value in node.attrib.items():
            if key in {"tests", "failures", "errors", "skipped", "disabled"} and re.fullmatch(r"\d+", value):
                attrs[key] = int(value)
            else:
                attrs[sha(key.encode())] = {"value_sha256": sha(value.encode()),
                                            "value_bytes": len(value.encode())}
        rows.append({"tag": node.tag, "attributes": attrs, "children": [x.tag for x in node],
                     "text_bytes": len((node.text or "").encode()),
                     "text_sha256": sha((node.text or "").encode()),
                     "text_equals_original_log": node.tag == "system-out"
                       and (node.text or "").replace("\r\n", "\n").strip() == normalized_log})
    return rows

def qualified_xml(raw, log):
    require(b"<!DOCTYPE" not in raw.upper() and b"<!ENTITY" not in raw.upper(), "XML_DTD")
    root = ET.fromstring(raw)
    require(root.tag == "testsuites" and not root.attrib and len(root) == 1, "XML_ROOT")
    suite = root[0]
    name = r"codex-rs\git-utils\git-utils-unit-tests.bat"
    require(suite.tag == "testsuite"
            and suite.attrib == {"name": name, "tests": "1", "failures": "0", "errors": "1"}
            and [child.tag for child in suite] == ["testcase", "system-out"], "XML_SUITE")
    case, output = suite
    require(set(case.attrib) == {"name", "status", "duration", "time"}
            and case.attrib["name"] == name and case.attrib["status"] == "run"
            and all(re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", case.attrib[key]) is not None
                    for key in ("duration", "time"))
            and len(case) == 1, "XML_CASE")
    error = case[0]
    require(error.tag == "error" and error.attrib == {"message": "exited with error code 101"}
            and len(error) == 0 and not (error.text or "").strip(), "XML_ERROR")
    require(not output.attrib and len(output) == 0
            and (output.text or "").replace("\r\n", "\n").strip()
              == log.decode("utf-8-sig").replace("\r\n", "\n").strip(), "XML_LOG")
    raw_rejection(log)
    return {"wrapper_tests": 1, "wrapper_failures": 0, "wrapper_errors": 1,
            "rust_exit_code": 101, "exact_original_log_bound": True}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact_list = api("/actions/runs/" + str(RUN) + "/artifacts?per_page=100")
    matches = [item for item in artifact_list["artifacts"] if item["id"] == ARTIFACT]
    require(len(matches) == 1, "ARTIFACT_METADATA")
    artifact = matches[0]
    require(artifact["size_in_bytes"] == ZIP_BYTES
            and artifact.get("digest") == "sha256:" + ZIP_SHA256
            and artifact["expired"] is False
            and artifact["workflow_run"]["id"] == RUN
            and artifact["workflow_run"]["head_sha"] == SOURCE, "ARTIFACT_BINDING")
    run = api("/actions/runs/" + str(RUN))
    job = api("/actions/jobs/" + str(JOB))
    require(run["head_sha"] == SOURCE and run["run_attempt"] == 1
            and job["run_id"] == RUN and job["head_sha"] == SOURCE
            and run["status"] == "completed" and run["conclusion"] == "success"
            and job["status"] == "completed" and job["conclusion"] == "success", "JOB_BINDING")
    steps = {step["name"]: step["conclusion"] for step in job["steps"]}
    require(steps.get("Run original suites with fresh reports and no PowerShell prewarm") == "success"
            and steps.get("Reject surviving descendants when containment is deliberately omitted") == "success",
            "STEP_BINDING")
    commit = api("/git/commits/" + SOURCE)
    require(commit["tree"]["sha"] == TREE, "SOURCE_TREE")
    sources = {}
    source_proof = []
    for path, expected in INPUTS.items():
        item = api("/contents/" + path + "?ref=" + SOURCE)
        require(item["type"] == "file" and item["sha"] == expected
                and item["encoding"] == "base64" and item["size"] <= 64 * 1024, "SOURCE_PATH")
        value = base64.b64decode(item["content"], validate=False)
        require(len(value) == item["size"] and blob(value) == expected, "SOURCE_BYTES")
        sources[path] = value
        source_proof.append({"path": path, "git_blob_sha": expected,
                             "bytes": len(value), "sha256": sha(value)})
    data = members(download())
    receipt = json.loads(data["receipt.json"])
    require(receipt["status"] == "rejection-demonstrated" and receipt["source_commit"] == SOURCE
            and receipt["source_tree"] == TREE and receipt["native_product_acceptance"] is False
            and receipt["source_restored"] is True
            and type(receipt["clean_exit_code"]) is int and receipt["clean_exit_code"] == 0,
            "ORIGINAL_RECEIPT")
    require(data["restored-worktree.stdout"] == b"" and data["restored-worktree.stderr"] == b"",
            "ORIGINAL_RESTORE_OUTPUT")
    commands = receipt["commands"]
    require(len(commands) == 1 and type(commands[0]["exit_code"]) is int
            and commands[0]["exit_code"] == 3
            and commands[0]["log_sha256"] == sha(data["mutant-command.log"]), "ORIGINAL_COMMAND")
    original = sources["codex-rs/git-utils/src/git_process.rs"]
    start = original.index(b"    #[cfg(windows)]\n    let (child, job) = match JobObject::create()")
    end = original.index(b"    #[cfg(not(windows))]\n    let child", start)
    mutant = original[:start] + b"    #[cfg(windows)]\n    let (child, job) = (command.spawn().ok()?, None);\n" + original[end:]
    for key, value in (("production", original), ("mutant", mutant),
                       ("fixture", sources["codex-rs/git-utils/src/git_process_tests.rs"])):
        require(receipt[key]["git_blob_sha"] == blob(value)
                and receipt[key]["bytes"] == len(value)
                and receipt[key]["sha256"] == sha(value), "MUTATION_BINDING")
    checked_wrapper = qualified_xml(data["mutant-test.xml"], data["mutant-test.log"])
    require(receipt["wrapper"] == checked_wrapper, "WRAPPER_RECEIPT")
    for suffix in ("log", "xml"):
        value = data["mutant-test." + suffix]
        require(type(receipt["retained"][suffix]["bytes"]) is int
                and receipt["retained"][suffix]["bytes"] == len(value)
                and receipt["retained"][suffix]["sha256"] == sha(value), "RETAINED_BYTES")
    require(re.fullmatch(r"[0-9a-f]{64}", receipt["positive_receipt_sha256"]) is not None,
            "POSITIVE_RECEIPT_ID")
    report = {
        "schema": "hepta.env.f5.native-rejection-artifact-readback.v1",
        "reader": {"commit": os.environ["GITHUB_SHA"],
                   "git_blob_sha": blob(Path(__file__).read_bytes()),
                   "sha256": sha(Path(__file__).read_bytes()),
                   "bytes": len(Path(__file__).read_bytes())},
        "source": SOURCE, "tree": TREE, "run_id": RUN, "job_id": JOB, "run_attempt": 1,
        "artifact_id": ARTIFACT, "archive_bytes": ZIP_BYTES, "archive_sha256": ZIP_SHA256,
        "original_job_conclusion": "success", "original_receipt_status": "rejection-demonstrated",
        "positive_receipt_sha256_recorded": receipt["positive_receipt_sha256"],
        "positive_receipt_bytes_independently_verified_here": False,
        "wrapper_independently_verified": checked_wrapper,
        "original_source_restored": True, "original_git_clean_exit": 0,
        "all_six_members_crc_verified": True, "source_inputs": source_proof,
        "members": [{"path": name, "bytes": len(value), "sha256": sha(value)}
                    for name, value in sorted(data.items())],
        "raw_rejection": raw_rejection(data["mutant-test.log"]),
        "xml_shape": xml_shape(data["mutant-test.xml"], data["mutant-test.log"]),
        "exact_safe_files_base64": {name: safe_exact(data[name])
                                    for name in ("mutant-test.log", "mutant-test.xml")},
        "native_executed_by_reader": False, "artifact_code_executed": False,
        "product_qualification": False, "original_failure_reclassified": False,
        "source_binding_is_entire_transitive_tree": False,
        "limits": {"compressed": 65536, "returned_decoded": 524288,
                   "member": 131072, "members": 6, "output": OUT_LIMIT,
                   "limits_are_not_rss_guarantees": True},
    }
    raw = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode()
    require(len(raw) <= OUT_LIMIT, "OUTPUT_LIMIT")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "READBACK.json").write_bytes(raw)
    print("ENV_F5_READBACK_JSON=" + json.dumps(report, sort_keys=True), flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never print a signed URL, API token, raw response, or arbitrary exception text.
        code = str(error) if isinstance(error, Rejected) else type(error).__name__
        print("ENV_F5_READBACK_REJECTED=" + code, flush=True)
        sys.exit(1)
