"""Frozen small complete-network training and fresh-process continuation study.

This deliberately fits four disclosed synthetic trajectories, not a held-out
task. Sixty actual Adam updates test the same module used by downstream studies.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
from fractions import Fraction

import torch

from qualification.hcsn_currentstate.differentiable import Physics, Work
from .checkpoint import state_from_record, state_to_record
from .network import FlowNetwork


def laws():
    result = []
    for value in (1.7, 2.1):
        rate = torch.tensor(value, dtype=torch.float64)
        zero = rate.new_zeros(())
        result.append(Physics(-rate.reshape(1, 1), rate.reshape(1), zero.reshape(1),
                              rate.new_ones(1), zero.reshape(1), zero, zero, rate.new_tensor(.15),
                              Fraction(1, 5)))
    return tuple(result)


def model():
    return FlowNetwork(1, 2, layers=2, dt=Fraction(1, 10), activation="tanh").double()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def flatten_parameters(net):
    return torch.cat([p.detach().flatten() for p in net.parameters()]).tolist()


def cold(input_path, output_path):
    started, cpu = time.perf_counter(), time.process_time()
    payload = torch.load(input_path, weights_only=True)
    net = model(); net.load_state_dict(payload["model"])
    state = state_from_record(payload["state"])
    work = Work()
    with torch.no_grad():
        emitted, state = net(payload["future"], laws(), state, work)
    torch.save({"emitted": emitted, "state": state_to_record(state)}, output_path)
    write_json(output_path.with_suffix(".json"), {
        "forward_calls": 1, "optimizer_calls": 0, "exponentials": work.exponentials,
        "body_wall_seconds_after_imports": time.perf_counter() - started,
        "body_cpu_seconds_after_imports": time.process_time() - cpu,
        "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    })


def run(output):
    if output.exists():
        raise FileExistsError("one-shot study output already exists")
    output.mkdir(parents=True)
    started, cpu = time.perf_counter(), time.process_time()
    root = Path(__file__).resolve().parents[2]
    source_paths = ("qualification/hcsn_network/network.py", "qualification/hcsn_network/checkpoint.py",
                    "qualification/hcsn_network/study.py", "qualification/hcsn_network/PLAN.json",
                    "qualification/hcsn_currentstate/differentiable.py")
    source = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in source_paths}
    write_json(output / "SOURCE.json", {"files": source,
        "git_head_at_execution": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()})
    torch.manual_seed(53)
    teacher = model()
    generator = torch.Generator().manual_seed(271828)
    sequence = torch.rand((8, 4, 1), generator=generator, dtype=torch.float64) * 2 - 1
    physics = laws()
    teacher_work = Work()
    with torch.no_grad():
        target, _ = teacher(sequence, physics, work=teacher_work)
    torch.manual_seed(37)
    student = model()
    optimizer = torch.optim.Adam(student.parameters(), lr=.03)
    with torch.no_grad():
        initial_out, _ = student(sequence, physics)
        initial_loss = float((initial_out[:, :, 1:] - target[:, :, 1:]).square().mean())
    torch.save({"sequence": sequence, "target": target, "teacher": teacher.state_dict(),
                "student_initial": student.state_dict()}, output / "INPUT.pt")
    rows = []
    for step in range(1, 61):
        work = Work()
        optimizer.zero_grad(set_to_none=True)
        prediction, state = student(sequence, physics, work=work)
        loss = (prediction[:, :, 1:] - target[:, :, 1:]).square().mean()
        loss.backward()
        before = flatten_parameters(student)
        gradient = torch.cat([p.grad.flatten() for p in student.parameters()]).tolist()
        optimizer.step()
        rows.append({"step": step, "loss": float(loss.detach()), "parameters_before": before,
                     "gradient": gradient, "parameters_after": flatten_parameters(student),
                     "exp_avg": torch.cat([optimizer.state[p]["exp_avg"].flatten() for p in student.parameters()]).tolist(),
                     "exp_avg_sq": torch.cat([optimizer.state[p]["exp_avg_sq"].flatten() for p in student.parameters()]).tolist(),
                     "exponentials": work.exponentials, "largest_matrix_dimension": work.largest_dimension,
                     "state_tensor_bytes": state.tensor_bytes()})
        write_json(output / "TRAINING.json", rows)
    final_work = Work()
    with torch.no_grad():
        prediction, final_state = student(sequence, physics, work=final_work)
        final_loss = float((prediction[:, :, 1:] - target[:, :, 1:]).square().mean())
        balance_error = max(float(t.abs().max()) for t in final_state.balances())
        _, halfway = student(sequence[:4], physics)
        warm, warm_state = student(sequence[4:], physics, halfway)
    torch.save({"model": student.state_dict(), "optimizer": optimizer.state_dict(),
                "prediction": prediction, "state": state_to_record(final_state)}, output / "FINAL.pt")
    torch.save({"model": student.state_dict(), "future": sequence[4:],
                "state": state_to_record(halfway)}, output / "COLD_INPUT.pt")
    torch.save({"emitted": warm, "state": state_to_record(warm_state)}, output / "WARM.pt")
    child_started = time.perf_counter()
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    def limits():
        resource.setrlimit(resource.RLIMIT_AS, (8 * 1024**3, 8 * 1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (90, 95))
    with (output / "cold.stdout").open("w") as stdout, (output / "cold.stderr").open("w") as stderr:
        child = subprocess.run([sys.executable, "-m", "qualification.hcsn_network.study", "--cold",
                                str(output / "COLD_INPUT.pt"), str(output / "COLD.pt")], cwd=root,
                               env={**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                                    "MKL_NUM_THREADS": "1"}, stdout=stdout, stderr=stderr,
                               preexec_fn=limits, timeout=100, check=False)
    child_wall = time.perf_counter() - child_started
    children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    child_cpu = children_after.ru_utime + children_after.ru_stime - children_before.ru_utime - children_before.ru_stime
    child.check_returncode()
    saved = torch.load(output / "COLD.pt", weights_only=True)
    cold_state = state_from_record(saved["state"])
    pairs = [(warm, saved["emitted"]), *zip(warm_state.tensors(), cold_state.tensors())]
    mismatches = sum(int(torch.count_nonzero(a != b)) for a, b in pairs)
    compared = sum(a.numel() for a, _ in pairs)
    byte_equal = all(a.detach().contiguous().numpy().tobytes() == b.detach().contiguous().numpy().tobytes()
                     for a, b in pairs)
    result = {"scope": "finite shared-law causal network; four synthetic fit trajectories; no held-out task",
              "optimizer_calls": 60, "parent_student_forward_calls": 64, "teacher_forward_calls": 1,
              "cold_student_forward_calls": 1, "initial_loss": initial_loss, "final_loss": final_loss,
              "final_to_initial_loss": final_loss / initial_loss, "training_loss_reduction_pass": final_loss <= .2 * initial_loss,
              "content_mass_balance_max_abs": balance_error, "cold_compared_coordinates": compared,
              "cold_coordinate_mismatches": mismatches, "cold_tensor_bytes_equal": byte_equal,
              "cold_past_autograd_retained": False, "final_state_tensor_bytes": final_state.tensor_bytes(),
              "training_exponentials": sum(row["exponentials"] for row in rows),
              "largest_training_matrix": max(row["largest_matrix_dimension"] for row in rows),
              "teacher_exponentials": teacher_work.exponentials, "final_exponentials": final_work.exponentials,
              "body_wall_seconds_after_imports_including_child": time.perf_counter() - started,
              "parent_body_cpu_seconds_after_imports": time.process_time() - cpu,
              "fresh_child_wall_seconds_including_imports": child_wall, "fresh_child_cpu_seconds": child_cpu,
              "parent_process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "torch_version": torch.__version__, "python_version": sys.version}
    write_json(output / "RESULT.json", result)
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cold", nargs=2, type=Path)
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.cold:
        cold(*args.cold)
    elif args.output:
        run(args.output.resolve())
    else:
        parser.error("--output or --cold is required")
