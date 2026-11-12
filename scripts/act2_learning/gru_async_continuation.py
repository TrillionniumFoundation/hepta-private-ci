"""One controlled GRU invocation on the existing durable async SQLite owner.

Model proposals never create effect authority. A pending decision is committed
before the sole original release; restored controllers only query that effect.
No multi-step policy, copied-state, power-loss or production qualification.
"""

import hashlib
import io
import json
from pathlib import Path
import time
from types import SimpleNamespace

import numpy as np

import durable_async_owner
from durable_async_owner import DurableAsyncOwner, canonical
from file_family import FileOwner
import models
from models import Model
import run


def digest(data):
    return hashlib.sha256(data).hexdigest()


class GRUAsyncContinuation:
    @classmethod
    def start(cls, model_path, directory, **spec):
        self = cls._model(model_path)
        self.owner = DurableAsyncOwner.start(directory=directory, **spec)
        try:
            self.expected["owner"] = self.owner.expected
            self.state = {
                "binding": self.expected,
                "sequence": 0,
                "hidden": np.zeros(12, dtype="<f8").tobytes().hex(),
                "actions": [],
                "features": [],
                "phase": "READY",
                "pending": None,
            }
            self.revision = 0
            self.owner.db.execute(
                "CREATE TABLE gru_state(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER, digest TEXT, body BLOB)"
            )
            self.owner.db.execute("INSERT INTO gru_state VALUES(1,0,'',X'')")
            self.owner.db.commit()
            self._save()
            return self
        except BaseException:
            self.owner.close()
            raise

    @classmethod
    def restore(cls, model_path, directory, **spec):
        self = cls._model(model_path)
        self.owner = DurableAsyncOwner.restore(directory=directory, **spec)
        try:
            self.expected["owner"] = self.owner.expected
            self.revision, checksum, raw = self.owner.db.execute(
                "SELECT revision,digest,body FROM gru_state WHERE id=1"
            ).fetchone()
            if len(raw) > 65536 or digest(raw) != checksum:
                raise ValueError("GRU checkpoint checksum")
            self.state = json.loads(raw)
            self._validate()
            if self.owner.state["release_attempted"] and self.state["phase"] not in (
                "PENDING",
                "DONE",
            ):
                raise ValueError("GRU checkpoint predates original release")
            self.restored = True
            return self
        except BaseException:
            self.owner.close()
            raise

    @classmethod
    def _model(cls, path):
        self = cls()
        self.restored = False
        raw = Path(path).read_bytes()
        self.model = Model("gru", 0)
        with np.load(io.BytesIO(raw), allow_pickle=False) as saved:
            if set(saved.files) != set(self.model.p):
                raise ValueError("GRU parameter set")
            for name, expected in self.model.p.items():
                value = saved[name]
                if (
                    value.shape != expected.shape
                    or value.dtype != np.dtype("float64")
                    or not np.isfinite(value).all()
                ):
                    raise ValueError("GRU parameter shape/dtype/value")
                self.model.p[name] = value.copy()
        self.expected = {
            "model": digest(raw),
            "source": {
                p.name: digest(p.read_bytes())
                for p in (
                    Path(__file__),
                    Path(models.__file__),
                    Path(run.__file__),
                    Path(durable_async_owner.__file__),
                )
            },
        }
        return self

    def _pending(self):
        spec = self.owner.spec
        return {
            "invocation": spec["invocation"],
            "key": spec["key"],
            "goal_sha256": digest(spec["task"]["goals"][spec["key"]].encode()),
            "spec_sha256": digest(canonical(spec)),
        }

    def _validate(self):
        s = self.state
        if (
            set(s)
            != {
                "binding",
                "sequence",
                "hidden",
                "actions",
                "features",
                "phase",
                "pending",
            }
            or s["binding"] != self.expected
            or type(s["sequence"]) is not int
            or not 0 <= s["sequence"] <= 2
            or len(s["actions"]) != s["sequence"]
            or len(s["features"]) != s["sequence"]
            or any(a not in run.OPTIONS for a in s["actions"])
        ):
            raise ValueError("GRU checkpoint binding or sequence")
        hidden = bytes.fromhex(s["hidden"])
        if (
            len(hidden) != 96
            or not np.isfinite(np.frombuffer(hidden, dtype="<f8")).all()
            or hidden.hex() != s["hidden"]
        ):
            raise ValueError("GRU hidden checkpoint")
        if any(
            not isinstance(f, list) or len(f) != 10 or not np.isfinite(f).all()
            for f in s["features"]
        ):
            raise ValueError("GRU feature checkpoint")
        expected = {
            "READY": (0, None),
            "PENDING": (1, self._pending()),
            "NO_DISPATCH": (1, None),
            "DONE": (2, None),
        }
        if (
            s["phase"] not in expected
            or (s["sequence"], s["pending"]) != expected[s["phase"]]
        ):
            raise ValueError("GRU phase or original pending identity")
        if s["phase"] in ("PENDING", "DONE") and s["actions"][0] != "ensure":
            raise ValueError("GRU pending action drift")

    def _save(self):
        self._validate()
        raw = canonical(self.state)
        if len(raw) > 65536:
            raise ValueError("GRU checkpoint bound")
        with self.owner.db:
            changed = self.owner.db.execute(
                "UPDATE gru_state SET revision=?,digest=?,body=? WHERE id=1 AND revision=?",
                (self.revision + 1, digest(raw), raw, self.revision),
            ).rowcount
            if changed != 1:
                raise ValueError("GRU checkpoint writer conflict")
        self.revision += 1

    def _head(self):
        revision, checksum, raw = self.owner.db.execute(
            "SELECT revision,digest,body FROM gru_state WHERE id=1"
        ).fetchone()
        if (
            revision != self.revision
            or raw != canonical(self.state)
            or digest(raw) != checksum
        ):
            raise ValueError("GRU state is not the committed original checkpoint")

    def _feature(self, require_complete):
        spec = self.owner.spec
        if spec["key"] != 0 or len(spec["task"]["goals"]) != 1:
            raise ValueError("single original invocation only")
        # First enforce the original invocation/payload binding on every read.
        knowledge = self.owner.observe(time.monotonic_ns())["knowledge"]
        expected_knowledge = "CONFIRMED_COMPLETE" if require_complete else "UNKNOWN"
        if knowledge != expected_knowledge:
            raise ValueError("GRU original invocation knowledge changed")
        owner = FileOwner.__new__(FileOwner)
        owner.path, owner.calls, owner.task = (
            self.owner.directory / "destination",
            [],
            spec["task"],
        )
        owner.manifest_sha256 = digest(json.dumps(owner.task, sort_keys=True).encode())
        if any(
            r["invocation"] != spec["invocation"] or r["key"] != spec["key"]
            for r in owner._records()
        ):
            raise ValueError("foreign original GRU invocation")
        view = owner.observe()
        if view is None:
            raise ValueError("GRU public observation unavailable")
        if view["complete"] != require_complete:
            raise ValueError("GRU original invocation completion changed")
        return run.encode(
            SimpleNamespace(view=view, last="inspect", task=owner.task, failed_reads=0)
        )

    def _infer(self, feature):
        hidden = np.frombuffer(bytes.fromhex(self.state["hidden"]), dtype="<f8").copy()
        choice, hidden = self.model.choose(feature, hidden)
        self.state["hidden"] = hidden.astype("<f8").tobytes().hex()
        self.state["sequence"] += 1
        self.state["actions"].append(run.OPTIONS[choice])
        self.state["features"].append(feature)

    def plan(self):
        self._head()
        if self.state["phase"] != "READY" or self.owner.owner is None:
            raise ValueError("pending GRU inference cannot replay")
        self._infer(self._feature(False))
        selected = self.state["actions"][-1]
        self.state.update(
            phase="PENDING" if selected == "ensure" else "NO_DISPATCH",
            pending=self._pending() if selected == "ensure" else None,
        )
        self._save()  # Post-inference hidden and exact invocation precede release.
        return selected

    def release(self):
        self._head()
        if self.state["phase"] != "PENDING":
            raise ValueError("no committed GRU original invocation")
        self.owner.release()

    def observe(self, deadline_ns):
        self._head()
        result = self.owner.observe(deadline_ns)
        return {
            **result,
            "model_hidden_state_restored": self.restored,
            "hidden": self.state["hidden"],
            "sequence": self.state["sequence"],
            "pending": self.state["pending"],
            "actions": self.state["actions"].copy(),
        }

    def finish(self):
        result = self.observe(time.monotonic_ns())
        if result["knowledge"] != "CONFIRMED_COMPLETE":
            raise ValueError("original GRU pending effect remains UNKNOWN")
        if self.state["phase"] == "DONE":
            return result
        if self.state["phase"] != "PENDING":
            raise ValueError("no committed GRU pending decision")
        self._infer(self._feature(True))
        self.state.update(phase="DONE", pending=None)
        self._save()
        return self.observe(time.monotonic_ns())

    def close(self):
        self.owner.close()
