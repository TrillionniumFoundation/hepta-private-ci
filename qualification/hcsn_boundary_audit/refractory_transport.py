"""Bounded exact-age refractory transport research prototype (not HCSN flow).

Uniform/point HIT-time packets are external inputs. Their release-time law is
shifted by an exact fixed delay and retained without phase-bin reconstruction.
Released packets retain absolute release support for a future active solver;
lumping them at an interval endpoint would change the model. This module does
not solve diffusion, infer hit laws, implement autograd or migrate checkpoints.
"""

from dataclasses import dataclass
from fractions import Fraction


def rational(value):
    """Use explicit rational/int inputs; do not silently rationalize floats."""
    if isinstance(value, bool) or not isinstance(value, (int, Fraction)):
        raise ValueError("expected Fraction or int")
    return Fraction(value)


@dataclass(frozen=True)
class Packet:
    """Uniform law on [start,end], or an atom if start==end.

    mass and marked content are TOTALS on this packet, not densities. Content
    may be signed. Before release these bounds are absolute release times;
    supplied to advance_to as a hit packet they are absolute hit times instead.
    """

    identity: str
    start: Fraction
    end: Fraction
    mass: Fraction
    content: tuple[Fraction, ...]

    def __post_init__(self):
        if not isinstance(self.identity, str) or not self.identity:
            raise ValueError("packet requires a nonempty identity")
        for name in ("start", "end", "mass"):
            object.__setattr__(self, name, rational(getattr(self, name)))
        if self.start < 0 or self.end < self.start or self.mass <= 0:
            raise ValueError("invalid support or nonpositive mass")
        if not isinstance(self.content, tuple) or not 1 <= len(self.content) <= 128:
            raise ValueError("content requires 1..128 fixed channels")
        object.__setattr__(self, "content", tuple(map(rational, self.content)))

    def split_at(self, time):
        """Return released and pending packets, preserving each support law."""
        time = rational(time)
        if time < self.start:
            return None, self
        if time >= self.end:
            return self, None
        ratio = (time - self.start) / (self.end - self.start)
        if ratio == 0:
            return None, self
        released = Packet(self.identity, self.start, time, self.mass * ratio,
                          tuple(x * ratio for x in self.content))
        pending = Packet(self.identity, time, self.end, self.mass * (1 - ratio),
                         tuple(x * (1 - ratio) for x in self.content))
        return released, pending


@dataclass(frozen=True)
class ReleaseReceipt:
    """A new immutable state and releases within the requested interval."""

    state: "RefractoryState"
    released: tuple[Packet, ...]
    incoming_mass: Fraction
    incoming_content: tuple[Fraction, ...]


@dataclass(frozen=True)
class RefractoryState:
    """A finite set of exact support packets; overflow raises before mutation.

    max_packets is a count bound, not a complete memory/bit-complexity bound.
    No merging or lossy compaction silently relaxes it. IDs are scoped to the
    pending packet set, not an owner-authenticated deduplication ledger.
    """

    time: Fraction
    packets: tuple[Packet, ...]
    channels: int
    max_packets: int = 4096
    delay: Fraction = Fraction(1, 5)

    def __post_init__(self):
        object.__setattr__(self, "time", rational(self.time))
        object.__setattr__(self, "delay", rational(self.delay))
        if (self.time < 0 or self.delay < 0 or isinstance(self.channels, bool)
                or not isinstance(self.channels, int) or not 1 <= self.channels <= 128
                or isinstance(self.max_packets, bool)
                or not isinstance(self.max_packets, int) or not 1 <= self.max_packets <= 4096
                or not isinstance(self.packets, tuple)):
            raise ValueError("invalid state geometry or packet budget")
        if len(self.packets) > self.max_packets:
            raise OverflowError("packet budget exceeded; no implicit compaction")
        identities = set()
        for packet in self.packets:
            if not isinstance(packet, Packet) or len(packet.content) != self.channels:
                raise ValueError("invalid packet or content shape")
            if packet.start < self.time or packet.end <= self.time:
                raise ValueError("pending support must have a nonempty future part")
            if packet.identity in identities:
                raise ValueError("duplicate pending identity")
            identities.add(packet.identity)

    def advance_to(self, target, hits=()):
        """Transport exactly, admitting uniform/point hit influx in [time,target].

        The caller must provide the upstream hit law; no hit mass is computed
        here. A point releases at its exact deadline, including the right
        endpoint. Delay is fixed by the immutable state and may be zero.
        New hit laws are supplied once per call;
        replaying them is a new influx, not an idempotent read.
        """
        target = rational(target)
        if target < self.time or not isinstance(hits, tuple):
            raise ValueError("nonmonotone clock or mutable hit list")
        if len(self.packets) + len(hits) > self.max_packets:
            raise OverflowError("transient packet budget exceeded")
        identities = {p.identity for p in self.packets}
        shifted = []
        for hit in hits:
            if (not isinstance(hit, Packet) or len(hit.content) != self.channels
                    or hit.start < self.time or hit.end > target
                    or hit.identity in identities):
                raise ValueError("hit support, content or identity is invalid")
            identities.add(hit.identity)
            shifted.append(Packet(hit.identity, hit.start + self.delay, hit.end + self.delay,
                                  hit.mass, hit.content))
        released, pending = [], []
        for packet in self.packets + tuple(shifted):
            out, rest = packet.split_at(target)
            if out is not None:
                released.append(out)
            if rest is not None:
                pending.append(rest)
        state = RefractoryState(target, tuple(pending), self.channels, self.max_packets, self.delay)
        incoming_mass = sum((p.mass for p in hits), Fraction(0))
        incoming_content = tuple(sum((p.content[j] for p in hits), Fraction(0))
                                 for j in range(self.channels))
        return ReleaseReceipt(state, tuple(released), incoming_mass, incoming_content)

    def project_remaining(self, edges):
        """Read-only phase-bin projection; the returned bins are never state.

        Edges must cover every pending remaining-time support. Exact interval
        overlap handles uniform packets; half-open bins put boundary atoms in
        the right bin, except the final right edge belongs to the final bin.
        """
        edges = tuple(map(rational, edges))
        if (len(edges) < 2 or edges[0] != 0
                or any(b <= a for a, b in zip(edges, edges[1:]))):
            raise ValueError("strict edges must start at zero")
        probability = [Fraction(0) for _ in edges[1:]]
        marked = [[Fraction(0)] * self.channels for _ in edges[1:]]
        for packet in self.packets:
            lo, hi = packet.start - self.time, packet.end - self.time
            if hi > edges[-1]:
                raise ValueError("projection edges do not cover pending support")
            for j, (left, right) in enumerate(zip(edges, edges[1:])):
                if lo == hi:
                    ratio = Fraction(int(left <= lo < right or
                                         j == len(probability) - 1 and lo == right))
                else:
                    ratio = max(Fraction(0), min(hi, right) - max(lo, left)) / (hi - lo)
                probability[j] += packet.mass * ratio
                for k, value in enumerate(packet.content):
                    marked[j][k] += value * ratio
        return tuple(probability), tuple(tuple(row) for row in marked)
