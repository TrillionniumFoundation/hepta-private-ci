"""Immutable attempt journals; source rejection never creates a reusable result."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid


def source_snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(root).rglob('*.py'))}


def history(directory, key):
    records = []
    for start in sorted((Path(directory)/(key+'.attempts')).glob('*.started.json')):
        record = json.loads(start.read_text())
        outcome = start.with_name(record['attempt_id']+'.json')
        if outcome.exists():
            record = json.loads(outcome.read_text())
        else:
            record['result'] = dict(status='interrupted', training_status='unknown',
                                    training_examples_seen=None, training_tokens_seen=None,
                                    reason='start journal has no terminal outcome; budget and energy unknown',
                                    energy={'joules_by_physical_counter': None,
                                            'missing_reason': 'interrupted attempt; no terminal energy receipt'})
        records.append(record)
    return records


def execute(directory, key, provenance, operation, verify_source, publish):
    """Stage weights, verify source, then publish an immutable terminal outcome.

    A durable start journal makes interruption visible even without a terminal
    receipt. Rejected weights are quarantined and never referenced by a cache.
    """
    attempt_id = uuid.uuid4().hex
    folder = Path(directory)/(key+'.attempts')
    folder.mkdir(parents=True, exist_ok=True)
    pending = folder/(attempt_id+'.pending.pt')
    record = dict(provenance, attempt_id=attempt_id,
                  started_utc=datetime.now(timezone.utc).isoformat())
    publish(folder/(attempt_id+'.started.json'), record, replace=False)
    result = operation(pending)
    valid = verify_source()
    if pending.exists():
        weights = folder/(attempt_id+('.pt' if valid else '.rejected.pt'))
        os.replace(pending, weights)
        result['best_checkpoint'] = str(weights.resolve())
        result['best_checkpoint_relative'] = str(weights.relative_to(Path(directory)))
        result['best_checkpoint_sha256'] = hashlib.sha256(weights.read_bytes()).hexdigest()
    if not valid:
        result.update(status='invalidated', reason='source changed during attempt; quarantined, never reusable')
    record.update(result=result, finished_utc=datetime.now(timezone.utc).isoformat())
    publish(folder/(attempt_id+'.json'), record, replace=False)
    if not valid:
        raise RuntimeError('source changed during benchmark; attempt quarantined without reusable cache')
    return result, attempt_id


def resolve_weights(directory, result):
    relative = Path(result['best_checkpoint_relative'])
    root = Path(directory).resolve()
    weights = (root/relative).resolve()
    if relative.is_absolute() or not weights.is_relative_to(root):
        raise ValueError('checkpoint relative path escapes run directory')
    return weights


def accounting(attempts):
    results = [a['result'] for a in attempts]
    completed = sum(r['status'] == 'completed' for r in results)
    failed = sum(r['status'] == 'failed' for r in results)
    trained = [r for r in results if r['status'] in {'completed', 'failed'}
               and r.get('training_status') in {'completed', 'failed'}]
    measured = [r.get('energy', {}).get('joules_by_physical_counter') for r in results]
    measured = [v for v in measured if v is not None]
    by_completion = dict(complete=[], incomplete=[], unknown=[])
    for result in results:
        energy = result.get('energy', {})
        counters = energy.get('joules_by_physical_counter')
        if counters is not None:
            complete = energy.get('interval_complete')
            category = 'complete' if complete is True else 'incomplete' if complete is False else 'unknown'
            by_completion[category].append(counters)
    return dict(total=len(results), completed=completed, failed=failed,
                unavailable=sum(r['status'] == 'unavailable' for r in results),
                invalidated=sum(r['status'] == 'invalidated' for r in results),
                interrupted=sum(r['status'] == 'interrupted' for r in results),
                execution_failure_rate=failed/(completed+failed) if completed+failed else None,
                training_failure_rate=sum(r['training_status'] == 'failed' for r in trained)/len(trained)
                if trained else None,
                known_training_examples=sum(r.get('training_examples_seen') or 0 for r in results),
                known_training_tokens=sum(r.get('training_tokens_seen') or 0 for r in results),
                budget_unknown_attempts=sum(r.get('training_examples_seen') is None for r in results),
                energy_measured_attempts=len(measured), energy_missing_attempts=len(results)-len(measured),
                energy_measured_complete_interval_attempts=len(by_completion['complete']),
                energy_measured_incomplete_interval_attempts=len(by_completion['incomplete']),
                energy_measured_unknown_interval_attempts=len(by_completion['unknown']),
                measured_joules_by_counter={name: sum(v.get(name, 0) for v in measured)
                                           for name in {k for v in measured for k in v}},
                measured_joules_by_counter_by_interval_completion={
                    category: {name: sum(v[name] for v in values if name in v)
                               for name in {k for v in values for k in v}}
                    for category, values in by_completion.items()},
                energy_interval_completion_scope='Only explicit boolean interval_complete flags classify observed intervals; '
                'legacy/missing/nonboolean flags remain unknown. Complete interval does not mean complete training budget. '
                'Any-reading totals retain incomplete and unknown costs; missing counter values are excluded, never zero-filled.',
                energy_scope='sum of available attempt device/package readings; missing attempts excluded, never zero-filled')
