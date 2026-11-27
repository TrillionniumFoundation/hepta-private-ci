import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

SOURCE = "a6717d7228045e6cb60532966f06e6e02c4a6abe"
TREE = "647b9e78151299c1e7de455eae9c530ca93b28c9"
REPO = Path("/home/qian-qi/hepta-learn-positive-ce434-20261112-3270-v1")
BASE = Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native")
NATIVE = BASE / "live-owners-full-a6717d722804-v1/result.json"
NATIVE_SHA256 = "98348f69ead79e7a2428680b822b5d419784e20f99de12c2f0d0f8892f5b1f71"
OUTER = BASE / "unified-a6717d722804-validation-v1/result.json"
OUTER_SHA256 = "3db7ed1f0760fadbf50a741600f9d877767ef26fb51bed7ee935d3b46c17ce60"
ELF = Path("/data/hepta-learn-ce434-runtime-20261112-v2/target/debug/deps/codex_hepta_agentd-0bb720b95785b5fd")
OUT = BASE / "static-frames-a6717d722804-v1"
ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"}
TOOLS = {"git": "/usr/bin/git", "nm": "/usr/bin/nm", "objdump": "/usr/bin/objdump"}
ORIGINAL = "codex_hepta_agentd::runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::"
PANEL = ORIGINAL + "evaluation_provider::panel_members::"
TARGETS = (
    ("PanelFixture.completed", PANEL + "PanelFixture::completed"),
    ("preregistered", ORIGINAL + "evaluation_provider::preregistered"),
    ("completed_member", PANEL + "completed_member"),
    ("PositiveFixture.ready", ORIGINAL + "PositiveFixture::ready"),
    ("PositiveFixture.ready_with_profile", ORIGINAL + "PositiveFixture::ready_with_profile"),
    ("PositiveFixture.ready_with_admission", ORIGINAL + "PositiveFixture::ready_with_admission"),
    ("HostFixture.new", PANEL + "evaluation_host::HostFixture::new"),
    ("original_panel_test", PANEL + "original_panel_reads_actual_b_and_retention_with_full_original_signatures"),
)
MAX_SYMBOLS = 64
MAX_LINE = 65536
PROLOGUE_BYTES = 512
MAX_PROLOGUE_OUTPUT = 524288

def require(value, message):
    if not value:
        raise RuntimeError(message)

def identity(value):
    return {key: getattr(value, key) for key in (
        "st_dev", "st_ino", "st_mode", "st_nlink", "st_uid", "st_gid",
        "st_size", "st_mtime_ns", "st_ctime_ns"
    )}

def same_file(path, descriptor, expected):
    require(identity(os.lstat(path)) == expected, "path identity changed")
    require(identity(os.fstat(descriptor)) == expected, "open file identity changed")

def digest_fd(descriptor):
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while True:
        block = os.read(descriptor, 1024 * 1024)
        if not block:
            break
        digest.update(block)
    return digest.hexdigest()

def open_stable(path, maximum):
    observed = os.lstat(path)
    require(stat.S_ISREG(observed.st_mode), "input is not a regular non-symlink file")
    require(0 < observed.st_size <= maximum, "input size is outside diagnostic bound")
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        expected = identity(observed)
        same_file(path, descriptor, expected)
        digest = digest_fd(descriptor)
        same_file(path, descriptor, expected)
        return descriptor, expected, digest
    except BaseException:
        os.close(descriptor)
        raise

def pinned_json(path, expected_hash, expected_size):
    descriptor, observed, digest = open_stable(path, 1048576)
    try:
        require(observed["st_size"] == expected_size and digest == expected_hash,
                "terminal record does not match original observed bytes")
        os.lseek(descriptor, 0, os.SEEK_SET)
        raw = bytearray()
        while True:
            block = os.read(descriptor, 65536)
            if not block:
                break
            raw.extend(block)
        same_file(path, descriptor, observed)
        require(hashlib.sha256(raw).hexdigest() == expected_hash, "record changed while parsing")
        return json.loads(raw), {"path": str(path), "sha256": digest, "identity": observed}
    finally:
        os.close(descriptor)

def write_json(name, value):
    with (OUT / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")

def capture(command):
    require(command[0] in TOOLS.values(), "unexpected executable")
    process = subprocess.Popen(command, cwd=REPO, env=ENV, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        stdout, stderr = process.communicate()
    except BaseException:
        try:
            process.communicate()
        finally:
            process.wait()
        raise
    process.wait()
    result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    require(len(result.stdout) <= MAX_PROLOGUE_OUTPUT, "bounded command output exceeded")
    require(len(result.stderr) <= MAX_PROLOGUE_OUTPUT, "bounded command stderr exceeded")
    return result

def source_state():
    base = [TOOLS["git"], "--no-optional-locks", "-c", "core.fsmonitor=false"]
    result = {}
    for key, arguments in (
        ("head", ["rev-parse", "HEAD"]),
        ("tree", ["rev-parse", "HEAD^{tree}"]),
        ("status", ["status", "--porcelain=v1", "--untracked-files=all"]),
    ):
        value = capture(base + arguments)
        require(value.returncode == 0, "read-only git command failed")
        result[key] = value.stdout.decode("utf-8").strip()
    require(result == {"head": SOURCE, "tree": TREE, "status": ""}, "source is not exact clean a671")
    return result

def family(name):
    for label, prefix in TARGETS:
        if name == prefix or name.startswith(prefix + "::"):
            return label
    return None

def nm_rows(demangle, consume, descriptor, observed):
    same_file(ELF, descriptor, observed)
    command = [TOOLS["nm"], "--defined-only", "--print-size", "--format=posix",
               "--demangle=rust" if demangle else "--no-demangle", "--", str(ELF)]
    label = "nm-demangled" if demangle else "nm-raw"
    long_line = False
    with (OUT / (label + ".stderr")).open("xb") as errors:
        process = subprocess.Popen(command, cwd=REPO, env=ENV, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=errors)
        require(process.stdout is not None, "nm stdout missing")
        parse_error = None
        while True:
            line = process.stdout.readline(MAX_LINE + 1)
            if not line:
                break
            if len(line) > MAX_LINE or not line.endswith(b"\n"):
                long_line = True
                while line and not line.endswith(b"\n"):
                    line = process.stdout.readline(MAX_LINE + 1)
                continue
            if parse_error is not None:
                continue
            try:
                text = line.decode("utf-8", errors="strict").rstrip("\n")
                match = re.fullmatch(r"(.+?)\s+([TtWw])\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)", text)
                if match:
                    consume(match.group(1), match.group(2), int(match.group(3), 16), int(match.group(4), 16))
            except Exception as error:
                parse_error = error
        process.stdout.close()
        code = process.wait()
    same_file(ELF, descriptor, observed)
    require(code == 0, label + " did not succeed")
    require(not long_line, label + " had an overlong or incomplete symbol line")
    if parse_error is not None:
        raise parse_error
    return {"argv": command, "exit_code": code, "stderr_file": label + ".stderr"}

def stack_observations(text):
    observations = []
    instruction_count = 0
    for line in text.splitlines():
        match = re.match(r"^\s*([0-9a-fA-F]+):\s+(\S+)(?:\s+(.*))?$", line)
        if not match:
            continue
        instruction_count += 1
        opcode, operands = match.group(2), (match.group(3) or "")
        if "%rsp" in operands or "probestack" in operands or opcode.startswith("push"):
            item = {"address": "0x" + match.group(1), "instruction": opcode + " " + operands}
            immediate = re.fullmatch(r"\$0x([0-9a-fA-F]+),%rsp", operands)
            if opcode in ("sub", "subq") and immediate:
                item["rsp_subtract_bytes_per_instruction_execution"] = int(immediate.group(1), 16)
            target = re.fullmatch(r"-0x([0-9a-fA-F]+)\(%rsp\),%r(?:10|11)", operands)
            if opcode in ("lea", "leaq") and target:
                item["observed_probe_target_delta_bytes"] = int(target.group(1), 16)
            observations.append(item)
    return {"instruction_count_in_bounded_slice": instruction_count,
            "stack_related_instructions": observations,
            "computed_total_frame_bytes": None,
            "interpretation": "Immediate operands only. Loops, probes, calls, dynamic allocation and simultaneous caller frames are not summed. Static instruction evidence is not peak stack usage."}

def main():
    OUT.mkdir(mode=0o700, parents=False, exist_ok=False)
    result = {"schema": "hepta.learn.static-frame-diagnostic.v1", "state": "preparing",
              "source_sha": SOURCE, "source_tree": TREE, "elf_path": str(ELF),
              "target_executed": False, "process_attached": False, "signals_sent": False,
              "tests_executed": 0, "authority_created": False}
    descriptor = None
    try:
        missing = [name for name, path in TOOLS.items()
                   if not os.path.isfile(path) or not os.access(path, os.X_OK)]
        if missing:
            result.update(state="unavailable", missing_tools=missing)
            return 2
        result["source_before"] = source_state()
        native, result["native_terminal"] = pinned_json(NATIVE, NATIVE_SHA256, 51057)
        outer, result["outer_terminal"] = pinned_json(OUTER, OUTER_SHA256, 2396)
        require(native["source_sha"] == SOURCE and native["source_tree"] == TREE,
                "native source pin differs")
        require(native["state"] == "failed" and native["source_after"] == SOURCE
                and native["source_status_after"] == "", "native terminal is not original clean failure")
        require(native["native_tests_executed"] == 201
                and native["owner_coverage"]["exact_selected_cases"] is True,
                "native coverage is not the original exact 201")
        require(native["native_exit_code"] == 100 and native["collection_exit_code"] == 1,
                "native terminal exit differs")
        require(outer["state"] == "failed" and outer["source_after"] == SOURCE
                and outer["source_status_after"] == "", "outer terminal is not original clean failure")
        descriptor, observed, digest = open_stable(ELF, 536870912)
        os.lseek(descriptor, 0, os.SEEK_SET)
        require(os.read(descriptor, 4) == b"\x7fELF", "observed file is not ELF")
        result["elf_observation"] = {"identity": observed, "sha256": digest,
                                    "preexisting_hash_pin": None,
                                    "association": "Observed at the sole Root-listed owned test artifact path after the pinned terminal. This is not a source-to-binary attestation."}
        selected = {}
        overflow = False
        def choose(name, kind, address, size):
            nonlocal overflow
            label = family(name)
            if label is None:
                return
            key = (address, size)
            if key not in selected:
                if len(selected) >= MAX_SYMBOLS:
                    overflow = True
                    return
                selected[key] = {"address": address, "size": size, "names": [], "original_mangled_names": []}
            require(len(selected[key]["names"]) < 16, "demangled alias bound exceeded")
            selected[key]["names"].append({"family": label, "demangled": name, "type": kind})
        result["nm_demangled"] = nm_rows(True, choose, descriptor, observed)
        require(not overflow, "selected symbol bound exceeded; no expansion permitted")
        require(bool(selected), "no exact requested symbol prefix found")
        def raw(name, kind, address, size):
            if (address, size) in selected:
                names = selected[(address, size)]["original_mangled_names"]
                require(len(names) < 16, "symbol alias bound exceeded")
                names.append({"name": name, "type": kind})
        result["nm_raw"] = nm_rows(False, raw, descriptor, observed)
        require(all(value["original_mangled_names"] for value in selected.values()),
                "original mangled name missing")
        rows = sorted(selected.values(), key=lambda value: (value["address"], value["size"]))
        write_json("symbols.json", rows)
        result["selected_symbol_count"] = len(rows)
        result["missing_requested_families"] = sorted(set(label for label, _ in TARGETS)
            - set(item["family"] for row in rows for item in row["names"]))
        result["functions"] = []
        for index, row in enumerate(rows):
            entry = dict(row)
            if row["size"] == 0:
                entry["state"] = "unavailable_zero_symbol_size"
                result["functions"].append(entry)
                continue
            same_file(ELF, descriptor, observed)
            stop = row["address"] + min(row["size"], PROLOGUE_BYTES)
            command = [TOOLS["objdump"], "-d", "--wide", "--no-show-raw-insn",
                       "--start-address=" + hex(row["address"]), "--stop-address=" + hex(stop),
                       "--", str(ELF)]
            value = capture(command)
            same_file(ELF, descriptor, observed)
            stem = "prologue-%03d" % index
            (OUT / (stem + ".txt")).write_bytes(value.stdout)
            (OUT / (stem + ".stderr")).write_bytes(value.stderr)
            entry.update(argv=command, exit_code=value.returncode,
                         prologue_file=stem + ".txt", prologue_sha256=hashlib.sha256(value.stdout).hexdigest(),
                         prologue_bytes=len(value.stdout), inspected_address_bytes=stop - row["address"])
            require(value.returncode == 0, "objdump did not succeed")
            entry["observations"] = stack_observations(value.stdout.decode("utf-8", errors="strict"))
            result["functions"].append(entry)
        same_file(ELF, descriptor, observed)
        final_hash = digest_fd(descriptor)
        same_file(ELF, descriptor, observed)
        require(final_hash == digest, "ELF bytes changed during static inspection")
        result["elf_sha256_after"] = final_hash
        result["source_after"] = source_state()
        result["state"] = "observed_static_only"
        result["limits"] = ["No target execution, test rerun, stack/deadline change, process attachment or signals.",
                            "Only named symbol entry slices; no automatic whole-function disassembly.",
                            "Reserved bytes in a static frame are not peak stack use, recursion evidence or a causal proof.",
                            "Missing symbols, inlining and construction temporaries may leave the cause unresolved."]
        return 0
    except Exception as error:
        result["state"] = "rejected_or_unavailable"
        result["error_type"] = type(error).__name__
        result["error"] = str(error)
        return 2
    finally:
        if descriptor is not None:
            os.close(descriptor)
        write_json("result.json", result)
        print(json.dumps({"state": result["state"], "result": str(OUT / "result.json"),
                          "tests_executed": 0}, sort_keys=True))

if __name__ == "__main__":
    sys.exit(main())
