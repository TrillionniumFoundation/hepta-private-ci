import random
import unittest

from example_validation_reference import ErrorKind, validate


class BehavioralReferenceTest(unittest.TestCase):
    def test_empty_examples(self):
        result = validate([], [], lambda _: self.fail('must not be invoked'))
        self.assertEqual(result.error, ErrorKind.NONE)
        self.assertEqual(result.call_trace, ())

    def test_negative_first_match_stops_without_positive_effects(self):
        calls = []
        def callback(command):
            calls.append(tuple(command))
            return command[0] == 'match'
        n = [['miss'], ['match'], ['match']]
        p = [['match']]
        r = validate(n, p, callback)
        self.assertEqual(r.error, ErrorKind.EXAMPLE_DID_MATCH)
        self.assertEqual(r.offending_negative_index, 1)
        self.assertEqual(r.call_trace, (('not_match', 0), ('not_match', 1)))
        self.assertEqual(calls, [('miss',), ('match',)])

    def test_positive_unmatched_are_all_collected(self):
        n = [['miss']]
        p = [['match'], ['miss'], ['miss'], ['match']]
        r = validate(n, p, lambda c: c[0] == 'match')
        self.assertEqual(r.error, ErrorKind.EXAMPLE_DID_NOT_MATCH)
        self.assertEqual(r.unmatched_positive_indices, (1, 2))
        self.assertEqual(r.call_trace, (('not_match', 0), ('match', 0), ('match', 1), ('match', 2), ('match', 3)))

    def test_callbacks_are_not_memoized_even_for_identical_commands(self):
        seen = []
        def callback(command):
            seen.append(tuple(command))
            return len(seen) % 2 == 0
        r = validate([['a'], ['a'], ['a']], [['a']], callback)
        self.assertEqual(r.error, ErrorKind.EXAMPLE_DID_MATCH)
        self.assertEqual(r.offending_negative_index, 1)
        self.assertEqual(seen, [('a',), ('a',)])

    def test_callback_error_aborts_without_later_effects(self):
        seen = []
        def callback(command):
            seen.append(tuple(command))
            if command[0] == 'throw':
                raise RuntimeError('call effect')
            return False
        with self.assertRaisesRegex(RuntimeError, 'call effect'):
            validate([['miss'], ['throw'], ['miss']], [['miss']], callback)
        self.assertEqual(seen, [('miss',), ('throw',)])

    def test_30977_deterministic_cases(self):
        rng = random.Random(0x18E123)
        for i in range(30977):
            n_count = rng.randrange(0, 9)
            p_count = rng.randrange(0, 9)
            neg = [[str(i), 'n', str(j)] for j in range(n_count)]
            pos = [[str(i), 'p', str(j)] for j in range(p_count)]
            negative_matches = {j for j in range(n_count) if rng.getrandbits(1)}
            positive_matches = {j for j in range(p_count) if rng.getrandbits(1)}
            calls = []
            def callback(c):
                calls.append((c[1], int(c[2])))
                return int(c[2]) in (negative_matches if c[1] == 'n' else positive_matches)
            r = validate(neg, pos, callback)
            first = min(negative_matches) if negative_matches else None
            if first is not None:
                self.assertEqual(r.error, ErrorKind.EXAMPLE_DID_MATCH)
                self.assertEqual(r.offending_negative_index, first)
                self.assertEqual(r.unmatched_positive_indices, ())
                self.assertEqual(calls, [('n', j) for j in range(first + 1)])
            else:
                expected = tuple(j for j in range(p_count) if j not in positive_matches)
                self.assertEqual(r.unmatched_positive_indices, expected)
                self.assertEqual(r.error, ErrorKind.EXAMPLE_DID_NOT_MATCH if expected else ErrorKind.NONE)
                self.assertEqual(calls, [('n', j) for j in range(n_count)] + [('p', j) for j in range(p_count)])


if __name__ == '__main__':
    unittest.main()
