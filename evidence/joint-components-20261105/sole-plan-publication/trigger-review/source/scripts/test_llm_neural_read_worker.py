"""Private inference framing tests; these are not model execution evidence."""
import hashlib
import json
import socket
import unittest

import llm_neural_read_worker as worker


class NeuralReadFramingTests(unittest.TestCase):
    def request(self, raw):
        sender, receiver = socket.socketpair()
        with sender, receiver:
            sender.sendall(raw)
            sender.shutdown(socket.SHUT_WR)
            return worker.read_request(receiver)

    def test_real_socket_binds_exact_raw_bytes_and_has_no_expected_label(self):
        value = dict(schema='hepta-smollm-inference-input-v1', request_id='next-task-1', prompt='Actual query')
        raw = json.dumps(value).encode()
        self.assertEqual(self.request(raw+b'\n'), (value, hashlib.sha256(raw).hexdigest()))
        with self.assertRaisesRegex(ValueError, 'NEURAL_READ_REQUEST'):
            self.request(json.dumps(dict(value, expected_output='answer')).encode()+b'\n')

    def test_partial_duplicate_oversized_and_multiple_frames_are_rejected(self):
        for raw in (b'', b'{}', b'{}\n{}\n', b'{}\ntrailing', b'x'*8193+b'\n',
                    b'{"schema":"bad","schema":"hepta-smollm-inference-input-v1"}\n'):
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError):
                self.request(raw)

    def test_exact_stop_is_not_a_query_or_a_coerced_number(self):
        raw = json.dumps(dict(schema=worker.SCHEMA, stop=True)).encode()
        self.assertEqual(self.request(raw+b'\n'), (None, hashlib.sha256(raw).hexdigest()))
        for value in (dict(schema=worker.SCHEMA, stop=1), dict(schema=worker.SCHEMA, stop=False),
                      dict(schema=worker.SCHEMA, stop=True, prompt='extra'), None, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.request(json.dumps(value).encode()+b'\n')

    def test_frozen_action_vocabulary_rejects_aliases_order_and_extra_fields(self):
        actions = [dict(action_id='action-a', completion='no'), dict(action_id='action-b', completion='yes')]
        self.assertEqual(worker.action_profile(actions), actions)
        for value in ([], actions[::-1], [actions[0], actions[0]],
                      [actions[0], dict(action_id='action-b', completion='no')],
                      [dict(actions[0], expected_for_current_query=True)],
                      [dict(action_id='action-a', completion='x'*65)]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                worker.action_profile(value)


if __name__ == '__main__':
    unittest.main()
