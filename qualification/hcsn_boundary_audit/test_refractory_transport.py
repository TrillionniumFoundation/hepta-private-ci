"""Exact arithmetic controls for persistent age and external reset influx."""

from fractions import Fraction as F
import random
import unittest

from qualification.hcsn_boundary_audit.refractory_transport import Packet, RefractoryState
from qualification.hcsn_boundary_audit.test_phase_delay_oracle import (
    CELLS, EDGES, TOTAL_TIME, project_uniform_cell,
)


def totals(packets, channels=2):
    return (sum((p.mass for p in packets), F(0)),
            tuple(sum((p.content[j] for p in packets), F(0)) for j in range(channels)))


def release_moment(packets, degree):
    result = F(0)
    for packet in packets:
        if packet.start == packet.end:
            moment = packet.start ** degree
        else:
            moment = ((packet.end ** (degree + 1) - packet.start ** (degree + 1))
                      / ((degree + 1) * (packet.end - packet.start)))
        result += packet.mass * moment
    return result


class TestPersistentRefractoryTransport(unittest.TestCase):
    def test_all_original_phase_rows_and_irregular_partitions_are_exact(self):
        rng = random.Random(9127)
        for source in range(CELLS):
            original = Packet(str(source), EDGES[source], EDGES[source + 1], F(1), (F(2), F(-3)))
            # The source-zero uniform support includes a zero-measure endpoint;
            # it is valid at time zero, unlike a point mass already due then.
            for count in (2, 4, 8, 16, 32):
                increments = [rng.randint(1, 29) for _ in range(count)]
                denominator = sum(increments)
                state = RefractoryState(F(0), (original,), 2)
                released = []
                elapsed = F(0)
                for increment in increments:
                    elapsed += TOTAL_TIME * increment / denominator
                    receipt = state.advance_to(elapsed)
                    state = receipt.state
                    released.extend(receipt.released)
                    self.assertEqual(totals(state.packets + tuple(released)), (F(1), (F(2), F(-3))))
                probability, marked = state.project_remaining(EDGES)
                actual = probability + (totals(released)[0],)
                self.assertEqual(actual, project_uniform_cell(source, TOTAL_TIME))
                self.assertEqual(tuple(sum(x[j] for x in marked) for j in range(2)),
                                 totals(state.packets)[1])

    def test_new_hit_influx_preserves_release_law_across_call_partitions(self):
        hit = Packet("hit", F(0), F(3, 25), F(3), (F(-6), F(9)))
        initial = Packet("initial", F(3, 50), F(2, 25), F(2), (F(4), F(-2)))
        initial_state = RefractoryState(F(0), (initial,), 2)
        direct = initial_state.advance_to(F(1, 2), (hit,))
        state, pieces, incoming = initial_state, [], F(0)
        for i, target in enumerate(map(F, (".01", ".04", ".10", ".15", ".21", ".30", ".32", ".50"))):
            lo, hi = max(state.time, hit.start), min(target, hit.end)
            hits = ()
            if hi > lo:
                ratio = (hi - lo) / (hit.end - hit.start)
                hits = (Packet(f"hit-{i}", lo, hi, hit.mass * ratio,
                               tuple(x * ratio for x in hit.content)),)
            receipt = state.advance_to(target, hits)
            incoming += receipt.incoming_mass
            before_mass, before_content = totals(state.packets)
            after_mass, after_content = totals(receipt.state.packets + receipt.released)
            self.assertEqual(before_mass + receipt.incoming_mass, after_mass)
            self.assertEqual(tuple(a + b for a, b in zip(before_content, receipt.incoming_content)), after_content)
            state = receipt.state
            pieces.extend(receipt.released)
        self.assertEqual(incoming, 3)
        self.assertEqual(totals(pieces), totals(direct.released))
        self.assertEqual(state.packets, ())
        for degree in (0, 1, 2, 3):
            self.assertEqual(release_moment(pieces, degree), release_moment(direct.released, degree))

    def test_no_early_release_and_exact_endpoint_atom(self):
        uniform = Packet("uniform", F(3, 50), F(2, 25), F(1), (F(-1), F(2)))
        atom = Packet("atom", F(7, 100), F(7, 100), F(2), (F(4), F(-1)))
        state = RefractoryState(F(0), (uniform, atom), 2)
        early = state.advance_to(F(52, 1000))
        self.assertEqual(early.released, ())
        at_endpoint = early.state.advance_to(F(7, 100))
        self.assertEqual(totals(at_endpoint.released), (F(5, 2), (F(7, 2), F(0))))
        self.assertEqual(at_endpoint.state.packets[0].start, F(7, 100))
        self.assertEqual(at_endpoint.state.packets[0].mass, F(1, 2))

    def test_release_packets_preserve_downstream_active_occupation(self):
        # A released tracer stays active forever. Integrate its actual release
        # time; a lump at the query endpoint would incorrectly yield zero.
        state = RefractoryState(F(0), (Packet("p", F(3, 50), F(2, 25), F(2), (F(1), F(-1))),), 2)
        receipt = state.advance_to(F(1, 10))
        active_time = F(1, 10) * totals(receipt.released)[0] - release_moment(receipt.released, 1)
        self.assertEqual(active_time, F(3, 50))
        self.assertGreater(active_time, 0)

    def test_read_only_projection_does_not_feed_back_and_atoms_have_one_bin(self):
        atom = Packet("p", F(1, 10), F(1, 10), F(1), (F(2), F(-2)))
        state = RefractoryState(F(0), (atom,), 2)
        self.assertEqual(state.project_remaining((0, F(1, 10), F(1, 5))),
                         ((F(0), F(1)), ((F(0), F(0)), (F(2), F(-2)))))
        self.assertEqual(state.packets, (atom,))
        self.assertEqual(state.project_remaining((0, F(1, 10)))[0], (F(1),))
        with self.assertRaises(ValueError):
            state.project_remaining((0, F(1, 20)))

    def test_zero_delay_influx_and_zero_interval_atom_release(self):
        state = RefractoryState(F(1), (), 1, delay=F(0))
        hit = Packet("now", F(1), F(1), F(2), (F(-3),))
        receipt = state.advance_to(F(1), (hit,))
        self.assertEqual(receipt.state.packets, ())
        self.assertEqual(receipt.released, (hit,))
        self.assertEqual(receipt.incoming_content, (F(-3),))
        self.assertEqual(receipt.state.delay, F(0))

    def test_overflow_invalid_clock_and_bad_influx_leave_original_immutable(self):
        packet = Packet("p", F(1), F(2), F(1), (F(-1),))
        state = RefractoryState(F(0), (packet,), 1, max_packets=1)
        hit = Packet("new", F(0), F(1, 2), F(1), (F(2),))
        with self.assertRaises(OverflowError):
            state.advance_to(F(1, 2), (hit,))
        with self.assertRaises(ValueError):
            state.advance_to(F(-1))
        for hits in ((Packet("q", F(0), F(2), F(1), (F(1),)),),
                     (Packet("p", F(0), F(1, 2), F(1), (F(1),)),)):
            roomy = RefractoryState(F(0), (packet,), 1, max_packets=4)
            with self.assertRaises(ValueError):
                roomy.advance_to(F(1), hits)
        self.assertEqual(state, RefractoryState(F(0), (packet,), 1, max_packets=1))

    def test_rejects_inexact_time_signed_probability_and_wrong_content(self):
        with self.assertRaises(ValueError):
            Packet("p", 0.1, F(1), F(1), (F(1),))
        with self.assertRaises(ValueError):
            Packet("p", 0, 1, F(-1), (F(1),))
        with self.assertRaises(ValueError):
            RefractoryState(0, (Packet("p", 1, 2, 1, (F(1),)),), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
