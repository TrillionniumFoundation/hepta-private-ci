"""Read the exact failed binary's symbols/prologues; never execute Rust."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import traceback

SOURCE = "cc22a69972d029d3ef28d49096f396eb5214c616"
TREE = "827fb70ed75d30c48d4693cbd0d23ea04f5744da"
REPO = Path("/home/qian-qi/hepta-learn-common-20261112-037c")
EVIDENCE = Path("/home/qian-qi/hepta-learn-037c-evidence")
GDB_RECORDS = EVIDENCE / "stack-diagnostic-cc22-v1"
RECORDS = EVIDENCE / "stack-static-prologues-cc22-v1"
BINARY = Path("/data/hepta-learn-037c-20261112/target-cache-v1/debug/deps/codex_hepta_agentd-0bb720b95785b5fd")
BINARY_BYTES = 282306816
BINARY_SHA256 = "670f90e41e4313efdf00d5452e23ea1b0359c9942b0d7c6092b332416136ba04"
AGENT = "codex_hepta_agentd::runtime::tests::circuit_task_ingress::q24_tests::"
PROVIDER = AGENT + "model_selection_owner::original::evaluation_provider::"
PANEL = PROVIDER + "panel_members::"
TARGETS = [
    PANEL + "PanelFixture::completed_for_publication",
    PANEL + "PanelFixture::completed",
    PANEL + "completed_member",
    PANEL + "original_panel_reads_actual_b_and_retention_with_full_original_signatures",
    PROVIDER + "preregistered_for_publication",
    AGENT + "support::admission",
    "codex_hepta_agentd::runtime::tests::attach_runtime_prerequisites",
    "codex_hepta_agentd::neuron_cell_evaluation::tests::original_provider::panel_members::PanelMemberFixture::complete",
    "codex_hepta_memory::cognitive_store::CognitiveStore::open",
]


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save(name, value):
    with (RECORDS / name).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")


def source_metadata():
    def git(*args):
        return subprocess.check_output(
            ["git", "--no-optional-locks", *args], cwd=REPO
        ).decode().strip()
    return {
        "commit": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "status": git("status", "--porcelain=v1", "--untracked-files=all"),
        "cargo_lock_sha256": sha(REPO / "codex-rs/Cargo.lock"),
    }


RECORDS.mkdir(mode=0o700, exist_ok=False)
result = {
    "schema": 1,
    "diagnostic_only": True,
    "executed_rust_tests": False,
    "compiled_or_formatted": False,
    "acceptance_pass": False,
    "installed_tools": False,
    "source": SOURCE,
    "tree": TREE,
    "started_at": now(),
}
status = 1
before = None
try:
    admission = json.loads((GDB_RECORDS / "debug-admission.json").read_text())
    terminal = json.loads((GDB_RECORDS / "result.json").read_text())
    assert terminal["source_unchanged"] is True
    assert admission["source_before"]["commit"] == SOURCE
    assert admission["source_before"]["tree"] == TREE
    assert admission["binary"]["path"] == str(BINARY)
    assert admission["binary"]["bytes"] == BINARY_BYTES
    assert admission["binary"]["sha256"] == BINARY_SHA256
    assert BINARY.stat().st_size == BINARY_BYTES and sha(BINARY) == BINARY_SHA256
    gdb_log = GDB_RECORDS / "gdb.raw.log"
    assert gdb_log.stat().st_size == terminal["gdb_log"]["bytes"]
    assert sha(gdb_log) == terminal["gdb_log"]["sha256"]
    before = source_metadata()
    assert before["commit"] == SOURCE and before["tree"] == TREE and before["status"] == ""
    save("source-metadata-before.json", before)
    tools = {name: shutil.which(name) for name in ("nm", "objdump")}
    if not all(tools.values()):
        result.update(status="required_readonly_tool_unavailable", tools=tools)
        raise RuntimeError("nm/objdump missing; no installation attempted")
    environment = dict(os.environ, LC_ALL="C")
    versions = {}
    for name, path in tools.items():
        versions[name] = {
            "path": path,
            "sha256": sha(Path(path)),
            "version": subprocess.check_output([path, "--version"], env=environment).decode(),
        }
    save("admission.json", {
        "binary": admission["binary"],
        "gdb_result_sha256": sha(GDB_RECORDS / "result.json"),
        "gdb_log": terminal["gdb_log"],
        "source_metadata": before,
        "targets": TARGETS,
        "tools": versions,
        "prologue_max_bytes_per_symbol": 512,
        "scope": "Original binary static text only. No inferior process, Rust test, rebuild, stack change or deadline change.",
    })
    command = [tools["nm"], "--print-size", "--numeric-sort", "--defined-only", "--demangle", str(BINARY)]
    save("symbol-command.json", {"command": command, "output_retention": "Only exact target names and their closure symbols; nonmatching original nm lines are deliberately not archived."})
    pattern = re.compile(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+([tT])\s+(.+)$")
    symbols = []
    with (RECORDS / "nm.stderr.log").open("xb") as stderr, (RECORDS / "matched-symbols.raw.txt").open("xb") as matched:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=stderr, env=environment)
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.decode("utf-8", errors="strict").rstrip("\n")
            found = pattern.match(line)
            if not found:
                continue
            address, size, kind, name = found.groups()
            target = next((target for target in TARGETS if name == target or name.startswith(target + "::{{closure}}")), None)
            if target is None:
                continue
            matched.write(raw)
            symbols.append({"target": target, "name": name, "address": int(address, 16), "symbol_text_bytes": int(size, 16), "kind": kind})
        assert process.wait() == 0, "nm failed; original stderr retained"
    assert 1 <= len(symbols) <= 64, len(symbols)
    for required in TARGETS[:2] + [PROVIDER + "preregistered_for_publication", AGENT + "support::admission"]:
        assert any(item["target"] == required for item in symbols), required
    (RECORDS / "prologues").mkdir()
    for index, symbol in enumerate(symbols):
        stop = symbol["address"] + min(512, symbol["symbol_text_bytes"])
        assert stop > symbol["address"]
        command = [tools["objdump"], "--disassemble", "--demangle", "--start-address=" + hex(symbol["address"]), "--stop-address=" + hex(stop), str(BINARY)]
        output = subprocess.run(command, capture_output=True, env=environment, check=False)
        path = RECORDS / "prologues" / (f"{index:02d}.asm")
        path.write_bytes(output.stdout)
        (RECORDS / "prologues" / (f"{index:02d}.stderr.log")).write_bytes(output.stderr)
        assert output.returncode == 0, command
        symbol.update(prologue_path=str(path), prologue_bytes=len(output.stdout), prologue_sha256=sha(path), command=command)
    save("symbols.json", symbols)
    result.update(status="static_prologue_collection_complete", symbols=symbols, unmatched_targets=[target for target in TARGETS if not any(item["target"] == target for item in symbols)], binary_sha256_after=sha(BINARY))
    assert result["binary_sha256_after"] == BINARY_SHA256
    status = 0
except BaseException as error:
    result.setdefault("status", "static_diagnostic_error")
    result["error"] = repr(error)
    traceback.print_exc()
finally:
    if before is not None:
        after = source_metadata()
        save("source-metadata-after.json", after)
        result.update(source_metadata_before=before, source_metadata_after=after, source_metadata_unchanged=before == after)
        if before != after:
            status = 1
    result.update(finished_at=now(), exit_code=status)
    save("result.json", result)
    print(json.dumps(result, sort_keys=True, indent=2), flush=True)
sys.exit(status)
