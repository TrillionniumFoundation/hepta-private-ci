"""Validate one Bazel observation without granting operator authority."""

import base64
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


TARGET = "//codex-rs/hepta-operator-acceptance:hepta-operator-acceptance-tests"
CASE = "trust::tests::openssh_diagnostic::collect_openssh_programdata_path_matrix"
CELLS = ("absent_extended", "os_bound_extended", "absent_plain", "os_bound_plain")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    preserve((json.dumps(value, indent=2, allow_nan=False) + "\n").encode(), path)


def preserve(raw, destination, *, bep=False):
    """Retain public bytes and original hashes; never publish client env/BES keys."""
    raw_hash = digest(raw)
    removed = []
    public = raw
    if bep:
        lines = []
        for number, line in enumerate(raw.splitlines(), 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                removed.append({"line": number, "fields": ["invalid_or_partial_json"], "raw_line_sha256": digest(line)})
                lines.append(json.dumps({"withheld_invalid_bep_line": number, "raw_line_sha256": digest(line)}).encode())
                continue
            keys = [key for key in ("unstructuredCommandLine", "structuredCommandLine",
                    "optionsParsed") if key in event]
            if keys:
                for key in keys:
                    del event[key]
                event["withheld_client_options"] = keys
            if "started" in event and "optionsDescription" in event["started"]:
                del event["started"]["optionsDescription"]
                keys.append("started.optionsDescription")
            if keys:
                removed.append({"line": number, "fields": keys, "raw_line_sha256": digest(line)})
                line = json.dumps(event, separators=(",", ":")).encode()
            lines.append(line)
        public = b"\n".join(lines) + b"\n"
    replacements = 0
    # Values are used only for redaction, never copied into a receipt or argv.
    for key, value in os.environ.items():
        if value and re.search(r"(?:TOKEN|PASSWORD|SECRET|API_KEY)$", key):
            for encoded in {value.encode(), json.dumps(value)[1:-1].encode()}:
                replacements += public.count(encoded)
                public = public.replace(encoded, b"<REDACTED_CREDENTIAL>")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as handle:
        handle.write(public)
    return {"raw_bytes": len(raw), "raw_sha256": raw_hash, "published_bytes": len(public),
            "published_sha256": digest(public), "raw_equal_published": raw == public,
            "credential_occurrences_redacted": replacements, "withheld_bep_fields": removed}


def inspect_bep(path, expected_sha, expected_tag):
    raw = path.read_bytes()
    events = [json.loads(line) for line in raw.splitlines()]
    require(events and events[-1].get("lastMessage") is True, "BEP is incomplete")
    require(sum(event.get("lastMessage") is True for event in events) == 1, "multiple BEP ends")
    started = [event["started"] for event in events if "started" in event]
    finished = [event["finished"] for event in events if "finished" in event]
    require(len(started) == len(finished) == 1, "BEP needs one invocation and terminal")
    require(started[0].get("uuid") and started[0].get("command") == "test", "not one test invocation")
    require(started[0].get("buildToolVersion") == "9.3.0", "unexpected Bazel version")
    metadata = [event["buildMetadata"]["metadata"] for event in events if "buildMetadata" in event]
    require(len(metadata) == 1 and metadata[0].get("COMMIT_SHA") == expected_sha
            and metadata[0].get("TAG_windows_test_shard") == expected_tag, "BEP source/scope mismatch")
    exit_code = finished[0].get("exitCode")
    require(isinstance(exit_code, dict) and isinstance(exit_code.get("name"), str)
            and exit_code["name"] and type(exit_code.get("code", 0)) is int,
            "missing actual Bazel exit")
    require((exit_code.get("code", 0) == 0) == (exit_code["name"] == "SUCCESS"),
            "Bazel exit code/name disagree")
    results = [(event["id"]["testResult"], event["testResult"]) for event in events
               if "testResult" in event and event["id"]["testResult"].get("label") == TARGET]
    summaries = [event["testSummary"] for event in events if "testSummary" in event
                 and event["id"]["testSummary"].get("label") == TARGET]
    require(results and len(summaries) == 1, "original target has no complete test evidence")
    ids = [json.dumps(identifier, sort_keys=True) for identifier, _ in results]
    require(len(ids) == len(set(ids)), "repeated test attempt identity")
    require(summaries[0].get("totalRunCount") == len(results), "test attempts disagree with summary")
    public_started = {key: value for key, value in started[0].items() if key != "optionsDescription"}
    return raw, events, {"uuid": started[0]["uuid"], "started": public_started,
                         "finished": finished[0], "results": results, "summary": summaries[0]}


def retain_test_files(observation, repo, output):
    root = (repo / "bazel-testlogs/codex-rs/hepta-operator-acceptance/hepta-operator-acceptance-tests").resolve(strict=True)
    retained = []
    for index, (identifier, result) in enumerate(observation["results"]):
        files = {}
        for item in result.get("testActionOutput", []):
            if item.get("name") not in ("test.log", "test.xml"):
                continue
            name = item["name"]
            require(name not in files, "duplicate test artifact")
            uri = urlsplit(item.get("uri", ""))
            require(uri.scheme == "file" and uri.netloc in ("", "localhost"), "test artifact is not local")
            decoded = unquote(uri.path)
            if os.name == "nt" and re.match(r"^/[A-Za-z]:/", decoded):
                decoded = decoded[1:]
            source = Path(decoded).resolve(strict=True)
            ordinary = source.parent == root and source.name == name
            retry = source.parent == root / "test_attempts" and re.fullmatch(
                r"attempt_\d+\." + name.rsplit(".", 1)[1], source.name)
            require(ordinary or retry, "unexpected test artifact path")
            data = source.read_bytes()
            if item.get("digest"):
                require(item["digest"] == digest(data), "BEP artifact digest mismatch")
            if "length" in item:
                require(int(item["length"]) == len(data), "BEP artifact length mismatch")
            files[name] = {"source": str(source), **preserve(data, output / f"attempt-{index}" / name)}
        require(set(files) == {"test.log", "test.xml"}, "missing full test.log/test.xml")
        retained.append({"identity": identifier, "files": files})
    return retained


def require_fresh_single(observation, events, actual_exit):
    require(actual_exit == 0 and observation["finished"]["exitCode"].get("code", 0) == 0,
            "Bazel diagnostic command failed")
    all_results = [event for event in events if "testResult" in event]
    require(len(all_results) == len(observation["results"]) == 1, "not one selected test attempt")
    result = observation["results"][0][1]
    require(result.get("status") == "PASSED" and result.get("cachedLocally", False) is False
            and result.get("executionInfo", {}).get("cachedRemotely", False) is False,
            "diagnostic result failed or was cached")
    require(observation["summary"].get("overallStatus") == "PASSED"
            and observation["summary"].get("totalNumCached", 0) == 0, "diagnostic summary mismatch")


def check_exact_list(log):
    names = re.findall(r"^([^\r\n]+): (?:test|benchmark)\r?$", log, re.M)
    require(names == [CASE], "official ignored list is not the exact one test")
    require([line.rstrip("\r") for line in re.findall(r"^\d+ tests?, \d+ benchmarks?\r?$", log, re.M)] == ["1 test, 0 benchmarks"],
            "list terminal count mismatch")


def check_matrix(log, output):
    require(len(re.findall(r"^running 1 test\r?$", log, re.M)) == 1, "not one native test body")
    summaries = re.findall(r"^test result: (.+)\r?$", log, re.M)
    require(len(summaries) == 1 and summaries[0].startswith(
        "ok. 1 passed; 0 failed; 0 ignored; 0 measured; 33 filtered out;"), "native test terminal mismatch")
    rows = [json.loads(match.group(1)) for match in re.finditer(r"HEPTA_OPENSSH_MATRIX ([^\r\n]+)", log)]
    pre = [row for row in rows if row.get("event") == "preflight"]
    cells = [row for row in rows if row.get("event") == "cell"]
    done = [row["result"] for row in rows if row.get("event") == "cell_complete"]
    final = [row for row in rows if row.get("event") == "matrix_complete"]
    require(len(pre) == len(final) == 1 and [row.get("cell") for row in cells] == list(CELLS)
            and [row.get("cell") for row in done] == list(CELLS), "partial or repeated matrix")
    require(final[0].get("results") == done and final[0].get("diagnostic_only") is True
            and final[0].get("product_qualification") is False, "matrix terminal binding mismatch")
    require(rows[0] == pre[0] and rows[-1] == final[0]
            and final[0].get("executable_after") == pre[0].get("executable_identity"),
            "matrix envelope or signer identity changed")
    expected_events = ["preflight"]
    for result in done:
        cell = result["cell"]
        success = result.get("generation_success")
        require(type(success) is bool, "missing keygen outcome")
        stages = ("keygen", "fingerprint", "sign") if success else ("keygen",)
        expected_events += ["cell"] + ["before_spawn", "terminal", "output"] * len(stages) + ["cell_complete"]
        actual = [row for row in rows if row.get("cell") == cell and row.get("stage")]
        require(len(actual) == 3 * len(stages), "unexpected or incomplete child command capture")
        for stage in stages:
            selected = [row for row in actual if row["stage"] == stage]
            require([row.get("event") for row in selected] == ["before_spawn", "terminal", "output"],
                    "child capture lacks ordered start/terminal/output")
            before, terminal, captured = selected
            require(before.get("argv") and type(terminal.get("exit_code")) is int
                    and terminal.get("success") is (terminal["exit_code"] == 0), "unknown child exit")
            if stage == "keygen":
                require(terminal["success"] == success and terminal["exit_code"] == result.get("generation_exit_code"),
                        "keygen result does not bind actual terminal")
            for stream in ("stdout", "stderr"):
                data = base64.b64decode(captured[stream + "_base64"], validate=True)
                require(len(data) == terminal[stream + "_bytes"] and digest(data) == terminal[stream + "_sha256"],
                        "child public stream does not match terminal hash")
                preserve(data, output / "streams" / f"{cell}-{stage}-{stream}.raw")
        require(not success or result.get("post_generation_verified") is True,
                "generated key lacks actual fingerprint/sign/production verify")
    require([row.get("event") for row in rows] == expected_events + ["matrix_complete"],
            "extra or reordered matrix evidence")
    write_json(output / "matrix.json", rows)
    return {"cells": done, "collection_complete": True, "original_33_requalified": False,
            "product_qualification": False, "semantic_causal_proof": False}
