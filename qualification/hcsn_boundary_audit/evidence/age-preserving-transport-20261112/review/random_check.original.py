"""Retained original pre-fixed-delay reviewer command; not a final-head rerun."""

from fractions import Fraction as F
import random
from qualification.hcsn_boundary_audit.refractory_transport import Packet, RefractoryState

rng = random.Random(457)
checks = 0
for case in range(1000):
    cuts = sorted(set([0, 100] + [rng.randrange(1, 100) for _ in range(12)]))
    packets = []
    for i in range(6):
        a = rng.randrange(1, 200)
        b = a + rng.randrange(0, 50)
        packets.append(Packet(str(i), F(a, 100), F(b, 100), F(rng.randrange(1, 7), 5),
                              (F(rng.randrange(-9, 10), 5),)))
    state = RefractoryState(0, tuple(packets), 1)
    released = []
    for cut in cuts[1:]:
        receipt = state.advance_to(F(cut, 100))
        released.extend(receipt.released)
        state = receipt.state
        mass = sum((p.mass for p in state.packets), F(0)) + sum((p.mass for p in released), F(0))
        content = (sum((p.content[0] for p in state.packets), F(0))
                   + sum((p.content[0] for p in released), F(0)))
        assert mass == sum((p.mass for p in packets), F(0))
        assert content == sum((p.content[0] for p in packets), F(0))
        # Independent cumulative release CDF evaluated from ORIGINAL laws.
        expected = F(0)
        t = F(cut, 100)
        for p in packets:
            ratio = (F(int(t >= p.start)) if p.start == p.end
                     else min(F(1), max(F(0), (t - p.start) / (p.end - p.start))))
            expected += p.mass * ratio
        assert sum((p.mass for p in released), F(0)) == expected
        checks += 1
print({'random_cases': 1000, 'intervals_checked': checks, 'mass_content_cdf_failures': 0})
