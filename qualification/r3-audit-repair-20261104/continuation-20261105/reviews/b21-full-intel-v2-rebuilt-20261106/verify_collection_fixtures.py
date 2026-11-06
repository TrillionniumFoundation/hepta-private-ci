#!/usr/bin/env python3
"""Only fabricated data: exercise required evidence/privacy failure boundaries."""
import base64
import copy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import subprocess
sys.dont_write_bytecode = True
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("collector_under_review", ROOT / "collect_attempts.py")
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
KEY = "SYNTHETIC_ONLY_KEY_WITH_UNICODE_\u03c0_273914"
TARGET = "//codex-rs/utils/pty:pty-unit-tests"
RESULTS = []


class Fixture:
    def __init__(self, base):
        self.base = base
        self.public = base / "public"
        self.public.mkdir()
        self.private = base / "private"
        self.private.mkdir(mode=0o700)
        self.execution = base / "execution"
        self.execution.mkdir()
        (self.execution / "original.compact.zst").write_bytes(subprocess.run(
            ["zstd", "-q", "-c"], input=b"Fabricated compact payload only.\n",
            capture_output=True, check=True).stdout)
        self.actual = base / "actual testlogs with spaces"
        self.actual.mkdir()
        self.logs = base / "bazel-testlogs"
        self.logs.symlink_to(self.actual, target_is_directory=True)
        self.target = self.actual / "codex-rs/utils/pty/pty-unit-tests"
        (self.target / "test_attempts").mkdir(parents=True)
        self.paths = [
            self.target / "test_attempts/attempt_1.log",
            self.target / "test_attempts/attempt_1.xml",
            self.target / "test.log",
            self.target / "test.xml",
        ]
        for i, path in enumerate(self.paths):
            path.write_bytes((("FAILED original first attempt\n" if i == 0 else
                               "PASSED final attempt\n" if i == 2 else
                               '<testsuite synthetic="true"/>\n')).encode("utf-8"))
        self.raw = self.private / "build-events.jsonl"
        self.write_exit("original-bazel-exit-code.txt", 0)
        self.write_exit("console-copy-exit-code.txt", 0)
        (self.public / "console.log").write_text("Synthetic outer console, original exit retained.\n")
        first = {"testResult": {"label": TARGET, "configuration": {"id": "synthetic"},
                                "run": 1, "shard": 1, "attempt": 1}}
        second = copy.deepcopy(first)
        second["testResult"]["attempt"] = 2
        summary = {"testSummary": {"label": TARGET, "configuration": {"id": "synthetic"}}}
        command = {"structuredCommandLine": {"commandLineLabel": "synthetic"}}
        finish = {"buildFinished": {}}
        self.events = [
            {"id": {"started": {}}, "children": [command, first, second, summary, finish],
             "started": {"command": "test"}},
            {"id": command, "structuredCommandLine": {
                "sections": [{"optionList": {"option": [
                    {"optionName": "remote_header", "optionValue": "x-key=" + KEY,
                     "combinedForm": "--remote_header=x-key=" + KEY}]}}]}},
            {"id": first, "testResult": {"status": "FAILED", "cachedLocally": False,
             "executionInfo": {"strategy": "synthetic-local", "cachedRemotely": False},
             "testActionOutput": [self.file(self.paths[0], "test.log"),
                                  self.file(self.paths[1], "test.xml")]}},
            {"id": second, "testResult": {"status": "PASSED", "cachedLocally": False,
             "executionInfo": {"strategy": "synthetic-local", "cachedRemotely": False},
             "testActionOutput": [self.file(self.paths[2], "test.log"),
                                  self.file(self.paths[3], "test.xml")]}},
            {"id": summary, "testSummary": {"overallStatus": "FLAKY", "totalRunCount": 2,
                 "totalNumCached": 0, "failed": [self.file(self.paths[0], "test.log")],
                 "passed": [self.file(self.paths[2], "test.log")]}},
            {"id": finish, "finished": {"exitCode": {"name": "SUCCESS", "code": 0}},
             "lastMessage": True},
        ]

    def file(self, path, name):
        body = path.read_bytes()
        return {"name": name, "uri": path.as_uri(), "length": str(len(body)),
                "digest": hashlib.sha256(body).hexdigest()}

    def write_exit(self, name, value):
        (self.public / name).write_text(str(value) + "\n", encoding="ascii")

    def output(self, attempt=0, item=0):
        return self.events[2 + attempt]["testResult"]["testActionOutput"][item]

    def run(self):
        self.raw.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n"
                                    for x in self.events), encoding="utf-8")
        if hasattr(self, "raw_override"):
            self.raw.write_text(self.raw_override, encoding="utf-8")
        return collector.collect(self.raw, self.public, TARGET, self.execution,
                                 secret=KEY, testlogs=self.logs)

    def derived(self):
        return (self.public / collector.DERIVED_NAME).read_text(encoding="utf-8")


def check(name, mutate, expect_complete, expect_safe=True, inspect=None):
    with tempfile.TemporaryDirectory(prefix="b21-evidence-synthetic-") as directory:
        fixture = Fixture(Path(directory))
        mutate(fixture)
        manifest, gate = fixture.run()
        assert manifest["complete"] == expect_complete, (name, manifest["errors"])
        assert gate["safe_for_upload"] == expect_safe, (name, gate)
        if inspect:
            inspect(fixture, manifest, gate)
        # All non-intentionally unsafe public outputs must be free of known key.
        if expect_safe:
            for path in fixture.public.rglob("*"):
                assert not collector.SecretPolicy(KEY).sensitive_text(str(path)), name
                if path.is_file():
                    assert not collector.SecretPolicy(KEY).sensitive_bytes(path.read_bytes()), name
        RESULTS.append({"case": name, "complete": manifest["complete"],
                        "safe_for_upload": gate["safe_for_upload"], "passed": True})


def check_baseline(f, m, _g):
    assert len(m["files"]) == 4
    assert [a["id"]["attempt"] for a in m["actual_attempts"]] == [1, 2]
    assert [a["status"] for a in m["actual_attempts"]] == ["FAILED", "PASSED"]
    for original in f.paths:
        copied = f.public / "all-testlogs" / original.relative_to(f.actual)
        assert copied.read_bytes() == original.read_bytes()
    assert m["original_bazel_exit"] == 0 and m["console_copy_exit"] == 0


check("01_all_actual_attempts_keep_initial_failure", lambda f: None, True, inspect=check_baseline)


def headers(f):
    tokens, separate, progress, objects = [], [], [], []
    for index, flag in enumerate(sorted(collector.HEADERS)):
        token = "UNKNOWN_SYNTHETIC_BEARER_" + str(index)
        tokens.append("--" + flag + "=Authorization=Bearer " + token)
        separate.extend(["--" + flag, "Authorization=Bearer SEPARATE_" + token])
        progress.append("before --" + flag + "=Authorization=Bearer PROGRESS_" + token + " after")
        objects.append({"optionName": flag, "optionValue": "STRUCTURED_" + token,
                        "combinedForm": "--" + flag + "=STRUCTURED_" + token})
    f.events[1]["unstructuredCommandLine"] = {"args": tokens + separate}
    f.events[1]["progress"] = {"stdout": "\n".join(progress)}
    f.events[1]["structuredCommandLine"] = {"sections": [{"optionList": {"option": objects}}]}


def headers_check(f, _m, _g):
    out = f.derived()
    for index in range(5):
        assert ("UNKNOWN_SYNTHETIC_BEARER_" + str(index)) not in out
    assert "SEPARATE_UNKNOWN" not in out and "PROGRESS_UNKNOWN" not in out
    assert "STRUCTURED_UNKNOWN" not in out


check("02_all_five_space_bearer_header_forms", headers, True, inspect=headers_check)


def uri_auth(f):
    f.events[1]["progress"] = {
        "stdout": "https://USERNAME_SECRET:PASSWORD_SECRET@example.invalid/path"
                  "?accessToken=CAMEL_SECRET&apiKey=CAMEL_KEY&unknownAuth=UNKNOWN_SECRET#ordinary"}


def uri_auth_check(f, _m, _g):
    out = f.derived()
    for token in ("USERNAME_SECRET", "PASSWORD_SECRET", "CAMEL_SECRET", "CAMEL_KEY", "UNKNOWN_SECRET"):
        assert token not in out
    assert "accessToken=" in out and "#ordinary" in out


check("03_uri_userinfo_and_all_query_values", uri_auth, True, inspect=uri_auth_check)


def header_keys_opaque(f):
    f.events[1]["--remote_header"] = "TOP_LEVEL_UNKNOWN_BEARER"
    f.events[1]["flags"] = {"remote_cache_header": "DICT_UNKNOWN_AUTH",
                            KEY: "key field is sanitized"}
    opaque = ("opaque contains " + KEY + " and UNKNOWN_PAYLOAD").encode("utf-8")
    f.events[1]["buildToolLogs"] = {"log": [
        {"name": "opaque", "contents": base64.b64encode(opaque).decode("ascii"),
         "digest": "SYNTHETIC_ORIGINAL_OPAQUE_DIGEST", "length": str(len(opaque))}]}


def opaque_check(f, m, _g):
    out = f.derived()
    for token in ("TOP_LEVEL_UNKNOWN_BEARER", "DICT_UNKNOWN_AUTH", "SYNTHETIC_ORIGINAL_OPAQUE_DIGEST"):
        assert token not in out
    assert m["opaque_payload_omission_count"] == 1


check("04_header_json_keys_and_opaque_payload_digest", header_keys_opaque, True, inspect=opaque_check)


def inline_attempt(f):
    f.events[2]["testResult"]["testActionOutput"][0] = {
        "name": "test.log", "contents": base64.b64encode(b"inline fake log").decode("ascii"),
        "digest": "SYNTHETIC_OPAQUE_LOG_DIGEST"}


check("05_inline_attempt_payload_is_incomplete", inline_attempt, False)
check("06_unselected_secret_filename_not_exported",
      lambda f: (f.target / (KEY + ".txt")).write_text("irrelevant file"), True)
check("07_selected_secret_attempt_filename_is_withheld",
      lambda f: (f.target / "test_attempts" / (KEY + ".log")).write_text("fake"), False)
check("08_bytestream_never_fetched_or_guessed",
      lambda f: f.output().update(uri="bytestream://example.invalid/blobs/abcdef/32"), False)


def outside(f):
    path = f.base / "outside.log"
    path.write_text("outside")
    f.output().update(uri=path.as_uri())


check("09_local_uri_outside_authorized_root", outside, False)
check("10_file_uri_nonlocal_authority",
      lambda f: f.output().update(uri="file://remote.invalid" + f.paths[0].as_posix()), False)


def traversal(f):
    path = f.base / "outside.log"
    path.write_text("outside")
    f.output().update(uri=f.actual.as_uri() + "/%2e%2e/outside.log")


check("11_percent_encoded_traversal_escape", traversal, False)
check("12_file_uri_nul_path", lambda f: f.output().update(uri=f.paths[0].as_uri() + "%00"), False)
check("13_missing_initial_failed_attempt_log", lambda f: f.paths[0].unlink(), False)


def linked_log(f):
    path = f.base / "outside.log"
    path.write_text("outside")
    f.paths[0].unlink()
    f.paths[0].symlink_to(path)


check("14_nested_log_symlink_escape", linked_log, False)
check("15_xml_digest_mismatch", lambda f: f.output(item=1).update(digest="0" * 64), False)
check("16_log_length_mismatch", lambda f: f.output().update(length="987654321"), False)


def duplicate(f):
    f.events.insert(3, copy.deepcopy(f.events[2]))
    f.events[-2]["testSummary"]["totalRunCount"] = 3


check("17_duplicate_actual_attempt", duplicate, False)


def gap(f):
    first = f.events.pop(2)
    f.events[0]["children"].remove(first["id"])
    f.events[-2]["testSummary"]["totalRunCount"] = 1


check("18_missing_early_attempt_sequence", gap, False)
check("19_summary_attempt_count_mismatch",
      lambda f: f.events[-2]["testSummary"].update(totalRunCount=3), False)
check("20_missing_final_last_message", lambda f: f.events[-1].pop("lastMessage"), False)
check("21_unexpected_cached_actual_result",
      lambda f: f.events[2]["testResult"].update(cachedLocally=True), False)
check("22_original_bazel_exit_mismatch",
      lambda f: f.write_exit("original-bazel-exit-code.txt", 7), False)
check("23_console_copy_failure_is_independent",
      lambda f: f.write_exit("console-copy-exit-code.txt", 5), False)


def original_failure(f):
    f.write_exit("original-bazel-exit-code.txt", 3)
    f.events[-1]["finished"]["exitCode"] = {"name": "BUILD_FAILURE", "code": 3}


def original_failure_check(_f, m, _g):
    assert m["original_bazel_exit"] == 3


check("24_complete_evidence_preserves_original_exit_three",
      original_failure, True, inspect=original_failure_check)


def truncated(f):
    f.raw_override = json.dumps(f.events[0]) + '\n{"id":'


def no_derived(f, _m, _g):
    assert not (f.public / collector.DERIVED_NAME).exists()


check("25_truncated_bep_never_publishes_partial_stream", truncated, False, inspect=no_derived)


def credential_log(f):
    f.paths[0].write_text("prefix " + KEY + " suffix", encoding="utf-8")


def withheld_log(f, m, _g):
    assert not (f.public / "all-testlogs" / f.paths[0].relative_to(f.actual)).exists()
    assert hashlib.sha256(f.paths[0].read_bytes()).hexdigest() not in json.dumps(m)


check("26_credential_log_withheld_without_digest", credential_log, False, inspect=withheld_log)
check("27_percent_encoded_credential_uri_rejects_derived_bep",
      lambda f: f.output().update(uri=f.actual.as_uri() + "/" + quote(KEY, safe="")),
      False, inspect=no_derived)
check("28_upload_gate_blocks_plain_console_credential",
      lambda f: (f.public / "console.log").write_text(KEY, encoding="utf-8"),
      True, False)
check("29_upload_gate_blocks_percent_encoded_public_path",
      lambda f: (f.public / quote(KEY, safe="")).write_text("fake"), True, False)
check("30_upload_gate_decodes_source_gzip",
      lambda f: (f.public / "source-head.tar.gz").write_bytes(gzip.compress(KEY.encode("utf-8"), mtime=0)),
      True, False)
check("31_upload_gate_blocks_linked_export",
      lambda f: (f.public / "linked-export").symlink_to(f.paths[0]), True, False)


def encoded_boundary(f):
    encoded = KEY.encode("utf-8")
    for _ in range(4):
        encoded = b"".join(("%%%02X" % byte).encode("ascii") for byte in encoded)
    policy = collector.SecretPolicy(KEY)
    assert policy.sensitive_bytes(encoded)
    assert len(encoded) > 256 and policy.overlap >= len(encoded)
    (f.public / "console.log").write_bytes(
        b"p" * (collector.CHUNK - (len(encoded) - 10)) + encoded + b"\n")


check("32_four_layer_encoded_credential_crosses_read_boundary", encoded_boundary, True, False)


def compressed_credential(f):
    payload = json.dumps([{"fixture": "synthetic only", "index": i, "token": KEY,
                           "padding": "repeated application fields " * (i % 11)}
                          for i in range(5000)], ensure_ascii=False).encode()
    packed = subprocess.run(["zstd", "-q", "-19", "-c"], input=payload,
                            capture_output=True, check=True).stdout
    assert KEY.encode() not in packed
    path = f.execution / "original.compact.zst"
    path.write_bytes(packed)
    f.compressed_before = packed


def compressed_unchanged(f, _m, g):
    assert (f.execution / "original.compact.zst").read_bytes() == f.compressed_before
    assert any(x.get("error_code") == "known_credential_in_bytes" for x in g["errors"])


check("33_valid_compressed_credential_is_blocked_without_rewrite",
      compressed_credential, True, False, inspect=compressed_unchanged)


def truncated_frame(f):
    path = f.execution / "original.compact.zst"
    path.write_bytes(path.read_bytes()[:-2])


def decode_failure(_f, _m, g):
    assert any(x.get("error_code") == "zstd_decode_failed_or_incomplete" for x in g["errors"])


check("34_truncated_zstd_frame_blocks_upload", truncated_frame, True, False, inspect=decode_failure)
saved_which = collector.shutil.which
try:
    collector.shutil.which = lambda _name: None
    check("35_unavailable_decoder_blocks_upload", lambda f: None, True, False,
          inspect=lambda _f, _m, g: (
              g["errors"][0]["error_code"] == "zstd_decoder_missing"
              or (_ for _ in ()).throw(AssertionError("decoder missing code"))))
finally:
    collector.shutil.which = saved_which


def truncated_second_frame(f):
    path = f.execution / "original.compact.zst"
    original = path.read_bytes()
    path.write_bytes(original + original[:-2])


check("36_complete_first_but_truncated_second_zstd_frame_blocks_upload",
      truncated_second_frame, True, False, inspect=decode_failure)

assert len(RESULTS) == 36
print(json.dumps({"schema": "b21-rebuilt-required-synthetic-fixtures-v1",
                  "input": "Fabricated data only; no Bazel, Rust, product or native execution.",
                  "case_count": len(RESULTS), "passed": len(RESULTS), "cases": RESULTS},
                 ensure_ascii=True, indent=2, sort_keys=True))
