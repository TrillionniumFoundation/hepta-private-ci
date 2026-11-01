"""Independent Gillespie owner for a fixed four-address absolute-time world.

All arms share the same pre-sampled paths and query deadlines.  Actions reveal
emissions only on completion; they never resample or reset the hidden world.
Public WRITE events reveal content, not physical phase, and preserve the phase.
Public typed DISTRACTOR events do not alter the world.  Type and address routing
are common infrastructure, so this task does not prove learned routing/gating.
"""

import hashlib
import json

import numpy as np


DURATION_SETS = {"iid": (.25, .50, .75), "ood": (.35, .65, .95)}


def _seed(*parts):
    payload = json.dumps(parts, separators=(",", ":"), allow_nan=False).encode()
    return int.from_bytes(hashlib.blake2b(payload, digest_size=16).digest(), "big")


class Episode:
    """Environment owner; actors receive its public metadata and observe only.

    ``target`` is scorer-only.  Prefix policies must not receive this object,
    its private paths, or target results: the campaign passes public values
    and calls ``observe`` after the chosen action has consumed its duration.
    Python private names document ownership; they are not a security sandbox.
    """

    def __init__(self, law, seed, domain, query_count=6):
        if domain not in DURATION_SETS:
            raise ValueError("Episode domain must be iid or ood")
        if not isinstance(seed, (int, np.integer)) or int(seed) < 0:
            raise ValueError("Seed must be a nonnegative integer")
        if not isinstance(query_count, (int, np.integer)) or query_count < 4:
            raise ValueError("At least four queries are needed for all addresses")
        self.seed, self.domain = int(seed), domain
        self._law = law
        schedule = np.random.default_rng(_seed("r15-schedule", self.seed, domain))
        self.initial_values = schedule.permutation(4)
        repeats = []
        while len(repeats) < query_count - 4:
            repeats.extend(schedule.permutation(4).tolist())
        self.query_keys = np.r_[schedule.permutation(4), repeats[:query_count - 4]].astype(int)
        self.dts = schedule.choice(DURATION_SETS[domain], size=query_count)
        self.deadlines = np.cumsum(3 * self.dts)
        self.starts = np.r_[0., self.deadlines[:-1]]
        self.public_events = tuple(dict(kind="WRITE", time=0., key=key,
                                        value=int(self.initial_values[key])) for key in range(4))
        self._events = []
        forced_by_key = [[] for _ in range(4)]
        for query in range(query_count):
            events = []
            write_key = None
            if query in (2, 4):
                write_key = int(schedule.integers(4))
                value = int(schedule.integers(4))
                event = dict(kind="WRITE", key=write_key, value=value,
                             time=float(self.starts[query]))
                events.append(event)
                forced_by_key[write_key].append((event["time"], value))
            candidates = [key for key in range(4)
                          if key != int(self.query_keys[query]) and key != write_key]
            events.append(dict(kind="DISTRACTOR", key=int(schedule.choice(candidates)),
                               value=int(schedule.integers(4)), time=float(self.starts[query])))
            self._events.append(tuple(events))
        self._events = tuple(self._events)
        self._paths = []
        for key in range(4):
            rng = np.random.default_rng(_seed("r15-path", self.seed, domain, key))
            phase = int(rng.choice(law.phase_count, p=law.phase_prior))
            state = 4 * phase + int(self.initial_values[key])
            times, states = [0.], [state]
            time = 0.
            segments = forced_by_key[key] + [(float(self.deadlines[-1]), None)]
            for boundary, write_value in segments:
                while time < boundary:
                    rate = float(-law.Q[state, state])
                    if rate <= 0:
                        break
                    jump_time = time + float(rng.exponential(1 / rate))
                    if jump_time >= boundary:
                        break
                    time = jump_time
                    probabilities = law.Q[state].copy()
                    probabilities[state] = 0
                    probabilities /= rate
                    state = int(rng.choice(law.state_count, p=probabilities))
                    times.append(time)
                    states.append(state)
                time = boundary
                if write_value is not None:
                    state = 4 * (state // 4) + write_value
                    times.append(time)
                    states.append(state)
            times, states = np.asarray(times), np.asarray(states, dtype=np.int64)
            times.setflags(write=False)
            states.setflags(write=False)
            self._paths.append((times, states))
        self._paths = tuple(self._paths)
        metadata = dict(schema="hcsn-r15-world-tape-v1", law=law.identity,
                        seed=self.seed, domain=domain,
                        initial_values=self.initial_values.tolist(),
                        query_keys=self.query_keys.tolist(), dts=self.dts.tolist(),
                        deadlines=self.deadlines.tolist(), events=self._events,
                        paths=[(times.tolist(), states.tolist()) for times, states in self._paths])
        self.fingerprint = hashlib.sha256(json.dumps(
            metadata, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        for name in ("initial_values", "query_keys", "dts", "deadlines", "starts"):
            getattr(self, name).setflags(write=False)

    def _state_at(self, key, time, side="right"):
        if not isinstance(key, (int, np.integer)) or not 0 <= key < 4:
            raise ValueError("Address must be an integer from zero to three")
        time = float(time)
        if not np.isfinite(time) or time < 0 or time > self.deadlines[-1] + 1e-12:
            raise ValueError("Time is outside the pre-sampled episode")
        if side not in ("left", "right"):
            raise ValueError("State time side must be left or right")
        times, states = self._paths[int(key)]
        return int(states[max(0, np.searchsorted(times, time, side=side) - 1)])

    def events_at(self, query_index):
        """Public events available at this query start, returned as copies."""
        if not isinstance(query_index, (int, np.integer)) or not 0 <= query_index < len(self.query_keys):
            raise ValueError("Invalid query index")
        return [dict(event) for event in self._events[int(query_index)]]

    def observe(self, key, time, quality, query_index, step):
        """Return one token at completed grid step 1..3 of this query.

        READ takes one step and REFRESH two.  The caller controls the previous
        completed step; a REFRESH cannot finish at step one.  Repeating an
        identical call returns the same emission.  Noise is keyed by absolute
        time, address, quality and public query/step, independently of arm and
        of how many earlier calls were made.
        """
        if not isinstance(query_index, (int, np.integer)) or not 0 <= query_index < len(self.query_keys):
            raise ValueError("Invalid query index")
        if not isinstance(step, (int, np.integer)) or not 1 <= step <= 3:
            raise ValueError("step is the completed time index from one to three")
        quality = str(quality).lower()
        if quality not in ("read", "refresh"):
            raise ValueError("Quality must be read or refresh")
        if quality == "refresh" and step < 2:
            raise ValueError("REFRESH needs two elapsed steps")
        expected = float(self.deadlines[query_index] if step == 3 else
                         self.starts[query_index] + step * self.dts[query_index])
        time = float(time)
        if not np.isfinite(time) or abs(time - expected) > 1e-10:
            raise ValueError("Observation is available only at the completed action time")
        # A query's deadline observation/score precedes the next query's
        # public WRITE at the same absolute time.  New writes cannot affect
        # a target before that write is publicly presented.
        state = self._state_at(key, expected, side="left" if step == 3 else "right")
        emission = self._law.E_read if quality == "read" else self._law.E_refresh
        noise = _seed("r15-emission", self.seed, self.domain, int(key),
                      expected.hex(), quality, int(query_index), int(step))
        uniform = ((noise >> 64) + .5) / 2 ** 64
        # Guard the top-bit rounding case without changing the keyed draw.
        uniform = min(float(uniform), np.nextafter(1., 0.))
        return int(np.searchsorted(np.cumsum(emission[state]), uniform, side="right"))

    def target(self, key, time):
        """Scorer-only pre-boundary target; scoring precedes next-query WRITE."""
        return self._state_at(key, time, side="left") % 4


def make_episode(law, seed, domain, query_count=6):
    return Episode(law, seed, domain, query_count=query_count)
