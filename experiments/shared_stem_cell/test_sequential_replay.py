"""Real process exits and file-prefix replay; prediction fixture is synthetic."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from experiments.shared_stem_cell import execution as e, sequential_confirmation as s
from experiments.shared_stem_cell import sequential_replay as r


def fixture():
    rows = s.cohort([f'replay fixture text {i}' for i in range(300)], [], confirmation=256, final=16)
    lock = {'selected': 'residual_corrected', 'parameter_counts':
            {'bank': 100, 'shared': 20, 'residual_corrected': 60, 'linear_distilled': 40}}
    return rows, lock


def worker(root, cut=None, checkpoint=None, anchor=None):
    rows, lock = fixture()
    root.mkdir()
    trace = root.parent / (root.name + '-calls.jsonl')
    def event(value):
        with trace.open('ab') as stream:
            stream.write(e.canonical(value)); stream.flush(); os.fsync(stream.fileno())
    def predict(part):
        event({'kind': 'predict', 'ids': [row['case_id'] for row in part]})
        return {'predictions': {k: [[1., 0, 0, 0] if k == 'residual_corrected' and row['cell'] == 0
                                   else [0., 1, 0, 0] for row in part] for k in s.NAMES}}
    def label(index):
        event({'kind': 'label', 'index': index}); return 0
    original = e.write_once
    def write(path, value):
        seal = original(path, value)
        if path.name == cut:
            os._exit(73)  # actual child termination AFTER an fsynced record
        return seal
    with patch.object(e, 'write_once', write):
        replay = r.Replay(checkpoint, anchor) if checkpoint is not None else None
        result = s.stream(root, rows, lock, predict, label) if replay is None else replay.run(root, rows, lock, predict, label)
        original(root / 'report.json', result)


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.rows, self.lock = fixture()

    def tearDown(self): self.tmp.cleanup()

    def process(self, name, cut=None, checkpoint=None, anchor=None):
        argv = [sys.executable, '-m', __name__ if __name__ != '__main__' else
                'experiments.shared_stem_cell.test_sequential_replay', '--worker', str(self.root / name),
                cut or '-', str(checkpoint) if checkpoint else '-', anchor or '-']
        done = subprocess.run(argv, capture_output=True, timeout=20, check=False)
        self.assertEqual(done.returncode, 73 if cut else 0, done.stderr.decode())

    def trace(self, name, kind):
        p = self.root / (name + '-calls.jsonl')
        rows = [e.decode(v) for v in p.read_bytes().splitlines()] if p.exists() else []
        return [i for v in rows if v['kind'] == kind for i in (v['ids'] if kind == 'predict' else [v['index']])]

    def test_four_actual_process_cuts_resume_without_reencoding_committed_rows(self):
        self.process('reference')
        reference = e.decode((self.root / 'reference/report.json').read_bytes())
        for n, cut in enumerate(('batch-0000-predictions.json', 'batch-0000-outcomes.json',
                                 'decision.json', 'evaluation-predictions.json')):
            with self.subTest(cut=cut):
                old, new = f'cut{n}', f'continued{n}'
                self.process(old, cut)
                checkpoint = self.root / f'checkpoint{n}'
                anchor = r.seal(self.root / old, checkpoint)
                before = {p.name: p.read_bytes() for p in checkpoint.iterdir()}
                self.process(new, checkpoint=checkpoint, anchor=anchor)
                result = e.decode((self.root / new / 'report.json').read_bytes())
                self.assertEqual({k: result[k] for k in reference}, reference)
                self.assertEqual((self.root/new/'decision.json').read_bytes(), (self.root/'reference/decision.json').read_bytes())
                first, second = self.trace(old, 'predict'), self.trace(new, 'predict')
                self.assertFalse(set(first).intersection(second))
                self.assertEqual(first + second, self.trace('reference', 'predict'))
                self.assertEqual(before, {p.name: p.read_bytes() for p in checkpoint.iterdir()})
                self.assertFalse(result['continuation']['evidence_reset'])

    def test_completed_stream_replays_with_zero_external_callbacks(self):
        worker(self.root/'source'); anchor = r.seal(self.root/'source', self.root/'checkpoint')
        replay = r.Replay(self.root/'checkpoint', anchor)
        out = self.root/'new'; out.mkdir()
        with patch.object(e, 'fit', side_effect=AssertionError('no fitting')):
            result = replay.run(out, self.rows, self.lock, lambda p: self.fail('no encoding'), lambda i: self.fail('no labels'))
        self.assertEqual((result['continuation']['new_prediction_rows'], result['continuation']['new_label_rows']), (0, 0))
        self.assertFalse(replay.needs_encoder)

    def test_changed_cohort_and_threshold_lock_rejected_before_live_callbacks(self):
        worker(self.root/'source'); anchor = r.seal(self.root/'source', self.root/'checkpoint')
        replay = r.Replay(self.root/'checkpoint', anchor)
        for rows, lock in ((self.rows[::-1], self.lock), (self.rows, {**self.lock, 'alpha': .04})):
            with self.assertRaises(e.InputError): replay.bind(rows, lock)

    def test_wrong_external_digest_and_changed_member_rejected(self):
        worker(self.root/'source'); anchor = r.seal(self.root/'source', self.root/'checkpoint')
        with self.assertRaises(e.InputError): r.Replay(self.root/'checkpoint', '0'*64)
        (self.root/'checkpoint/decision.json').write_bytes(b'{}\n')
        with self.assertRaises(e.InputError): r.Replay(self.root/'checkpoint', anchor)

    def test_rehashed_false_evidence_never_gets_a_checkpoint(self):
        worker(self.root/'source')
        path = self.root/'source/batch-0000-outcomes.json'; value = e.decode(path.read_bytes())
        value['evidence']['per_cell'][0]['gains'] -= 1
        path.write_bytes(e.canonical(value))
        with self.assertRaisesRegex(e.InputError, 'recomputed'):
            r.seal(self.root/'source', self.root/'checkpoint')
        self.assertFalse((self.root/'checkpoint').exists())

    def test_rehashed_forged_final_score_is_refused(self):
        worker(self.root/'source')
        path = self.root/'source/report.json'; value = e.decode(path.read_bytes()); value['scores']['bank']['correct'] = 999
        path.write_bytes(e.canonical(value))
        with self.assertRaisesRegex(e.InputError, 'final scores'): r.seal(self.root/'source', self.root/'checkpoint')

    def test_orphan_outcome_and_hole_refused(self):
        worker(self.root/'source')
        (self.root/'source/batch-0000-predictions.json').unlink()
        with self.assertRaises(e.InputError): r.seal(self.root/'source', self.root/'checkpoint')

    def test_partial_json_and_extra_members_refused(self):
        worker(self.root/'source')
        p = self.root/'source/failure.json'; p.write_bytes(b'{"unfinished":')
        with self.assertRaises((e.InputError, json.JSONDecodeError)): r.seal(self.root/'source', self.root/'checkpoint')
        p.unlink(); (self.root/'source/unregistered').write_bytes(b'{}\n')
        with self.assertRaises(e.InputError): r.seal(self.root/'source', self.root/'checkpoint')

    def test_checkpoint_never_overwrites_or_follows_symlink(self):
        worker(self.root/'source'); r.seal(self.root/'source', self.root/'checkpoint')
        with self.assertRaises(FileExistsError): r.seal(self.root/'source', self.root/'checkpoint')
        (self.root/'alias').symlink_to(self.root/'source', target_is_directory=True)
        with self.assertRaises(e.InputError): r.seal(self.root/'alias', self.root/'other')

    def test_failure_record_is_retained_not_rewritten_as_success(self):
        worker(self.root/'source')
        failed = {'error': 'InterruptedAfterResults', 'message': 'preserved', 'production_accepted': False}
        e.write_once(self.root/'source/failure.json', failed)
        anchor = r.seal(self.root/'source', self.root/'checkpoint')
        out = self.root/'new'; out.mkdir()
        result = r.Replay(self.root/'checkpoint', anchor).run(out, self.rows, self.lock,
                    lambda p: self.fail('no encoding'), lambda i: self.fail('no label'))
        self.assertEqual(result['continuation']['prior_failure_sha256'], e.sha(e.canonical(failed)))
        self.assertEqual(e.decode((self.root/'source/failure.json').read_bytes()), failed)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        worker(Path(sys.argv[2]), None if sys.argv[3] == '-' else sys.argv[3],
               None if sys.argv[4] == '-' else Path(sys.argv[4]), None if sys.argv[5] == '-' else sys.argv[5])
    else: unittest.main()
