"""Four-content finite CTMC used by the addressed R15 experiment.

State ``4 * phase + content`` has eight active and two recovery phases.
The HX mode expands the unchanged R12 binary generator symmetrically.  This
is a finite synthetic regenerative law, not a continuum He--Xiong solution.
No financial payoff, observation cost, or intervention reward is inherited.
"""

import hashlib
import json

import numpy as np
from scipy.linalg import expm
from scipy.special import expit, logit

from ..unified_cell_r12_20261031.cell import Cell, PROTOCOL


SCHEMA = "hcsn-addressed-r15-law-v1"
DEFAULT_THETA = (.30, .018)


def _reference(theta):
    theta = np.asarray(theta, dtype=float)
    if theta.shape != (2,) or not np.isfinite(theta).all():
        raise ValueError("Expected finite sigma and liquidity")
    return Cell(np.r_[theta, 1.3])


def default_free_raw(theta=DEFAULT_THETA):
    """Four unconstrained coordinates exactly matching the initial HX law."""
    cell = _reference(theta)
    position = (cell.reset_log_distance - cell.centers[0]) / (
        cell.centers[-1] - cell.centers[0])
    return np.array([np.log(cell.rates[name]) for name in
                     ("up", "down", "absorption")] + [logit(position)])


class Law:
    """One row-generator identity for filtering, planning and world sampling."""

    phase_count = 10
    class_count = 4
    state_count = 40
    n_active = 8
    n_recovery = 2

    def __init__(self, theta=DEFAULT_THETA, mode="hx", free_raw=None):
        self.mode = mode
        self.theta = np.asarray(theta, dtype=float).copy()
        if self.theta.shape != (2,) or not np.isfinite(self.theta).all():
            raise ValueError("Expected finite sigma and liquidity")
        self.centers = (np.arange(self.n_active) + .5) * (
            float(PROTOCOL["log_upper"]) / self.n_active)
        self.recovery_rate = self.n_recovery / float(PROTOCOL["recovery_mean"])
        self.same_content = (1 + float(PROTOCOL["content_retention"])) / 2
        self.boundary = None
        self.free_raw = None
        if mode == "hx":
            if free_raw is not None:
                raise ValueError("free_raw belongs only to free mode")
            cell = _reference(self.theta)
            same = cell.Q[::2, ::2]
            different = cell.Q[::2, 1::2]
            if not (np.allclose(same, cell.Q[1::2, 1::2], atol=1e-14)
                    and np.allclose(different, cell.Q[1::2, ::2], atol=1e-14)):
                raise ValueError("R12 content generator is not symmetric")
            self.Q = np.kron(same, np.eye(self.class_count)) + np.kron(
                different, (np.ones((4, 4)) - np.eye(4)) / 3)
            self.reset_weights = cell.reset_weights.copy()
            self.reset_log_distance = float(cell.reset_log_distance)
            self.boundary = float(cell.boundary)
            self.rates = cell.rates.copy()
        elif mode == "free":
            raw = default_free_raw(self.theta) if free_raw is None else np.asarray(free_raw, dtype=float)
            if raw.shape != (4,) or not np.isfinite(raw).all():
                raise ValueError("Expected four finite free coordinates")
            self.free_raw = raw.copy()
            with np.errstate(over="ignore", under="ignore"):
                rates = np.exp(raw[:3])
            position = float(expit(raw[3]))
            if not np.isfinite(rates).all() or np.any(rates <= 0) or not 0 < position < 1:
                raise ValueError("Free rates or reset position are not representable")
            self.rates = dict(zip(("up", "down", "absorption"), map(float, rates)))
            self.reset_log_distance = self.centers[0] + position * (
                self.centers[-1] - self.centers[0])
            lower = min(int(np.searchsorted(self.centers, self.reset_log_distance) - 1), 6)
            fraction = (self.reset_log_distance - self.centers[lower]) / (
                self.centers[lower + 1] - self.centers[lower])
            self.reset_weights = np.zeros(self.n_active)
            self.reset_weights[lower:lower + 2] = [1 - fraction, fraction]
            self.Q = np.zeros((self.state_count, self.state_count))
            for phase in range(self.n_active):
                for content in range(self.class_count):
                    source = 4 * phase + content
                    if phase + 1 < self.n_active:
                        self._edge(source, source + 4, self.rates["up"])
                    if phase:
                        self._edge(source, source - 4, self.rates["down"])
                    else:
                        self._edge(source, 32 + content, self.rates["absorption"])
            for content in range(self.class_count):
                self._edge(32 + content, 36 + content, self.recovery_rate)
                for phase, weight in enumerate(self.reset_weights):
                    for destination in range(self.class_count):
                        retention = self.same_content if destination == content else (
                            1 - self.same_content) / 3
                        self._edge(36 + content, 4 * phase + destination,
                                   self.recovery_rate * weight * retention)
        else:
            raise ValueError("Law mode must be hx or free")
        self.phase_prior = np.r_[self.reset_weights, np.zeros(self.n_recovery)]
        self.prior = np.repeat(self.phase_prior / self.class_count, self.class_count)
        self.E_read = np.zeros((self.state_count, 5))
        self.E_read[:32, :4] = .10
        self.E_read[np.arange(32), np.arange(32) % 4] = .70
        self.E_read[32:, 4] = 1.
        self.E_refresh = np.full((self.state_count, 4), .01)
        self.E_refresh[np.arange(self.state_count), np.arange(self.state_count) % 4] = .97
        self.reward = (np.arange(self.state_count)[:, None] % 4 == np.arange(4)).astype(float)
        self.params = dict(mode=self.mode, theta=self.theta.tolist(), maturity=1.3,
                           free_raw=None if self.free_raw is None else self.free_raw.tolist(),
                           boundary=self.boundary, rates=self.rates,
                           reset_log_distance=self.reset_log_distance,
                           recovery_rate=self.recovery_rate, same_content=self.same_content)
        self._finish()

    def _edge(self, source, destination, rate):
        self.Q[source, destination] += rate
        self.Q[source, source] -= rate

    def _finish(self):
        if self.Q.shape != (40, 40) or not np.isfinite(self.Q).all():
            raise ValueError("Expected finite 40-state generator")
        off_diagonal = self.Q.copy()
        np.fill_diagonal(off_diagonal, 0)
        if np.any(off_diagonal < 0) or not np.allclose(self.Q.sum(1), 0, rtol=0, atol=5e-12):
            raise ValueError("Invalid conservative row generator")
        for emission, columns in ((self.E_read, 5), (self.E_refresh, 4)):
            if (emission.shape != (40, columns) or not np.isfinite(emission).all()
                    or np.any(emission < 0) or not np.allclose(emission.sum(1), 1, atol=1e-14)):
                raise ValueError("Invalid emission matrix")
        self._belief(self.prior)
        self.event_rate = np.zeros(self.state_count)
        self.event_rate[:4] = self.Q[np.arange(4), 32 + np.arange(4)]
        self.killed = self.Q.copy()
        self.killed[np.arange(4), 32 + np.arange(4)] = 0
        self._transition_cache = {}
        self._event_cache = {}
        array_payload = {name: getattr(self, name).tolist() for name in
                         ("Q", "prior", "phase_prior", "reset_weights", "centers",
                          "E_read", "E_refresh", "reward")}
        canonical = json.dumps(array_payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self.operator_identity = hashlib.sha256(canonical.encode()).hexdigest()
        canonical += json.dumps(self.params, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self.identity = hashlib.sha256(canonical.encode()).hexdigest()
        for name in ("Q", "prior", "phase_prior", "reset_weights", "centers", "E_read",
                     "E_refresh", "reward", "event_rate", "killed", "theta"):
            getattr(self, name).setflags(write=False)

    @staticmethod
    def _duration(dt):
        dt = float(dt)
        if not np.isfinite(dt) or dt < 0:
            raise ValueError("Duration must be finite and nonnegative")
        return dt

    def _belief(self, belief):
        p = np.asarray(belief, dtype=float)
        if (p.ndim < 1 or p.shape[-1] != self.state_count or not np.isfinite(p).all()
                or np.any(p < -1e-13) or not np.allclose(p.sum(-1), 1, rtol=0, atol=2e-11)):
            raise ValueError("Belief must be normalized with final dimension 40")
        return p

    def initial_prior(self, value):
        """Condition only on a public, exact initial WRITE value."""
        if not isinstance(value, (int, np.integer)) or not 0 <= value < 4:
            raise ValueError("Initial content must be an integer from zero to three")
        prior = np.zeros(self.state_count)
        prior[int(value)::4] = self.phase_prior
        return prior

    def transition(self, dt, method="expm"):
        """Finite-model row transition; its matrix is immutable and cached."""
        dt = self._duration(dt)
        if method != "expm":
            raise ValueError("Only expm is implemented; uniformization is an independent audit")
        if dt not in self._transition_cache:
            transition = expm(dt * self.Q)
            transition.setflags(write=False)
            self._transition_cache[dt] = transition
        return self._transition_cache[dt]

    def _events(self, p, dt, first):
        p, dt = self._belief(p), self._duration(dt)
        key = (dt, first)
        if key not in self._event_cache:
            augmented = np.zeros((self.state_count + 1, self.state_count + 1))
            augmented[:-1, :-1] = self.killed if first else self.Q
            augmented[:-1, -1] = self.event_rate
            self._event_cache[key] = expm(dt * augmented)[:-1, -1]
        return p @ self._event_cache[key]

    def first_hit(self, p, dt):
        """Probability of a future natural absorption, including after recovery."""
        return self._events(p, dt, True)

    def event_count(self, p, dt):
        """Expected number of natural absorptions; repeated hits are retained."""
        return self._events(p, dt, False)

    def project(self, p, mode="full"):
        """Explicit state approximation, never a hidden change to the world.

        factorized retains both marginals. mean further retains only the mean
        *phase index*, represented on its two neighbors; this is a declared
        information-destroying closure, not a sufficient physical statistic.
        """
        p = self._belief(p)
        if mode == "full":
            return p.copy()
        joint = p.reshape(*p.shape[:-1], self.phase_count, self.class_count)
        phase, content = joint.sum(-1), joint.sum(-2)
        if mode == "mean":
            average = phase @ np.arange(self.phase_count)
            lower = np.minimum(np.floor(average).astype(int), self.phase_count - 2)
            fraction = average - lower
            phase = np.eye(self.phase_count)[lower] * (1 - fraction)[..., None]
            phase += np.eye(self.phase_count)[lower + 1] * fraction[..., None]
        elif mode != "factorized":
            raise ValueError("Projection must be full, factorized, or mean")
        return (phase[..., :, None] * content[..., None, :]).reshape(p.shape)

    def export(self):
        """JSON-compatible exact matrices, public parameters and identities."""
        return dict(schema=SCHEMA, identity=self.identity,
                    operator_identity=self.operator_identity,
                    params=json.loads(json.dumps(self.params)),
                    **{name: getattr(self, name).tolist() for name in
                       ("Q", "prior", "phase_prior", "reset_weights", "centers",
                        "E_read", "E_refresh", "reward")})

    @classmethod
    def from_payload(cls, payload):
        """Restore frozen arrays without recomputing the financial kernel."""
        if payload.get("schema") != SCHEMA:
            raise ValueError("Unsupported law payload")
        result = cls.__new__(cls)
        result.params = json.loads(json.dumps(payload["params"], allow_nan=False))
        for name in ("mode", "boundary", "rates", "reset_log_distance",
                     "recovery_rate", "same_content"):
            setattr(result, name, result.params[name])
        result.theta = np.asarray(result.params["theta"], dtype=float)
        raw = result.params["free_raw"]
        result.free_raw = None if raw is None else np.asarray(raw, dtype=float)
        for name in ("Q", "prior", "phase_prior", "reset_weights", "centers",
                     "E_read", "E_refresh", "reward"):
            setattr(result, name, np.asarray(payload[name], dtype=float))
        result._finish()
        if result.identity != payload["identity"] or result.operator_identity != payload["operator_identity"]:
            raise ValueError("Frozen law identity mismatch")
        return result

    from_export = from_payload
