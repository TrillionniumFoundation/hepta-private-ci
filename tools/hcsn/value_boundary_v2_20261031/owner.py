"""Actual file/model execution for the declared regenerative evidence cell.

The decoder channel is exact on a finite, exhaustively checked payload support.
This deliberately narrow control benchmark makes no natural-content claim.
One hidden deadline is drawn per session and competes with all elapsed intervals.
"""
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from tools.hcsn.task_value_factorial_20261030.task import ContentAdapter, packet, save, sha
from .model import ACTION_NAMES, FIRE, Model, READ, STOP


class PayloadBank:
    """Finite model-input support; every member is decoded before task use."""

    def __init__(self, root, adapter=None):
        wall, cpu = time.perf_counter(), time.process_time()
        self.adapter = ContentAdapter() if adapter is None else adapter
        self.templates, self.classes, rows = {}, {0: [], 1: []}, []
        for index in range(8):
            template = packet(index % 2, 703100+index, length=16)
            path = Path(root)/f"support_{index}.json"
            save(path, template)
            decoded = self.adapter.read(path)
            observed = decoded["observation"]
            self.templates[index] = template
            self.classes[observed].append(index)
            rows.append(dict(index=index, path=str(path), **decoded))
        if any(not self.classes[label] for label in (0, 1)):
            raise RuntimeError("The verified finite support does not span both observations")
        self.receipt = dict(schema="hcsn.regenerative-evidence.finite-support.v1", rows=rows,
            classes=self.classes, adapter_setup=self.adapter.setup,
            cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall,
            scope="Exact observation classes on eight checked symbols/dt inputs only; nonce is ignored by the frozen decoder")

    def make_episode(self, root, contract, identifier, seed):
        wall, cpu = time.perf_counter(), time.process_time()
        contract.validate()
        rng = np.random.default_rng(seed)
        folder = Path(root)/identifier
        labels = rng.integers(0, 2, len(contract.reliability)).tolist()
        public = dict(id=identifier, contract=contract.serializable(), packets=[])
        files = {}
        for job, q in enumerate(contract.reliability):
            names = []
            for index in range(contract.budget):
                observation = labels[job] if rng.random() < q else 1-labels[job]
                template_id = int(rng.choice(self.classes[observation]))
                value = dict(self.templates[template_id], template_id=template_id,
                             receipt_nonce=int(rng.integers(0, 2**63-1)))
                name = f"job{job}_read{index}.json"
                save(folder/name, value)
                files[name] = sha(folder/name)
                names.append(name)
            public["packets"].append(names)
        clocks = dict(deadline=float(rng.exponential(1/contract.deadline_rate)),
            read_waits=[rng.exponential(1/rate, contract.budget).tolist() for rate in contract.arrival_rate],
            recovery_waits=[rng.exponential(1/contract.recovery_rate, contract.recovery_phases).tolist()
                            for _ in contract.reliability])
        for name, data in (("public.json", public), ("private_clocks.json", clocks),
                           ("evaluator_labels.json", dict(labels=labels))):
            save(folder/name, data)
            files[name] = sha(folder/name)
        return dict(id=identifier, seed=seed, folder=str(folder.resolve()), files=files,
                    cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall)


class Owner:
    """Policy sees only (job,budget,evidence), public contract and event history."""

    def __init__(self, episode, contract, bank):
        self.folder, self.contract, self.bank = Path(episode["folder"]), contract, bank
        self.public = json.loads((self.folder/"public.json").read_text())
        if self.public["contract"] != json.loads(json.dumps(contract.serializable())):
            raise ValueError("Public task contract mismatch")
        self.clocks = json.loads((self.folder/"private_clocks.json").read_text())
        jobs = len(contract.reliability)
        deadline = np.asarray(self.clocks["deadline"], float)
        read_waits = np.asarray(self.clocks["read_waits"], float)
        recovery_waits = np.asarray(self.clocks["recovery_waits"], float)
        if (deadline.shape != () or read_waits.shape != (jobs, contract.budget)
                or recovery_waits.shape != (jobs, contract.recovery_phases)
                or not all(np.all(np.isfinite(x)) and np.all(x >= 0)
                           for x in (deadline, read_waits, recovery_waits))):
            raise ValueError("Malformed hidden competing-clock tape")
        self.model = Model(contract)
        self.job, self.budget, self.evidence, self.read_index = 0, contract.budget, 0, 0
        self.elapsed, self.query_charge, self.time_charge, self.fire_charge = 0., 0., 0., 0.
        self.terminal, self.answers, self.events = False, [], []
        self.support_cpu_seconds, self.support_wall_seconds = 0., 0.
        self.counts = dict(READ=0, FIRE=0, STOP=0, deadline=0, recovery_phases=0,
                           decoder_calls=0, payload_bytes=0, failed_reads=0,
                           support_check_reads=0, support_check_bytes=0,
                           READ_attempts=0, censored_reads=0, successful_decoder_calls=0)

    @property
    def state(self):
        return self.job, self.budget, self.evidence

    def _wait(self, duration, phase):
        remaining = max(0., self.clocks["deadline"]-self.elapsed)
        actual = min(duration, remaining)
        self.elapsed += actual
        self.time_charge += self.contract.time_cost*actual
        censored = duration >= remaining
        if censored:
            self.terminal = True
            self.counts["deadline"] += 1
        return dict(phase=phase, duration=actual, censored=censored, elapsed=self.elapsed)

    def act(self, action):
        if self.terminal or action not in (STOP, READ, FIRE):
            raise ValueError("Invalid or post-terminal action")
        if action == READ and self.budget == 0:
            raise ValueError("READ budget exhausted")
        if not self.model.valid[self.model.index[self.state], action]:
            raise ValueError("Action violates the shared public quality/resource guard")
        before = self.state
        event = dict(action=ACTION_NAMES[action], before=list(before), started_at=self.elapsed)
        if action == STOP:
            self.terminal = True
            self.counts["STOP"] += 1
        elif action == READ:
            self.counts["READ_attempts"] += 1
            wait = self._wait(self.clocks["read_waits"][self.job][self.read_index], "READ")
            event["wait"] = wait
            if self.terminal:
                self.counts["censored_reads"] += 1
            if not self.terminal:
                name = self.public["packets"][self.job][self.read_index]
                path = (self.folder/name).resolve()
                if path.parent != self.folder.resolve():
                    raise ValueError("Packet escaped session")
                self.query_charge += self.contract.query_cost[self.job]
                support_cpu = None
                try:
                    self.counts["decoder_calls"] += 1
                    decoded = self.bank.adapter.read(path)
                    self.counts["successful_decoder_calls"] += 1
                    self.counts["payload_bytes"] += decoded["payload_bytes"]
                    event.update(packet=name, decoded=decoded)
                    # Input-support validation is based only on the now-read packet.
                    support_wall, support_cpu = time.perf_counter(), time.process_time()
                    support_bytes = path.read_bytes()
                    self.counts["support_check_reads"] += 1
                    self.counts["support_check_bytes"] += len(support_bytes)
                    if hashlib.sha256(support_bytes).hexdigest() != decoded["payload_sha256"]:
                        raise ValueError("Packet changed between inference and support validation")
                    body = json.loads(support_bytes)
                    template = self.bank.templates[body["template_id"]]
                    if body["symbols"] != template["symbols"] or body["dt"] != template["dt"]:
                        raise ValueError("READ outside the exhaustively verified input support")
                    if body["template_id"] not in self.bank.classes[decoded["observation"]]:
                        raise ArithmeticError("Frozen decoder changed its verified finite-support class")
                    self.support_cpu_seconds += time.process_time()-support_cpu
                    self.support_wall_seconds += time.perf_counter()-support_wall
                except Exception as exc:
                    if support_cpu is not None:
                        self.support_cpu_seconds += time.process_time()-support_cpu
                        self.support_wall_seconds += time.perf_counter()-support_wall
                    self.terminal = True
                    self.counts["failed_reads"] += 1
                    event.update(error_type=type(exc).__name__, error=str(exc))
                    self.events.append(event)
                    raise
                self.evidence += 2*decoded["observation"]-1
                self.budget -= 1
                self.read_index += 1
                self.counts["READ"] += 1
        else:
            answer = dict(job=self.job, prediction=int(self.evidence >= 0),
                          posterior=self.model.posterior(self.job, self.evidence), evidence=self.evidence)
            self.answers.append(answer)
            self.fire_charge += self.contract.fire_cost
            self.counts["FIRE"] += 1
            event["answer"] = answer
            event["recovery"] = []
            self.job += 1
            self.evidence, self.read_index = 0, 0
            if self.job == len(self.contract.reliability):
                self.terminal = True
            else:
                for phase, duration in enumerate(self.clocks["recovery_waits"][self.job-1]):
                    wait = self._wait(duration, f"RECOVERY_{phase}")
                    event["recovery"].append(wait)
                    if self.terminal:
                        break
                    self.counts["recovery_phases"] += 1
        event.update(after=list(self.state), elapsed=self.elapsed, terminal=self.terminal)
        self.events.append(event)
        return event

    def score(self):
        if not self.terminal:
            raise RuntimeError("Labels are terminal-only")
        labels = json.loads((self.folder/"evaluator_labels.json").read_text())["labels"]
        correct = sum(labels[a["job"]] == a["prediction"] for a in self.answers)
        reward = 2*correct-len(self.answers)
        charged = self.query_charge+self.time_charge+self.fire_charge
        return dict(reward=reward, utility=reward-charged, query_charge=self.query_charge,
                    time_charge=self.time_charge, fire_charge=self.fire_charge,
                    completed_jobs=len(self.answers), correct_jobs=correct,
                    label_access_after_terminal=True)


def execute(episode, contract, bank, actions=None, mode="ordinary_gate", probabilities=None,
            rng_seed=0, capture_failure=False):
    """Two encodings of the same hard boundary, on identical causal event tapes.

    Analytic mode additionally predicts the same process's first-FIRE CDF. It
    does not observe future packets or change actions. Equal-policy task utility
    must therefore be pathwise identical; any cost difference is implementation.
    """
    if mode not in ("ordinary_gate", "analytic_boundary"):
        raise ValueError("Unknown execution mode")
    wall, cpu = time.perf_counter(), time.process_time()
    owner = Owner(episode, contract, bank)
    setup_cpu, setup_wall = time.process_time()-cpu, time.perf_counter()-wall
    cdf_cpu, cdf_wall, cdf_calls = 0., 0., 0
    failure = None
    model = owner.model
    if (actions is None) == (probabilities is None):
        raise ValueError("Supply exactly one hard or randomized boundary policy")
    if probabilities is None:
        probabilities = model.deterministic(actions)
        actions = np.asarray(actions, int)
        randomized = False
    else:
        probabilities = model.checked_policy(probabilities)
        randomized = True
    rng = np.random.default_rng(rng_seed)
    traces = []
    while not owner.terminal:
        state = owner.state
        action = int(rng.choice(3, p=probabilities[model.index[state]])) if randomized else int(actions[model.index[state]])
        row = dict(state=list(state), action=ACTION_NAMES[action])
        if mode == "analytic_boundary":
            cdf_begin_wall, cdf_begin_cpu = time.perf_counter(), time.process_time()
            row["first_fire"] = model.first_fire_policy(probabilities, state, 1/contract.deadline_rate)
            cdf_cpu += time.process_time()-cdf_begin_cpu
            cdf_wall += time.perf_counter()-cdf_begin_wall
            cdf_calls += 1
        traces.append(row)
        try:
            owner.act(action)
        except Exception as exc:
            if not capture_failure:
                raise
            failure = dict(type=type(exc).__name__, message=str(exc))
            owner.terminal = True
    decoded = [event["decoded"] for event in owner.events if "decoded" in event]
    public_digest = sha(owner.folder/"public.json")
    clocks_digest = sha(owner.folder/"private_clocks.json")
    return dict(schema="hcsn.regenerative-evidence.execution.v1", episode=episode["id"], mode=mode,
        score=owner.score(), counts=owner.counts, events=owner.events, decision_trace=traces,
        randomized_policy=randomized, policy_rng_seed=rng_seed,
        failure=failure,
        components=dict(owner_setup_cpu_seconds=setup_cpu, owner_setup_wall_seconds=setup_wall,
            cdf_calls=cdf_calls, cdf_cpu_seconds=cdf_cpu, cdf_wall_seconds=cdf_wall,
            support_check_cpu_seconds=owner.support_cpu_seconds,
            support_check_wall_seconds=owner.support_wall_seconds,
            decoder_cpu_seconds=sum(row["total_cpu_seconds"] for row in decoded),
            decoder_wall_seconds=sum(row["total_wall_seconds"] for row in decoded),
            decoder_io_wall_seconds=sum(row["io_wall_seconds"] for row in decoded),
            decoder_feature_wall_seconds=sum(row["feature_wall_seconds"] for row in decoded),
            decoder_content_wall_seconds=sum(row["content_wall_seconds"] for row in decoded)),
        task_elapsed=owner.elapsed, cpu_seconds=time.process_time()-cpu,
        wall_seconds=time.perf_counter()-wall,
        public_sha256=public_digest, clocks_sha256=clocks_digest)


def semantic_trace(result):
    """Timing-free actual outcomes for the required pathwise null comparison."""
    events = json.loads(json.dumps(result["events"]))
    for event in events:
        if "decoded" in event:
            event["decoded"] = {k:event["decoded"][k] for k in
                ("observation", "logits", "payload_sha256", "payload_bytes")}
    return dict(score=result["score"], counts=result["counts"], events=events,
                elapsed=result["task_elapsed"])
