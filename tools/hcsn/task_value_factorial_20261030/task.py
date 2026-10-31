"""Actual file/model actions for a bounded synthetic two-job research task.

The inherited content weights are frozen. This owner is Python research code,
not the production Rust Hepta owner. Policy code never receives unread packets
or evaluator labels. Bellman and execution share feasibility, elapsed time,
resource prices, posterior updates, FIRE reset and refractory semantics. Public
durations define the declared task clock; measured hardware CPU/wall durations
are recorded separately and are never inferred from this clock.
"""
import hashlib
import importlib.util
import json
from functools import lru_cache
from pathlib import Path
import time

import numpy as np

HERE = Path(__file__).resolve().parent
HCSN = HERE.parent
ACTIONS = ("STOP", "SKIP", "READ", "FIRE")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    data = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with path.open("x") as stream:
        stream.write(data)


def verify_upstream():
    manifest = json.loads((HERE / "UPSTREAM_FILES.json").read_text())
    root = HCSN.parents[1]
    for item in manifest["files"]:
        if sha(root / item["path"]) != item["sha256"]:
            raise ValueError(("upstream byte mismatch", item["path"]))
    return manifest


class ContentAdapter:
    """Frozen FullHX NumPy inference; each READ really opens its packet."""

    def __init__(self):
        wall, cpu = time.perf_counter(), time.process_time()
        self.upstream = verify_upstream()
        source = HCSN / "third/memory/reference.py"
        spec = importlib.util.spec_from_file_location("hcsn_factorial_reference", source)
        if spec is None or spec.loader is None:
            raise RuntimeError("Cannot load verified content reference")
        self.reference = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.reference)
        checkpoint = HCSN / "third/memory/checkpoints/memory_full_mass_seed29.npz"
        with np.load(checkpoint, allow_pickle=False) as archive:
            self.parameters = dict(archive)
        self.setup = dict(checkpoint_sha256=sha(checkpoint),
                          source_sha256=sha(source), trainable_parameters=0,
                          frozen_parameter_count=sum(a.size for a in self.parameters.values()),
                          load_wall_seconds=time.perf_counter()-wall,
                          load_cpu_seconds=time.process_time()-cpu)

    def read(self, path):
        wall, cpu = time.perf_counter(), time.process_time()
        start = time.perf_counter()
        raw = Path(path).read_bytes()
        packet = json.loads(raw)
        io = time.perf_counter()-start
        start = time.perf_counter()
        symbols = np.asarray(packet["symbols"], np.int32)
        dt = np.asarray(packet["dt"], np.float32)
        if (packet["schema"] != "hcsn.memory.packet.v1" or symbols.ndim != 1
                or not 2 <= len(symbols) <= 128 or symbols[-1] != -1
                or not np.all((symbols[:-1] >= 0) & (symbols[:-1] < 4))
                or dt.shape != symbols.shape or not np.all(np.isfinite(dt))
                or not np.all(dt > 0)):
            raise ValueError("Invalid content packet")
        x = np.zeros((1, len(symbols), 16), np.float32)
        x[0, np.arange(len(symbols)-1), symbols[:-1]] = 1.
        x[0, 0, 4], x[0, -1, 5] = 1., 1.
        feature = time.perf_counter()-start
        start = time.perf_counter()
        state = self.reference.forward(self.parameters, x, dt[None], "full")
        logits, numerical = self.reference.readout(self.parameters, state, "mass", solver_dtype=np.float64)
        content = time.perf_counter()-start
        if not np.all(np.isfinite(logits)):
            raise FloatingPointError("Content decoder produced nonfinite output")
        return dict(observation=int(np.argmax(logits[0, :2])), logits=logits[0].tolist(),
                    payload_sha256=hashlib.sha256(raw).hexdigest(), payload_bytes=len(raw),
                    io_wall_seconds=io, feature_wall_seconds=feature,
                    content_wall_seconds=content, total_wall_seconds=time.perf_counter()-wall,
                    total_cpu_seconds=time.process_time()-cpu, numerical=numerical)


def packet(symbol, seed, length=32):
    """Same marked-first-symbol task as the inherited content model."""
    if symbol not in (0, 1) or not 2 <= length <= 128:
        raise ValueError("Invalid packet request")
    rng = np.random.default_rng(seed)
    symbols = rng.integers(0, 4, length).tolist()
    symbols[0], symbols[-1] = int(symbol), -1
    return dict(schema="hcsn.memory.packet.v1", symbols=symbols, dt=[1.] * length)


def metadata(rng, identifier, protocol):
    deadline = int(rng.choice(protocol["deadlines"]))
    return dict(id=identifier, deadline=deadline,
                budget=int(rng.choice(protocol["read_budgets"])),
                reliability=rng.choice(protocol["packet_reliabilities"], (2, deadline)).tolist(),
                price=rng.choice(protocol["packet_prices"], (2, deadline)).tolist(),
                duration=rng.choice(protocol.get("step_durations", [1.]), deadline).tolist())


def build_cohort(root, split, seed, count, protocol):
    """One disjoint RNG namespace per split/seed; preserve every generated byte."""
    root = Path(root)
    split_index = {"train": 0, "validation": 1, "test": 2, "ood": 3}[split]
    rng = np.random.default_rng(protocol["data_seed_base"] + seed*1000000 + split_index*100000)
    records, files, payload_hashes = [], {}, set()
    wall, cpu = time.perf_counter(), time.process_time()
    for index in range(count):
        identifier = f"{split}_seed{seed}_{index:04d}"
        folder = root / identifier
        public = metadata(rng, identifier, protocol)
        labels = rng.integers(0, 2, 2).tolist()
        public["packets"] = []
        for job in range(2):
            names = []
            for tick in range(public["deadline"]):
                symbol = labels[job] if rng.random() < public["reliability"][job][tick] else 1-labels[job]
                name = f"job{job}_tick{tick}.json"
                save(folder / name, packet(symbol, int(rng.integers(0, 2**63-1)), protocol["packet_length"]))
                digest = sha(folder / name)
                if digest in payload_hashes:
                    raise ValueError("Duplicate packet bytes")
                payload_hashes.add(digest)
                files[str((folder / name).relative_to(root))] = digest
                names.append(name)
            public["packets"].append(names)
        save(folder / "public.json", public)
        save(folder / "evaluator_labels.json", dict(labels=labels))
        for name in ("public.json", "evaluator_labels.json"):
            files[str((folder / name).relative_to(root))] = sha(folder / name)
        records.append(dict(id=identifier, seed=seed, split=split, folder=str(folder)))
    return dict(records=records, files=files, payload_hashes=sorted(payload_hashes),
                generation_wall_seconds=time.perf_counter()-wall,
                generation_cpu_seconds=time.process_time()-cpu)


def calibrate(adapter, root, seed, count, protocol):
    if count < 2 or count % 2:
        raise ValueError("Calibration needs balanced positive class counts")
    wall, cpu = time.perf_counter(), time.process_time()
    rng = np.random.default_rng(protocol["data_seed_base"] + seed*1000000 + 900000)
    counts, rows = np.zeros((2, 2), np.int64), []
    for index in range(count):
        symbol = index % 2
        path = Path(root) / f"calibration_seed{seed}" / f"packet{index:04d}.json"
        save(path, packet(symbol, int(rng.integers(0, 2**63-1)), protocol["packet_length"]))
        result = adapter.read(path)
        counts[symbol, result["observation"]] += 1
        rows.append(dict(path=str(path), symbol=symbol, **result))
    confusion = (counts+.5)/(counts.sum(axis=1, keepdims=True)+1.)
    return confusion, dict(seed=seed, split="TRAIN only", counts=counts.tolist(), rows=rows,
                           confusion=confusion.tolist(), wall_seconds=time.perf_counter()-wall,
                           cpu_seconds=time.process_time()-cpu)


def feasible(meta, job, tick, budget):
    active = job < 2 and tick < meta["deadline"]
    return np.array([True, active and tick+1 < meta["deadline"],
                     active and budget > 0 and tick+1 < meta["deadline"], active])


def elapsed(meta, tick, steps):
    return float(sum(meta["duration"][tick:min(tick+steps, meta["deadline"])]))


def likelihood(confusion, reliability):
    return reliability*confusion + (1-reliability)*confusion[::-1]


def outcomes(posterior, law):
    probability = (1-posterior)*law[0] + posterior*law[1]
    beliefs = np.divide(posterior*law[1], probability, out=np.full(2, .5), where=probability > 0)
    return probability, beliefs


class Bellman:
    """Exact finite recursion for the TRAIN-fitted observation law only."""

    def __init__(self, meta, confusion, multiplier, latency_price=0., future=True):
        self.meta, self.confusion = meta, np.asarray(confusion, np.float64)
        self.multiplier, self.latency_price, self.future = float(multiplier), float(latency_price), future
        self.value = lru_cache(maxsize=None)(self._value)
        self.q = lru_cache(maxsize=None)(self._q)

    def _value(self, job, tick, budget, posterior):
        return float(max(self.q(job, tick, budget, posterior)))

    def _q(self, job, tick, budget, posterior):
        valid = feasible(self.meta, job, tick, budget)
        result = [0., -np.inf, -np.inf, -np.inf]
        if not valid[3]:
            return tuple(result)
        one_cost = self.latency_price*elapsed(self.meta, tick, 1)
        if valid[1]:
            result[1] = self.value(job, tick+1, budget, posterior)-one_cost
        if valid[2]:
            prob, belief = outcomes(posterior, likelihood(self.confusion, self.meta["reliability"][job][tick]))
            result[2] = sum(float(prob[o])*self.value(job, tick+1, budget-1, float(belief[o])) for o in range(2))
            result[2] -= self.multiplier*self.meta["price"][job][tick]+one_cost
        continuation = self.value(job+1, tick+2, budget, .5) if self.future else 0.
        result[3] = abs(2*posterior-1)+continuation-self.latency_price*elapsed(self.meta, tick, 2)
        return tuple(result)


class Owner:
    """Research state owner with real effects and terminal-only label scoring."""

    def __init__(self, folder, adapter, confusion, multiplier, latency_price=0.):
        self.folder = Path(folder).resolve()
        self.adapter, self.confusion = adapter, np.asarray(confusion, np.float64)
        if (self.confusion.shape != (2, 2) or not np.all(np.isfinite(self.confusion))
                or np.any(self.confusion <= 0) or not np.allclose(self.confusion.sum(axis=1), 1.)):
            raise ValueError("Invalid calibrated observation law")
        self.multiplier, self.latency_price = float(multiplier), float(latency_price)
        if not np.isfinite(self.multiplier+self.latency_price) or min(self.multiplier, self.latency_price) < 0:
            raise ValueError("Invalid resource price")
        start = time.perf_counter()
        raw = (self.folder / "public.json").read_bytes()
        self.meta = json.loads(raw)
        self.public_sha256 = hashlib.sha256(raw).hexdigest()
        self.metadata_wall_seconds = time.perf_counter()-start
        self.job, self.tick, self.budget, self.posterior = 0, 0, self.meta["budget"], .5
        self.terminal, self.reads_in_job = False, 0
        self.charged_cost, self.query_cost, self.latency_cost, self.task_elapsed = 0., 0., 0., 0.
        self.answers, self.events = [], []
        self.counts = dict(READ=0, SKIP=0, FIRE=0, STOP=0, content_invocations=0,
                           packet_file_reads=0, failed_read_attempts=0,
                           metadata_file_reads=1, payload_bytes=0)
        self.times = dict(io_wall_seconds=0., feature_wall_seconds=0., content_wall_seconds=0., content_total_cpu_seconds=0.)

    def snapshot(self):
        state = {k: getattr(self, k) for k in ("job", "tick", "budget", "posterior", "terminal", "reads_in_job",
                 "charged_cost", "query_cost", "latency_cost", "task_elapsed", "answers", "events", "counts", "times")}
        snapshot = dict(schema="hcsn.factorial.owner.v1", session=self.meta["id"], state=state,
                    public_sha256=self.public_sha256, checkpoint_sha256=self.adapter.setup["checkpoint_sha256"],
                    confusion=self.confusion.tolist(), multiplier=self.multiplier, latency_price=self.latency_price)
        return json.loads(json.dumps(snapshot, allow_nan=False))

    def restore(self, snapshot):
        expected = self.snapshot()
        for key in ("schema", "session", "public_sha256", "checkpoint_sha256", "confusion", "multiplier", "latency_price"):
            if snapshot[key] != expected[key]:
                raise ValueError(("Recovery identity mismatch", key))
        state = json.loads(json.dumps(snapshot["state"], allow_nan=False))
        if set(state) != set(expected["state"]):
            raise ValueError("Recovery state schema mismatch")
        for key, value in state.items():
            setattr(self, key, value)

    def act(self, action):
        if self.terminal:
            raise RuntimeError("Terminal owner rejects subsequent actions")
        if action not in ACTIONS or not feasible(self.meta, self.job, self.tick, self.budget)[ACTIONS.index(action)]:
            raise ValueError(("Infeasible action", action, self.job, self.tick, self.budget))
        event = dict(action=action, job=self.job, tick=self.tick, budget_before=self.budget, posterior_before=self.posterior)
        self.counts[action] += 1
        duration = elapsed(self.meta, self.tick, 2 if action == "FIRE" else 1) if action != "STOP" else 0.
        self.task_elapsed += duration
        self.latency_cost += self.latency_price*duration
        if action == "STOP":
            self.terminal = True
        elif action == "SKIP":
            # Do not construct a packet path, open its file, or run the decoder.
            self.tick += 1
        elif action == "READ":
            path = (self.folder / self.meta["packets"][self.job][self.tick]).resolve()
            if path.parent != self.folder:
                raise ValueError("Packet is outside its session")
            self.query_cost += self.multiplier*self.meta["price"][self.job][self.tick]
            try:
                result = self.adapter.read(path)
            except Exception as exc:
                self.terminal = True
                self.counts["failed_read_attempts"] += 1
                self.charged_cost = self.query_cost+self.latency_cost
                event.update(status="failed_read", error_type=type(exc).__name__, duration=duration,
                             charged_cost=self.charged_cost)
                self.events.append(event)
                raise
            # These count completed accesses/inferences. Failed attempts retain
            # their charge and error, without inventing a completed decoder call.
            self.counts["packet_file_reads"] += 1
            self.counts["content_invocations"] += 1
            self.counts["payload_bytes"] += result["payload_bytes"]
            for key in ("io_wall_seconds", "feature_wall_seconds", "content_wall_seconds"):
                self.times[key] += result[key]
            self.times["content_total_cpu_seconds"] += result["total_cpu_seconds"]
            _, beliefs = outcomes(self.posterior, likelihood(self.confusion, self.meta["reliability"][self.job][self.tick]))
            self.posterior = float(beliefs[result["observation"]])
            event.update(packet=self.meta["packets"][self.job][self.tick], **result)
            self.tick, self.budget, self.reads_in_job = self.tick+1, self.budget-1, self.reads_in_job+1
        elif action == "FIRE":
            answer = dict(job=self.job, prediction=int(self.posterior >= .5), posterior=self.posterior,
                          tick=self.tick, reads=self.reads_in_job)
            self.answers.append(answer)
            event["answer"] = answer
            self.job, self.tick, self.posterior, self.reads_in_job = self.job+1, self.tick+2, .5, 0
        self.charged_cost = self.query_cost+self.latency_cost
        self.terminal = self.terminal or self.job >= 2 or self.tick >= self.meta["deadline"]
        event.update(duration=duration, posterior_after=self.posterior, budget_after=self.budget,
                     next_job=self.job, next_tick=self.tick, terminal=self.terminal, charged_cost=self.charged_cost)
        self.events.append(event)
        return event


def score_terminal(owner):
    if not owner.terminal:
        raise RuntimeError("Labels may be scored only after termination")
    labels = json.loads((owner.folder / "evaluator_labels.json").read_text())["labels"]
    correct = sum(a["prediction"] == labels[a["job"]] for a in owner.answers)
    reward = 2*correct-len(owner.answers)
    return dict(utility=reward-owner.charged_cost, reward=reward, charged_cost=owner.charged_cost,
                query_cost=owner.query_cost, latency_cost=owner.latency_cost,
                completed_jobs=len(owner.answers), correct_jobs=correct, label_access_after_terminal=True)
