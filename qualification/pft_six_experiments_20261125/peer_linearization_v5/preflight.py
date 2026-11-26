"""One read-only ai395 -> pocket4 metadata probe; only Python standard library."""
import base64
import hashlib
import json
import os
import platform
import resource
import selectors
import shlex
import signal
import socket
import stat
import subprocess
import sys
import time

PINS = {
    "/home/qq/.ssh/hepta-transport/ssh_transport.py":
        "62806672b699d794e2fe9c738a281727fa1fd6595266440a747f8a4145d449e9",
    "/home/qq/.ssh/hepta-transport/inventory.json":
        "130f7f8f5fb4eb8bd6717f532f07ba069fe8110e842dfeb95c4132cc7aa8007f",
    "/home/qq/.ssh/hepta-transport/known_hosts":
        "1463442349bbb6b56e9ffbb66acce3c4abcceefe1c141c7b7f1ea9bb0dedf034",
}
REMOTE_PYTHON = "/home/alex/pft-six-actual-hcsn-20261125/venv/bin/python"


def require(value, message):
    if not value:
        raise ValueError(message)


def read_pin(path, expected=None):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= 65536, "bounded regular source")
        raw = stream.read(65537)
        after = os.fstat(stream.fileno())
        stamp = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        require(stamp(before) == stamp(after) and len(raw) == before.st_size, "source changed")
    hashed = hashlib.sha256(raw).hexdigest()
    require(expected is None or hashed == expected, "source or public host pin changed")
    return {"path": path, "bytes": len(raw), "sha256": hashed}


def expired(_signum, _frame):
    raise TimeoutError("metadata preflight deadline")


def command():
    payload = ("import json,os,platform,resource,signal,socket,sys; "
               "resource.setrlimit(resource.RLIMIT_CPU,(2,3)); signal.alarm(8); "
               "print(json.dumps(dict(hostname=socket.gethostname(),uid=os.getuid(),"
               "executable=sys.executable,python=platform.python_version(),"
               "implementation=platform.python_implementation(),"
               "ssh_connection=os.environ.get('SSH_CONNECTION','')),sort_keys=True))")
    proxy = shlex.join(["/usr/bin/python3", "/home/qq/.ssh/hepta-transport/ssh_transport.py",
                        "--inventory", "/home/qq/.ssh/hepta-transport/inventory.json", "--peer", "pocket4", "--verbose"])
    options = ["BatchMode=yes", "StrictHostKeyChecking=yes", "ForwardAgent=no", "ClearAllForwardings=yes",
               "ConnectTimeout=8", "ConnectionAttempts=1", "ControlMaster=no", "ControlPath=none",
               "ControlPersist=no", "ProxyJump=none", "ProxyUseFdpass=yes", "GlobalKnownHostsFile=/dev/null",
               "HostKeyAlias=hepta-node-pocket4", "CheckHostIP=no", "User=alex", "Port=22", "UpdateHostKeys=no",
               "PermitLocalCommand=no", "UserKnownHostsFile=/home/qq/.ssh/hepta-transport/known_hosts", "ProxyCommand=" + proxy]
    return ["ssh", "-T"] + [part for option in options for part in ("-o", option)] + [
        "pocket4", shlex.join([REMOTE_PYTHON, "-I", "-B", "-c", payload])]


def probe(record, output):
    argv = command()
    record["ssh_argv"] = argv
    with selectors.DefaultSelector() as selector:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, bufsize=0, start_new_session=True)
        try:
            for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map():
                for key, _ in selector.select(timeout=0.1):
                    chunk = os.read(key.fd, 1024)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    name = key.data
                    remaining = (4096 if name == "stdout" else 16384) - len(output[name])
                    output[name].extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        record["stream_truncated_on_failure"] = name
                        raise ValueError("metadata stream cap")
            while True:
                observed = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if observed is not None:
                    break
                time.sleep(0.01)
            record["child_observed_status"] = {"si_code": observed.si_code, "si_status": observed.si_status}
            require(observed.si_code == os.CLD_EXITED and observed.si_status == 0, "metadata SSH failed")
        finally:
            # The leader remains unreaped until its own group has been cleaned.
            signal.alarm(0)
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            record["ssh_exit_code"] = process.wait(timeout=2)
            process.stdout.close()
            process.stderr.close()
    remote = json.loads(output["stdout"])
    parts = remote["ssh_connection"].split()
    require(len(parts) == 4 and parts[0] == "10.77.0.2" and parts[2:] == ["10.77.0.4", "22"], "metadata SSH route")
    require(remote["implementation"] == "CPython" and remote["executable"] == REMOTE_PYTHON, "remote Python identity")
    reports = []
    for line in output["stderr"].splitlines():
        try:
            value = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if isinstance(value, dict) and value.get("peer") == "pocket4" and "selected" in value:
            reports.append(value)
    require(len(reports) == 1 and reports[0]["selected"], "one direct selector receipt")
    selected = reports[0]["selected"]
    require(selected["transport"] == "usb4" and selected["interface"] == "br-usb4"
            and selected["interface_bound"] is True and selected["port"] == 22
            and selected["local_address"][0] == "10.77.0.2"
            and selected["remote_address"][0] == "10.77.0.4", "direct USB4 selection changed")
    record.update(remote=remote, transport=reports[0], status="METADATA_DIRECT_SSH_CONFIRMED")


def main():
    start, cpu = time.monotonic(), time.process_time()
    resource.setrlimit(resource.RLIMIT_CPU, (2, 3))
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(12)
    output = {"stdout": bytearray(), "stderr": bytearray()}
    record = {"schema": "hepta.peer-v5.metadata-preflight.v1", "status": "FAILED",
              "local": {"hostname": socket.gethostname(), "uid": os.getuid(), "python": platform.python_version(),
                        "implementation": platform.python_implementation(), "executable": sys.executable},
              "new_listeners": 0, "scientific_solves": 0, "model_forwards": 0, "retries": 0}
    try:
        record["source"] = read_pin(__file__)
        record["dependency_pins"] = [read_pin(path, expected) for path, expected in PINS.items()]
        probe(record, output)
    except Exception as error:
        record["error"] = {"type": type(error).__name__, "message": str(error)[:2048]}
    finally:
        signal.alarm(0)
    record.update(wall_seconds=time.monotonic() - start, python_cpu_seconds=time.process_time() - cpu)
    for name, raw in output.items():
        record[name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                        "base64": base64.b64encode(raw).decode("ascii")}
    raw = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
    require(len(raw.encode()) <= 65536, "preflight result cap")
    print(raw, flush=True)
    return 0 if record["status"] == "METADATA_DIRECT_SSH_CONFIRMED" else 1


if __name__ == "__main__":
    sys.exit(main())
