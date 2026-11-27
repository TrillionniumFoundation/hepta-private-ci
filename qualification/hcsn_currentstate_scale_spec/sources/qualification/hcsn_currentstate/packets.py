"""Bounded, fixed-physics current state; no renewal-total reconstruction."""
from dataclasses import dataclass, replace
from fractions import Fraction as F
import hashlib
import json
import math

import numpy as np
from scipy.linalg import expm


OPERATOR = "finite-exponential-flux-packets-v1"
MAX_TIME = F(9, 25)
MAX_PACKETS = 128
MAX_DIM = 64
MAX_SEGMENTS = 128
MAX_BYTES = 900_000


def frozen(a):
    a = np.array(a, dtype=float, copy=True)
    if not np.all(np.isfinite(a)):
        raise ValueError("nonfinite array")
    a.flags.writeable = False
    return a


def rational(t):
    if not isinstance(t, F):
        raise TypeError("logical time must be Fraction")
    return t


def array_json(a):
    a = np.asarray(a)
    return {"shape": list(a.shape), "hex": [float(v).hex() for v in a.flat]}


def array_load(x):
    if set(x) != {"shape", "hex"}:
        raise ValueError("bad array schema")
    shape = x["shape"]
    if any(type(v) is not int or v < 0 or v > 128 for v in shape):
        raise ValueError("bad shape")
    if math.prod(shape) != len(x["hex"]):
        raise ValueError("shape mismatch")
    return frozen([float.fromhex(v) for v in x["hex"]]).reshape(shape)


def time_json(t):
    return [t.numerator, t.denominator]


def time_load(x):
    if not isinstance(x, list) or len(x) != 2 or any(type(v) is not int for v in x):
        raise ValueError("bad rational")
    if x[1] <= 0:
        raise ValueError("bad denominator")
    t = F(*x)
    if time_json(t) != x:
        raise ValueError("noncanonical rational")
    return t


def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


@dataclass(frozen=True)
class Physics:
    Q: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    reset: np.ndarray
    discount: float = .15
    delay: F = F(1, 5)

    def __post_init__(self):
        for k in ("Q", "lower", "upper", "reset"):
            object.__setattr__(self, k, frozen(getattr(self, k)))
        n = self.Q.shape[0]
        if n not in (1, 2) or self.Q.shape != (n, n):
            raise ValueError("only bounded one/two-state controls")
        if any(getattr(self, k).shape != (n,) for k in ("lower", "upper", "reset")):
            raise ValueError("physics shape")
        off = self.Q.copy(); np.fill_diagonal(off, 0)
        if np.min(off) < 0 or np.any(np.diag(self.Q) > 0):
            raise ValueError("not killed Metzler")
        if np.min(self.lower) < 0 or np.min(self.upper) < 0 or np.min(self.reset) < 0:
            raise ValueError("negative physics")
        if any(sum((F.from_float(float(v)) for v in row), F(0))
               + F.from_float(float(lo)) + F.from_float(float(up)) != 0
               for row, lo, up in zip(self.Q, self.lower, self.upper)):
            raise ValueError("row conservation")
        if sum((F.from_float(float(v)) for v in self.reset), F(0)) != 1:
            raise ValueError("reset normalization")
        if type(self.discount) is not float or not math.isfinite(self.discount) or self.discount < 0:
            raise ValueError("bad discount")
        if rational(self.delay) != F(1, 5):
            raise ValueError("this stage fixes delay")

    def payload(self):
        return {"operator": OPERATOR, "Q": array_json(self.Q),
                "lower": array_json(self.lower), "upper": array_json(self.upper),
                "reset": array_json(self.reset), "q": self.discount.hex(),
                "delay": time_json(self.delay)}

    @property
    def identity(self):
        return hashlib.sha256(canonical(self.payload())).hexdigest()


@dataclass(frozen=True)
class FluxPacket:
    start: F
    end: F
    alpha: np.ndarray
    generator: np.ndarray
    output: np.ndarray
    target: int
    origin: int

    def __post_init__(self):
        rational(self.start); rational(self.end)
        if (self.start >= self.end or type(self.target) is not int or type(self.origin) is not int
                or self.target not in (1, 2, 3) or self.origin != self.target - 1):
            raise ValueError("packet support/origin")
        for k in ("alpha", "generator", "output"):
            object.__setattr__(self, k, frozen(getattr(self, k)))
        n = self.generator.shape[0]
        if n < 1 or n > MAX_DIM or self.generator.shape != (n, n):
            raise ValueError("packet dimension")
        if self.alpha.shape != (3, n) or self.output.shape != (n,):
            raise ValueError("packet shape")
        off = self.generator.copy(); np.fill_diagonal(off, 0)
        if np.min(off) < 0 or np.any(np.diag(self.generator) > 0):
            raise ValueError("packet not Metzler")
        if np.min(self.alpha[0]) < 0 or np.min(self.output) < 0:
            raise ValueError("negative probability packet")


@dataclass(frozen=True)
class AtomPacket:
    time: F
    mass: np.ndarray
    target: int
    origin: int

    def __post_init__(self):
        rational(self.time)
        object.__setattr__(self, "mass", frozen(self.mass))
        if self.mass.shape != (3,) or self.mass[0] < 0:
            raise ValueError("bad atom mass")
        if (type(self.target) is not int or type(self.origin) is not int
                or self.target not in (1, 2, 3) or self.origin != self.target - 1):
            raise ValueError("bad atom target")


def packet_payload(p):
    common = {"target": p.target, "origin": p.origin}
    if isinstance(p, AtomPacket):
        return dict(common, kind="atom", time=time_json(p.time), mass=array_json(p.mass))
    return dict(common, kind="flux", start=time_json(p.start), end=time_json(p.end),
                alpha=array_json(p.alpha), generator=array_json(p.generator), output=array_json(p.output))


@dataclass(frozen=True)
class State:
    physics_id: str
    time: F
    active: np.ndarray
    upper: np.ndarray
    M: np.ndarray
    H: np.ndarray
    A: np.ndarray
    pending: tuple
    fingerprint: str = ""

    def __post_init__(self):
        rational(self.time)
        for k in ("active", "upper", "M", "H", "A"):
            object.__setattr__(self, k, frozen(getattr(self, k)))
        object.__setattr__(self, "pending", tuple(self.pending))
        if any(type(p) not in (FluxPacket, AtomPacket) for p in self.pending):
            raise ValueError("packet type")
        object.__setattr__(self, "fingerprint", hashlib.sha256(canonical(self.payload())).hexdigest())

    def payload(self):
        return {"operator": OPERATOR, "physics_id": self.physics_id, "time": time_json(self.time),
                **{k: array_json(getattr(self, k)) for k in ("active", "upper", "M", "H", "A")},
                "pending": [packet_payload(p) for p in self.pending]}


class Ledger:
    """Per-invocation work counter; it is not persisted numerical state."""
    def __init__(self, maximum=500):
        if type(maximum) is not int or maximum < 1 or maximum > 500:
            raise ValueError("bad expm budget")
        self.maximum = maximum
        self.expm_calls = 0
        self.segments = 0
        self.max_matrix = 0

    def exponential(self, a):
        if type(self.maximum) is not int or not 1 <= self.maximum <= 500:
            raise ValueError("mutated expm cap")
        if self.expm_calls >= self.maximum:
            raise RuntimeError("expm cap")
        if a.shape[0] > 128:
            raise RuntimeError("augmented dimension cap")
        self.expm_calls += 1
        self.max_matrix = max(self.max_matrix, a.shape[0])
        return expm(a)


def checked(s, physics):
    if not isinstance(s, State) or s.physics_id != physics.identity:
        raise ValueError("incompatible physics/state")
    if hashlib.sha256(canonical(s.payload())).hexdigest() != s.fingerprint:
        raise ValueError("mutated state")
    n = len(physics.lower)
    if not F(0) <= s.time <= MAX_TIME:
        raise ValueError("time out of bounded domain")
    if s.active.shape != (3, 2, n) or s.upper.shape != (3, 3):
        raise ValueError("physical state shape")
    if s.M.shape != (3, 2) or s.H.shape != (3, 2) or s.A.shape != (3, 3):
        raise ValueError("accrual shape")
    if any(np.min(getattr(s, k)[0]) < 0 for k in ("active", "upper", "M", "H", "A")):
        raise ValueError("negative probability coordinates")
    if s.time < physics.delay and any(np.any(v != 0) for v in
            (s.active[:, 1], s.upper[:, 2], s.M[:, 1], s.H[:, 1], s.A[:, 2])):
        raise ValueError("second excursion before episode-origin delay")
    if s.time == 0 and (any(np.any(v != 0) for v in (s.M, s.H, s.A, s.upper[:, 1:]))
                        or any(p.target != 1 for p in s.pending)):
        raise ValueError("initial episode origin must have no accrued/new-cycle history")
    if len(s.pending) > MAX_PACKETS:
        raise ValueError("packet cap")
    for p in s.pending:
        if not isinstance(p, (FluxPacket, AtomPacket)):
            raise ValueError("unknown packet")
        begin, end = (p.time, p.time) if isinstance(p, AtomPacket) else (p.start, p.end)
        if begin < s.time or end > s.time + physics.delay or (isinstance(p, AtomPacket) and begin == s.time):
            raise ValueError("pending causality")
        if p.origin and begin < p.origin * physics.delay:
            raise ValueError("generation causality")
    return s


def dump(s, physics):
    checked(s, physics)
    body = s.payload()
    raw = canonical({"state": body, "sha256": hashlib.sha256(canonical(body)).hexdigest()})
    if len(raw) > MAX_BYTES:
        raise ValueError("snapshot byte cap")
    return raw


def load(raw, physics):
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("snapshot bytes")
    x = json.loads(raw)
    if set(x) != {"state", "sha256"} or hashlib.sha256(canonical(x["state"])).hexdigest() != x["sha256"]:
        raise ValueError("snapshot checksum")
    b = x["state"]
    if set(b) != {"operator", "physics_id", "time", "active", "upper", "M", "H", "A", "pending"} or b["operator"] != OPERATOR:
        raise ValueError("snapshot schema")
    if b["physics_id"] != physics.identity:
        raise ValueError("wrong expected physics")
    if len(b["pending"]) > MAX_PACKETS:
        raise ValueError("packet cap")
    packets = []
    for p in b["pending"]:
        if p["kind"] == "atom" and set(p) == {"kind", "time", "mass", "target", "origin"}:
            packets.append(AtomPacket(time_load(p["time"]), array_load(p["mass"]), p["target"], p["origin"]))
        elif p["kind"] == "flux" and set(p) == {"kind", "start", "end", "alpha", "generator", "output", "target", "origin"}:
            packets.append(FluxPacket(time_load(p["start"]), time_load(p["end"]), array_load(p["alpha"]), array_load(p["generator"]), array_load(p["output"]), p["target"], p["origin"]))
        else:
            raise ValueError("missing/unknown phase law")
    s = State(b["physics_id"], time_load(b["time"]), *(array_load(b[k]) for k in ("active", "upper", "M", "H", "A")), tuple(packets))
    checked(s, physics)
    if dump(s, physics) != raw:
        raise ValueError("noncanonical snapshot")
    return s


def reduced_packet(start, end, alpha, matrix, output, target, origin):
    """Output-ancestor graph reduction, never pruning a floating alpha zero."""
    ancestors = set(np.flatnonzero(output > 0).tolist())
    frontier = list(ancestors)
    while frontier:
        i = frontier.pop()
        for j in np.flatnonzero(matrix[:, i] > 0):
            if int(j) not in ancestors:
                ancestors.add(int(j)); frontier.append(int(j))
    idx = sorted(ancestors)
    if not idx:
        return None
    return FluxPacket(start, end, alpha[:, idx], matrix[np.ix_(idx, idx)], output[idx], target, origin)


def integral(matrix, selectors, duration, ledger, discount=0.):
    n, k = selectors.shape
    z = np.zeros((n + k, n + k))
    z[:n, :n] = matrix - discount * np.eye(n)
    z[:n, n:] = selectors
    e = ledger.exponential(z * float(duration))
    return e[:n, :n], e[:n, n:]


def advance(s, new_time, physics, ledger):
    checked(s, physics); rational(new_time)
    if not s.time <= new_time <= MAX_TIME:
        raise ValueError("backward/out-of-domain time")
    n = len(physics.lower)
    while s.time < new_time:
        ledger.segments += 1
        if ledger.segments > 20:
            raise RuntimeError("segment cap")
        left = s.time
        boundaries = [new_time, left + physics.delay]
        for p in s.pending:
            boundaries += [p.time] if isinstance(p, AtomPacket) else [p.start, p.end]
        right = min(t for t in boundaries if t > left)
        releasing = [p for p in s.pending if isinstance(p, FluxPacket) and p.start == left]
        if any(p.target > 2 for p in releasing):
            raise ValueError("third excursion outside stage")
        sizes = [len(p.output) for p in releasing]
        source_dim = sum(sizes)
        size = source_dim + 2*n
        if size > MAX_DIM:
            raise RuntimeError("packet source dimension cap")
        c = np.zeros((size, size)); y = np.zeros((3, size))
        offsets = []; j = 0
        for p, k in zip(releasing, sizes):
            sl = slice(j, j+k); offsets.append(sl)
            c[sl, sl] = p.generator; y[:, sl] = p.alpha
            dst = slice(source_dim + (p.target-1)*n, source_dim + p.target*n)
            c[sl, dst] = p.output[:, None] * physics.reset[None, :]
            j += k
        for g in range(2):
            sl = slice(source_dim+g*n, source_dim+(g+1)*n)
            c[sl, sl] = physics.Q; y[:, sl] = s.active[:, g]
        lower = np.zeros((size, 2))
        for g in range(2):
            lower[source_dim+g*n:source_dim+(g+1)*n, g] = physics.lower
        extended = np.zeros((size+3, size+3)); extended[:size, :size] = c
        for g in range(2):
            extended[source_dim+g*n:source_dim+(g+1)*n, size+g+1] = physics.upper
        initial = np.concatenate([y, s.upper], axis=1)
        hit = np.zeros((size+3, 2)); hit[:size] = lower
        evolution, hit_i = integral(extended, hit, right-left, ledger)
        final = initial @ evolution
        selectors = np.zeros((size+3, 5)); selectors[:, :2] = hit
        selectors[size, 2] = 1
        for g in range(2):
            selectors[source_dim+g*n:source_dim+(g+1)*n, 3+g] = 1
            selectors[size+g+1, 3+g] = 1
        _, discounted_i = integral(extended, selectors, right-left, ledger, physics.discount)
        discounted = math.exp(-physics.discount*float(left)) * (initial @ discounted_i)
        pending = []
        source_index = {id(p): sl for p, sl in zip(releasing, offsets)}
        for p in s.pending:
            if isinstance(p, FluxPacket) and p.start == left:
                if p.end > right:
                    pending.append(replace(p, start=right, alpha=final[:, source_index[id(p)]]))
            else:
                pending.append(p)
        for g in range(2):
            # Episode starts at zero with no gen2 mass. Before d no gen2
            # source can release; this logical certificate, not a floating
            # zero in y, proves its flux identically zero on this segment.
            if g == 1 and left < physics.delay:
                continue
            p = reduced_packet(left+physics.delay, right+physics.delay, y, c, lower[:, g], g+2, g+1)
            if p is not None:
                pending.append(p)
        active = final[:, source_dim:size].reshape(3, 2, n).copy()
        future = []
        for p in pending:
            if isinstance(p, AtomPacket) and p.time == right:
                if p.target > 2:
                    raise ValueError("third atom excursion")
                active[:, p.target-1] += p.mass[:, None] * physics.reset
            else:
                future.append(p)
        s = State(physics.identity, right, active, final[:, size:], s.M+initial@hit_i,
                  s.H+discounted[:, :2], s.A+discounted[:, 2:], tuple(future))
        checked(s, physics)
    return s


def observe(s, physics, ledger):
    checked(s, physics)
    refractory = np.zeros((3, 3)); weighted = np.zeros((3, 3))
    for p in s.pending:
        if isinstance(p, AtomPacket):
            refractory[:, p.origin] += p.mass
            weighted[:, p.origin] += math.exp(-physics.discount*float(p.time-s.time))*p.mass
        else:
            _, j = integral(p.generator, p.output[:, None], p.end-p.start, ledger)
            _, jq = integral(p.generator, p.output[:, None], p.end-p.start, ledger, physics.discount)
            refractory[:, p.origin] += (p.alpha @ j)[:, 0]
            weighted[:, p.origin] += math.exp(-physics.discount*float(p.start-s.time))*(p.alpha@jq)[:, 0]
    return {"active": s.active.copy(), "upper": s.upper.copy(), "M": s.M.copy(),
            "H": s.H.copy(), "A": s.A.copy(), "R": refractory, "Z": weighted}
