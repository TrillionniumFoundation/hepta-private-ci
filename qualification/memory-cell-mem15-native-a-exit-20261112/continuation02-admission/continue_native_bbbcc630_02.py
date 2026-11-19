"""Continue only the unexecuted MEM15 controls and capture arms.

The prior wrapper's --no-run conflicted with just test's --no-fail-fast.
The required two ack controls compile the identical Agentd --lib test binary
before any listener is started. No source, timeout or test gate is relaxed.
"""
import base64
import hashlib
import json
from pathlib import Path

PRIOR_TERMINAL_B64 = "eyJyZXN1bHRUeXBlIjoiY29tcGxldGUiLCJjb250ZW50IjpbeyJ0eXBlIjoidGV4dCIsInRleHQiOiJ7XG4gIFwiYXRfdW5peF9tc1wiOiAxNzk0NDc1OTg0OTc5LFxuICBcImF1ZGl0X3JlY29yZGVkXCI6IHRydWUsXG4gIFwiYXV0b21hdGljX3JldHJ5XCI6IGZhbHNlLFxuICBcImNhbmNlbGxlZFwiOiBmYWxzZSxcbiAgXCJleGl0X2NvZGVcIjogMSxcbiAgXCJqb2JfaWRcIjogXCIxYTFjZjE1NWI1OC0yNTY0LTE5N2VcIixcbiAgXCJsYXVuY2hfbm9uY2VcIjogXCI4NjQwOTMwYjE1ZDMwOTcyM2FmM2RlMjNhY2M2YmEwNlwiLFxuICBcImxvZ19ieXRlc1wiOiB7XG4gICAgXCJzdGRlcnJcIjoge1xuICAgICAgXCJzZWVuXCI6IDAsXG4gICAgICBcInN0b3JlZFwiOiAwXG4gICAgfSxcbiAgICBcInN0ZG91dFwiOiB7XG4gICAgICBcInNlZW5cIjogMzI3LFxuICAgICAgXCJzdG9yZWRcIjogMzI3XG4gICAgfVxuICB9LFxuICBcImxvZ19lcnJvcnNcIjoge1xuICAgIFwic3RkZXJyXCI6IG51bGwsXG4gICAgXCJzdGRvdXRcIjogbnVsbFxuICB9LFxuICBcImxvZ19zeW5jZWRcIjoge1xuICAgIFwic3RkZXJyXCI6IHRydWUsXG4gICAgXCJzdGRvdXRcIjogdHJ1ZVxuICB9LFxuICBcImxvZ190cnVuY2F0ZWRcIjoge1xuICAgIFwic3RkZXJyXCI6IGZhbHNlLFxuICAgIFwic3Rkb3V0XCI6IGZhbHNlXG4gIH0sXG4gIFwib3V0cHV0X2NvbXBsZXRlXCI6IHRydWUsXG4gIFwib3V0cHV0X2R1cmFibGVcIjogdHJ1ZSxcbiAgXCJzdGF0ZVwiOiBcImZhaWxlZFwiLFxuICBcInRlcm1pbmFsX3B1YmxpY2F0aW9uX2NvbmZpcm1lZFwiOiB0cnVlLFxuICBcInRlcm1pbmFsX3B1YmxpY2F0aW9uX3Byb3RvY29sXCI6IDEsXG4gIFwidGltZWRfb3V0XCI6IGZhbHNlXG59In1dLCJpc0Vycm9yIjpmYWxzZX0="
PRIOR_TERMINAL_SHA = "b5944cef02ff59bcbe143a8881739dc0eee394f44577b0746b26d7fed81666d2"
ORIGINAL = Path("/home/qq/work/mem15-native-qualification-20261112-ef0c/capture-bbbcc630-01")
ORIGINAL_RUNNER_SHA = "ec700c2c9f5ad2cabb8b845e357661976e4dd370b0badb2cf5ceeb7153de1e38"
runner = (ORIGINAL / "submitted.py").read_bytes()
if hashlib.sha256(runner).hexdigest() != ORIGINAL_RUNNER_SHA:
    raise RuntimeError("original reviewed helper source differs")
marker = b"\nOUT.mkdir(mode=0o700, exist_ok=False)\n"
if runner.count(marker) != 1:
    raise RuntimeError("original helper/main boundary differs")
# Reuse only the exact reviewed definitions; never execute the prior main body.
exec(compile(runner.split(marker)[0], "<mem15-reviewed-helper-definitions>", "exec"), globals())
OUT = ROOT / "capture-bbbcc630-02"
OUT.mkdir(mode=0o700, exist_ok=False)
RESULT["schema"] = "hepta.mem15.native-capture-continuation.v1"
RESULT["scope"] = "same-source unexecuted three controls and four capture arms; prior build/811 controls not repeated; original null counts unchanged"

try:
    save()
    terminal_raw = base64.b64decode(PRIOR_TERMINAL_B64, validate=True)
    if hashlib.sha256(terminal_raw).hexdigest() != PRIOR_TERMINAL_SHA:
        raise ValueError("original terminal SDK pin differs")
    terminal_sdk = json.loads(terminal_raw)
    terminal = json.loads(next(item["text"] for item in terminal_sdk["content"] if item["type"] == "text"))
    if (terminal_sdk.get("isError") or terminal["job_id"] != "1a1cf155b58-2564-197e"
            or terminal["state"] != "failed" or terminal["exit_code"] != 1 or terminal["timed_out"]
            or terminal["cancelled"] or not terminal["output_complete"] or not terminal["output_durable"]
            or not terminal["terminal_publication_confirmed"] or any(terminal["log_truncated"].values())):
        raise ValueError("original job has no complete authoritative failed terminal")
    raw = (ORIGINAL / "RESULT.json").read_bytes()
    if pin(raw)["sha256"] != "d108ba62295c0c9bbf23225db219ef35801bca365d56702eac58e55037a01a15":
        raise ValueError("original complete RESULT differs")
    prior = json.loads(raw)
    phases = {phase["name"]: phase for phase in prior["phases"]}
    if (set(phases) != {"fetch-final", "new-worktree", "verified-v8", "native-binaries", "capture-precompile", "final-format"}
            or prior["status"] != "incomplete" or prior["arms"] != [] or prior["new_controls_passed"] is not False
            or not prior["source_unchanged"] or not prior["binary_bytes_unchanged"]
            or prior["source_before"] != prior["source_after"] or prior["source_after"] != require_source()
            or not prior.get("finished_unix_ns") or terminal["at_unix_ms"] * 10**6 < prior["finished_unix_ns"]
            or prior["model_generation_count"] is not None or prior["physical_native_http_count"] is not None
            or phases["native-binaries"]["exit_code"] != 0 or phases["capture-precompile"]["exit_code"] != 2
            or phases["final-format"]["exit_code"] != 0):
        raise ValueError("original result does not establish the exact unexecuted-stage boundary")
    original_archive = ROOT / "capture-bbbcc630-01.tar.xz"
    if digest(original_archive) != {"bytes": 68348, "sha256": "7ccd0c04afabd3faa37a21f8431b3791235e3a1f963bb658cc4e29e729276b8d"}:
        raise ValueError("original completed archive changed")
    with tarfile.open(original_archive, "r:xz") as archive:
        if archive.extractfile("RESULT.json").read() != raw:
            raise ValueError("original archived RESULT differs")
        v8_raw = archive.extractfile("v8.env").read()
    for arm in ARMS:
        # These directories precede every native/adapter side effect in the original runner.
        # Absence is used only with the original args, failed terminal, complete phase chain and zero arms.
        if (ORIGINAL / arm["arm"]).exists():
            raise ValueError("an original arm directory already exists; no reissue")
    previous = OUT / "prior-originals"
    previous.mkdir()
    (previous / "TERMINAL.original-sdk-payload.json").write_bytes(terminal_raw)
    (previous / "RESULT.json").write_bytes(raw)
    (previous / "reviewed-helper-source.py").write_bytes(runner)
    (previous / "v8.env").write_bytes(v8_raw)
    for name in ("verified-v8", "native-binaries", "capture-precompile", "final-format"):
        receipt = document(ORIGINAL / (name + ".receipt.json"))
        if receipt != phases[name]["receipt"]:
            raise ValueError("original stage receipt differs: " + name)
        if (receipt["timed_out"] or receipt["observed_passed_tests"] != 0 or receipt["observed_failed_tests"] != 0
                or any(receipt[side]["commit"] != COMMIT or receipt[side]["tree"] != TREE or receipt[side]["dirty"] for side in ("before", "after"))):
            raise ValueError("prior stage does not bind exact clean source and zero executed tests")
        log = ORIGINAL / receipt["log_file"]
        if digest(log)["sha256"] != receipt["log_sha256"]:
            raise ValueError("original stage log changed: " + name)
        shutil.copyfile(log, previous / log.name)
        shutil.copyfile(ORIGINAL / (name + ".receipt.json"), previous / (name + ".receipt.json"))
    blocker = phases["capture-precompile"]["receipt"]
    blocker_raw = (ORIGINAL / blocker["log_file"]).read_bytes()
    if (pin(blocker_raw) != {"bytes": 461, "sha256": "6efde22e243471a30ea88fba2f12bc2e557f1f5a777f4cca2f42ae5d721de3b5"}
            or b"the argument '--no-fail-fast' cannot be used with '--no-run'" not in blocker_raw
            or blocker["command_exit_code"] != 2 or phases["native-binaries"]["receipt"]["command_exit_code"] != 0):
        raise ValueError("the original failure was not the known nextest argument conflict")
    RESULT["prior"] = {"job_id": terminal["job_id"], "result": pin(raw), "terminal_sdk": pin(terminal_raw),
        "archive": digest(original_archive), "precompile_error": pin(blocker_raw), "old_arm_directories_absent": True,
        "original_counts_preserved_as_null": True, "completed_native_build_repeated": False}
    RESULT["source_before"] = require_source()
    if digest(PROFILE)["sha256"] != PROFILE_SHA:
        raise ValueError("frozen profile differs")
    PROFILE_VALUE = document(PROFILE)
    shutil.copyfile(PROFILE, OUT / "frozen-profile.json")
    repair_path, deps_path = OLD / "clang-resources-v1/REPAIR.json", OLD / "build-dependencies/DEPENDENCIES.json"
    repair, deps = document(repair_path), document(deps_path)
    if repair["status"] != "prepared" or repair["system_packages_modified"] or not deps["protoc_usable"]:
        raise ValueError("known task-local prerequisites unavailable")
    if digest(Path(repair["stddef_header"]["path"]))["sha256"] != repair["stddef_header"]["sha256"]:
        raise ValueError("task-local Clang resource changed")
    ENV.update(repair["build_environment"], PROTOC=deps["protoc_path"], LD_LIBRARY_PATH=deps["protoc_libraries"])
    for line in v8_raw.decode().splitlines():
        key, value = line.split("=", 1)
        if key not in {"RUSTY_V8_ARCHIVE", "RUSTY_V8_SRC_BINDING_PATH"}:
            raise ValueError("unexpected original V8 export")
        ENV[key] = value
    BINARIES = prior["binaries_before"]
    if BINARIES != prior["binaries_after"] or set(BINARIES) != {"codex", "hepta-infer-worker"}:
        raise ValueError("original binary postimages differ")
    for name, value in BINARIES.items():
        path = Path(value["path"])
        if digest(path) != value["pin"]:
            raise ValueError("original successful binary changed: " + name)
        ENV["CARGO_BIN_EXE_" + name] = str(path)
    RESULT["binaries_before"] = BINARIES
    postimages = prior["formatted_postimages"]
    for path, expected in postimages.items():
        if digest(SOURCE / path) != {key: expected[key] for key in ("bytes", "sha256")}:
            raise ValueError("formatted postimage changed: " + path)
    RESULT["formatted_postimages"] = postimages
    ADAPTER_PINS = prior["adapter_source_pins"]
    if ADAPTER_PINS != {name: digest(SOURCE / "scripts" / name) for name in ADAPTER_PINS}:
        raise ValueError("adapter source postimages differ")
    RESULT["adapter_source_pins"] = ADAPTER_PINS
    RESULT["build_environment"] = prior["build_environment"]
    write(OUT / "PLAN.json", {"source_commit": COMMIT, "source_tree": TREE, "codex_rs_tree": CODEX_TREE,
        "arms": ARMS, "continuation_arm_root": str(OUT), "prior_unused_arm_root": str(ORIGINAL),
        "original_request_ids_unchanged": True, "prior_arm_effects_absent_bound_to_completed_original_job": True,
        "phase": "capture", "maximum_attempts_per_arm": 1, "model_generation_authorized": False,
        "controls": sorted(ACK_CASES | {CLI_CASE}), "capture_case": CAPTURE_CASE,
        "precompile": "the required two ack controls compile the identical Agentd --lib test executable before any listener",
        "nextest_retries": 0, "nextest_timeout_policy_changed": False, "listener_timeout_seconds": 120,
        "max_input_tokens": 1024, "max_output_tokens": 32, "post_capture_token_only_predeclared": True})
    import __main__
    (OUT / "submitted.py").write_text(__main__.SUBMITTED_PAYLOAD)
    ok = command("ack-controls", ["just", "test", "--locked", "-p", "codex-hepta-agentd", "--lib", "-E",
        " | ".join("test(=" + name + ")" for name in sorted(ACK_CASES)), "--no-capture", "--retries", "0"], expected=ACK_CASES)
    if ok:
        ok = command("cli-control", ["just", "test", "--locked", "-p", "codex-hepta-infer-worker-host", "--bin", "hepta-infer-worker",
            "-E", "test(=" + CLI_CASE + ")", "--no-capture", "--retries", "0"], expected={CLI_CASE})
    RESULT["new_controls_passed"] = ok
    if ok:
        RESULT["precompile_completed_at_unix_ns"] = time.time_ns()
        save()
        for arm in ARMS:
            run_arm(arm)
        if all(entry["status"] == "joined" for entry in RESULT["arms"]):
            RESULT["model_generation_count"] = sum(entry["model_generation_count"] for entry in RESULT["arms"])
            RESULT["physical_native_http_count"] = sum(entry["physical_native_http_count"] for entry in RESULT["arms"])
        left, right = (OUT / arm / "adapter/http-0001/body.bin" for arm in ("reader-off", "withhold"))
        if left.is_file() and right.is_file():
            a, b = left.read_bytes(), right.read_bytes()
            ja, jb = json.loads(a), json.loads(b)
            RESULT["reader_off_vs_withhold"] = {"raw_body_equal": a == b, "parsed_json_equal": ja == jb,
                "left": pin(a), "right": pin(b), "differing_top_level_fields": sorted(key for key in set(ja) | set(jb) if ja.get(key) != jb.get(key)),
                "no_normalization_or_dynamic_field_removal": True}
        try:
            token_only()
        except BaseException as error:
            RESULT["token_preflight_error"] = type(error).__name__ + ": " + str(error)
            (OUT / "token-preflight-exception.txt").write_text(traceback.format_exc())
        RESULT["scoped_fix_passed"] = command("scoped-fix", ["just", "fix", "--locked", "-p", "codex-hepta-agentd", "-p", "codex-hepta-infer-worker-host"], final=True)
    RESULT["format_passed"] = command("final-format", ["just", "fmt", "--base", BASE], timeout=900, final=True)
    RESULT["source_after"] = identity()
    (OUT / "source-rewrites.patch").write_bytes(subprocess.check_output(["git", "-C", str(SOURCE), "diff", "--binary", "HEAD"], env=ENV))
    RESULT["source_unchanged"] = RESULT["source_before"] == RESULT["source_after"]
    RESULT["binaries_after"] = {name: {"path": value["path"], "pin": digest(Path(value["path"]))} for name, value in BINARIES.items()}
    RESULT["binary_bytes_unchanged"] = RESULT["binaries_after"] == BINARIES
    RESULT["status"] = "capture_controls_passed" if (ok and len(RESULT["arms"]) == 4
        and all(entry["status"] == "joined" for entry in RESULT["arms"])
        and RESULT.get("scoped_fix_passed") and RESULT["format_passed"] and RESULT["source_unchanged"]
        and RESULT["binary_bytes_unchanged"]) else "incomplete"
except BaseException as error:
    RESULT.update(status="incomplete", error=type(error).__name__ + ": " + str(error))
    (OUT / "exception.txt").write_text(traceback.format_exc())
finally:
    RESULT["finished_unix_ns"] = time.time_ns()
    save()
    selected = [path for path in OUT.rglob("*") if path.is_file() and not path.is_symlink()
        and not any(part in {"home", "cache", "work", "token-home", "__pycache__"} for part in path.relative_to(OUT).parts)]
    write(OUT / "MEMBER_MANIFEST.json", {str(path.relative_to(OUT)): digest(path) for path in selected})
    archive = ROOT / "capture-bbbcc630-02.tar.xz"
    with tarfile.open(archive, "x:xz") as stream:
        for path in selected + [OUT / "MEMBER_MANIFEST.json"]:
            stream.add(path, arcname=str(path.relative_to(OUT)), recursive=False)
    publication = {"archive": str(archive), **digest(archive), "result": str(OUT / "RESULT.json"), "status": RESULT["status"]}
    write(ROOT / "CAPTURE_BBBCC630_02_PUBLICATION.json", publication)
    print(json.dumps(publication, indent=2))
if RESULT["status"] != "capture_controls_passed":
    raise SystemExit(1)
