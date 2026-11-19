"""Execute adversarial boundary probes on Linux; this is software evidence only."""

import argparse
import hashlib
import json
from pathlib import Path
import secrets
import sys

from .common import write_json
from .isolate import run_actor

ATTACKER = r"""
import ctypes, errno, hashlib, json, os, pathlib, socket, subprocess, sys
request = json.load(sys.stdin)
results = {}
def read(label, path):
    try:
        data = pathlib.Path(path).read_bytes()
        results[label] = {"outcome": "READ", "sha256": hashlib.sha256(data).hexdigest()}
    except OSError as error:
        results[label] = {"outcome": "DENIED", "errno": error.errno}
read("public_current", request["public"])
read("private_absolute", request["private"])
read("private_dotdot", str(pathlib.Path(request["public"]).parent / ".." / "private" / "canary.json"))
read("other_episode", request["other_episode"])
read("real_source_archive", request["source_archive"])
read("parent_environment", "/proc/" + str(request["parent_pid"]) + "/environ")
read("parent_file_descriptor", "/proc/" + str(request["parent_pid"]) + "/fd/0")
link = pathlib.Path("escape-link")
link.symlink_to(request["private"])
read("symlink_to_private", link)
try:
    os.link(request["private"], "stolen-hardlink")
    results["hardlink_private"] = {"outcome": "CREATED"}
except OSError as error:
    results["hardlink_private"] = {"outcome": "DENIED", "errno": error.errno}
try:
    pathlib.Path(request["private"]).chmod(0o777)
    results["chmod_private"] = {"outcome": "CHANGED"}
except OSError as error:
    results["chmod_private"] = {"outcome": "DENIED", "errno": error.errno}
try:
    socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    results["network_socket"] = {"outcome": "CREATED"}
except OSError as error:
    results["network_socket"] = {"outcome": "DENIED", "errno": error.errno}
libc = ctypes.CDLL(None, use_errno=True)
ret = libc.process_vm_readv(request["parent_pid"], 0, 0, 0, 0, 0)
results["process_memory_read"] = {"outcome": "DENIED" if ret < 0 else "ALLOWED", "errno": ctypes.get_errno()}
ret = libc.syscall(438, -1, 0, 0)
results["pidfd_getfd"] = {"outcome": "DENIED" if ret < 0 else "ALLOWED", "errno": ctypes.get_errno()}
child = subprocess.run([sys.executable, "-I", "-c",
    "import pathlib,sys; pathlib.Path(sys.argv[1]).read_bytes()", request["private"]],
    capture_output=True, text=True)
results["child_inherits_boundary"] = {"outcome": "DENIED" if child.returncode != 0 and
    "PermissionError" in child.stderr else "ALLOWED"}
results["clean_environment"] = {"outcome": "CLEAN" if not
    ({"HF_TOKEN", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY"} & set(os.environ)) else "LEAKED"}
print(json.dumps(results, sort_keys=True))
"""

TORCH = r"""
import hashlib, io, json, pathlib, sys
sys.path.insert(0, sys.argv[1])
import numpy as np
import torch
from PIL import Image
left = torch.tensor([[1., 2.], [3., 4.]])
result = left @ left.T
assert result.tolist() == [[5., 11.], [11., 25.]]
image = Image.new("RGB", (4, 3), (17, 23, 41))
buffer = io.BytesIO(); image.save(buffer, format="PNG")
restored = Image.open(io.BytesIO(buffer.getvalue())).convert("RGB")
assert restored.tobytes() == image.tobytes()
pathlib.Path("torch-pillow.png").write_bytes(buffer.getvalue())
print(json.dumps({"torch": torch.__version__, "numpy": np.__version__,
    "pillow": Image.__version__, "matrix": result.tolist(),
    "png_sha256": hashlib.sha256(buffer.getvalue()).hexdigest()}))
"""

DUPLEX = r"""
import json, os, sys
print(json.dumps({"type": "ready", "pid": os.getpid()}), flush=True)
count = 0
for raw in sys.stdin:
    event = json.loads(raw)
    assert event["step"] == count
    count += 1
    print(json.dumps({"type": "observation", "step": event["step"], "count": count,
                      "pid": os.getpid()}), flush=True)
    if count == 2:
        print(json.dumps({"type": "STOP", "count": count, "pid": os.getpid()}), flush=True)
        break
"""


def probe(output, data_root, torch_python, torch_prefix, torch_base, pillow_root):
    import os

    root, dataset = Path(output), Path(data_root)
    root.mkdir(parents=True, exist_ok=False)
    public, private, other = root / "public", root / "private", root / "other-episode"
    for directory in (
        public,
        private,
        other,
        root / "attack-output",
        root / "torch-output",
        root / "duplex-output",
        root / "callback-error-output",
    ):
        directory.mkdir(mode=0o700)
    token = secrets.token_hex(32)
    (private / "canary.json").write_text(json.dumps({"hidden_target": token}))
    (public / "current.txt").write_text("Current public input only.\n")
    (other / "future.txt").write_text("Not part of this actor's current episode.\n")
    (public / "attacker.py").write_text(ATTACKER)
    (public / "torch_probe.py").write_text(TORCH)
    (public / "duplex.py").write_text(DUPLEX)
    common_runtime = [
        path
        for path in (
            "/usr",
            "/lib",
            "/lib64",
            "/etc/ld.so.cache",
            "/proc/cpuinfo",
            "/dev/urandom",
        )
        if Path(path).exists()
    ]
    request = {
        "public": str(public / "current.txt"),
        "private": str(private / "canary.json"),
        "other_episode": str(other / "future.txt"),
        "source_archive": str(
            dataset / "private/upstream/data/train-00000-of-00001.parquet"
        ),
        "parent_pid": os.getpid(),
    }
    attack = run_actor(
        [sys.executable, "-I", str(public / "attacker.py")],
        public_root=public,
        output_root=root / "attack-output",
        runtime_roots=common_runtime + [sys.prefix, sys.base_prefix],
        private_roots=[private, other, dataset / "private"],
        input_bytes=json.dumps(request).encode(),
        timeout_seconds=30,
    )
    write_json(root / "attack-execution.json", attack)
    if attack["exit_code"] != 0 or not attack["enforced_before_actor_exec"]:
        raise RuntimeError(
            "Actor boundary probe could not execute under mandatory isolation"
        )
    observed = json.loads(attack["stdout"])
    expected_denials = {
        "private_absolute",
        "private_dotdot",
        "other_episode",
        "real_source_archive",
        "parent_environment",
        "parent_file_descriptor",
        "symlink_to_private",
        "hardlink_private",
        "chmod_private",
        "network_socket",
        "process_memory_read",
        "pidfd_getfd",
        "child_inherits_boundary",
    }
    if (
        observed["public_current"]["outcome"] != "READ"
        or any(observed[key]["outcome"] != "DENIED" for key in expected_denials)
        or observed["clean_environment"]["outcome"] != "CLEAN"
    ):
        raise AssertionError(
            "A real actor probe crossed the intended isolation boundary"
        )
    if (
        observed["process_memory_read"]["errno"] != 1
        or observed["pidfd_getfd"]["errno"] != 1
    ):
        raise AssertionError("Process access was not rejected by the seccomp policy")
    if token in attack["stdout"] + attack["stderr"]:
        raise AssertionError("Private canary appeared in actor output")
    runtime = run_actor(
        [torch_python, "-I", str(public / "torch_probe.py"), pillow_root],
        public_root=public,
        output_root=root / "torch-output",
        runtime_roots=common_runtime + [torch_prefix, torch_base, pillow_root],
        private_roots=[private, other, dataset / "private"],
        timeout_seconds=60,
    )
    write_json(root / "torch-pillow-execution.json", runtime)
    if runtime["exit_code"] != 0 or not runtime["enforced_before_actor_exec"]:
        raise RuntimeError(
            "Torch/Pillow did not execute successfully inside the actor boundary"
        )
    events = []

    def callback(event):
        events.append(event)
        if event["type"] == "ready":
            return b'{"step":0}\n'
        if event["type"] == "observation" and event["step"] == 0:
            return b'{"step":1}\n'
        return None

    duplex = run_actor(
        [sys.executable, "-I", str(public / "duplex.py")],
        public_root=public,
        output_root=root / "duplex-output",
        runtime_roots=common_runtime + [sys.prefix, sys.base_prefix],
        private_roots=[private, other, dataset / "private"],
        timeout_seconds=30,
        host_callback=callback,
    )
    write_json(root / "duplex-execution.json", duplex)
    if (
        duplex["exit_code"] != 0
        or duplex["callback_error"] is not None
        or len({event["pid"] for event in events}) != 1
        or [event["type"] for event in events]
        != ["ready", "observation", "observation", "STOP"]
    ):
        raise AssertionError(
            "Interactive host exchange did not preserve one isolated actor process"
        )

    def failing_callback(event):
        raise RuntimeError("intentional host callback failure")

    failed = run_actor(
        [sys.executable, "-I", str(public / "duplex.py")],
        public_root=public,
        output_root=root / "callback-error-output",
        runtime_roots=common_runtime + [sys.prefix, sys.base_prefix],
        private_roots=[private, other, dataset / "private"],
        timeout_seconds=30,
        host_callback=failing_callback,
    )
    write_json(root / "callback-error-execution.json", failed)
    if (
        failed["exit_code"] == 0
        or failed["callback_error"] is None
        or not failed["stdout"]
        or not failed["enforced_before_actor_exec"]
    ):
        raise AssertionError(
            "Callback error did not kill/reap actor and preserve original diagnostics"
        )
    result = {
        "schema": "ndu.real.isolation-probe.v1",
        "status": "PASS",
        "probe_count": len(expected_denials),
        "denied": sorted(expected_denials),
        "clean_environment": True,
        "private_canary_unchanged": json.loads((private / "canary.json").read_text())[
            "hidden_target"
        ]
        == token,
        "actual_torch_pillow": json.loads(runtime["stdout"]),
        "interactive_single_actor_process": True,
        "interactive_events": len(events),
        "callback_failure_killed_and_reaped": True,
        "actor_kernel_enforcement": attack["launch_receipt"],
        "attack_receipt_sha256": hashlib.sha256(
            (root / "attack-execution.json").read_bytes()
        ).hexdigest(),
        "torch_receipt_sha256": hashlib.sha256(
            (root / "torch-pillow-execution.json").read_bytes()
        ).hexdigest(),
        "scope": "Actual OS denial and runtime compatibility; no efficacy or native owner authentication",
    }
    write_json(root / "isolation-report.json", result)
    print(json.dumps(result, sort_keys=True), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--torch-python", required=True)
    parser.add_argument("--torch-prefix", required=True)
    parser.add_argument("--torch-base", required=True)
    parser.add_argument("--pillow-root", required=True)
    args = parser.parse_args()
    probe(
        args.output,
        args.data_root,
        args.torch_python,
        args.torch_prefix,
        args.torch_base,
        args.pillow_root,
    )
