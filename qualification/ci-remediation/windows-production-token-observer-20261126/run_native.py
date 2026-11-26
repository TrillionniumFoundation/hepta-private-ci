"""Run the original production-token failures once; never promote observations to a fix."""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import tomllib

from environment_observer_parser import record_environment_observations
from parent_sd_parser import record_parent_sd_observation

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = "codex-windows-sandbox"
BRANCH = "research/windows-production-delete-observer-20261126-87d09924"
TESTS = (
    "token::tests::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces",
    "unified_exec::tests::legacy_workspace_write_delete_is_limited_to_writable_roots",
)
FILTER = " | ".join(f"test(={name})" for name in TESTS)
REQUESTS = (("target", 0x10000), ("parent", 0x40), ("target", 0x10002),
            ("parent", 0x42), ("target", 0x2), ("target", 0x1))
OBSERVER_BLOBS = {
    "codex-rs/windows-sandbox-rs/src/token_delete_product_facts_tests.rs": "6a23b3fa53f64a97d0dac9dbadc9f0aab10dddbc",
    "codex-rs/windows-sandbox-rs/src/token_delete_product_observer_tests.rs": "c9666da4ed815954d23c408ab0a96f4c6a9d6597",
    "codex-rs/windows-sandbox-rs/src/token_delete_parent_sd_tests.rs": "2b04631184917819a8e6b009ec5a3d21c18656e9",
    "qualification/ci-remediation/windows-production-token-observer-20261126/PARENT_SD_PROTOCOL.md": "f36b7ef54710ddc9228c4df487d051b38e969e6d",
    "codex-rs/windows-sandbox-rs/src/token_tests.rs": "d6cb6be7dac762a209a7f7f52dd6e626fa446c0b",
    "qualification/ci-remediation/windows-production-token-observer-20261126/README.md": "fa5fd1a46412360abb94f4dbdcfdf95862108517",
}
SOURCES = (
    "codex-rs/windows-sandbox-rs", "codex-rs/Cargo.toml", "codex-rs/Cargo.lock",
    "codex-rs/rust-toolchain.toml", "codex-rs/.cargo/config.toml",
    "codex-rs/.config/nextest.toml", "justfile", "scripts/just-shell.py",
    "scripts/run-nextest.py", "MODULE.bazel", "MODULE.bazel.lock",
    ".github/workflows/hepta-windows-production-delete-observer.yml",
    "qualification/ci-remediation/windows-production-token-observer-20261126",
)
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def binary_identity(path):
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": sha256(data)}


def record_binary_after(report):
    if "test_binary" not in report:
        return
    try:
        report["test_binary_after"] = binary_identity(Path(report["test_binary"]["path"]))
        report["test_binary_unchanged"] = report["test_binary_after"] == report["test_binary"]
        require(report["test_binary_unchanged"], "selected test binary changed after native command")
    except Exception as error:
        report["test_binary_unchanged"] = False
        report["errors"].append(f"binary-final: {type(error).__name__}: {error}")
        if isinstance(report["native"], dict):
            report["native"]["observation_complete"] = False


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def source_snapshot(expected):
    require(git("rev-parse", "HEAD").decode().strip() == expected, "checkout head mismatch")
    require(not git("status", "--porcelain"), "checkout is not clean")
    rows = []
    for path in git("ls-files", "-z", "--", *SOURCES).decode().split("\0"):
        if not path:
            continue
        canonical = git("show", f"HEAD:{path}")
        actual = (ROOT / path).read_bytes()
        require(actual == canonical or actual.replace(b"\r\n", b"\n") == canonical,
                f"unexpected checkout bytes: {path}")
        blob = hashlib.sha1(b"blob " + str(len(canonical)).encode() + b"\0" + canonical).hexdigest()
        if path in OBSERVER_BLOBS:
            require(blob == OBSERVER_BLOBS[path], f"reviewed observer changed: {path}")
        rows.append({"path": path, "bytes": len(actual), "sha256": sha256(actual),
                     "git_blob": blob, "checkout_is_git_bytes": actual == canonical})
    require(set(OBSERVER_BLOBS) <= {row["path"] for row in rows}, "missing frozen observer file")
    return rows


def verify_list(data):
    require(len(data["rust-suites"]) == 1, "expected one production library test binary")
    suite = next(iter(data["rust-suites"].values()))
    require(suite["package-name"] == PACKAGE and suite["kind"] == "lib"
            and suite["status"] == "listed", "unexpected test binary")
    cases = suite["testcases"]
    require(data["test-count"] == len(cases), "list test count mismatch")
    selected, excluded = [], Counter()
    for name, case in cases.items():
        match = case["filter-match"]
        if match["status"] == "matches":
            require(not case["ignored"], "selected test is ignored")
            selected.append(name)
        else:
            require(match["status"] == "mismatch"
                    and match["reason"] in {"expression", "ignored"}, "unknown exclusion")
            excluded[match["reason"]] += 1
    require(sorted(selected) == sorted(TESTS), "original selected identities changed")
    return {"binary_id": suite["binary-id"], "binary_path": suite["binary-path"],
            "selected": selected, "discovered": len(cases), "excluded_by_reason": dict(excluded),
            "excluded_total": sum(excluded.values())}


def verify_native(texts, listing):
    attempts, summaries, records, unknown = [], [], [], []
    for text in texts:
        text = ANSI.sub("", text)
        require(not re.search(r"(?m)^\s*(?:TRY\s*\d+|RETRY|FLAKY)\b", text),
                "unexpected retry or flaky attempt")
        before_summary = re.split(r"(?m)^\s*Summary\s+\[", text, maxsplit=1)[0]
        pattern = (r"(?m)^\s*(PASS|FAIL|TIMEOUT|ABORT|LEAK)\s+\[[^\]\r\n]+\]\s+"
                   + re.escape(listing["binary_id"]) + r"\s+(\S+)\s*$")
        attempts.extend(re.findall(pattern, before_summary))
        summaries.extend(re.findall(r"(?m)^\s*Summary\s+\[[^\]\r\n]+\]\s+(.*)$", text))
        for line in before_summary.splitlines():
            if "HEPTA_PRODUCTION_DELETE_UNKNOWN" in line:
                unknown.append(line.strip()[:1024])
            match = re.fullmatch(r"\s*HEPTA_PRODUCTION_DELETE (\{.*\})", line)
            if match:
                records.append(json.loads(match[1]))
    require(Counter(name for _, name in attempts) == Counter(TESTS), "missing/duplicate test attempt")
    require(len(summaries) == 1 and re.match(r"2 tests run:", summaries[0])
            and "flaky" not in summaries[0], "unexpected native summary")
    skipped = re.search(r", (\d+) skipped", summaries[0])
    require((int(skipped[1]) if skipped else 0) == listing["excluded_total"], "excluded count mismatch")
    require(not unknown, "observer emitted unknown or truncated output")
    tokens = [row for row in records if row["kind"] == "token"]
    accesses = [row for row in records if row["kind"] == "access"]
    fresh = [row for row in records if row["kind"] == "fresh_post_impersonation_readback"]
    require(len(records) == 15 and len(tokens) == 2 and len(accesses) == 12 and len(fresh) == 1,
            "observer record count is incomplete")
    require([row["phase"] for row in tokens] == ["before", "after"], "token phase mismatch")
    expected = [(phase, obj, mask) for phase in ("before", "after") for obj, mask in REQUESTS]
    require([(r["phase"], r["object"], r["requested"]) for r in accesses] == expected,
            "six-query order/count mismatch")
    for row in accesses:
        result = row["result"]
        require(row["descriptor_source"] == "pre_action_memory" and result["api_success"] is True
                and type(result["allowed"]) is bool and type(result["granted"]) is int,
                "AccessCheck API outcome is unknown")
    require(all(t["exact_expected_capabilities"] is True and t["sd_memory_unchanged"] is True
                for t in tokens), "token/descriptor provenance mismatch")
    require(tokens[1]["same_semantic_token_as_before"] is True, "captured raw token facts changed")
    require(fresh[0]["parent_sd_same"] is True, "fresh parent SD changed")
    require((fresh[0]["target_exists"] is False and fresh[0]["target_sd_same_if_present"] is None)
            or (fresh[0]["target_exists"] is True and fresh[0]["target_sd_same_if_present"] is True),
            "fresh target SD is unknown or changed")
    return {"attempts": attempts, "summary": summaries[0], "records": records,
            "observation_complete": True, "production_confinement_qualified": False,
            "raw_privilege_attributes_note": "Equality includes usage bits; inequality is not proof of an authorization change."}


def verify_child_token(texts):
    prefix = "HEPTA_LEGACY_SPAWN_TOKEN "
    records = []

    def exact_keys(value, keys):
        require(type(value) is dict and set(value) == set(keys.split()),
                "child-token record has unexpected fields")

    def integer(value, minimum=0, maximum=0xFFFFFFFF):
        require(type(value) is int and minimum <= value <= maximum,
                "child-token numeric field is outside its typed bound")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate child-token JSON key")
            result[key] = value
        return result

    def roles(value):
        allowed = {"token_user", "token_default_owner", "world", "administrators",
                   "users", "authenticated_users", "system", "other"}
        require(type(value) is list and 1 <= len(value) <= len(allowed)
                and all(type(role) is str and role in allowed for role in value)
                and len(set(value)) == len(value), "invalid child-token role summary")
        require("other" not in value or value == ["other"], "ambiguous other role")

    def facts(value):
        exact_keys(value, "token_type user_roles user_attributes owner_roles group_count groups "
                   "restricting_count restricting privilege_count privileges_luid_and_raw_attributes "
                   "integrity_rid integrity_attributes mandatory_policy")
        integer(value["token_type"], 1, 1)
        roles(value["user_roles"])
        roles(value["owner_roles"])
        require("token_user" in value["user_roles"]
                and "token_default_owner" in value["owner_roles"], "missing token identity role")
        for field in ("user_attributes", "integrity_rid", "integrity_attributes", "mandatory_policy"):
            integer(value[field])
        for count_key, entries_key in (("group_count", "groups"), ("restricting_count", "restricting")):
            integer(value[count_key], 0, 64)
            entries = value[entries_key]
            require(type(entries) is list and len(entries) == value[count_key],
                    "child-token group count mismatch")
            for entry in entries:
                exact_keys(entry, "roles attributes")
                roles(entry["roles"])
                integer(entry["attributes"])
        integer(value["privilege_count"], 0, 64)
        entries = value["privileges_luid_and_raw_attributes"]
        require(type(entries) is list and len(entries) == value["privilege_count"],
                "child-token privilege count mismatch")
        for entry in entries:
            require(type(entry) is list and len(entry) == 3, "invalid child-token privilege tuple")
            integer(entry[0], -(2**31), 2**31 - 1)
            integer(entry[1])
            integer(entry[2])

    for text in texts:
        before_summary = re.split(r"(?m)^\s*Summary\s+\[", ANSI.sub("", text), maxsplit=1)[0]
        for line in before_summary.splitlines():
            if "HEPTA_LEGACY_SPAWN_TOKEN" not in line:
                continue
            line = line.lstrip()
            require(line.startswith(prefix) and len(line.encode("utf-8")) + 1 <= 16 * 1024,
                    "malformed or oversized child-token record")
            records.append(json.loads(line[len(prefix):], object_pairs_hook=unique_object))
    require(len(records) == 1, "missing or duplicate child-token observation")
    record = records[0]
    exact_keys(record, "status poll_count hook_count overlapping_scope launch_input actual_child_primary comparison")
    require(record["status"] == "observed" and record["overlapping_scope"] is False,
            "child-token observation is unknown or overlapping")
    integer(record["poll_count"], 1, 2**64 - 1)
    integer(record["hook_count"], 1, 1)
    for name in ("launch_input", "actual_child_primary"):
        exact_keys(record[name], "status facts")
        require(record[name]["status"] == "observed", "token snapshot is unknown")
        facts(record[name]["facts"])
    comparison = record["comparison"]
    exact_keys(comparison, "raw_observed_fields_equal user_equal owner_equal groups_equal "
               "restricting_equal raw_privileges_equal integrity_equal mandatory_policy_equal token_type_equal")
    require(all(type(value) is bool for value in comparison.values()), "untyped token comparison")
    require(comparison["raw_observed_fields_equal"] == all(
        value for key, value in comparison.items() if key != "raw_observed_fields_equal"),
        "inconsistent aggregate token comparison")
    launch = record["launch_input"]["facts"]
    child = record["actual_child_primary"]["facts"]
    for name, fields in (
        ("token_type_equal", ("token_type",)),
        ("integrity_equal", ("integrity_rid", "integrity_attributes")),
        ("mandatory_policy_equal", ("mandatory_policy",)),
        ("raw_privileges_equal", ("privileges_luid_and_raw_attributes",)),
    ):
        require(comparison[name] == all(launch[field] == child[field] for field in fields),
                "token comparison contradicts complete visible facts")
    for name, count, entries in (("groups_equal", "group_count", "groups"),
                                  ("restricting_equal", "restricting_count", "restricting")):
        if launch[count] == 0 and child[count] == 0:
            require(comparison[name], "two empty raw SID arrays must compare equal")
        if comparison[name]:
            require(launch[count] == child[count]
                    and [entry["attributes"] for entry in launch[entries]]
                    == [entry["attributes"] for entry in child[entries]],
                    "equal raw SID arrays contradict visible count or attributes")
    require(not comparison["user_equal"] or launch["user_attributes"] == child["user_attributes"],
            "equal raw users contradict visible attributes")
    # Lossy role summaries cannot establish either equality or inequality of raw SIDs.
    return record


def record_child_token(report, texts):
    observation = {"status": "unknown", "observation_complete": False,
                   "production_confinement_qualified": False}
    report["native"]["child_token_observation"] = observation
    try:
        observation["record"] = verify_child_token(texts)
        observation.update({"status": "observed", "observation_complete": True})
    except Exception as error:
        report["errors"].append(f"child-token-observation: {type(error).__name__}: {error}")


def main():
    evidence = Path(os.environ["RUNNER_TEMP"]) / "hepta-production-delete-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    expected = os.environ["EXPECTED_HEAD"]
    report = {"expected_head": expected, "commands": [], "errors": [], "native": "not started"}
    env = os.environ.copy()
    env.update({"NEXTEST_PROFILE": "local", "CARGO_TERM_COLOR": "never", "NO_COLOR": "1"})

    def run(label, command):
        stdout, stderr = evidence / f"{label}.stdout.log", evidence / f"{label}.stderr.log"
        item = {"label": label, "command": command, "status": "started"}
        report["commands"].append(item)
        write_json(evidence / "receipt.json", report)
        started = time.monotonic()
        with stdout.open("wb") as out, stderr.open("wb") as err:
            completed = subprocess.run(command, cwd=ROOT / "codex-rs", env=env, stdout=out, stderr=err)
        item.update({"status": "completed", "exit": completed.returncode,
                     "elapsed_seconds": time.monotonic() - started,
                     "stdout": {"path": stdout.name, "sha256": sha256(stdout.read_bytes())},
                     "stderr": {"path": stderr.name, "sha256": sha256(stderr.read_bytes())}})
        write_json(evidence / "receipt.json", report)
        print(f"{label}: exit {completed.returncode}", flush=True)
        return completed.returncode, stdout, stderr

    before = None
    try:
        require(sys.platform == "win32" and os.environ["GITHUB_EVENT_NAME"] == "push", "wrong host/event")
        before = source_snapshot(expected)
        write_json(evidence / "source-before.json", before)
        commit = git("cat-file", "-p", "HEAD")
        (evidence / "git-commit.raw").write_bytes(commit)
        report["event"] = {key: os.environ.get(key) for key in
                           ("GITHUB_SHA", "GITHUB_REF", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
                            "RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion")}
        require(os.environ["GITHUB_SHA"] == expected and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
                and os.environ["GITHUB_REF"] == f"refs/heads/{BRANCH}",
                "event identity or attempt changed")
        versions = {}
        for label, command in (("rustc", ["rustc", "-Vv"]), ("cargo", ["cargo", "-V"]),
                               ("just", ["just", "--version"]), ("nextest", ["cargo", "nextest", "--version"])):
            code, out, _ = run(label, command)
            require(code == 0, f"{label} identity query failed")
            versions[label] = out.read_text(encoding="utf-8")
        require("release: 1.96.0" in versions["rustc"]
                and "host: x86_64-pc-windows-msvc" in versions["rustc"], "wrong Rust toolchain")
        require(versions["cargo"].startswith("cargo 1.96.0 ")
                and versions["just"].strip() == "just 1.51.0"
                and versions["nextest"].startswith("cargo-nextest 0.9.103 "), "wrong tools")
        config_bytes = (ROOT / "codex-rs/.config/nextest.toml").read_bytes()
        config = tomllib.loads(config_bytes.decode())
        require(config["profile"]["default"]["slow-timeout"] == {"period": "30s", "terminate-after": 2}
                and config["profile"]["local"]["inherits"] == "default", "original profile changed")
        (evidence / "nextest-original.toml").write_bytes(config_bytes)
        write_json(evidence / "effective-config-inputs.json", {
            "source_config": config, "profile": "local", "cli_retries": 0, "cli_test_threads": 1,
            "filter": FILTER, "RUST_MIN_STACK_from_original_just_recipe": "8388608",
            "note": "Declared effective inputs, not an invented nextest show-config response.",
            "environment": {k: env.get(k) for k in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS",
                "CARGO_TARGET_DIR", "CARGO_INCREMENTAL", "CARGO_BUILD_JOBS", "CARGO_PROFILE_DEV_DEBUG",
                "CARGO_PROFILE_TEST_DEBUG", "NEXTEST_PROFILE")}})
        code, out, _ = run("metadata", ["cargo", "metadata", "--locked", "--no-deps", "--format-version=1"])
        require(code == 0, "workspace manifest metadata failed")
        metadata = json.loads(out.read_bytes())
        require(PACKAGE in {p["name"] for p in metadata["packages"]}, "missing production package")
        metadata_path = out
        run("clippy", ["cargo", "clippy", "-p", PACKAGE, "--lib", "--tests", "--locked", "--", "-D", "warnings"])
        code, out, _ = run("list", ["cargo", "nextest", "list", "-p", PACKAGE, "--lib", "--locked",
                                   "-E", FILTER, "--message-format", "json", "--cargo-metadata", str(metadata_path)])
        require(code == 0, "original test enumeration/build failed; native bodies not started")
        listing = verify_list(json.loads(out.read_bytes()))
        write_json(evidence / "selected-and-excluded.json", listing)
        binary = Path(listing["binary_path"])
        report["test_binary"] = binary_identity(binary)
        report["native"] = {"status": "started"}
        code, out, err = run("native", ["just", "test", "-p", PACKAGE, "--lib", "--locked",
            "-E", FILTER, "--test-threads", "1", "--retries", "0",
            "--success-output", "immediate", "--failure-output", "immediate"])
        report["native"] = {"status": "command_completed", "exit": code, "observation": "unverified"}
        record_child_token(report, [out.read_text(encoding="utf-8"), err.read_text(encoding="utf-8")])
        record_environment_observations(report, [out.read_text(encoding="utf-8"), err.read_text(encoding="utf-8")])
        record_parent_sd_observation(report, [out.read_text(encoding="utf-8"), err.read_text(encoding="utf-8")])
        report["native"].update(verify_native(
            [out.read_text(encoding="utf-8"), err.read_text(encoding="utf-8")], listing))
    except Exception as error:
        report["errors"].append(f"{type(error).__name__}: {error}")
    finally:
        record_binary_after(report)
        try:
            after = source_snapshot(expected)
            write_json(evidence / "source-after.json", after)
            require(before is not None and after == before, "source-before/after mismatch")
        except Exception as error:
            report["errors"].append(f"source-final: {type(error).__name__}: {error}")
        exits = [item["exit"] for item in report["commands"] if item.get("exit", 0) != 0]
        report["controller_exit"] = exits[0] if exits else (1 if report["errors"] else 0)
        report["production_confinement_qualified"] = False
        write_json(evidence / "receipt.json", report)
    return report["controller_exit"]


if __name__ == "__main__":
    raise SystemExit(main())
