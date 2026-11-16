import random
import unittest

from example_validation_reference import ErrorKind


class PendingValidationReferenceTest(unittest.TestCase):
    def test_start_is_an_exclusive_lower_bound_not_a_replay(self):
        from example_validation_reference import PendingValidation, validate_pending
        groups = [PendingValidation([['fail']], [], 'skipped'),
                  PendingValidation([['miss']], [['match']], 'used')]
        seen = []
        result = validate_pending(groups, 1,
                                  lambda group, command: seen.append((group, tuple(command))) or command[0] == 'match')
        self.assertEqual(result.error, ErrorKind.NONE)
        self.assertEqual(result.call_trace, ((1, 'not_match', 0), (1, 'match', 0)))
        self.assertEqual(seen, [(1, ('miss',)), (1, ('match',))])
        self.assertIsNone(result.attached_location)

    def test_first_negative_group_error_blocks_all_remaining_groups(self):
        from example_validation_reference import PendingValidation, validate_pending
        groups = [PendingValidation([['miss'], ['hit'], ['never']], [['never']], 'first'),
                  PendingValidation([['never']], [], 'later')]
        seen = []
        result = validate_pending(groups, 0,
                                  lambda g, c: seen.append((g, tuple(c))) or c[0] == 'hit')
        self.assertEqual(result.error, ErrorKind.EXAMPLE_DID_MATCH)
        self.assertEqual(result.failing_validation_index, 0)
        self.assertEqual(result.local_result.offending_negative_index, 1)
        self.assertEqual(result.attached_location, 'first')
        self.assertEqual(result.call_trace, ((0, 'not_match', 0), (0, 'not_match', 1)))
        self.assertEqual(seen, [(0, ('miss',)), (0, ('hit',))])

    def test_first_positive_group_error_blocks_later_entries(self):
        from example_validation_reference import PendingValidation, validate_pending
        groups = [PendingValidation([], [['yes'], ['no'], ['no2']], None),
                  PendingValidation([['never']], [], 'later')]
        seen = []
        result = validate_pending(groups, 0,
                                  lambda g, c: seen.append((g, tuple(c))) or c[0] == 'yes')
        self.assertEqual(result.error, ErrorKind.EXAMPLE_DID_NOT_MATCH)
        self.assertEqual(result.local_result.unmatched_positive_indices, (1, 2))
        self.assertIsNone(result.attached_location)
        self.assertEqual(seen, [(0, ('yes',)), (0, ('no',)), (0, ('no2',))])

    def test_group_isolation_and_repeated_stateful_callbacks(self):
        from example_validation_reference import PendingValidation, validate_pending
        groups = [PendingValidation([['same']], [['same']], 'a'),
                  PendingValidation([['same']], [['same']], 'b')]
        calls = []
        def callback(group, command):
            calls.append((group, tuple(command)))
            return (len(calls), group) in ((2, 0), (3, 1))
        result = validate_pending(groups, 0, callback)
        self.assertEqual(result.error, ErrorKind.EXAMPLE_DID_MATCH)
        self.assertEqual(result.failing_validation_index, 1)
        self.assertEqual(result.attached_location, 'b')
        self.assertEqual(calls, [(0, ('same',)), (0, ('same',)), (1, ('same',))])
        self.assertEqual(result.call_trace, ((0, 'not_match', 0), (0, 'match', 0), (1, 'not_match', 0)))

    def test_callback_exception_has_no_future_group_effects(self):
        from example_validation_reference import PendingValidation, validate_pending
        groups = [PendingValidation([], [['boom'], ['later']]),
                  PendingValidation([['never']], [])]
        calls = []
        def callback(group, command):
            calls.append((group, tuple(command)))
            if command[0] == 'boom':
                raise LookupError('original callback error')
            return False
        with self.assertRaisesRegex(LookupError, 'original callback error'):
            validate_pending(groups, 0, callback)
        self.assertEqual(calls, [(0, ('boom',))])

    def test_empty_groups_and_exact_end_offset(self):
        from example_validation_reference import PendingValidation, validate_pending
        groups = [PendingValidation([], [], 'ignored'), PendingValidation([], [], 'also ignored')]
        for start in (0, 1, 2):
            result = validate_pending(groups, start, lambda *_: self.fail('callback called'))
            self.assertEqual((result.error, result.call_trace, result.attached_location),
                             (ErrorKind.NONE, (), None))

    def test_invalid_slice_bounds_are_not_silently_clamped(self):
        from example_validation_reference import PendingValidation, validate_pending
        groups = [PendingValidation([], [])]
        for start in (-1, 2, True, 1.1, '0'):
            with self.subTest(start=start), self.assertRaises(IndexError):
                validate_pending(groups, start, lambda *_: False)

    def test_18000_deterministic_multi_validation_sequences(self):
        from example_validation_reference import PendingValidation, validate_pending
        rng = random.Random(0xABC1800)
        for iteration in range(18000):
            groups = []
            answers = {}
            count = rng.randrange(0, 6)
            for group in range(count):
                n_count, p_count = rng.randrange(0, 5), rng.randrange(0, 5)
                negative = [[str(iteration), str(group), 'n', str(j)] for j in range(n_count)]
                positive = [[str(iteration), str(group), 'p', str(j)] for j in range(p_count)]
                groups.append(PendingValidation(negative, positive, f'loc-{group}'))
                for cmd in negative + positive:
                    answers[tuple(cmd)] = bool(rng.getrandbits(1))
            start = rng.randrange(count + 1)
            seen = []
            def callback(group, command):
                self.assertEqual(int(command[1]), group)
                seen.append((group, command[2], int(command[3])))
                return answers[tuple(command)]
            result = validate_pending(groups, start, callback)
            expected_calls = []
            expected_group = None
            expected_kind = ErrorKind.NONE
            expected_location = None
            expected_local_unmatched = ()
            for group in range(start, count):
                first_match = None
                for j, cmd in enumerate(groups[group].negative_examples):
                    expected_calls.append((group, 'n', j))
                    if answers[tuple(cmd)]:
                        first_match = j
                        break
                if first_match is not None:
                    expected_group, expected_kind = group, ErrorKind.EXAMPLE_DID_MATCH
                    expected_location = f'loc-{group}'
                    break
                unmatched = []
                for j, cmd in enumerate(groups[group].positive_examples):
                    expected_calls.append((group, 'p', j))
                    if not answers[tuple(cmd)]:
                        unmatched.append(j)
                if unmatched:
                    expected_group, expected_kind = group, ErrorKind.EXAMPLE_DID_NOT_MATCH
                    expected_location, expected_local_unmatched = f'loc-{group}', tuple(unmatched)
                    break
            self.assertEqual(result.error, expected_kind)
            self.assertEqual(result.failing_validation_index, expected_group)
            self.assertEqual(result.attached_location, expected_location)
            self.assertEqual(seen, expected_calls)
            if expected_kind == ErrorKind.EXAMPLE_DID_NOT_MATCH:
                self.assertEqual(result.local_result.unmatched_positive_indices, expected_local_unmatched)


if __name__ == '__main__':
    unittest.main()
