"""Continue ONE interrupted research stream by replaying a sealed prefix.

No saved statistical state is trusted. The existing stream recomputes every
outcome and decision before any live callback. Resume writes a NEW directory;
it does not reset alpha, change rows/models or overwrite historical failures.
A digest binds bytes, not authorship, quiescence or a rollback-proof authority.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import tempfile

from experiments.shared_stem_cell import execution as e
from experiments.shared_stem_cell import sequential_confirmation as s

MAX_FILE = 16 * 1024**2
MAX_TOTAL = 128 * 1024**2
SPECIAL = {'plan.json', 'candidate-lock.json', 'cohort.json', 'decision.json',
           'evaluation-predictions.json', 'report.json', 'failure.json'}
BATCH = re.compile(r'batch-[0-9]{4}-(predictions|outcomes)\.json\Z')
PROTOCOL = ('sequential_confirmation.py', 'sequential_evidence.py',
            'sequential_replay.py', 'sequential_work_audit.py')
RAW_KEYS = {'predictions', 'inference_costs', 'selected', 'encoding', 'feature_sha256'}


def source_identity():
    return {n: e.sha((Path(__file__).parent / n).read_bytes()) for n in PROTOCOL}


def files(root, *, manifest=False):
    if (not root.is_dir() or any(p.is_symlink() for p in (root, *root.parents))):
        raise e.InputError('ordinary checkpoint directory required')
    paths = list(root.iterdir())
    if not 2 <= len(paths) <= 520:
        raise e.InputError('bounded checkpoint inventory required')
    total = 0
    result = {}
    for p in paths:
        if (p.is_symlink() or not p.is_file() or
                not (p.name in SPECIAL or BATCH.fullmatch(p.name) or
                     (manifest and p.name == 'checkpoint.json'))):
            raise e.InputError('unexpected or linked checkpoint member')
        size = p.stat().st_size
        total += size
        if not 0 < size <= MAX_FILE or total > MAX_TOTAL:
            raise e.InputError('checkpoint byte budget exceeded')
        with p.open("rb") as stream:
            raw = stream.read(min(size, MAX_FILE) + 1)
        if len(raw) != size or e.canonical(e.decode(raw)) != raw:
            raise e.InputError('partial, changed or noncanonical checkpoint member')
        result[p.name] = raw
    return result


class _Boundary(Exception):
    pass


class Replay:
    """Validated immutable bytes; each run obtains its own callback counters."""
    def __init__(self, checkpoint, expected_sha256):
        raw = e.bound_file(checkpoint / 'checkpoint.json', expected_sha256, MAX_FILE)
        receipt = e.decode(raw)
        records = files(checkpoint, manifest=True)
        if (records.pop('checkpoint.json') != raw
                or receipt.get('schema') != 'hepta.sequential-prefix.v1'
                or receipt.get('source_sha256') != source_identity()
                or receipt.get('files') != {k: e.sha(v) for k, v in records.items()}
                or receipt.get('production_accepted') is not False):
            raise e.InputError('checkpoint source, inventory or external identity mismatch')
        self.records, self.anchor = records, expected_sha256
        self._validate()

    def _index(self):
        self.values = {k: e.decode(v) for k, v in self.records.items()}
        self.rows = self.values['cohort.json']
        self.lock = self.values['candidate-lock.json']
        if ('plan.json' in self.values and self.values['plan.json'] != self.lock):
            raise e.InputError('checkpoint plan and locked candidate differ')
        if ('source_sha256' in self.lock and self.lock['source_sha256'] != source_identity()):
            raise e.InputError('cannot resume across protocol source changes')
        self.predictions, self.labels = {}, {}
        if not isinstance(self.rows, list):
            raise e.InputError('checkpoint cohort must be a list')
        indices = {r['case_id']: r['source_index'] for r in self.rows}
        for name, value in self.values.items():
            if name.endswith('-predictions.json'):
                ids = tuple(value['case_ids'])
                if ids in self.predictions or any(i not in indices for i in ids):
                    raise e.InputError('duplicate or foreign saved prediction batch')
                self.predictions[ids] = {k: v for k, v in value.items() if k in RAW_KEYS}
            if name.endswith('-outcomes.json') or name == 'report.json':
                p = ('evaluation-predictions.json' if name == 'report.json' else
                     name.replace('-outcomes.json', '-predictions.json'))
                if p not in self.values:
                    raise e.InputError('orphan outcome without saved predictions')
                ids = self.values[p]['case_ids']
                labels = value['evaluation_labels'] if name == 'report.json' else value['labels']
                if not isinstance(labels, list) or len(labels) != len(ids):
                    raise e.InputError('incomplete saved outcome labels')
                for i, y in zip(ids, labels):
                    index = indices[i]
                    if index in self.labels:
                        raise e.InputError('duplicate saved label consumption')
                    self.labels[index] = e.integer(y, 0, 3, 'saved label')

    def _validate(self):
        self._index()
        def predicted(part):
            key = tuple(r['case_id'] for r in part)
            if key not in self.predictions:
                raise _Boundary()
            return self.predictions[key]
        def labeled(index):
            if index not in self.labels:
                raise _Boundary()
            return self.labels[index]
        # Invoke the UNCHANGED evidence update/schedule on a disposable replay.
        # It may stop at a pending prediction or pending labels, never at bad data.
        with tempfile.TemporaryDirectory(prefix='hepta-prefix-check-') as tmp:
            target = Path(tmp)
            complete = None
            try:
                complete = s.stream(target, self.rows, self.lock, predicted, labeled)
            except _Boundary:
                pass
            for name, raw in self.records.items():
                if name in ('plan.json', 'failure.json', 'report.json'):
                    continue
                if not (target / name).is_file() or (target / name).read_bytes() != raw:
                    raise e.InputError('saved prefix differs from recomputed schedule/evidence: ' + name)
            if 'report.json' in self.values and (complete is None or any(
                    self.values['report.json'].get(k) != v for k, v in complete.items())):
                raise e.InputError('saved final scores or decision differ from replay')

    @property
    def needs_encoder(self):
        return 'evaluation-predictions.json' not in self.records

    def bind(self, rows, lock):
        if e.canonical(rows) != self.records['cohort.json'] or e.canonical(lock) != self.records['candidate-lock.json']:
            raise e.InputError('resume cannot change candidate, cohort, order, budget or alpha')

    def run(self, output, rows, lock, predict_rows, label_at):
        self.bind(rows, lock)
        # Original prefix bytes were preflighted before either live callback.
        counts = {'reused_prediction_rows': 0, 'new_prediction_rows': 0,
                  'reused_label_rows': 0, 'new_label_rows': 0}
        calls = []
        def forward(part):
            key = tuple(r['case_id'] for r in part)
            reused = key in self.predictions
            counts['reused_prediction_rows' if reused else 'new_prediction_rows'] += len(part)
            calls.append({'case_ids': list(key), 'reused': reused})
            return self.predictions[key] if reused else predict_rows(part)
        def label(index):
            reused = index in self.labels
            counts['reused_label_rows' if reused else 'new_label_rows'] += 1
            return self.labels[index] if reused else label_at(index)
        result = s.stream(output, rows, lock, forward, label)
        result['continuation'] = {**counts, 'checkpoint_sha256': self.anchor, 'calls': calls,
            'prior_failure_sha256': e.sha(self.records['failure.json']) if 'failure.json' in self.records else None,
            'evidence_reset': False, 'same_stream_not_new_evidence': True,
            'unsealed_inflight_work': 'unknown_may_repeat; no exactly-once claim',
            'cost_semantics': 'batch costs describe original logical stream; new callback rows are this invocation',
            'production_accepted': False}
        return result


def seal(source, destination):
    """Snapshot a QUIESCENT complete prefix; preserve any old failure unchanged."""
    records = files(source)
    if not {'candidate-lock.json', 'cohort.json'} <= set(records):
        raise e.InputError('no locked sequential prefix to seal')
    # Reject malformed chains even when their local hashes have been recomputed.
    trial = object.__new__(Replay)
    trial.records = records
    trial._validate()
    if files(source) != records:
        raise e.InputError('source changed while checkpoint was checked')
    destination.mkdir(parents=True, exist_ok=False)
    for name, raw in records.items():
        value = e.decode(raw)
        if e.write_once(destination / name, value) != e.sha(raw):
            raise e.InputError('checkpoint copying changed source bytes')
    receipt = {'schema': 'hepta.sequential-prefix.v1',
        'files': {k: e.sha(v) for k, v in records.items()}, 'source_sha256': source_identity(),
        'requires_quiescent_source': True, 'rollback_proof': False, 'production_accepted': False}
    if files(source) != records:
        raise e.InputError('source changed before checkpoint publication')
    return e.write_once(destination / 'checkpoint.json', receipt)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    args = parser.parse_args()
    print(seal(args.source, args.checkpoint))
