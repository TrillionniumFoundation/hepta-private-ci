#!/usr/bin/env python3
"""Isolated original-owner VM crash, same-disk reboot, read-only old-D proof.

Creates its own private disk. Never accepts a caller disk, live VM, block
device, policy, or private key. A VM crash is not physical power-loss testing.
The disk can contain qualification keys and must remain private.
"""
import argparse
import fcntl
import gzip
import importlib.util
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import struct
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("native_owner_common", Path(__file__).with_name("run-native-owner-qualification.py"))
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)
require, save = common.require, common.save
OWNER = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12"
READY = "HEPTA_NATIVE_VM_CRASH_READY "


def lines(raw):
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", raw.decode(errors="strict")).replace("\r", "").splitlines()


def role_binding(raw, owner):
    text = lines(raw)
    images = [re.fullmatch(r"\[hepta-g2\] trusted initial image committed: bytes=([0-9]+) entry=0x([0-9a-f]+)", line) for line in text]
    images = [match.groups() for match in images if match]
    roles = [re.fullmatch(r"\[hepta-g1d\] trusted role committed: role=([123]) pid=([0-9]+)", line) for line in text]
    roles = [match.groups() for match in roles if match]
    boots = [re.fullmatch(r"HEPTA_NATIVE_BOOT role=([123]) pid=([0-9]+) original_owner=true production_ready=false", line) for line in text]
    boots = [match.groups() for match in boots if match]
    activate = [re.fullmatch(r"\[hepta-g1d\] initial control activated: manager=([0-9]+) workload=([0-9]+) recovery=([0-9]+) cap_ns=50000000 period_ns=100000000 lease_ns=300000000000 hepta_durability=false", line) for line in text]
    activate = [match.groups() for match in activate if match]
    require(len(images) == len(roles) == len(boots) == 3 and len(activate) == 1
            and all(int(size) == owner["bytes"] and int(entry, 16) == owner["entry"] for size, entry in images)
            and [role for role, _ in roles] == ["1", "2", "3"] and set(roles) == set(boots)
            and tuple(pid for _, pid in roles) == activate[0] and roles[0] == ("1", "1")
            and len({pid for _, pid in roles}) == 3, "sealed image/role binding differs")
    published = max(index for index, line in enumerate(text) if "trusted initial image committed:" in line or "trusted role committed:" in line)
    activation = next(index for index, line in enumerate(text) if "initial control activated:" in line)
    started = next(index for index, line in enumerate(text) if line.startswith("HEPTA_NATIVE_BOOT "))
    require(published < activation < started and not any("HEPTA_NATIVE_FAILURE" in line or "Kernel panic" in line for line in text),
            "image publication order or guest failure")
    return int(roles[2][1])


def bounded_boot_id(value):
    require(type(value) is list and len(value) == 16 and all(type(byte) is int and 0 <= byte <= 255 for byte in value),
            "invalid native boot identity")
    boot = uuid.UUID(bytes=bytes(value))
    require(boot.version == 4, "native boot is not the secure version-4 identity")
    return str(boot)


def crash_receipt(raw, owner):
    agent_pid = role_binding(raw, owner)
    text = lines(raw)
    rows = [json.loads(line[len(READY):]) for line in text if line.startswith(READY)]
    require(len(rows) == 1, "expected one independently retained Root crash marker")
    receipt = rows[0]
    candidate, head = receipt["candidate"], receipt["head"]
    payload = json.loads(candidate["payload"])
    boot = bounded_boot_id(payload["delivery"]["boot_id"])
    require(head["schema_version"] == 1 and head["owner_agent_id"] == OWNER and head["phase"] == "current"
            and head["proposal"] is None and 1 < head["counter"] < 2**64-1 and 0 < head["publisher_epoch"] < 2**64-1
            and head["last_mutation_sequence"] < 2**64-1 and candidate["current"] == head["last_current"]
            and head["peer_lifetime"]["pid"] == agent_pid and head["peer_lifetime"]["uid"] == 60002
            and head["peer_lifetime"]["boot_id"] == boot and head["peer_lifetime"]["process_start_ticks"] >= 0,
            "Root Current or original peer identity differs")
    cut = candidate["current"]
    require(set(cut) == {"profile", "owner_agent_id", "schema_digest", "state_digest"}
            and cut["profile"] == "hepta:cognitive:exact-current-cut:v1" and cut["owner_agent_id"] == OWNER
            and all(re.fullmatch(r"[0-9a-f]{64}", cut[key]) for key in ("schema_digest", "state_digest")),
            "incomplete original Current cut")
    observed = candidate["agent_independent_history"]
    require(candidate["dispatch_count"] == 1 and candidate["original_daemon_joined"] is True
            and observed["state"] == "applied" and observed["previous_revision"] == 1 and observed["revision"] == 2
            and payload["schema_version"] == 1 and payload["expected_revision"] == 1
            and payload["manage_slot"] == 2 and payload["manage_generation"] == 1
            and payload["cap_ns"] == 25_000_000 and payload["period_ns"] == 100_000_000
            and payload["delivery"]["sequence"] == "0000000000000001",
            "original native operation or Agentd history differs")
    require(receipt["root_resource_observation"] == {"boot_id": payload["delivery"]["boot_id"], "revision": 2,
            "active_cap_ns": 25_000_000, "active_period_ns": 100_000_000}
            and receipt["root_queried_delivery_history"] is False, "Root resource observation differs")
    tids = receipt["stopped_thread_ids"]
    require(type(tids) is list and 1 <= len(tids) <= 128 and all(type(tid) is int and tid > 0 for tid in tids)
            and tids == sorted(set(tids)) and agent_pid in tids, "stable all-task stop evidence missing")
    for marker in ("HEPTA_NATIVE_GENESIS_BEGIN original_sqlite=true", "HEPTA_NATIVE_GENESIS_COMPLETE original_sqlite=true",
                   "HEPTA_NATIVE_AGENT_CREDENTIALS uid=60002 capabilities=0 no_new_privs=true same_image=true",
                   "HEPTA_NATIVE_ROOT_SERVICE_BEGIN peer_uid=60002 production_ready=false",
                   "HEPTA_NATIVE_ORIGINAL_DAEMON_READY original_app_server=true original_sqlite=true",
                   "HEPTA_NATIVE_REPLY_WITHHELD actual_kernel_install=true replay=false"):
        require(text.count(marker) == 1, "first boot original-owner marker missing or repeated")
    return receipt


def observe_receipt(raw, owner, retained):
    role_binding(raw, owner)
    text = lines(raw)
    reports = [json.loads(line.removeprefix("HEPTA_NATIVE_HISTORY_OWNER_REPORT ")) for line in text if line.startswith("HEPTA_NATIVE_HISTORY_OWNER_REPORT ")]
    roots = [json.loads(line.removeprefix("HEPTA_NATIVE_HISTORY_COMPLETE ")) for line in text if line.startswith("HEPTA_NATIVE_HISTORY_COMPLETE ")]
    require(len(reports) == len(roots) == 1 and roots[0]["owner_report"] == reports[0]
            and roots[0]["root_protected_head"] == retained["head"], "second boot independent Root head differs")
    report = reports[0]
    expected = {"qualification": "original_retained_current_native_vm_crash_history", "production_ready": False,
                "state": "indeterminate", "observation": "unknown", "adapter_error": "native boot changed; the old D remains unknown",
                "old_boot_ioctl_issued": False, "dispatch_count_previous_boot": 1, "dispatch_count_this_boot": 0,
                "issuer_connected": False, "writer_opened": False, "retirement_attempted": False, "physical_power_loss": False}
    require(all(type(report.get(key)) is type(value) and report[key] == value for key, value in expected.items())
            and report["current_cut"] == retained["head"]["last_current"]
            and report["exact_payload"] == retained["candidate"]["payload"]
            and report["old_delivery"] == json.loads(retained["candidate"]["payload"])["delivery"]
            and bounded_boot_id(report["new_boot_id"]) != retained["head"]["peer_lifetime"]["boot_id"],
            "historical old-D/no-replay result differs")
    require(not any(line.startswith(("HEPTA_NATIVE_GENESIS_", "HEPTA_NATIVE_ROOT_SERVICE_BEGIN", "HEPTA_NATIVE_REPLY_WITHHELD",
                                    "HEPTA_NATIVE_ORIGINAL_DAEMON_READY")) for line in text), "second boot entered live owner/issuer")
    return report


def boot(argv, directory, timeout, owner, retained=None):
    raw, started = bytearray(), time.monotonic()
    timed_out = excessive = killed_at_marker = False
    marker = None
    failure = None
    with (directory / "serial.log").open("xb") as log, subprocess.Popen(argv, env=common.ENV,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True) as child:
        pid = child.pid
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                while True:
                    remaining = timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        timed_out = True
                        break
                    if not selector.select(min(remaining, .2)):
                        continue
                    block = os.read(child.stdout.fileno(), min(16384, common.MAX_SERIAL - len(raw) + 1))
                    if not block:
                        break
                    log.write(block)
                    raw.extend(block)
                    if len(raw) > common.MAX_SERIAL:
                        excessive = True
                        break
                    if retained is None and any(line.startswith(READY.encode()) for line in raw.splitlines(keepends=True) if line.endswith(b"\n")):
                        marker = crash_receipt(raw, owner)
                        log.flush()
                        os.fsync(log.fileno())
                        save(directory / "retained-root-current-before-kill.json", marker)
                        require(child.poll() is None, "QEMU already exited before the deliberate VM crash")
                        child.kill()
                        killed_at_marker = True
                        break
            if timed_out or excessive:
                child.kill()
            code = child.wait(timeout=10)
            # Include all trailing bytes after the child is reaped. They may
            # reveal a guest error or duplicate marker and must not be hidden.
            trailing = child.stdout.read(common.MAX_SERIAL - len(raw) + 1)
            log.write(trailing)
            raw.extend(trailing)
            excessive |= len(raw) > common.MAX_SERIAL
        except (OSError, ValueError, KeyError, TypeError, UnicodeError, subprocess.SubprocessError) as error:
            failure = error
        finally:
            if child.poll() is None:
                child.kill()
            code = child.wait(timeout=10)
    result = {"qemu_pid": pid, "qemu_exit": code, "qemu_reaped": True, "timed_out": timed_out,
              "excessive_output": excessive, "sigkill_after_exact_marker": killed_at_marker,
              "qemu_alive_immediately_before_sigkill": killed_at_marker,
              "elapsed_seconds": round(time.monotonic()-started, 3), "serial_sha256": common.digest(raw), "argv": argv}
    save(directory / "process-result.json", result)
    if failure is not None:
        raise failure
    require(not timed_out and not excessive, "guest timeout/output bound exceeded")
    if retained is None:
        require(code == -signal.SIGKILL and killed_at_marker and crash_receipt(raw, owner) == marker,
                "first QEMU was not SIGKILLed/reaped at the exact retained boundary")
        result["retained"] = marker
    else:
        require(code == 33 and not killed_at_marker, "second QEMU did not complete read-only observation")
        result["report"] = observe_receipt(raw, owner, retained)
    result["passed"] = True
    save(directory / "result.json", result)
    return result


def execute(args, result):
    source = common.load_desktop(args.desktop)
    before = source.source_snapshot(args.desktop, args.desktop_head, args.desktop_tree)
    hepta_before = source.source_snapshot(args.hepta, args.hepta_head, args.hepta_tree)
    save(args.output / "desktop-source-before.json", before)
    save(args.output / "hepta-source-before.json", hepta_before)
    owner = common.pinned(args.owner_elf, args.owner_sha256, common.MAX_OWNER)
    require(owner[:7] == b"\x7fELF\x02\x01\x01" and owner[16:20] == b"\x02\x00\x3e\x00", "owner is not x86_64 ET_EXEC")
    owner_info = {"bytes": len(owner), "entry": struct.unpack_from("<Q", owner, 24)[0]}
    kernel, base, manifest, lock, build = common.verified_build(args, args.output, source, owner, before)
    bios = source.replay.read_pinned_file(args.bios, source.replay.SEABIOS_SHA, 2*common.MIB)
    entries = source.replay.unpack(gzip.decompress(common.initramfs(base, owner, source.replay)), max_bytes=common.MAX_ARCHIVE)
    name, data = ".hepta-native-case.json", b'"crash_after_applied"'
    require(all(old.lstrip("./") != name.lstrip("./") for old, _, _ in entries), "qualification case already exists")
    fields = [max(item[1][0] for item in entries)+1, 0o100400, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(name)+1, 0]
    entries.append((name, fields, data))
    plain = source.replay.pack(entries)
    require(len(plain) <= common.MAX_ARCHIVE and source.replay.unpack(plain, max_bytes=common.MAX_ARCHIVE) == entries, "case image roundtrip differs")
    image = gzip.compress(plain, mtime=0)
    qemu = Path(shutil.which("qemu-system-x86_64") or "missing").resolve(strict=True)
    pins = {"kernel.elf": kernel, "bios.bin": bios, "initramfs.cpio.gz": image}
    for name, data in pins.items():
        path = args.output / name
        path.write_bytes(data)
        path.chmod(0o400)
    disk, disk_info = common.disk_fixture(args.output)
    require("," not in str(disk), "invalid QEMU path")
    argv = [str(qemu), "-kernel", str(args.output / "kernel.elf"), "-initrd", str(args.output / "initramfs.cpio.gz"),
            "-append", "earlycon console=ttyS0 loglevel=warn rdinit=/test/g1d-init SHELL=/bin/sh LOGNAME=root HOME=/ USER=root PATH=/bin:/sbin --",
            "-machine", "q35", "-accel", "tcg", "-cpu", "max", "-bios", str(args.output / "bios.bin"), "-m", "3072M", "-smp", "1",
            "-nodefaults", "-no-user-config", "-no-reboot", "-nographic", "-display", "none", "-monitor", "none", "-serial", "stdio",
            "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04", "-drive", f"file={disk},if=none,format=raw,id=hepta-store,snapshot=off,cache=writeback",
            "-device", "virtio-blk-pci,disable-legacy=on,disable-modern=off,drive=hepta-store"]
    qemu_sha = common.file_digest(qemu)
    result.update(owner_sha256=common.digest(owner), desktop_head=args.desktop_head, hepta_head=args.hepta_head,
                  manifest=manifest, kernel_build_directory=build,
                  kernel_build_receipt_sha256=common.file_digest(Path(build) / "native-kernel-build-receipt.json"),
                  kernel_lock_sha256=lock, disk=disk_info,
                  pins={name:common.digest(data) for name,data in pins.items()}, qemu_sha256=qemu_sha, guests={})
    save(args.output / "result.json", result)
    # The runner retains the one newly created inode and admits no competing
    # instance. QEMU itself also uses its default exclusive block image lock.
    with disk.open("rb") as identity:
        fcntl.flock(identity, fcntl.LOCK_EX | fcntl.LOCK_NB)
        retained = None
        for phase in ("before-crash", "after-reboot"):
            directory = args.output / phase
            directory.mkdir(mode=0o700)
            info = disk.lstat()
            require([info.st_dev, info.st_ino, info.st_size, info.st_uid] == disk_info["identity"]
                    and os.fstat(identity.fileno()).st_ino == info.st_ino and info.st_nlink == 1,
                    "original exclusive disk identity changed")
            result["stage"] = phase
            save(args.output / "result.json", result)
            observed = boot(argv, directory, args.timeout, owner_info, retained)
            for info in (disk.lstat(), os.fstat(identity.fileno())):
                require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
                        and [info.st_dev, info.st_ino, info.st_size, info.st_uid] == disk_info["identity"]
                        and info.st_nlink == 1, "exclusive disk identity changed during guest")
            observed["disk_after_sha256"] = common.file_digest(disk)
            result["guests"][phase] = observed
            save(args.output / "result.json", result)
            retained = observed.get("retained", retained)
            require(all(common.file_digest(args.output / name) == common.digest(data) for name,data in pins.items()), "immutable guest artifact changed")
    require(source.source_snapshot(args.desktop, args.desktop_head, args.desktop_tree) == before
            and source.source_snapshot(args.hepta, args.hepta_head, args.hepta_tree) == hepta_before
            and common.file_digest(args.owner_elf) == common.digest(owner) and common.file_digest(qemu) == qemu_sha, "source or executable changed")
    result.update(stage="complete", passed=True, source_unchanged=True, same_exclusive_disk=True,
                  old_vm_sigkill_reaped_before_new_vm=True, retained_current_history_only=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("desktop", "hepta", "owner-elf", "output", "target-dir"):
        parser.add_argument("--"+name, type=Path, required=True)
    for name in ("desktop-head", "desktop-tree", "hepta-head", "hepta-tree", "owner-sha256"):
        parser.add_argument("--"+name, required=True)
    parser.add_argument("--reuse-kernel-build", type=Path)
    parser.add_argument("--bios", type=Path, default=Path("/usr/share/seabios/bios-256k.bin"))
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    require(1 <= args.timeout <= 900, "finite timeout must be 1..900 seconds")
    for name in ("desktop", "hepta", "owner_elf", "output", "target_dir", "reuse_kernel_build", "bios"):
        value = getattr(args, name)
        if value is not None:
            setattr(args, name, value.absolute())
    require(not args.output.exists() and not args.output.is_symlink(), "evidence must be new")
    require(not any(args.output.resolve().is_relative_to(root.resolve()) or args.target_dir.resolve().is_relative_to(root.resolve())
                    for root in (args.desktop,args.hepta)), "evidence/target must remain outside source")
    args.output.mkdir(mode=0o700, parents=True)
    result = {"schema":"hepta.native-original-owner-vm-crash-history.v1", "passed":False, "stage":"admission",
              "production_ready":False, "physical_power_loss":False, "cross_boot_writer_handoff":False,
              "actual_kernel_history_lost":False, "smp_qualified":False,
              "runner_sha256":common.file_digest(Path(__file__).resolve()),
              "common_runner_sha256":common.file_digest(Path(__file__).with_name("run-native-owner-qualification.py").resolve())}
    try:
        execute(args,result)
    except (OSError,ValueError,KeyError,TypeError,UnicodeError,subprocess.SubprocessError) as error:
        result.update(passed=False,error=f"{type(error).__name__}: {error}")
    save(args.output/"result.json",result)
    print(json.dumps({"passed":result["passed"],"stage":result["stage"],"output":str(args.output)}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
