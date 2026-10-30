"""Compiler-backed repair tasks and a bounded, shared execution interface.

These are authored Rust fixtures executed by an actual pinned compiler, not
historical production incidents. All policies receive the same source and
diagnostics and can choose the same four transformations. Labels are evaluator
data; neither transformation nor observation exposes them to a policy.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

import numpy as np


ACTIONS = ("borrow", "clone", "widen", "unwrap")
CALL = re.compile(r"let (score\w*) = (view\w*)\((item\w*)\);")


def sha(data):
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Task:
    case_id: str
    phase: str
    source: str
    expected_stdout: str
    training_actions: tuple
    source_id: str


def _part(family, number, name):
    suffix = str(name)
    item, view, score = f"item{suffix}", f"view{suffix}", f"score{suffix}"
    if family in (0, 1):
        literal = "memo" + str(number)
        arg = "&str" if family == 0 else "String"
        definition = f"fn {view}(value: {arg}) -> usize {{ value.len() }}"
        declaration = f'let {item} = String::from("{literal}");'
        result = score if family == 0 else f"{score} + {item}.len()"
        expected = len(literal) * (1 if family == 0 else 2)
    elif family == 2:
        definition = f"fn {view}(value: u64) -> u64 {{ value + 3 }}"
        declaration = f"let {item}: u32 = {number};"
        result, expected = score, number + 3
    elif family == 3:
        definition = f"fn {view}(value: u32) -> u32 {{ value + 3 }}"
        declaration = f"let {item}: Option<u32> = Some({number});"
        result, expected = score, number + 3
    else:
        raise ValueError("unknown authored family")
    return (f"{definition}\nfn part{suffix}() -> u64 {{\n"
            f"    {declaration}\n    let {score} = {view}({item});\n"
            f"    ({result}) as u64\n}}\n"), expected


def make_tasks(seed, phase, per_family=12, *, paired=False, unknown=4):
    """Distinct source identities and values for each predeclared partition."""
    rng = np.random.default_rng(seed)
    tasks = []
    for family in range(4):
        for index in range(per_family):
            families = (family, (family + 1 + index % 3) % 4) if paired else (family,)
            name = f"x{int(rng.integers(0, 2**48)):012x}"
            parts, total = [], 0
            for slot, kind in enumerate(families):
                code, value = _part(kind, int(rng.integers(101, 100000)), f"{name}_{slot}")
                parts.append(code)
                total += value
            expression = " + ".join(f"part{name}_{slot}()" for slot in range(len(parts)))
            source = "".join(parts) + f'fn main() {{ println!("{{}}", {expression}); }}\n'
            tasks.append(Task(f"{phase}-{family}-{index}", phase, source,
                              str(total) + "\n", families, sha(source.encode())))
    for index in range(unknown):
        symbol = f"symbol{int(rng.integers(0, 2**48)):012x}"
        source = f'fn main() {{ println!("{{}}", {symbol}()); }}\n'
        tasks.append(Task(f"{phase}-unknown-{index}", phase, source, "", (), sha(source.encode())))
    return tasks


def transform(source, action, *, line=None):
    """One bounded textual operation; no generated shell or unrestricted code."""
    if action not in ACTIONS:
        raise ValueError("unregistered action")
    matches = list(CALL.finditer(source))
    if not matches:
        return source
    if line is None:
        match = matches[0]
    else:
        match = min(matches, key=lambda m: abs(source.count("\n", 0, m.start()) + 1 - line))
    variable, function, argument = match.groups()
    replacement = {"borrow": f"&{argument}", "clone": f"{argument}.clone()",
                   "widen": f"u64::from({argument})", "unwrap": f"{argument}.unwrap_or(0)"}[action]
    return source[:match.start()] + f"let {variable} = {function}({replacement});" + source[match.end():]


class Compiler:
    """Actual compilation/execution; cache reuse is explicit and separately counted."""

    def __init__(self, rustc, directory, *, timeout=20):
        self.rustc, self.directory, self.timeout = str(rustc), Path(directory), timeout
        self.directory.mkdir(parents=True, exist_ok=True)
        version = subprocess.run([self.rustc, "--version", "--verbose"], text=True,
                                 capture_output=True, check=True, timeout=timeout)
        self.identity = {"version": version.stdout, "path": self.rustc}
        self.calls, self.cache_hits, self.seconds = 0, 0, 0.0

    def inspect(self, source, *, use_cache=False):
        identity = sha(source.encode())
        saved = self.directory / (identity + ".json")
        if use_cache and saved.exists():
            self.cache_hits += 1
            return json.loads(saved.read_text())
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="compile-", dir=self.directory) as scratch:
            root = Path(scratch)
            (root / "fixture.rs").write_text(source)
            command = [self.rustc, "--edition=2024", "--error-format=json", "-C", "debuginfo=0",
                       str(root / "fixture.rs"), "-o", str(root / "fixture")]
            result = subprocess.run(command, text=True, capture_output=True, timeout=self.timeout)
            diagnostics = []
            for row in result.stderr.splitlines():
                try:
                    item = json.loads(row)
                except json.JSONDecodeError:
                    continue
                if item.get("level") == "error" and item.get("spans"):
                    span = next((s for s in item["spans"] if s.get("is_primary")), item["spans"][0])
                    diagnostics.append({"message": item["message"], "code": (item.get("code") or {}).get("code"),
                                        "line": span["line_start"],
                                        "rendered": item.get("rendered", "").replace(str(root), "$FIXTURE")})
            stdout, run_code = "", None
            if result.returncode == 0:
                run = subprocess.run([str(root / "fixture")], text=True, capture_output=True, timeout=self.timeout)
                stdout, run_code = run.stdout, run.returncode
            observation = {"source_sha256": identity, "compile_returncode": result.returncode,
                           "run_returncode": run_code, "stdout": stdout, "diagnostics": diagnostics,
                           "wall_seconds": time.perf_counter() - started,
                           "compiler_version": self.identity["version"]}
        self.calls += 1
        self.seconds += observation["wall_seconds"]
        if saved.exists() and json.loads(saved.read_text())["compiler_version"] != self.identity["version"]:
            raise ValueError("compiler cache version drift")
        saved.write_text(json.dumps(observation, sort_keys=True, indent=2) + "\n")
        return observation


def observation_text(source, observation):
    first = observation["diagnostics"][0] if observation["diagnostics"] else {}
    # Source and all diagnostic information are shared with every compared policy.
    return (f"Rust repair. Error {first.get('code', '')}: {first.get('message', '')}\n"
            f"{first.get('rendered', '')}\nSOURCE\n{source}")


def diagnostic_rule(observation):
    """Strong deterministic compiler-guided control, with the same public input."""
    if not observation["diagnostics"]:
        return None
    first = observation["diagnostics"][0]
    code, text = first["code"], first["rendered"]
    if code == "E0382":
        return "clone"
    if code == "E0308":
        if "expected `&str`" in text:
            return "borrow"
        if "expected `u64`" in text:
            return "widen"
        if "Option<u32>" in text:
            return "unwrap"
    return None


def execute_policy(task, compiler, choose, *, steps=2, use_cache=False):
    """Run a policy on observed intermediate compiler feedback under one budget."""
    source, trace = task.source, []
    initial_calls, initial_hits = compiler.calls, compiler.cache_hits

    def finish(result):
        return dict(result, actual_compiler_calls=compiler.calls - initial_calls,
                    observation_requests=compiler.calls - initial_calls + compiler.cache_hits - initial_hits,
                    cache_hits=compiler.cache_hits - initial_hits)

    for step in range(steps + 1):
        observation = compiler.inspect(source, use_cache=use_cache)
        if observation["compile_returncode"] == 0:
            correct = observation["run_returncode"] == 0 and observation["stdout"] == task.expected_stdout
            return finish({"case_id": task.case_id, "success": correct, "status": "executed", "trace": trace,
                           "final": observation, "source_sha256": task.source_id})
        if step == steps:
            break
        action, information = choose(observation_text(source, observation), observation)
        trace.append({"step": step, "action": action, "information": information, "applied": False,
                      "observed_source_sha256": observation["source_sha256"]})
        if action is None:
            return finish({"case_id": task.case_id, "success": not task.training_actions,
                           "status": "abstained", "trace": trace, "final": observation,
                           "source_sha256": task.source_id})
        line = observation["diagnostics"][0]["line"] if observation["diagnostics"] else None
        next_source = transform(source, action, line=line)
        if next_source == source:
            break
        trace[-1]["applied"] = True
        source = next_source
    return finish({"case_id": task.case_id, "success": False, "status": "budget_exhausted",
                   "trace": trace, "final": observation, "source_sha256": task.source_id})


def dump_tasks(tasks, path):
    Path(path).write_text(json.dumps([asdict(task) for task in tasks], sort_keys=True, indent=2) + "\n")
