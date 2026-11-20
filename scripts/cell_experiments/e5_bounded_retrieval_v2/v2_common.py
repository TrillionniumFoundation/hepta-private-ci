"""Immutable local preparation policy; this module grants no execution authority."""

import hashlib
import json
import re
import time
from pathlib import Path

POLICY_SHA = "723eedbec46c40cfd7a770e2667c981aeb23d18ef5892379830c7ec10773bc1d"
BASE = Path(__file__).resolve().parent


class Refusal(ValueError):
    pass


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def require(condition, message):
    if not condition:
        raise Refusal(message)


def policy():
    raw = (BASE / "POLICY.json").read_bytes()
    require(sha(raw) == POLICY_SHA, "frozen policy changed")
    return json.loads(raw)


def code_identity():
    return sha(
        canonical(
            {
                p.name: sha(p.read_bytes())
                for p in sorted(BASE.glob("*.py"))
                if not p.name.startswith("test_")
            }
        )
    )


_STOP = frozenset(policy()["terms"]["stop"])


def terms(text):
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    words = re.findall(r"[A-Za-z][A-Za-z0-9_]{1,63}", text)
    result = []
    for word in words:
        for part in word.lower().split("_"):
            if len(part) > 4 and part.endswith("s"):
                part = part[:-1]
            if len(part) >= 3 and part not in _STOP:
                result.append(part)
    return result


class Budget:
    def __init__(self):
        self.limits = policy()["cost_limits"]
        self.wall = time.monotonic()
        self.cpu = time.process_time()
        self.counts = {"source_units": 0, "ast_nodes": 0}

    def check(self, **counts):
        self.counts.update(counts)
        for name, value in self.counts.items():
            require(value <= self.limits[name], "source preparation limit: " + name)
        require(
            time.monotonic() - self.wall <= self.limits["wall_seconds"],
            "source preparation wall limit",
        )
        require(
            time.process_time() - self.cpu <= self.limits["cpu_seconds"],
            "source preparation CPU limit",
        )

    def receipt(self):
        self.check()
        return {
            **self.counts,
            "wall_seconds": time.monotonic() - self.wall,
            "cpu_seconds": time.process_time() - self.cpu,
            "retrieval_calls": 1,
            "hard_preemptive_deadline": False,
        }
