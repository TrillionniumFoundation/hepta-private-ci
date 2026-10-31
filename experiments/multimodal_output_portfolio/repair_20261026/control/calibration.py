"""Selected-operation calibration targets from closed native policy episodes.

This consumes retained native receipts and offline scores, not fresh media
observations. A fitted mapping is a candidate: changing admission changes the
policy, requiring frozen-pair replay and fresh independent qualification.
"""

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

from ...advance_20261026.native.calibrate import calibrated, ece, fit_curve
from .execution import digest, require, sha


def execution_identity(descriptor):
    """Only source/request names vary; modes, calibration and all pins remain."""
    return digest({k: v for k, v in descriptor.items() if k not in ('stream_id', 'source_group_id')})


@dataclass(frozen=True)
class EpisodeLabel:
    episode: str
    source_keys: tuple[str, ...]
    source_role: str
    execution_sha256: str
    route: str
    operation: str | None
    raw_probability: float | None
    strict_success: bool
    delivered: bool
    execution_failed: bool
    evidence_sha256: str


def load_native(directories, *, expected_execution_sha256, source_role, source_members):
    """Read every declared episode, including initial and continuation refusals.

source_members maps each native source_group to all original input SHA-256s;
writer, speaker and byte identities all participate in disjointness checks.
The caller supplies a complete frozen census; no successful-only discovery.
"""
    sha(expected_execution_sha256)
    require(source_role in ('old_fit', 'old_development', 'fresh_qualification'), 'Explicit source role required')
    rows = []
    for directory in map(Path, directories):
        paths = [directory / 'descriptor.json', directory / 'OFFLINE_SCORE.json']
        descriptor, score = (json.loads(p.read_text()) for p in paths)
        require(execution_identity(descriptor) == expected_execution_sha256
                and descriptor['policy'] == score['policy'], 'Mixed execution/continuation identities')
        require(score.get('initial_forecast_evaluated_against_actual_terminal_outcome') is True,
                'Labels must be scored after the entire policy, not the acquired observation')
        members = source_members[score['source_group']]
        require(bool(members), 'Original source bytes must be represented in the cohort identity')
        for member in members:
            sha(member)
        selected, raw = score['initial_action'], None
        decision_path, episode_path = directory / 'DECISION_H2.json', directory / 'EPISODE.json'
        if decision_path.exists():
            paths.append(decision_path)
            decision = json.loads(decision_path.read_text())['decision']
            require(decision['selected_action'] == selected, 'Scored initial operation differs from actual decision')
            if selected is not None:
                require(decision['actual_mask'][selected] is True, 'Selected operation was not actually admitted')
                raw = float(decision['raw_success'][selected])
        else:
            require(selected is None and score['execution_error'] is not None, 'Missing initial execution receipt')
        delivered = False
        if episode_path.exists():
            paths.append(episode_path)
            episode = json.loads(episode_path.read_text())
            require(episode['initial_action'] == selected and episode['policy'] == score['policy'],
                    'Closed episode does not match its initial action and policy')
            delivered = episode['actual_output_bundle'] is True
        success, failed = score['strict_success'], score['execution_error'] is not None
        if selected == 101 and not failed:
            later_path, commit_path = directory / 'DECISION_H1.json', directory / 'COMMITTED_EXTERNAL_AUDIO.json'
            later, committed = (json.loads(p.read_text()) for p in (later_path, commit_path))
            require(later['decision']['selected_action'] == score['final_action']
                    and later['decision']['parent_outcome_digest'] == committed['outcome_digest'],
                    'Acquisition target must follow the actual committed observation and later owner decision')
            paths.extend((later_path, commit_path))
        if delivered:
            for name in ('ACTUAL_OUTPUT.json', 'COMMITTED_OUTPUT.json'):
                require((directory / name).is_file(), 'Delivered bundle requires actual output and owner commit receipts')
        for name in ('EXTERNAL_AUDIO.json', 'ACTUAL_OUTPUT.json', 'COMMITTED_OUTPUT.json', 'EXECUTION_FAILURE.json'):
            path = directory / name
            if path.exists():
                paths.append(path)
        require(type(success) is bool and (not success or (delivered and not failed)),
                'A later refusal or execution failure cannot be labeled terminal success')
        keys = (f"group:{score['source_group']}", f"writer:{score['writer']}", f"speaker:{score['speaker']}")
        keys += tuple('bytes:' + member for member in sorted(set(members)))
        rows.append(EpisodeLabel(str(directory.resolve()), keys, source_role, expected_execution_sha256,
            score['route'], None if selected is None else 'acquire' if selected == 101 else 'emit',
            raw, success, delivered, failed,
            digest({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})))
    validate(rows)
    return rows


def validate(rows):
    require(bool(rows) and len({r.episode for r in rows}) == len(rows), 'Complete unique episode census required')
    for row in rows:
        sha(row.execution_sha256); sha(row.evidence_sha256)
        require(bool(row.source_keys) and row.operation in (None, 'emit', 'acquire')
                and type(row.strict_success) is bool and type(row.delivered) is bool
                and type(row.execution_failed) is bool, 'Invalid selected-policy terminal record')
        require(not row.strict_success or (row.delivered and not row.execution_failed),
                'Refused or failed terminal delivery is not success')
        require((row.raw_probability is None) == (row.operation is None), 'Only selected operations have forecasts')
        if row.raw_probability is not None:
            require(math.isfinite(row.raw_probability) and 0 <= row.raw_probability <= 1, 'Probability outside [0,1]')


def disjoint(first, second):
    a, b = ({k for r in rows for k in r.source_keys} for rows in (first, second))
    require(not a.intersection(b), 'Writer, speaker, source-group or input bytes cross fitting/evaluation cohorts')


def fit_selected(rows, *, execution_sha256):
    """Fit fixed-bin monotone maps to selected initial operation -> terminal event."""
    validate(rows); sha(execution_sha256)
    require(all(r.source_role == 'old_fit' and r.execution_sha256 == execution_sha256 for r in rows),
            'Only complete old fitting episodes of this exact execution may fit')
    groups = {}
    for row in rows:
        if row.operation is not None:
            groups.setdefault(row.route + ':' + row.operation, []).append(row)
    require(bool(groups), 'No selected-policy data: do not invent a confidence curve')
    curves = {key: fit_curve([r.raw_probability for r in values], [r.strict_success for r in values])
              for key, values in groups.items()}
    return {'schema': 'hepta.repair.selected-policy-calibration.v1',
            'fit_execution_sha256': execution_sha256, 'curves': curves,
            'episode_evidence_sha256': digest([r.evidence_sha256 for r in rows]),
            'fitting_source_keys': sorted({key for r in rows for key in r.source_keys}),
            'all_requests': len(rows), 'selected_operations': sum(len(v) for v in groups.values()),
            'later_failures_preserved': sum(r.operation == 'acquire' and not r.strict_success for r in rows),
            'candidate_only': True, 'requires_frozen_pair_replay': True, 'qualified': False}


def frozen_pair(base_execution, calibration):
    """No automatic activation: this identifies the exact pair that must rerun."""
    require(execution_identity(base_execution) == calibration['fit_execution_sha256'], 'Fitting policy closure differs')
    return {'schema': 'hepta.repair.policy-calibrator-pair.v1',
            'base_execution_sha256': execution_identity(base_execution),
            'selected_calibration_sha256': digest(calibration),
            'requires_new_actual_policy_replay': True, 'qualified': False}


def evaluate_selected(calibration, rows):
    """Probability diagnosis on disjoint sources for its unchanged target policy.

If admission has changed, this evaluation must not be relabeled qualification
of the changed policy; collect its new terminal records under a new identity.
"""
    validate(rows)
    require(all(r.source_role in ('old_development', 'fresh_qualification')
                and r.execution_sha256 == calibration['fit_execution_sha256'] for r in rows),
            'Changed policy/continuation requires actual replay and a new calibration target')
    require(not set(calibration['fitting_source_keys']).intersection(k for r in rows for k in r.source_keys),
            'Calibration evaluation contains fitting sources')
    probability, success, unsupported = [], [], []
    for row in rows:
        if row.operation is None:
            continue
        key = row.route + ':' + row.operation
        if key not in calibration['curves']:
            unsupported.append(row.episode)
            continue
        probability.append(float(calibrated(row.raw_probability, calibration['curves'][key])))
        success.append(int(row.strict_success))
    return {'requests': len(rows), 'selected_operations': sum(r.operation is not None for r in rows),
            'supported_selected_operations': len(probability), 'unsupported_episodes': unsupported,
            'selected_terminal_ECE': ece(probability, success) if not unsupported else None,
            'selected_terminal_brier': sum((p - y) ** 2 for p, y in zip(probability, success)) / len(probability)
                if probability and not unsupported else None,
            'request_coverage': sum(r.operation is not None for r in rows) / len(rows),
            'strict_success_including_refusals': sum(r.strict_success for r in rows) / len(rows),
            'execution_failures': sum(r.execution_failed for r in rows),
            'qualifies_changed_policy': False, 'fresh_policy_execution_performed_here': False}
