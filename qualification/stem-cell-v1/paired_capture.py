"""Execute every registered one-segment counterfactual before outcome scoring.

The stop endpoint is the supplied, pre-registration candidate, not a regenerated
answer. Continuation reuses run_reasoning's callback path, with no critic or
outcome access. Callbacks must be read-only/state-reconstructible from the public
boundary; hashes and Python object identity do not prove that owner contract.
"""
from __future__ import annotations

import copy
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from empirical_continuation import case_fingerprint
from execution_meter import WorkLedger, validate_policy as validate_meter_policy
from matrix_materials import file_sha256, strict_json
from next_round_matrix import _digest
from paired_critic import validate_protocol
from paired_execution import PHASES, _integer, _sha
from system2_execution import PublicTask, _text

SCHEMA = 'hepta.ndu.paired-capture-registration.v1'
PROFILE = 'registered_one_segment_capture.v1'
SOURCE_NAMES = ('paired_capture.py', 'paired_capture_export.py', 'system2_execution.py',
                'empirical_continuation.py', 'ndu_continuation.py', 'paired_critic.py',
                'execution_meter.py', 'work_record.py', 'aten_work.py', 'transformer_work.py',
                'host_counters.py', 'matrix_materials.py', 'matrix_runtime.py',
                'next_round_matrix.py', 'paired_execution.py', 'causal_generation.py', 'causal_snapshot.py', 'reasoning_baselines.py', 'causal_cache.py')


def source_fingerprints():
    return {n: file_sha256(Path(__file__).with_name(n)) for n in SOURCE_NAMES}


def read_task(value):
    if not isinstance(value, dict) or set(value) != {'prompt', 'as_of_ns', 'observations'}:
        raise ValueError('only a public task may enter capture')
    observations = value['observations']
    if (not isinstance(observations, list) or len(observations) > 64
            or any(not isinstance(r, list) or len(r) != 2 for r in observations)):
        raise ValueError('bounded public observation pairs required')
    task = PublicTask(value['prompt'], value['as_of_ns'], tuple(tuple(r) for r in observations))
    task.validate()
    return task


def freeze_capture(protocol, *, expected_protocol_id, boundaries, meter_policy, phase_caps):
    """Freeze actual public boundaries BEFORE observing either endpoint's utility."""
    validate_protocol(protocol, expected_protocol_id)
    validate_meter_policy(meter_policy)
    if not isinstance(phase_caps, dict) or set(phase_caps) != set(PHASES):
        raise ValueError('all capture work caps required')
    for cap in phase_caps.values():
        _integer(cap, 'capture cap')
    if not isinstance(boundaries, list) or len(boundaries) != len(protocol['pairs']):
        raise ValueError('every registered pair needs its exact public boundary')
    for pair, boundary in zip(protocol['pairs'], boundaries, strict=True):
        if not isinstance(boundary, dict) or set(boundary) != {
                'pair_id', 'task', 'candidate', 'feedback', 'available_at_ns', 'origin_receipt_sha256', 'initial_verifier_accepted'}:
            raise ValueError('complete label-free capture boundary required')
        if boundary['initial_verifier_accepted'] is not False:
            raise ValueError('critic capture population must start after a rejected verification')
        task = read_task(boundary['task'])
        _text(boundary['candidate']); _text(boundary['feedback'])
        _sha(boundary['origin_receipt_sha256'], 'upstream boundary receipt')
        _integer(boundary['available_at_ns'], 'boundary availability', 1)
        if not task.as_of_ns <= boundary['available_at_ns'] <= protocol['registered_at_ns']:
            raise ValueError('boundary must exist before paired registration')
        actual = dict(pair_id=boundary['pair_id'], group_id=pair['group_id'],
                      case_sha256=case_fingerprint(task, boundary['candidate'], boundary['feedback']),
                      candidate_bytes=len(boundary['candidate'].encode()), feedback_bytes=len(boundary['feedback'].encode()))
        if actual != pair:
            raise ValueError('registered case fingerprint, lengths or order differ from the actual boundary')
    body = dict(schema=SCHEMA, protocol=protocol, boundaries=boundaries,
                meter_policy=meter_policy, phase_caps=phase_caps, source_files_sha256=source_fingerprints(),
                callback_semantics='read_only_reconstructed_from_public_boundary',
                horizon='one_propose_verify_pair_no_critic', max_calls=2, max_rounds=1)
    if len(__import__('json').dumps(body, ensure_ascii=False).encode()) > 16 * 1024 * 1024:
        raise ValueError('capture registration exceeds 16 MiB')
    return copy.deepcopy({**body, 'capture_id': _digest(body)})


def validate_capture(value, expected_id):
    _sha(expected_id, 'externally retained capture registration')
    if not isinstance(value, dict):
        raise ValueError('capture registration required')
    keys = ('protocol', 'boundaries', 'meter_policy', 'phase_caps')
    try:
        expected = freeze_capture(**{k: value[k] for k in keys}, expected_protocol_id=value['protocol']['protocol_id'])
    except (KeyError, TypeError) as exc:
        raise ValueError('incomplete capture registration') from exc
    if expected['capture_id'] != expected_id or _digest(value) != _digest(expected):
        raise ValueError('capture inputs or first-party execution source changed')


@dataclass(frozen=True)
class PairedStart:
    """Explicit one-segment start, never a manufactured NDU continuation value."""
    capture_id: str
    task_sha256: str
    candidate: str
    feedback: str
    expires_at_ns: int
    meter_policy: dict
    phase_caps: dict

    def validate(self, task, meter, max_rounds, max_calls, value_profile, continue_values):
        _sha(self.capture_id, 'capture identity'); _sha(self.task_sha256, 'task identity')
        _text(self.candidate); _text(self.feedback)
        _integer(self.expires_at_ns, 'capture deadline', 1)
        if (self.task_sha256 != _digest(asdict(task)) or task.as_of_ns >= self.expires_at_ns
                or max_rounds != 1 or max_calls != 2 or value_profile != PROFILE or continue_values is not None
                or meter is None or _digest(meter.policy) != _digest(self.meter_policy)
                or _digest(meter.caps) != _digest(self.phase_caps)):
            raise ValueError('capture must use its bound task, budget and single segment without a critic')


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def create_capture(path, registration):
    from matrix_runtime import write_json_exclusive
    validate_capture(registration, registration['capture_id'])
    root = Path(path)
    root.mkdir(exist_ok=False)
    write_json_exclusive(root / 'REGISTRATION.json', registration)
    (root / 'pairs').mkdir()
    sync_directory(root); sync_directory(root.parent)


class PairCollector:
    """One callback pair, one-shot slots; no labels, fit, retries or case selection."""
    def __init__(self, root, *, expected_capture_id, callback_profile_sha256, propose, verify):
        self.root = Path(root)
        self.registration = strict_json(self.root / 'REGISTRATION.json')
        validate_capture(self.registration, expected_capture_id)
        if callback_profile_sha256 != self.registration['protocol']['callback_profile_sha256']:
            raise ValueError('callback profile differs from the paired experiment')
        if not callable(propose) or not callable(verify):
            raise ValueError('actual generator/verifier callbacks required')
        self._id, self._propose, self._verify = expected_capture_id, propose, verify

    def run_pair(self, pair_id, *, clock=time.time_ns):
        from matrix_runtime import write_json_exclusive
        from system2_execution import run_reasoning
        fixed = copy.deepcopy(self.registration)
        validate_capture(strict_json(self.root / 'REGISTRATION.json'), self._id)
        if _digest(fixed) != _digest(strict_json(self.root / 'REGISTRATION.json')):
            raise ValueError('collector registration changed')
        pairs = fixed['protocol']['pairs']
        index = next((i for i, p in enumerate(pairs) if p['pair_id'] == pair_id), None)
        if index is None:
            raise ValueError('unregistered pair')
        boundary = fixed['boundaries'][index]
        p = fixed['protocol']
        task = read_task(boundary['task'])
        start = clock()
        _integer(start, 'capture start', 1)
        if not p['registered_at_ns'] <= start < p['cutoff_ns']:
            raise ValueError('capture outside registered observation window')
        root = self.root / 'pairs' / f'{index:05d}'
        root.mkdir(exist_ok=False)  # An incomplete, failed or completed slot cannot retry.
        attempt = dict(capture_id=self._id, pair_id=pair_id, started_at_ns=start,
                       boundary_sha256=_digest(boundary))
        write_json_exclusive(root / 'STARTED.json', attempt)
        sync_directory(root); sync_directory(root.parent)
        meter = WorkLedger(fixed['meter_policy'], fixed['phase_caps'])
        began = time.perf_counter_ns()
        initial = PairedStart(self._id, _digest(asdict(task)), boundary['candidate'], boundary['feedback'],
                              p['cutoff_ns'], fixed['meter_policy'], fixed['phase_caps'])
        try:
            report = run_reasoning(task, propose=self._propose, verify=self._verify,
                                   continue_values=None, value_profile=PROFILE, max_rounds=1, max_calls=2,
                                   meter=meter, paired_start=initial, clock=clock)
            duration = max(1, time.perf_counter_ns() - began)
            ended = clock()
            if not start + duration <= ended < p['cutoff_ns']:
                raise ValueError('clock discontinuity or collection completed after cutoff')
            completed = report['status'] in ('depth_exhausted', 'verifier_accepted_not_independent_eval')
            status = 'completed' if completed else ('timed_out' if report['work_observation']['stopped'] == 'wall_time_budget' else 'failed')
            result = dict(schema='hepta.ndu.captured-pair.v1', capture_id=self._id, pair_id=pair_id,
                          protocol_id=p['protocol_id'], boundary_sha256=_digest(boundary), decision_at_ns=start,
                          duration_ns=duration, finished_at_ns=ended, status=status,
                          stop_candidate=boundary['candidate'], continue_candidate=report['candidate'] if completed else None,
                          execution=report, utility_labels_loaded=False, owner_authenticity_verified=False,
                          source_files_sha256=source_fingerprints(), production_authorized=False)
            if result['source_files_sha256'] != fixed['source_files_sha256']:
                raise ValueError('capture source changed during callbacks')
            write_json_exclusive(root / 'pair.json', result)
            seal = dict(schema='hepta.ndu.paired-terminal.v1', capture_id=self._id, pair_id=pair_id,
                        sealed_at_ns=clock(), files={n: file_sha256(root / n) for n in ('STARTED.json', 'pair.json')})
            if not ended <= seal['sealed_at_ns'] < p['cutoff_ns']:
                raise ValueError('terminal seal outside capture window')
            seal['terminal_id'] = _digest(seal)
            write_json_exclusive(root / 'TERMINAL.json', seal)
            sync_directory(root)
            return seal
        except Exception as exc:
            write_json_exclusive(root / 'FAILED_CAPTURE.json', dict(error_type=type(exc).__name__,
                                 expected_pair_id=pair_id, work_observation=meter.report(), production_authorized=False))
            sync_directory(root)
            raise
