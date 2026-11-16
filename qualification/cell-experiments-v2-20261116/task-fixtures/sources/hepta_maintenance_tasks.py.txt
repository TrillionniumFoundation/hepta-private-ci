"""Fixed generated maintenance tasks, CPython observations and raw evidence."""

import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np

try:
    import resource
except ImportError:
    resource = None

ARMS = ("frozen", "no_learning", "no_memory", "candidate", "deterministic")

TOKENS = (
    "expected ':'",
    "was never closed",
    "unterminated string",
    "expected an indented block",
)

UPDATES, WALL_BUDGET_SECONDS = 16, 120


def save(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def sources():
    base = Path(__file__).resolve().parents[1]
    paths = {
        Path(__file__).resolve(),
        Path(__file__).with_name("maintenance_cycle.py").resolve(),
    }
    paths.update(
        Path(m.__file__).resolve()
        for n, m in sys.modules.items()
        if n.startswith(("hepta_cells", "hepta_pred1")) and getattr(m, "__file__", None)
    )
    return {
        str(p.relative_to(base)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(paths)
    }


def freeze_sources(root, source_hashes):
    """Retain the exact executed module bytes before any observations occur."""
    base = Path(__file__).resolve().parents[1]
    destination = root / "executed-source"
    destination.mkdir()
    for name, expected in source_hashes.items():
        raw = (base / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("source changed while freezing original bytes")
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())


def child_cpu_seconds():
    if resource is None:
        return None
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def fixtures():
    panels = {}
    for phase, offset in (("A", 0), ("B", 100), ("C", 200)):
        rows = []
        for i in range(8):
            name, number = f"fixture_{phase}_{i}", offset + i + 3
            programs = (
                f"def {name}(x)\n    return x + {number}\n",
                f"def {name}(x):\n    return (x + {number}\n",
                f'def {name}(x):\n    return "tag_{number}\n',
                f"def {name}(x):\nreturn x + {number}\n",
            )
            rows.append({"id": name, "source": programs[i % 4]})
        panels[phase] = rows
    return panels


def repair(source, action):
    lines = source.splitlines()
    if action == 0 and not lines[0].endswith(":"):
        lines[0] += ":"
    elif action == 1:
        lines[-1] += ")"
    elif action == 2:
        lines[-1] += '"'
    elif action == 3:
        lines[-1] = "    " + lines[-1].lstrip()
    return "\n".join(lines) + "\n"


class Compiler:
    def __init__(self, root, started):
        self.path, self.started, self.calls = root / "compile.jsonl", started, 0
        self.path.touch(exist_ok=False)

    def check(self, task, source, phase, arm):
        if time.perf_counter() - self.started > WALL_BUDGET_SECONDS:
            raise TimeoutError("predeclared whole-run budget exhausted")
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        success, message, line = True, None, None
        try:
            compile(source, task["id"] + ".py", "exec", dont_inherit=True)
        except SyntaxError as error:
            success, message, line = False, error.msg, error.lineno
        result = dict(
            task=task["id"],
            phase=phase,
            arm=arm,
            source=source,
            source_sha256=hashlib.sha256(source.encode()).hexdigest(),
            success=success,
            error=message,
            error_line=line,
            wall_ns=time.perf_counter_ns() - wall,
            cpu_ns=time.process_time_ns() - cpu,
        )
        with self.path.open("a") as stream:
            stream.write(json.dumps(result, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.calls += 1
        return result


def observations(task, original):
    text = task["source"]
    first = [
        len(text) / 128,
        len(text.splitlines()) / 4,
        (text.count("(") - text.count(")")) / 4,
        text.count('"') % 2,
        text.count(":") / 4,
        int(text.splitlines()[-1].startswith("    ")),
        0,
        0,
        0,
        0,
        1,
        0,
        0,
    ]
    second = (
        [0.0] * 6 + [float(token in original["error"]) for token in TOKENS] + [0, 1, 0]
    )
    return np.asarray([first, second, [0.0] * 12 + [1.0]], dtype=np.float64)
