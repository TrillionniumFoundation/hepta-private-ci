"""Versioned local owner: real READ, pre-read SKIP, terminal STOP and recovery."""
import json
import hashlib
import time
from pathlib import Path
import numpy as np
from common import save, sha
from oracle import feasible, likelihood, outcomes


class Owner:
    def __init__(self, folder, adapter, confusion, multiplier):
        self.folder = Path(folder)
        self.adapter, self.confusion = adapter, np.asarray(confusion, float)
        self.multiplier = float(multiplier)
        start = time.perf_counter()
        public_raw = (self.folder / "public.json").read_bytes()
        self.meta = json.loads(public_raw)
        self.public_sha256 = hashlib.sha256(public_raw).hexdigest()
        self.metadata_wall_seconds = time.perf_counter()-start
        self.job, self.tick, self.budget, self.posterior = 0, 0, self.meta["budget"], .5
        self.terminal, self.reads_in_job, self.charged_cost = False, 0, 0.
        self.answers, self.events = [], []
        self.counts = dict(READ=0, SKIP=0, FIRE=0, STOP=0, content_invocations=0,
                           packet_file_reads=0, metadata_file_reads=1, payload_bytes=0)
        self.times = dict(io_wall_seconds=0., feature_wall_seconds=0., content_wall_seconds=0.,
                          content_total_cpu_seconds=0.)

    def snapshot(self):
        return dict(schema="hcsn.local-owner.snapshot.v1", session=self.meta["id"],
                    checkpoint_sha256=self.adapter.setup["checkpoint_sha256"],
                    public_sha256=self.public_sha256, multiplier=self.multiplier,
                    confusion=self.confusion.tolist(), job=self.job, tick=self.tick,
                    budget=self.budget, posterior=self.posterior, terminal=self.terminal,
                    reads_in_job=self.reads_in_job, charged_cost=self.charged_cost,
                    answers=self.answers, events=self.events, counts=self.counts, times=self.times)

    def restore(self, state):
        assert state["schema"] == "hcsn.local-owner.snapshot.v1"
        assert state["session"] == self.meta["id"]
        assert state["checkpoint_sha256"] == self.adapter.setup["checkpoint_sha256"]
        assert state["public_sha256"] == self.public_sha256
        assert state["multiplier"] == self.multiplier
        assert np.array_equal(state["confusion"], self.confusion)
        for key in ("job", "tick", "budget", "posterior", "terminal", "reads_in_job", "charged_cost", "answers", "events", "counts", "times"):
            setattr(self, key, state[key])

    def act(self, action):
        if self.terminal:
            raise RuntimeError("Terminal owner rejects every further action")
        from common import ACTIONS
        if action not in ACTIONS or not feasible(self.meta, self.job, self.tick, self.budget)[ACTIONS.index(action)]:
            raise ValueError((action, self.job, self.tick, self.budget))
        event = dict(action=action, job=self.job, tick=self.tick, budget_before=self.budget,
                     posterior_before=self.posterior)
        self.counts[action] += 1
        if action == "STOP":
            self.terminal = True
        elif action == "SKIP":
            # Branch occurs before path construction, file opening or content computation.
            self.tick += 1
        elif action == "READ":
            path = self.folder / self.meta["packets"][self.job][self.tick]
            result = self.adapter.read(path)
            self.counts["content_invocations"] += 1
            self.counts["packet_file_reads"] += 1
            self.counts["payload_bytes"] += result["payload_bytes"]
            for key in ("io_wall_seconds", "feature_wall_seconds", "content_wall_seconds"):
                self.times[key] += result[key]
            self.times["content_total_cpu_seconds"] += result["total_cpu_seconds"]
            law = likelihood(self.confusion, self.meta["reliability"][self.job][self.tick])
            _, beliefs = outcomes(self.posterior, law)
            self.posterior = float(beliefs[result["observation"]])
            self.charged_cost += self.multiplier*self.meta["price"][self.job][self.tick]
            event.update(packet=self.meta["packets"][self.job][self.tick], **result)
            self.tick, self.budget = self.tick+1, self.budget-1
            self.reads_in_job += 1
        elif action == "FIRE":
            answer = dict(job=self.job, prediction=int(self.posterior >= .5), posterior=self.posterior,
                          tick=self.tick, reads=self.reads_in_job)
            self.answers.append(answer)
            event["answer"] = answer
            self.job, self.tick = self.job+1, self.tick+2
            self.posterior, self.reads_in_job = .5, 0
        if self.job >= 2 or self.tick >= self.meta["deadline"]:
            self.terminal = True
        event.update(posterior_after=self.posterior, budget_after=self.budget,
                     next_job=self.job, next_tick=self.tick, terminal=self.terminal)
        self.events.append(event)
        return event
