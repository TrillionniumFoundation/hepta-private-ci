#!/usr/bin/env python3
"""Run the original sealed Hepta owner on a private native guest fixture.

No caller disk, host block device, network, production grant or replacement
owner is accepted. The newly generated disk may contain qualification keys;
keep it private and never commit or publish it with source/evidence summaries.
"""
import argparse
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import shutil
import stat
import struct
import subprocess
import sys
import time
import tomllib
import uuid

sys.dont_write_bytecode = True
MIB = 1024 * 1024
MAX_OWNER = 224 * MIB
MAX_KERNEL = 256 * MIB
MAX_SERIAL = 4 * MIB
MAX_ARCHIVE = 320 * MIB
MEMORY_MIB = 3072
ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"}


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def pinned(path, sha, limit):
    require(re.fullmatch(r"[0-9a-f]{64}", sha), "invalid SHA256 pin")
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= limit, "invalid bounded artifact")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    require(0 < len(data) <= limit and digest(data) == sha, "artifact SHA256 or size mismatch")
    return data


def command(argv, log, **kwargs):
    with log.open("xb") as stream:
        completed = subprocess.run(argv, stdout=stream, stderr=subprocess.STDOUT, **kwargs)
    require(completed.returncode == 0, f"command failed; actual log retained at {log}")


def load_desktop(root):
    sys.path.insert(0, str(root / "tests/kernel/control"))
    spec = importlib.util.spec_from_file_location("native_owner_source", root / "tests/kernel/control/run_queryabi_candidate_guest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def disk_fixture(output):
    path = output / "fixture.ext2"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.truncate(64 * MIB)
    tool = Path("/usr/sbin/mke2fs")
    argv = [str(tool), "-q", "-F", "-t", "ext2", "-b", "4096", "-I", "128", "-m", "0",
            "-O", "none,filetype,sparse_super,large_file", "-E", "lazy_itable_init=0",
            "-U", str(uuid.uuid4()), str(path)]
    command(argv, output / "fixture-create.log", timeout=30, env=ENV)
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
            and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size == 64 * MIB, "fixture identity differs")
    return path, {"path": str(path), "identity": [info.st_dev, info.st_ino, info.st_size, info.st_uid],
                  "creation_argv": argv, "before_sha256": file_digest(path), "tool_sha256": file_digest(tool),
                  "snapshot": "off", "host_block_device": False, "qualification_keys_may_be_present": True}


def initramfs(base, owner, replay):
    require(len(base) <= 8 * MIB and 0 < len(owner) <= MAX_OWNER, "initramfs inputs exceed bounds")
    with gzip.GzipFile(fileobj=io.BytesIO(base)) as archive:
        plain = archive.read(64 * MIB + 1)
    require(len(plain) <= 64 * MIB, "base initramfs inflate bound exceeded")
    entries = replay.unpack(plain, max_bytes=64 * MIB)
    require(replay.unpack(replay.pack(entries), max_bytes=64 * MIB) == entries, "base cpio roundtrip differs")
    require(sum(name.lstrip("./") == "test" and stat.S_ISDIR(fields[1]) for name, fields, _ in entries) == 1,
            "base must have exactly one test directory")
    name = "test/g1d-init"
    require(all(old.lstrip("./") != name for old, _, _ in entries), "native initial entry already exists")
    fields = [max(fields[0] for _, fields, _ in entries) + 1, 0o100755, 0, 0, 1, 0,
              len(owner), 0, 0, 0, 0, len(name) + 1, 0]
    entries.append((name, fields, owner))
    encoded = replay.pack(entries)
    require(len(encoded) <= MAX_ARCHIVE and replay.unpack(encoded, max_bytes=MAX_ARCHIVE) == entries,
            "final cpio differs or exceeds bound")
    result = gzip.compress(encoded, mtime=0)
    require(len(result) <= MAX_ARCHIVE, "compressed cpio exceeds bound")
    return result


def retained_build_kernel(directory, kernel_path, inputs, *, fresh_build):
    """Bind successful fresh output once; reuse never blesses current bytes."""
    path = directory / "native-kernel-build-receipt.json"
    if fresh_build:
        kernel = pinned(kernel_path, file_digest(kernel_path), MAX_KERNEL)
        receipt = {"schema": "hepta.native-kernel-build.v1", "inputs": inputs,
                   "kernel": {"sha256": digest(kernel), "bytes": len(kernel)}}
        with path.open("x") as stream:
            json.dump(receipt, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o400)
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o400
            and 0 < info.st_size <= 8192, "missing or invalid retained kernel build receipt")
    receipt = json.loads(path.read_text())
    require(set(receipt) == {"schema", "inputs", "kernel"}
            and receipt["schema"] == "hepta.native-kernel-build.v1" and receipt["inputs"] == inputs
            and set(receipt["kernel"]) == {"sha256", "bytes"}, "kernel build receipt binding differs")
    kernel = pinned(kernel_path, receipt["kernel"]["sha256"], MAX_KERNEL)
    require(type(receipt["kernel"]["bytes"]) is int and len(kernel) == receipt["kernel"]["bytes"],
            "retained kernel length differs")
    return kernel


def verified_build(args, output, source, owner, before):
    directory = args.reuse_kernel_build
    if directory is None:
        directory = output / "kernel-build"
        require(not args.target_dir.exists() and not args.target_dir.is_symlink(), "new build target must be fresh")
        env = dict(os.environ)
        for name in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER",
                     "CARGO_TARGET_DIR", "HEPTA_TRUSTED_INITIAL_ELF", "HEPTA_G1C_TRUSTED_OBSERVE",
                     "HEPTA_G1D_TRUSTED_CONTROL", "HEPTA_G2_NATIVE_AGENTD", "FEATURES"):
            env.pop(name, None)
        env.update(A01_RUN_DIR=str(directory), A01_SMP="1", CARGO_TARGET_DIR=str(args.target_dir),
                   HEPTA_G2_NATIVE_AGENTD="1", HEPTA_TRUSTED_INITIAL_ELF=str(args.owner_elf), CARGO_BUILD_JOBS="2")
        command([str(args.desktop / "support/build/kernel.sh"), "kernel"], output / "build-wrapper.log",
                cwd=args.desktop, env=env)
    for name in ("make-exit-code.txt", "log-exit-code.txt", "run-exit-code.txt"):
        require((directory / name).read_text().strip() == "0", f"kernel build stage failed: {name}")
    require((directory / "environment.log").read_text().splitlines().count(args.desktop_head) == 1,
            "kernel build did not record expected Desktop source")
    actual = shlex.split((directory / "command.sh").read_text())
    expected = ["make", "-C", str(args.desktop / "kernel/asterinas"), "-f", "Makefile", "-f",
                str(args.desktop / "support/build/minimal.mk"), "kernel"]
    fields = {"TARGET_ARCH=x86_64", "SMP=1", f"MEM={MEMORY_MIB}M", "ENABLE_KVM=0", "BOOT_PROTOCOL=multiboot",
              "INITRAMFS=on", "AUTO_TEST=none", "HEPTA_G2_NATIVE_AGENTD=1", "FEATURES=g2-native-agentd",
              f"A01_INITRAMFS={directory / 'initramfs.cpio.gz'}",
              f"A01_QEMU_WRAPPER={args.desktop / 'support/build/record-qemu.py'}"}
    require(actual[:8] == expected and len(actual) == 20 and actual[8].startswith("CARGO_OSDK=")
            and set(actual[9:]) == fields, "unexpected G2 product build arguments")
    require("--features=g2-native-agentd" in (directory / "kernel.log").read_text(), "G2 feature was not passed to OSDK")
    gate = subprocess.check_output([sys.executable, "-I", str(args.desktop / "support/build/verify-source.py")], cwd=args.desktop)
    require(json.loads(gate) == json.loads((directory / "source-inputs.json").read_text()), "kernel source gate differs")
    require(source.source_snapshot(args.desktop, args.desktop_head, args.desktop_tree) == before, "Desktop source changed")
    fixed = args.desktop / "support/build/minimal/Cargo.lock"
    generated = args.target_dir / "osdk/asterinas-run-base/Cargo.lock"
    require(generated.read_bytes() == fixed.read_bytes() and len(tomllib.loads(generated.read_text())["package"]) == 204,
            "kernel generated lock differs from fixed product lock")
    embedded = directory / "trusted-initial.elf"
    require(embedded.read_bytes() == owner and stat.S_IMODE(embedded.stat().st_mode) == 0o444, "embedded native owner differs")
    manifest = json.loads((directory / "trusted-initial-manifest.json").read_text())
    require(manifest["schema"] == "hepta-g2-trusted-initial-v1" and manifest["profile"] == "g2-native-agentd"
            and manifest["sha256"] == digest(owner) and manifest["bytes"] == len(owner)
            and manifest["supported_ops"] == 62 and manifest["features"] == 0
            and manifest["bootstrap_version"] == 2 and manifest["bootstrap_bytes"] == 192
            and manifest["roles"] == ["manager", "workload", "recovery"]
            and manifest["workload_address_space_bytes"] == 256 * MIB
            and manifest["guest_memory_mib"] == MEMORY_MIB
            and manifest["max_kernel_bytes"] == MAX_KERNEL
            and manifest["qualification"] == "loader-stage-not-native-qualified"
            and manifest["cap_ns"] == 50_000_000 and manifest["period_ns"] == 100_000_000
            and manifest["lease_ns"] == 300_000_000_000 and manifest["recovery_grace_ns"] == 30_000_000_000,
            "G2 manifest identity/profile differs")
    inspector_spec = importlib.util.spec_from_file_location("native_owner_elf_inspector", args.desktop / "support/build/prepare-trusted-image.py")
    inspector = importlib.util.module_from_spec(inspector_spec)
    inspector_spec.loader.exec_module(inspector)
    expected_limits = {"max_file_bytes": MAX_OWNER, "max_mapped_bytes": MAX_OWNER, "max_load_segments": 16,
                       "max_program_headers": 64, "max_tls_memsz": 65536, "max_tls_align": 4096,
                       "workload_address_space_bytes": 256 * MIB}
    require(manifest["profile_limits"] == expected_limits
            and manifest["elf_profile"] == inspector.inspect_g2_elf(args.owner_elf),
            "actual ELF measurement or fixed G2 limits differ")
    kernel_path = args.target_dir / "osdk/asterinas/asterinas-osdk-bin.elf"
    image = json.loads((directory / "initramfs-manifest.json").read_text())
    base = pinned(directory / "initramfs.cpio.gz", image["image_sha256"], 8 * MIB)
    binding = {"desktop_head": args.desktop_head, "desktop_tree": args.desktop_tree,
               "desktop_source_sha256": digest(json.dumps(before, sort_keys=True).encode()),
               "owner_sha256": digest(owner), "owner_bytes": len(owner),
               "build_directory": str(directory.resolve(strict=True)),
               "target_directory": str(args.target_dir.resolve(strict=True)),
               "kernel_path": str(kernel_path.resolve(strict=True)),
               "kernel_lock_sha256": file_digest(generated),
               "command_sha256": file_digest(directory / "command.sh"),
               "manifest_sha256": file_digest(directory / "trusted-initial-manifest.json"),
               "base_initramfs_sha256": digest(base)}
    kernel = retained_build_kernel(directory, kernel_path, binding, fresh_build=args.reuse_kernel_build is None)
    require(kernel[:6] == b"\x7fELF\x02\x01" and kernel[18:20] == b"\x03\x00", "kernel is not OSDK multiboot conversion")
    return kernel, base, manifest, file_digest(generated), str(directory)


def verdict(raw, code, timed_out, excessive, reason, owner_info):
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", raw.decode(errors="replace")).replace("\r", "")
    lines = text.splitlines()
    if reason is not None:
        rejected = lines.count("[hepta-g2] rejected initial image: " + reason)
        passed = (rejected == 1 and code == 65 and not timed_out and not excessive
                  and sum("rejected initial image:" in line for line in lines) == 1
                  and text.count("failed to run the init process") == 1
                  and not any("HEPTA_NATIVE_" in line or "trusted role committed:" in line
                              or "trusted initial image committed:" in line or "initial control activated:" in line
                              or "initial observe activated:" in line for line in lines))
        return {"passed": passed, "expected_rejection": reason, "matching_rejections": rejected}
    rows = [json.loads(line.removeprefix("HEPTA_NATIVE_COMPLETE ")) for line in lines if line.startswith("HEPTA_NATIVE_COMPLETE ")]
    owner_rows = [json.loads(line.removeprefix("HEPTA_NATIVE_OWNER_REPORT ")) for line in lines if line.startswith("HEPTA_NATIVE_OWNER_REPORT ")]
    boots = re.findall(r"^HEPTA_NATIVE_BOOT role=([123]) pid=([0-9]+) original_owner=true production_ready=false$", text, re.M)
    images = re.findall(r"^\[hepta-g2\] trusted initial image committed: bytes=([0-9]+) entry=0x([0-9a-f]+)$", text, re.M)
    roles = re.findall(r"^\[hepta-g1d\] trusted role committed: role=([123]) pid=([0-9]+)$", text, re.M)
    activations = re.findall(r"^\[hepta-g1d\] initial control activated: manager=([0-9]+) workload=([0-9]+) recovery=([0-9]+) "
                             r"cap_ns=50000000 period_ns=100000000 lease_ns=300000000000 hepta_durability=false$", text, re.M)
    kernel_bound = (len(images) == len(roles) == 3 and len(activations) == 1
                    and all(int(size) == owner_info["bytes"] and int(entry, 16) == owner_info["entry"] for size, entry in images)
                    and [role for role, _ in roles] == ["1", "2", "3"]
                    and tuple(pid for _, pid in roles) == activations[0] and set(roles) == set(boots))
    if kernel_bound:
        last_commit = max(index for index, line in enumerate(lines) if "trusted initial image committed:" in line or "trusted role committed:" in line)
        activation_index = next(index for index, line in enumerate(lines) if "initial control activated:" in line)
        first_boot = next(index for index, line in enumerate(lines) if line.startswith("HEPTA_NATIVE_BOOT "))
        kernel_bound = last_commit < activation_index < first_boot
    mandatory = ("HEPTA_NATIVE_GENESIS_BEGIN original_sqlite=true", "HEPTA_NATIVE_GENESIS_COMPLETE original_sqlite=true",
                 "HEPTA_NATIVE_AGENT_CREDENTIALS uid=60002 capabilities=0 no_new_privs=true same_image=true",
                 "HEPTA_NATIVE_ROOT_SERVICE_BEGIN peer_uid=60002 production_ready=false",
                 "HEPTA_NATIVE_ORIGINAL_DAEMON_READY original_app_server=true original_sqlite=true",
                 "HEPTA_NATIVE_REPLY_WITHHELD actual_kernel_install=true replay=false")
    expected = {"qualification": "original_root_agentd_sqlite_native_hos2", "production_ready": False,
                "original_daemon_initialized": True, "original_app_server_ready": True, "supervisor_promoted": False,
                "fleet_lifecycle": "starting", "native_hos2": True, "uid": 60002,
                "foreign_scope_grant_refused": True, "refused_scope_effect_entries": 0,
                "dispatch_count": 1, "terminal": "committed", "native_retired_through": 1,
                "loss_injection": "wrapper_withheld_actual_ioctl_reply", "physical_power_loss": False,
                "cross_boot_qualified": False}
    passed = (code == 33 and not timed_out and not excessive and kernel_bound and len(rows) == len(owner_rows) == 1
              and rows == owner_rows and len(boots) == 3 and {role for role, _ in boots} == {"1", "2", "3"}
              and len({pid for _, pid in boots}) == 3 and ("1", "1") in boots
              and all(lines.count(marker) == 1 for marker in mandatory)
              and not any("HEPTA_NATIVE_FAILURE" in line or "Kernel panic" in line for line in lines))
    if passed:
        row = rows[0]
        cut = row.get("current_cut")
        passed = (all(type(row.get(key)) is type(value) and row[key] == value for key, value in expected.items())
                  and type(row.get("native_observation_count")) is int and row["native_observation_count"] >= 1
                  and isinstance(cut, dict) and set(cut) == {"profile", "owner_agent_id", "schema_digest", "state_digest"}
                  and cut["profile"] == "hepta:cognitive:exact-current-cut:v1"
                  and cut["owner_agent_id"] == "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12"
                  and all(isinstance(cut[key], str) and re.fullmatch(r"[0-9a-f]{64}", cut[key])
                          for key in ("schema_digest", "state_digest")))
    return {"passed": bool(passed), "root_and_owner_reports_equal": rows == owner_rows and len(rows) == 1,
            "manifest_and_roles_bound_before_resume": bool(kernel_bound), "actual_reports": rows, "sealed_role_boots": boots}


def boot(argv, directory, timeout, reason, owner_info):
    raw = bytearray()
    timed_out = excessive = False
    started = time.monotonic()
    with (directory / "serial.log").open("xb") as log, subprocess.Popen(
            argv, env=ENV, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True) as child:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                while True:
                    remaining = timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        timed_out = True
                        break
                    if not selector.select(min(remaining, 0.2)):
                        continue
                    block = os.read(child.stdout.fileno(), min(16384, MAX_SERIAL - len(raw) + 1))
                    if not block:
                        break
                    log.write(block)
                    raw.extend(block)
                    if len(raw) > MAX_SERIAL:
                        excessive = True
                        break
            if timed_out or excessive:
                child.kill()
            code = child.wait(timeout=10)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
    result = {"qemu_argv": argv, "qemu_exit": code, "timed_out": timed_out, "excessive_output": excessive,
              "elapsed_seconds": round(time.monotonic() - started, 3), "serial_sha256": digest(raw)}
    result.update(verdict(raw, code, timed_out, excessive, reason, owner_info))
    save(directory / "result.json", result)
    return result


def execute(args, output, result):
    source = load_desktop(args.desktop)
    before = source.source_snapshot(args.desktop, args.desktop_head, args.desktop_tree)
    hepta_before = source.source_snapshot(args.hepta, args.hepta_head, args.hepta_tree)
    save(output / "desktop-source-before.json", before)
    save(output / "hepta-source-before.json", hepta_before)
    owner = pinned(args.owner_elf, args.owner_sha256, MAX_OWNER)
    require(owner[:7] == b"\x7fELF\x02\x01\x01" and owner[16:20] == b"\x02\x00\x3e\x00", "owner must be static-profile x86_64 ET_EXEC")
    owner_info = {"bytes": len(owner), "entry": struct.unpack_from("<Q", owner, 24)[0]}
    result.update(stage="kernel_build", owner_sha256=digest(owner), owner_bytes=len(owner),
                  hepta_head=args.hepta_head, desktop_head=args.desktop_head,
                  runner_sha256=file_digest(Path(__file__).resolve()))
    save(output / "result.json", result)
    kernel, base, manifest, lock, build_dir = verified_build(args, output, source, owner, before)
    bios = source.replay.read_pinned_file(args.bios, source.replay.SEABIOS_SHA, 2 * MIB)
    qemu = Path(shutil.which("qemu-system-x86_64") or "missing").resolve(strict=True)
    require(qemu.is_file(), "QEMU unavailable")
    qemu_sha = file_digest(qemu)
    (output / "kernel.elf").write_bytes(kernel)
    (output / "bios.bin").write_bytes(bios)
    result.update(stage="guests", kernel_sha256=digest(kernel), bios_sha256=digest(bios), qemu_sha256=qemu_sha,
                  kernel_lock_sha256=lock, hepta_lock_sha256=file_digest(args.hepta / "codex-rs/Cargo.lock"),
                  trusted_manifest=manifest, kernel_build_directory=build_dir,
                  kernel_build_receipt_sha256=file_digest(Path(build_dir) / "native-kernel-build-receipt.json"), guests={})
    changed = bytearray(owner)
    changed[-1] ^= 1
    for name, actual, reason in (("exact", owner, None), ("byte-mismatch", changed, "manifest-byte-mismatch"),
                                  ("truncated", owner[:-1], "truncated-snapshot")):
        directory = output / name
        directory.mkdir(mode=0o700)
        disk, disk_record = disk_fixture(directory)
        image = initramfs(base, actual, source.replay)
        image_path = directory / "initramfs.cpio.gz"
        image_path.write_bytes(image)
        require("," not in str(disk), "QEMU fixture path contains a comma")
        argv = [str(qemu), "-kernel", str(output / "kernel.elf"), "-initrd", str(image_path),
                "-append", "earlycon console=ttyS0 loglevel=info rdinit=/test/g1d-init SHELL=/bin/sh LOGNAME=root HOME=/ USER=root PATH=/bin:/sbin --",
                "-machine", "q35", "-accel", "tcg", "-cpu", "max", "-bios", str(output / "bios.bin"),
                "-m", f"{MEMORY_MIB}M", "-smp", "1", "-nodefaults", "-no-user-config", "-no-reboot", "-nographic",
                "-display", "none", "-monitor", "none", "-serial", "stdio",
                "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
                "-drive", f"file={disk},if=none,format=raw,id=hepta-store,snapshot=off,cache=writeback",
                "-device", "virtio-blk-pci,disable-legacy=on,disable-modern=off,drive=hepta-store"]
        save(directory / "inputs.json", {"argv": argv, "disk": disk_record, "owner_sha256": digest(actual),
                                         "initramfs_sha256": digest(image)})
        result["stage"] = name
        save(output / "result.json", result)
        observed = boot(argv, directory, args.timeout, reason, owner_info)
        observed.update(disk=disk_record, disk_final_sha256=file_digest(disk), initramfs_sha256=digest(image), owner_sha256=digest(actual))
        result["guests"][name] = observed
        save(output / "result.json", result)
        info = disk.lstat()
        require([info.st_dev, info.st_ino, info.st_size, info.st_uid] == disk_record["identity"], "disk identity changed")
        require(file_digest(image_path) == digest(image) and file_digest(output / "kernel.elf") == digest(kernel)
                and file_digest(output / "bios.bin") == digest(bios), "guest inputs changed")
        require(observed["passed"], f"actual {name} guest failed; logs/disk retained")
    require(source.source_snapshot(args.desktop, args.desktop_head, args.desktop_tree) == before
            and source.source_snapshot(args.hepta, args.hepta_head, args.hepta_tree) == hepta_before, "source changed during qualification")
    require(file_digest(qemu) == qemu_sha and file_digest(args.owner_elf) == digest(owner), "executed program changed")
    result.update(stage="complete", passed=True, source_unchanged=True, artifact_unchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("desktop", "hepta", "owner-elf", "output", "target-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("desktop-head", "desktop-tree", "hepta-head", "hepta-tree", "owner-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--reuse-kernel-build", type=Path)
    parser.add_argument("--bios", type=Path, default=Path("/usr/share/seabios/bios-256k.bin"))
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    require(1 <= args.timeout <= 900, "guest timeout outside finite 1..900 second bound")
    for name in ("desktop", "hepta", "owner_elf", "output", "target_dir", "bios", "reuse_kernel_build"):
        value = getattr(args, name)
        if value is not None:
            setattr(args, name, value.absolute())
    require(not args.output.exists() and not args.output.is_symlink(), "evidence output must be new")
    require(not any(args.output.resolve().is_relative_to(root.resolve()) or args.target_dir.resolve().is_relative_to(root.resolve())
                    for root in (args.desktop, args.hepta)), "evidence and target must be outside source")
    args.output.mkdir(mode=0o700, parents=True)
    result = {"schema": "hepta.native-original-owner-qualification.v1", "passed": False, "stage": "source_admission",
              "profile": "g2-native-agentd", "production_ready": False, "native_guest_qualified": False,
              "hardware_qualification": False, "smp_qualification": False, "cross_boot_qualified": False,
              "physical_power_loss": False, "supervisor_promoted": False}
    try:
        execute(args, args.output, result)
        result["native_guest_qualified"] = result["passed"]
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        result.update(passed=False, error=f"{type(error).__name__}: {error}")
    save(args.output / "result.json", result)
    print(json.dumps({"passed": result["passed"], "stage": result["stage"], "output": str(args.output)}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
