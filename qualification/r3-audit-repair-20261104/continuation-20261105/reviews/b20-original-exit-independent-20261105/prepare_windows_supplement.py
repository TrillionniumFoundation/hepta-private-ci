"""Re-open already retained original Windows artifacts; runs no product tests."""
import hashlib
import importlib.util
import json
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import zstandard

BASE = Path(__file__).resolve().parent
WORK = BASE.parents[1]
ORIGINAL = WORK / "research-audit/published-5b633-ci-20261105/terminal/main-win-shard2-127339255880"
OUT = BASE / "windows"


def ident(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == data, str(path)
    else:
        path.write_bytes(data)


def js(path, value):
    save(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def main():
    zip_path = ORIGINAL / "artifact-13431285250/artifact.zip"
    zip_bytes = zip_path.read_bytes()
    assert ident(zip_bytes)["sha256"] == "d0dd2347f5be91ae1f445d21e892ea5d4559499dc8e2f71554ce0ce2bb93ba85"
    prefix = "selected-target-test-logs/invocation-pj7csqys/"
    zip_rows = []
    with zipfile.ZipFile(zip_path) as z:
        assert z.testzip() is None
        assert len(z.infolist()) == 54
        for info in z.infolist():
            data = z.read(info.filename)
            assert len(data) == info.file_size
            zip_rows.append({"member": info.filename, "crc32": f"{info.CRC:08x}", **ident(data)})
            if info.filename == prefix + "manifest.json" or "/targets/0000/" in info.filename:
                save(OUT / "zip-members" / info.filename, data)
        compressed_name = "execution-log-test-test-windows-shard-3215.zst"
        compressed = z.read(compressed_name)
    manifest = json.loads((OUT / "zip-members" / prefix / "manifest.json").read_bytes())
    assert manifest["complete_for_selected_targets"] and manifest["errors"] == []
    for row in manifest["files"]:
        if not row["archive_relative_path"].startswith("targets/0000/"):
            continue
        raw = (OUT / "zip-members" / prefix / row["archive_relative_path"]).read_bytes()
        assert len(raw) == row["bytes"] and hashlib.sha256(raw).hexdigest() == row["sha256"]
    names = [v["name"] for v in json.loads((BASE / "originals/app-remote-fixed-originals-status.json").read_bytes())["testcases"]]
    selected = {name: [] for name in names}
    wrappers = []
    for path in sorted((OUT / "zip-members" / prefix / "targets/0000").rglob("*.log")):
        raw = path.read_bytes()
        wrapper = path.with_suffix(".xml")
        xml = ET.fromstring(wrapper.read_bytes())
        system_out = xml.find(".//system-out")
        assert system_out is not None
        text = raw.decode("utf-8")
        assert system_out.text == text.replace("\x1b", "?")
        wrappers.append({"raw": str(path.relative_to(OUT)), **ident(raw), "wrapper": str(wrapper.relative_to(OUT)), "wrapper_identity": ident(wrapper.read_bytes()), "entire_raw_equals_wrapper_system_out": system_out.text == text, "only_XML_invalid_ESC_0x1B_replaced_by_question_mark": True, "ESC_character_count": text.count("\x1b"), "ESC_byte_offsets": [i for i, b in enumerate(raw) if b == 27]})
        for line_no, line in enumerate(raw.decode().splitlines(), 1):
            for name in names:
                if line.startswith(f"test {name} ... "):
                    selected[name].append({"member": str(path.relative_to(OUT / "zip-members")), "line": line_no, "physical_line": line, "result": line.split(" ... ", 1)[1]})
    assert len(wrappers) == 16
    assert all(len(rows) == 1 and rows[0]["result"] == "ok" for rows in selected.values())

    donor = WORK / "research-audit/b10-original-contracts-20261105"
    save(OUT / "upstream-b10-project-originals.py.source.txt", (donor / "project_originals.py").read_bytes())
    save(OUT / "bazel-9.3.0-spawn.proto.source.txt", (donor / "primary/bazel-9.3.0-spawn.proto.source.txt").read_bytes())
    save(OUT / "bazel-9.3.0-spawn-proto-GitHub-original-response.json", (donor / "primary/bazel-9.3.0-spawn-proto-GitHub-original-response.json").read_bytes())
    spec = importlib.util.spec_from_file_location("b20_original_compact_parser", donor / "project_originals.py")
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    decoder = zstandard.ZstdDecompressor().decompressobj()
    compact = decoder.decompress(compressed) + decoder.flush()
    assert decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
    pos = count = 0
    frames = []
    while pos < len(compact):
        start = pos
        size, pos = parser.varint(compact, pos)
        assert pos + size <= len(compact)
        fields = parser.fields(compact[pos:pos + size])
        pos += size
        count += 1
        if 7 not in fields:
            continue
        spawn = parser.fields(parser.first(fields, 7))
        if parser.first(spawn, 7) != b"//codex-rs/app-server:app-server-all-test" or parser.first(spawn, 8) != b"TestRunner":
            continue
        env = {}
        for item in spawn.get(2, []):
            fields = parser.fields(item)
            key, value = parser.first(fields, 1).decode(), parser.first(fields, 2).decode()
            assert key not in env
            env[key] = value
        args = [v.decode() for v in spawn.get(1, [])]
        binary = args[0].replace("\\", "/").rsplit("/", 1)[-1]
        assert binary in ["tw.exe", "xml.exe"]
        frame_name = f"frames/action-{len(frames):02d}.protobuf"
        save(OUT / frame_name, compact[start:pos])
        frames.append({"entry_number": count, "start_byte": start, "end_byte": pos, "frame": frame_name, "frame_identity": ident(compact[start:pos]), "role": "actual_test_action" if binary == "tw.exe" else "wrapper_xml_generation", "args": args, "environment_keys": sorted(env), "observed_environment": {k: env[k] for k in ["TEST_SHARD_INDEX", "TEST_TOTAL_SHARDS", "TEST_TARGET", "TEST_TIMEOUT", "TEST_BINARY", "TEST_RUN_NUMBER", "TEST_RANDOM_SEED", "RUST_TEST_THREADS"] if k in env}, "CODEX_SANDBOX_NETWORK_DISABLED_present_case_insensitive": any(k.upper() == "CODEX_SANDBOX_NETWORK_DISABLED" for k in env), "exit_code": parser.first(spawn, 9, 0), "status": parser.first(spawn, 10).decode(), "runner": parser.first(spawn, 11).decode(), "cache_hit": bool(parser.first(spawn, 12, 0)), "timeout_millis": parser.first(spawn, 17, 0)})
    tests = [row for row in frames if row["role"] == "actual_test_action"]
    assert pos == len(compact)
    assert len(frames) == 32 and len(tests) == 16
    assert {int(row["observed_environment"]["TEST_SHARD_INDEX"]) for row in tests} == set(range(16))
    assert all(row["exit_code"] == 0 and row["runner"] == "local" and not row["cache_hit"] and row["timeout_millis"] == 900000 and not row["CODEX_SANDBOX_NETWORK_DISABLED_present_case_insensitive"] for row in tests)
    log = (ORIGINAL / "job.log").read_bytes()
    assert ident(log)["sha256"] == "1b7114b1ff639cc2cd5d38e5d53326e16796ffb1516fef1e960d8df371c3de65"
    save(OUT / "job.log", log)
    lines = log.decode().splitlines()
    terminal = [line for line in lines if "//codex-rs/app-server:app-server-all-test" in line and "PASSED" in line]
    assert len(terminal) == 1
    assert "9063c52a063b6f26c48e9418f6d8dbd14e9e06ff" in log.decode()
    js(OUT / "original-selection-and-execution-verification.json", {
        "schema": "b20-existing-windows-full-original-supplement-v1",
        "job_id": 127339255880, "artifact_id": 13431285250,
        "checkout_merge": "9063c52a063b6f26c48e9418f6d8dbd14e9e06ff",
        "original_zip": ident(zip_bytes), "all54_members_CRC_read": True,
        "members": zip_rows, "selected_target": "//codex-rs/app-server:app-server-all-test",
        "target_terminal_original_line": terminal[0], "selected_19_final_rows": selected,
        "wrappers": wrappers, "compressed_execution_log": {"member": compressed_name, **ident(compressed)},
        "decompressed_execution_log": ident(compact), "complete_entries": count,
        "all_bytes_consumed": pos, "selected_actions": frames,
        "real_test_actions": len(tests), "separate_xml_actions": len(frames) - len(tests),
        "all_real_actions_local_noncache_exit0_original_900000ms": True,
        "primary_schema_git_blob": "19f68f22a4d62c4fd1aa28fd1c7c0217aa6a7cb0",
        "archive_reuse": "Full ZIP and job are already preserved by published V7 main-Windows 85-part transport. This package retains full selected target raw/XML members and original selected protobuf frames without duplicating the ZIP.",
        "scope": "Current 5b Windows original target supplement. Earlier historical 19+3 attempt/FLAKY observations are separate and are not assigned to this selected archive. No current-head whole-workspace or GNU/musl final-platform pass.",
        "new_native_execution": False,
    })
    print(json.dumps({"selected_cases": 19, "selected_logs": len(wrappers), "actions": len(tests), "compact_entries": count, "compact_bytes": len(compact), "output": str(OUT / "original-selection-and-execution-verification.json")}))


if __name__ == "__main__":
    main()
