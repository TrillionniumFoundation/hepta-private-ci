"""Same-PID captured H entry; no extra training child and no H request changes."""

import os
import resource
import sys
import types

from qualification.hcsn_training.joint_outputs import read_claim, read_inputs
from qualification.hcsn_training.joint_process import arm_deadline, host_id, process_identity, remaining_ns
from qualification.hcsn_training.joint_protocol import PACKET_CAP, require
from qualification.hcsn_training.joint_runner import admitted_job


def _lower_limit(kind, bound):
    soft, hard = resource.getrlimit(kind)
    maximum = min(bound, hard) if hard != resource.RLIM_INFINITY else bound
    maximum = min(maximum, soft) if soft != resource.RLIM_INFINITY else maximum
    resource.setrlimit(kind, (maximum, maximum))


def run_worker(root, key, nonce, sources, deadline_ns, expected_boot):
    # The entry already armed this same absolute deadline before HC bootstrap.
    # Re-arming uses remaining time; it never resets a full training interval.
    arm_deadline(deadline_ns, expected_boot)
    job, reservation, _ = admitted_job(root, key, nonce, sources)
    claim, _ = read_claim(root, job, reservation, sources)
    require(claim["deadline_nanoseconds"] == deadline_ns and claim["boot_id"] == expected_boot,
            "worker must inherit exact original absolute deadline")
    require(process_identity(os.getppid(), host_id()) == claim["runner"], "actual parent runner incarnation")
    require(remaining_ns(claim) > 0, "worker deadline elapsed")
    _lower_limit(resource.RLIMIT_CPU, max(1, (remaining_ns(claim) + 999999999) // 1000000000))
    _lower_limit(resource.RLIMIT_FSIZE, PACKET_CAP)
    _lower_limit(resource.RLIMIT_CORE, 0)
    child = process_identity(os.getpid(), host_id())
    job.write("worker.json", child)
    inputs, _, _, _ = read_inputs(root, reservation["input"], sources)
    root.check()
    sources.check()
    relative = "scripts/joint_generation_v4_text_worker.py"
    raw = sources.snapshots[relative][0]
    module = types.ModuleType("_joint_original_captured_H_entry")
    module.__file__ = str(sources.repo / relative)
    module.__package__ = ""
    # __name__ is not __main__; call the captured entry exactly once below.
    exec(compile(raw, module.__file__, "exec"), module.__dict__)
    sys.argv = [module.__file__, "--request", str(inputs.path / "request.json"),
                "--predecessor", str(inputs.path / "predecessor.heptapk"),
                "--output", str(job.path / reservation["identity"]["output_id"])]
    original_pid = os.getpid()
    code = module.main()
    require(os.getpid() == original_pid == child["process_id"], "H entry must execute in recorded worker PID")
    require(type(code) is int and code in (0, 1), "original H return code")
    root.check()
    sources.check()
    read_inputs(root, reservation["input"], sources)
    return code
