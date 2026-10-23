"""Analytic transcript fixtures and corruption checks, with no model execution."""

from copy import deepcopy
import hashlib
import io
import os
import struct
import subprocess
import unittest

from audit_native import NativeAudit


NAMES = ('text', 'audio', 'image', 'video')
ACTIONS = ('EMIT', *(f'REFINE_{name}' for name in NAMES))


def sha(label):
    return hashlib.sha256(label.encode()).hexdigest()


def joint(values, kind='latents'):
    return hashlib.sha256(f'hepta.modality-portfolio.{kind}.v1\0'.encode()
                          + b''.join(bytes.fromhex(value) for value in values)).hexdigest()


def fixture(mode='ADAPTIVE', plan='-', sid=1):
    hashes, counts, remaining, version = [sha(n) for n in NAMES], [0] * 4, 347648, 0
    q_hash = hashlib.sha256(struct.pack('<8f', 0, 0, 1, 0, 0, 0, 0, 0)).hexdigest()
    records = []

    def reply(command, phase, suffix=()):
        return ['MP1', 'OK', command, sid, version, remaining, sum(counts), *counts,
                phase, joint(hashes), *suffix]

    records.append((['MP1', 'INIT', sid, 2, q_hash, 351232, 3584, 2,
                     6656, 69632, 53248, 200704, *([8704] * 4), *hashes, mode, plan],
                    reply('INIT', 'ready')))
    selected = [0] if mode == 'CLEAN' or (mode == 'COMMITTED' and plan == '-') else [1, 2, 0]
    for depth, action in enumerate(selected):
        values = ([-3., -1., -1. + 5e-13, -4., -5.] if depth == 0 else
                  [-1., -3., -.2, -2., -4.] if depth == 1 else [-.4, 0., 0., 0., 0.])
        if mode != 'ADAPTIVE':
            values = [(-10. if depth == 0 else -.4) if i == action else 0. for i in range(5)]
        entries = [item for i in reversed(range(5)) for item in
                   (ACTIONS[i], repr(values[i]), 330240 if i == 0 else 8704)]
        command = ['MP1', 'CHOOSE', sid, version, joint(hashes), *entries]
        version += 1
        remaining -= 330240 if action == 0 else 8704
        if action:
            counts[action - 1] += 1
        records.append((command, reply('CHOOSE', 'await_refinement' if action else 'await_outputs',
                                       (ACTIONS[action], format(values[action], '.17e')))))
        if action:
            hashes[action - 1] = sha(f'changed-{depth}')
            records.append((['MP1', 'REFINED', sid, version, ACTIONS[action], *hashes],
                            reply('REFINED', 'ready')))
        else:
            outputs = [sha(f'output-{n}') for n in NAMES]
            named = [item for pair in zip(NAMES, outputs) for item in pair]
            records.append((['MP1', 'EMITTED', sid, version, joint(hashes), *named],
                            reply('EMITTED', 'sealed', (*named, joint(outputs, 'outputs')))))
    return records


def audit(records):
    reader = NativeAudit.__new__(NativeAudit)
    content = ''.join('> ' + '\t'.join(map(str, command)) + '\n< '
                      + '\t'.join(map(str, response)) + '\n' for command, response in records).encode()
    reader.stream = io.BytesIO(content)
    reader.digest = hashlib.sha256()
    reader.requests, reader.sessions, reader.last_sid = 0, 0, 0
    return reader


class NativeAuditTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('HEPTA_V4_AUDIT_BINARY'), 'explicit native fixture binary required')
    def test_actual_native_transcript_matches_independent_auditor(self):
        records = (fixture() + fixture('COMMITTED', 'REFINE_text,REFINE_audio', 2)
                   + fixture('COMMITTED', '-', 3) + fixture('CLEAN', '-', 4))
        requests = ['\t'.join(map(str, command)) for command, _ in records]
        executed = subprocess.run([os.environ['HEPTA_V4_AUDIT_BINARY']], input='\n'.join(requests) + '\n',
                                  text=True, capture_output=True, timeout=30, check=True)
        self.assertEqual(executed.stderr, '')
        responses = executed.stdout.splitlines()
        self.assertEqual(len(responses), len(requests))
        reader = audit([(command, response.split('\t'))
                        for (command, _), response in zip(records, responses)])
        sessions = [reader.session() for _ in range(4)]
        self.assertEqual([s['refinement_counts'] for s in sessions], [[1, 1, 0, 0]] * 2 + [[0] * 4] * 2)
        self.assertEqual(reader.finish()['requests'], 20)

    def test_all_modes_canonical_tie_and_terminal_mask(self):
        records = (fixture() + fixture('COMMITTED', 'REFINE_text,REFINE_audio', 2)
                   + fixture('COMMITTED', '-', 3) + fixture('CLEAN', '-', 4))
        reader = audit(records)
        sessions = [reader.session() for _ in range(4)]
        self.assertEqual([s['spent_macs'] for s in sessions], [351232, 351232, 333824, 333824])
        self.assertEqual([e['action'] for e in sessions[0]['events']], [1, 2, 0])
        self.assertEqual(sessions[1]['plan'], (0, 1))
        self.assertIsNone(reader.session())
        self.assertEqual(reader.finish()['requests'], 20)

    def test_corrupt_state_score_policy_and_output_are_rejected(self):
        cases = [(0, 0, 4, sha('wrong-q')), (1, 1, 5, 1), (1, 1, 13, 'REFINE_audio'),
                 (1, 0, 3, 99), (2, 0, 8, sha('unrelated-video')),
                 (5, 0, 6, '0.1'), (6, 0, 5, 'audio'), (6, 1, 21, sha('wrong-bundle')),
                 (1, 0, 6, 'nan'), (1, 0, 5, 'REFINE_audio')]
        for exchange, side, field, value in cases:
            with self.subTest(corruption=(exchange, side, field)):
                records = deepcopy(fixture())
                records[exchange][side][field] = value
                with self.assertRaises(AssertionError):
                    audit(records).session()
        records = fixture('COMMITTED', 'REFINE_text,REFINE_audio')
        records[1][0][-2] = '1.0'
        with self.assertRaisesRegex(AssertionError, 'ineligible'):
            audit(records).session()

    def test_incomplete_and_uncovered_sessions_fail(self):
        with self.assertRaises(AssertionError):
            audit(fixture()[:-1]).session()
        reader = audit(fixture() + fixture('CLEAN', '-', 2))
        reader.session()
        with self.assertRaises(AssertionError):
            reader.finish()
        reader = audit(fixture() + fixture('CLEAN', '-', 1))
        reader.session()
        with self.assertRaisesRegex(AssertionError, 'monotone'):
            reader.session()


if __name__ == '__main__':
    unittest.main()
