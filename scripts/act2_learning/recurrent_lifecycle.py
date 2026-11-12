"""Joint GRU/control checkpoint for the Linux cooperating, same-UID file fixture.

One SQLite row contains controls, post-inference hidden bytes and pending intent.
This is process-death recovery, not production authority, power-loss durability,
new-boot continuation, hostile-owner authentication or common-rollback protection.
An entered effect is reconciled, never automatically sent again.
"""

import io
import json
import os
from pathlib import Path
import stat
import zipfile

import numpy as np

import diagnose
import models
import run
from durable_lifecycle import DurableLifecycle, FIELDS, binding, canonical, sha
from sqlite_destination import BudgetExhausted


CONFIG = {"features": 10, "hidden": 12, "dtype": "<f8", "actions": list(run.OPTIONS)}


class RecurrentLifecycle(DurableLifecycle):
    """Persist existing guarded inspect/ensure/stop state before file owner entry.

    ``step`` returns false when terminal or blocked; ``report`` distinguishes those
    states and obtains fresh goal knowledge. Restoring never performs inference or
    replays an entered skill. Original pause, deadline and budgets remain in force.
    """

    state_fields = FIELDS + ("policy",)

    def _binding(self, task, contract, model_path):
        with Path(model_path).open("rb") as source:
            raw = source.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("model artifact exceeds bound")
        self.model = models.Model("gru", 0)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if (
                len(members) != len(self.model.p)
                or {m.filename for m in members} != {k + ".npy" for k in self.model.p}
                or any(m.file_size > 65536 for m in members)
                or sum(m.file_size for m in members) > 262144
            ):
                raise ValueError("model archive members exceed contract")
            for key, reference in self.model.p.items():
                payload = archive.read(key + ".npy")
                stream = io.BytesIO(payload)
                if np.lib.format.read_magic(stream) != (1, 0):
                    raise ValueError("unsupported bounded model tensor format")
                shape, fortran, dtype = np.lib.format.read_array_header_1_0(
                    stream, max_header_size=4096
                )
                if (
                    shape != reference.shape
                    or dtype != np.dtype("<f8")
                    or fortran
                    or len(payload) - stream.tell() != reference.nbytes
                ):
                    raise ValueError("model tensor shape or dtype drift")
                value = np.frombuffer(
                    payload, dtype="<f8", offset=stream.tell()
                ).reshape(shape)
                if not np.isfinite(value).all():
                    raise ValueError("model tensor value drift")
                self.model.p[key] = value.copy()
        self.directory = self.directory.absolute()
        configuration = {
            "features": self.model.p["Wz"].shape[0],
            "hidden": self.model.hidden,
            "dtype": "<f8",
            "actions": list(run.OPTIONS),
        }
        if configuration != CONFIG:
            raise ValueError("unsupported recurrent configuration")
        self.restored = False
        self.policy = {
            "hidden": np.zeros(12, dtype="<f8").tobytes().hex(),
            "sequence": 0,
            "phase": "ready",
            "pending": None,
            "decisions": [],
            "claimed": False,
            "owner": None,
        }
        return {
            **binding(task, contract, model_path, model_digest=sha(raw)),
            "controller": {
                "schema": "act3-recurrent-lifecycle-v1",
                "uid": os.geteuid(),
                "configuration": configuration,
                "source": {
                    p.name: sha(p.read_bytes())
                    for p in (
                        Path(__file__),
                        Path(models.__file__),
                        Path(run.__file__),
                        Path(diagnose.__file__),
                    )
                },
            },
        }

    @classmethod
    def restore(cls, task, contract, model_path, directory):
        self = super().restore(task, contract, model_path, directory)
        self.restored = True
        return self

    def _open(self, create):
        if self.directory.resolve() != self.directory:
            raise ValueError("original owner path is aliased")
        directory = self.directory.lstat()
        admission = canonical(
            {
                "binding": self.expected,
                "directory": [directory.st_dev, directory.st_ino, directory.st_uid],
            }
        )
        path = self.directory / "admission.json"
        if create:
            with path.open("xb") as stream:
                stream.write(admission)
                stream.flush()
                os.fsync(stream.fileno())
            descriptor = os.open(self.directory, os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        if not create:
            # A rejected restore must not create a missing lock or follow an
            # alias before the persisted owner identity can be checked.
            self._owner_identity()
            with path.open("rb") as stream:
                original = stream.read(65537)
            if original != admission:
                raise ValueError("original admission binding or directory drift")
            # Binding rejection precedes writable SQLite open, including any
            # recovery of a hot rollback journal. This is a same-UID original,
            # not an independently authenticated or anti-rollback witness.
        super()._open(create)

    def _owner_identity(self):
        if self.directory.resolve() != self.directory:
            raise ValueError("original owner path is aliased")
        identity = {}
        for name, directory in (
            ("", True),
            ("control.db", False),
            ("admission.json", False),
            ("writer.lock", False),
            ("destination", True),
            ("destination/owner.json", False),
            ("destination/contract.json", False),
            ("destination/effects", True),
            ("destination/staged", True),
        ):
            value = (self.directory / name).lstat()
            valid = (
                stat.S_ISDIR(value.st_mode)
                if directory
                else stat.S_ISREG(value.st_mode)
            )
            if (
                not valid
                or value.st_uid != os.geteuid()
                or (not directory and value.st_nlink != 1)
            ):
                raise ValueError("original owner path type or UID changed")
            identity[name] = [value.st_dev, value.st_ino, value.st_uid]
        return identity

    def _save(self):
        # Called by every inherited primitive reservation, original apply entry,
        # pause/resume and restore. Validation precedes the sole SQL UPDATE.
        state = self.policy
        if (
            not isinstance(state, dict)
            or set(state)
            != {
                "hidden",
                "sequence",
                "phase",
                "pending",
                "decisions",
                "claimed",
                "owner",
            }
            or type(state["sequence"]) is not int
            or not 0 <= state["sequence"] <= 2 * self.budget
            or not isinstance(state["decisions"], list)
            or len(state["decisions"]) != state["sequence"]
            or any(action not in run.OPTIONS for action in state["decisions"])
            or state["phase"] not in ("ready", "prepared", "entered", "terminal")
            or type(state["claimed"]) is not bool
            or (state["claimed"] and state["phase"] != "terminal")
            or not isinstance(state["hidden"], str)
            or len(state["hidden"]) != 192
        ):
            raise ValueError("invalid recurrent checkpoint fields")
        hidden = bytes.fromhex(state["hidden"])
        if (
            hidden.hex() != state["hidden"]
            or not np.isfinite(np.frombuffer(hidden, dtype="<f8")).all()
        ):
            raise ValueError("invalid recurrent hidden bytes")
        pending = state["pending"]
        if state["phase"] in ("prepared", "entered"):
            if (
                not isinstance(pending, dict)
                or set(pending)
                != {"action", "proposed", "key", "invocation", "goal_sha256"}
                or not state["decisions"]
                or pending["action"] != state["decisions"][-1]
                or pending["proposed"] not in run.OPTIONS
                or type(pending["key"]) is not int
                or not 0 <= pending["key"] <= len(self.task["goals"])
            ):
                raise ValueError("invalid recurrent pending decision")
            key = pending["key"]
            goal = self.task["goals"][key] if key < len(self.task["goals"]) else None
            if pending["invocation"] != self.task["id"] + ":" + str(key) or pending[
                "goal_sha256"
            ] != (sha(goal.encode()) if goal is not None else None):
                raise ValueError("recurrent original invocation drift")
        elif pending is not None:
            raise ValueError("unexpected recurrent pending decision")
        identity = self._owner_identity()
        if state["owner"] is None and self.revision == 0:
            state["owner"] = identity
        if state["owner"] != identity:
            raise ValueError("original recurrent owner identity drift")
        super()._save()

    def step(self):
        self._refresh()
        self._save()
        state = self.policy
        if state["phase"] == "terminal":
            return False
        if self.calls >= self.budget:
            raise BudgetExhausted()
        if state["phase"] == "entered":
            # An earlier controller may have entered this skill. Only an exact
            # original readback can settle it; absence does not permit a resend.
            pending = state["pending"]
            current = self.inspect()
            if pending["action"] == "ensure" and (
                current is None or current["index"] <= pending["key"]
            ):
                return False
            state.update(
                phase="terminal" if pending["action"] == "stop" else "ready",
                claimed=bool(
                    pending["action"] == "stop" and current and current["complete"]
                ),
                pending=None,
            )
            self._save()
            return state["phase"] == "ready" and self.state == "RUNNING"
        if self.state != "RUNNING":
            return False
        if state["phase"] == "ready":
            if state["sequence"] >= 2 * self.budget:
                raise BudgetExhausted()
            hidden = np.frombuffer(bytes.fromhex(state["hidden"]), dtype="<f8").copy()
            choice, hidden = self.model.choose(run.encode(self), hidden)
            proposed = run.OPTIONS[choice]
            selected, _ = diagnose.guard_action(self, proposed)
            key = self.view["index"] if self.view is not None else 0
            goal = self.task["goals"][key] if key < len(self.task["goals"]) else None
            state.update(
                hidden=hidden.astype("<f8").tobytes().hex(),
                sequence=state["sequence"] + 1,
                phase="prepared",
                pending={
                    "action": selected,
                    "proposed": proposed,
                    "key": key,
                    "invocation": self.task["id"] + ":" + str(key),
                    "goal_sha256": sha(goal.encode()) if goal is not None else None,
                },
            )
            state["decisions"].append(selected)
            self._save()  # Hidden and exact decision precede any owner operation.
        pending = state["pending"]
        if pending["action"] == "ensure":
            # Restore discarded the old observation. Also refresh for a live
            # controller: a prepared skill never changes to a different key.
            current = self.inspect()
            if current is None:
                return False
            if current["index"] < pending["key"]:
                raise ValueError("original prepared goal regressed")
            if current["index"] > pending["key"] or current["complete"]:
                state.update(phase="ready", pending=None)
                self._save()
                return True
            if not self._may_mutate("recurrent_ensure"):
                self._save()
                return False
        state["phase"] = "entered"
        self._save()  # Conservative uncertainty covers a cut before owner entry.
        if pending["action"] == "ensure":
            self.ensure()
            if pending["key"] in self.unresolved:
                return False
        else:
            current = self.inspect()
            state["claimed"] = bool(
                pending["action"] == "stop" and current and current["complete"]
            )
        state.update(
            phase="terminal" if pending["action"] == "stop" else "ready", pending=None
        )
        self._save()
        return state["phase"] == "ready" and self.state == "RUNNING"

    def report(self):
        # A saved successful STOP is a proposal, not a current completion receipt.
        try:
            self.inspect()
        except BudgetExhausted:
            self.view = None
        result = self.score(self.policy["claimed"])
        if (
            self.policy["phase"] == "entered"
            and self.policy["pending"]["action"] == "ensure"
            and (
                self.view is None or self.view["index"] <= self.policy["pending"]["key"]
            )
        ):
            result["effect_knowledge"] = "UNKNOWN"
        return {
            **result,
            "model_hidden_state_restored": self.restored,
            "policy": json.loads(canonical(self.policy)),
            "binding": json.loads(canonical(self.expected)),
            "production_adoption": False,
            "learning_gain_qualified": False,
        }
