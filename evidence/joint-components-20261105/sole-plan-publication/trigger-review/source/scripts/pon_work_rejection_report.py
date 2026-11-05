#!/usr/bin/env python3
"""Collect, independently check, or compare explicitly versioned W1 rejection costs.

The old pon-structured-cost-v3 collector remains unchanged. New observations keep
complete honest acquisition, existing-proof mutation, and verification separate.
This is a controlled cost diagnostic, not a lower bound or public-service result.
"""
from __future__ import annotations

import argparse
from collections import Counter
import datetime
from fractions import Fraction
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/ci'))
sys.path.insert(0, str(ROOT / 'formal/pon-nakamoto-v1'))
from bounded_process import ProcessFailure, run_bounded
from ci_observation import digest as file_digest, source
from check_cross_arch_cost import (ARCHITECTURES, elf_machine,
    REJECTION_IDENTITY_TIMEOUT_SECONDS, REJECTION_BUILD_TIMEOUT_SECONDS,
    REJECTION_CAMPAIGN_TIMEOUT_SECONDS, REJECTION_TERMINATION_GRACE_SECONDS,
    rejection_job_budget_seconds)
from check_invariant_evidence import source_bytes
from work_oracle import evaluate as scalar_evaluate

SCHEMA = 'pon-work-rejection-cost-v2'
PROFILE = 'pon-matmul-transcript-64-v1'
EXAMPLE = 'pon_rejection_cost'
CLASSES = ('dense', 'zero', 'rank-one', 'sparse')
TARGETS = ('7f' + 'ff' * 31, '07' + 'ff' * 31)
KERNELS = ('retained-transposed', 'scalar-reference', 'limb-transcript', 'production-full-limb')
VARIANTS = ('legal', 'transcript', 'product-last-cell')
RESULTS = ('Accepted', 'Transcript', 'Product')
ARMS = len(VARIANTS) * len(KERNELS)
LIMIT, SAMPLES, N, R, Q = 4096, 12, 64, 8, 4294967291
CELLS, PROOF_BYTES = N * N, 49188
FALSE_FLAGS = ('fastest_adversary_qualified', 'work_hardness_accepted',
               'worst_case_rejection_qualified', 'public_service_measured', 'production_activation')
SOURCE_PATHS = {
    'scripts/pon_work_rejection_report.py', 'scripts/ci/test_work_rejection_report.py',
    'docs/research/PON_WORK_REJECTION_COST_V2_PLAN.md',
    'scripts/ci/ci_observation.py', 'scripts/ci/verify_ci_source.py',
    'scripts/ci/check_cross_arch_cost.py', 'scripts/ci/check_invariant_evidence.py',
    'formal/pon-nakamoto-v1/work_oracle.py', 'formal/pon-nakamoto-v1/contract_wire.py',
    'formal/pon-nakamoto-v1/bounded_process.py', 'formal/pon-nakamoto-v1/test_bounded_process.py',
    'config/pon/devnet-v1.json', 'config/pon/work-profile-v1.json', 'rust-toolchain.toml',
}
RUNNER_FIELDS = ('GITHUB_ACTIONS', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB',
    'GITHUB_REPOSITORY', 'GITHUB_EVENT_NAME', 'GITHUB_SHA', 'RUNNER_ARCH', 'RUNNER_OS',
    'RUNNER_NAME', 'ImageOS', 'ImageVersion', 'TRNM_COST_RUNNER_LABEL')
RAW_LIMIT = 256 * 1024 * 1024


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError('W1 rejection diagnostic: ' + message)


def exact(value: Any, fields: set[str], name: str) -> None:
    require(type(value) is dict and set(value) == fields, name + ' exact fields')


def integer(value: Any, name: str, *, minimum: int = 0, maximum: int = (1 << 128) - 1) -> int:
    require(type(value) is int and minimum <= value <= maximum, name + ' integer range')
    return value


def hash_text(value: Any, name: str) -> str:
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None, name + ' canonical hash')
    return value


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key ' + key)
        result[key] = value
    return result


def load(path: Path) -> dict:
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= RAW_LIMIT,
            'missing, linked or oversized JSON ' + str(path))
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def h(tag: bytes, *parts: bytes) -> bytes:
    value = hashlib.sha256(b'TRNM-PON1\0' + len(tag).to_bytes(2, 'little') + tag)
    for part in parts:
        value.update(len(part).to_bytes(4, 'little') + part)
    return value.digest()


@lru_cache(maxsize=4)
def material(class_name: str) -> tuple[tuple[int, ...], tuple[int, ...], bytes, str]:
    require(class_name in CLASSES, 'fixed task class')
    if class_name == 'zero':
        a = b = (0,) * CELLS
    elif class_name == 'sparse':
        a = b = tuple(int(i // N == i % N) for i in range(CELLS))
    elif class_name == 'rank-one':
        a = tuple((i // N + 1) * (i % N + 1) for i in range(CELLS))
        b = tuple((i // N + 2) * (i % N + 1) for i in range(CELLS))
    else:
        a = tuple(i % 31 for i in range(CELLS))
        b = tuple((i * 7) % 37 for i in range(CELLS))
    product = tuple(sum(a[i * N + k] * b[k * N + j] for k in range(N)) % Q
                    for i in range(N) for j in range(N))
    pack = lambda values: struct.pack('<' + 'I' * len(values), *values)
    prefix = b'PNW1' + pack(a) + pack(b) + pack(product)
    task = h(b'task', pack(a), pack(b)).hex()
    return a, b, prefix, task


@lru_cache(maxsize=144)
def independent_winner(class_name: str, challenge: str) -> tuple[bytes, bytes]:
    a, b, _, _ = material(class_name)
    product, trace = scalar_evaluate(bytes.fromhex(challenge), a, b)
    return struct.pack('<' + 'I' * CELLS, *product), trace


def challenge_for(class_name: str, target: str, sample: int, nonce: int) -> bytes:
    return h(b'rejection-cost-challenge-v1', class_name.encode(), bytes.fromhex(target),
             sample.to_bytes(8, 'little'), nonce.to_bytes(8, 'little'))


def expected_progress(challenge: bytes, variant: str) -> dict:
    sequence = bytearray([0])
    counts = []
    for label in range(4):
        accepted, counter = 0, 0
        while accepted < N * R:
            require(counter < 128, 'noise sampling budget')
            sequence.extend(bytes([1, label]) + struct.pack('<I', counter))
            values = struct.unpack('<8I', h(b'noise', challenge, bytes([label]), struct.pack('<I', counter)))
            accepted += sum(v < Q for v in values)
            counter += 1
        counts.append(counter)
    for _ in range(2):
        for row in range(N): sequence.extend(b'\x02' + struct.pack('<I', row))
    for row in range(N // R):
        for column in range(N // R):
            for inner in range(N // R): sequence.extend(b'\x03' + struct.pack('<III', row, column, inner))
    rows, before_product, before_verified = 2 * N, 0, 0
    if variant != 'transcript':
        sequence.append(4)
        before_product = 1
        for count in (N, N, R, N):
            for row in range(count): sequence.extend(b'\x02' + struct.pack('<I', row))
            rows += count
        if variant == 'legal':
            sequence.append(5)
            before_verified = 1
    return {'timed': False, 'actual_result': RESULTS[VARIANTS.index(variant)],
        'sequence_sha256': digest(sequence), 'events': 1 + sum(counts) + rows + 512 + before_product + before_verified,
        'noise_counts': counts, 'before_replay': 1, 'matrix_rows': rows, 'transcript_tiles': 512,
        'before_product': before_product, 'before_verified_work': before_verified}


def ratio(numerator: int | Fraction, denominator: int | Fraction) -> dict | None:
    if not denominator:
        return None
    value = Fraction(numerator) / Fraction(denominator)
    return {'numerator': str(value.numerator), 'denominator': str(value.denominator),
            'decimal': float(value)}


def median(values: list[int]) -> Fraction | None:
    if not values:
        return None
    values = sorted(values)
    middle = len(values) // 2
    return Fraction(values[middle]) if len(values) % 2 else Fraction(values[middle - 1] + values[middle], 2)


def deterministic_projection(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: deterministic_projection(item) for key, item in value.items() if not key.endswith('_ns')}
    if isinstance(value, list):
        return [deterministic_projection(item) for item in value]
    return value


def projection_sha256(raw: dict) -> str:
    return digest(encoded(deterministic_projection(raw)))


def validate_search(row: dict, prefix: bytes) -> tuple[dict | None, int]:
    searched = row['honest_search']
    exact(searched, {'outcome', 'attempt_limit', 'wall_ns', 'challenge_ns', 'proof_construction_ns',
                    'ticket_ns', 'diagnostic_overhead_ns', 'attempts'}, 'honest search')
    require(type(searched['attempt_limit']) is int and searched['attempt_limit'] == LIMIT, 'actual search limit')
    require(searched['outcome'] in ('winner', 'exhausted'), 'honest search outcome')
    require(type(searched['attempts']) is list and 0 < len(searched['attempts']) <= LIMIT, 'all attempted proofs')
    totals = Counter()
    winner = None
    for nonce, attempted in enumerate(searched['attempts']):
        exact(attempted, {'nonce', 'challenge', 'trace', 'ticket', 'proof_sha256', 'selected',
                          'challenge_ns', 'proof_construction_ns', 'ticket_ns'}, 'proof attempt')
        require(type(attempted['nonce']) is int and attempted['nonce'] == nonce, 'contiguous attempt nonce')
        require(type(attempted['selected']) is bool, 'actual selected boolean')
        for name in ('challenge', 'trace', 'ticket', 'proof_sha256'): hash_text(attempted[name], name)
        challenge = challenge_for(row['class'], row['target'], row['sample'], nonce)
        require(attempted['challenge'] == challenge.hex(), 'challenge stream identity')
        ticket = h(b'ticket', challenge, bytes.fromhex(attempted['trace']))
        require(attempted['ticket'] == ticket.hex(), 'actual ticket bytes')
        selected = ticket.hex() <= row['target']
        require(attempted['selected'] is selected, 'target decision')
        require(attempted['proof_sha256'] == digest(prefix + bytes.fromhex(attempted['trace'])),
                'complete attempted proof bytes')
        for name in ('challenge_ns', 'proof_construction_ns', 'ticket_ns'):
            totals[name] += integer(attempted[name], name)
        if selected:
            require(nonce == len(searched['attempts']) - 1 and winner is None, 'search stops at first winner')
            winner = attempted
    require((winner is not None) == (searched['outcome'] == 'winner'), 'recorded winner/exhaustion')
    if winner is None:
        require(len(searched['attempts']) == LIMIT, 'exhaustion cannot omit remaining attempted budget')
    for name, total in totals.items():
        require(integer(searched[name], name) == total, 'omitted search phase ' + name)
    overhead = integer(searched['diagnostic_overhead_ns'], 'search recording overhead')
    require(integer(searched['wall_ns'], 'whole search wall', minimum=1) == sum(totals.values()) + overhead,
            'search wall includes phase timers and audit/recording overhead')
    return winner, len(searched['attempts'])


def validate_mutation(mutation: dict, proof: bytes, challenge: bytes, target: str) -> bytes | None:
    exact(mutation, {'id', 'outcome', 'source_proof_sha256', 'proof_sha256', 'trace', 'ticket',
        'clone_ns', 'mutation_ns', 'ticket_search_wall_ns', 'ticket_candidate_ns', 'ticket_hash_ns',
        'ticket_recording_overhead_ns', 'construction_ns', 'construction_overhead_ns',
        'ticket_origin', 'ticket_attempts', 'product_cell'}, 'mutation')
    variant = mutation['id']
    require(variant in VARIANTS[1:], 'known late rejection input')
    require(mutation['source_proof_sha256'] == digest(proof), 'mutation includes actual complete honest proof identity')
    require(mutation['outcome'] in ('ready', 'search-exhausted'), 'mutation outcome')
    for name in ('clone_ns', 'mutation_ns', 'ticket_search_wall_ns', 'ticket_candidate_ns',
                 'ticket_hash_ns', 'ticket_recording_overhead_ns', 'construction_ns', 'construction_overhead_ns'):
        integer(mutation[name], name)
    require(mutation['construction_ns'] > 0, 'measured mutation construction')
    require(mutation['construction_ns'] == mutation['clone_ns'] + mutation['mutation_ns'] +
            mutation['ticket_search_wall_ns'] + mutation['construction_overhead_ns'], 'complete mutation timer')
    require(mutation['ticket_search_wall_ns'] == mutation['ticket_candidate_ns'] + mutation['ticket_hash_ns'] +
            mutation['ticket_recording_overhead_ns'], 'fake ticket search accounting')
    require(type(mutation['ticket_attempts']) is list, 'fake ticket records')
    changed = bytearray(proof)
    if variant == 'product-last-cell':
        require(mutation['ticket_origin'] == 'honest-winner' and mutation['outcome'] == 'ready', 'product reuses real passing ticket')
        require(mutation['ticket_attempts'] == [] and all(mutation[name] == 0 for name in
            ('ticket_search_wall_ns', 'ticket_candidate_ns', 'ticket_hash_ns', 'ticket_recording_overhead_ns')),
            'product mutation must not search or change the real trace')
        exact(mutation['product_cell'], {'index', 'before', 'after'}, 'changed last product cell')
        cell = mutation['product_cell']
        for name in cell: integer(cell[name], 'cell ' + name, maximum=Q - 1)
        require(cell['index'] == CELLS - 1, 'only the last logical product cell changes')
        before = struct.unpack('<I', proof[-36:-32])[0]
        require(cell['before'] == before and cell['after'] == (before + 1) % Q, 'canonical nonidentical product mutation')
        changed[-36:-32] = struct.pack('<I', cell['after'])
    else:
        require(mutation['ticket_origin'] == 'new-fake-trace-search' and mutation['product_cell'] is None,
                'transcript mutation has a separately searched fake trace')
        require(0 < len(mutation['ticket_attempts']) <= LIMIT, 'complete fake ticket attempts')
        candidate_ns = ticket_ns = 0
        winner = None
        for nonce, attempted in enumerate(mutation['ticket_attempts']):
            exact(attempted, {'nonce', 'trace', 'ticket', 'selected', 'candidate_ns', 'ticket_ns'}, 'fake ticket attempt')
            require(type(attempted['nonce']) is int and attempted['nonce'] == nonce, 'contiguous fake trace attempts')
            trace = h(b'rejection-cost-fake-trace-v1', challenge, nonce.to_bytes(8, 'little'))
            ticket = h(b'ticket', challenge, trace)
            selected = ticket.hex() <= target and trace != proof[-32:]
            require(attempted['trace'] == trace.hex() and attempted['ticket'] == ticket.hex(), 'fake trace/ticket exact stream')
            require(type(attempted['selected']) is bool and attempted['selected'] is selected, 'fake target decision')
            candidate_ns += integer(attempted['candidate_ns'], 'candidate time')
            ticket_ns += integer(attempted['ticket_ns'], 'fake ticket time')
            if selected:
                require(nonce == len(mutation['ticket_attempts']) - 1, 'fake search stops at first winner')
                winner = trace
        require(mutation['ticket_candidate_ns'] == candidate_ns and mutation['ticket_hash_ns'] == ticket_ns,
                'all failed fake candidates remain charged')
        require((winner is not None) == (mutation['outcome'] == 'ready'), 'fake winner/exhaustion result')
        if winner is None:
            require(len(mutation['ticket_attempts']) == LIMIT and
                    all(mutation[name] is None for name in ('proof_sha256', 'trace', 'ticket')),
                    'exhausted fake search cannot manufacture a verified input')
            return None
        changed[-32:] = winner
    require(mutation['proof_sha256'] == digest(changed), 'exact mutated proof commitment')
    require(mutation['trace'] == bytes(changed[-32:]).hex(), 'mutation trace bytes')
    ticket = h(b'ticket', challenge, bytes(changed[-32:]))
    require(mutation['ticket'] == ticket.hex() and ticket.hex() <= target, 'late rejection passes the same target')
    return bytes(changed)


def summarize(raw: dict) -> dict:
    exact(raw, {'schema', 'profile', 'attempt_limit', 'samples_per_group', 'producer', 'kernels', 'samples', *FALSE_FLAGS}, 'raw diagnostic')
    require(raw['schema'] == SCHEMA and raw['profile'] == PROFILE, 'explicit new raw schema/profile')
    require(type(raw['attempt_limit']) is int and raw['attempt_limit'] == LIMIT and
            type(raw['samples_per_group']) is int and raw['samples_per_group'] == SAMPLES,
            'fixed native attempt and sample bounds')
    require(raw['producer'] == 'prepared-task-full-transcript' and raw['kernels'] == list(KERNELS),
            'producer/kernel identities')
    for flag in FALSE_FLAGS: require(raw[flag] is False, 'unsupported acceptance ' + flag)
    expected_keys = [(c, t, s) for c in CLASSES for t in TARGETS for s in range(SAMPLES)]
    require(type(raw['samples']) is list and len(raw['samples']) == len(expected_keys), 'complete fixed cohort inventory')
    groups = {(c, t): {'flows': 0, 'honest_winners': 0, 'honest_exhausted': 0, 'fake_exhausted': 0,
                      'honest_attempts': 0, 'fake_ticket_trials': 0, 'honest_acquisition_ns': 0,
                      'setup_ns': 0, 'honest_search_wall_ns': 0,
                      'mutation_construction_ns': {variant: 0 for variant in VARIANTS[1:]},
                      'variants': {}, 'positions': Counter()}
              for c in CLASSES for t in TARGETS}
    independent_replays = measured = 0
    for expected_key, row in zip(expected_keys, raw['samples']):
        exact(row, {'class', 'sample', 'target', 'task', 'proof_prefix_hex', 'setup', 'honest_search',
                    'honest_acquisition_ns', 'mutations', 'measurements'}, 'cohort')
        require(type(row['sample']) is int and (row['class'], row['target'], row['sample']) == expected_key,
                'native cohort order/identity cannot change')
        _, _, prefix, task = material(row['class'])
        require(row['task'] == task and row['proof_prefix_hex'] == prefix.hex(),
                'independently computed material/task/product prefix')
        exact(row['setup'], {'material_ns', 'task_binding_ns', 'reusable_preprocessing_ns', 'total_ns'}, 'one actual setup')
        for name, value in row['setup'].items(): integer(value, name)
        require(row['setup']['total_ns'] == sum(row['setup'][name] for name in
                ('material_ns', 'task_binding_ns', 'reusable_preprocessing_ns')), 'setup cannot disappear into a reused label')
        winner, attempted = validate_search(row, prefix)
        acquisition = integer(row['honest_acquisition_ns'], 'honest acquisition', minimum=1)
        require(acquisition == row['setup']['total_ns'] + row['honest_search']['wall_ns'], 'all honest acquisition phases charged once')
        group = groups[(row['class'], row['target'])]
        group['flows'] += 1
        group['honest_attempts'] += attempted
        group['honest_acquisition_ns'] += acquisition
        group['setup_ns'] += row['setup']['total_ns']
        group['honest_search_wall_ns'] += row['honest_search']['wall_ns']
        require(type(row['mutations']) is list and type(row['measurements']) is list, 'actual mutation/verification lists')
        if winner is None:
            group['honest_exhausted'] += 1
            require(not row['mutations'] and not row['measurements'], 'exhaustion cannot supply a legal baseline or late rejection')
            continue
        group['honest_winners'] += 1
        challenge = bytes.fromhex(winner['challenge'])
        proof = prefix + bytes.fromhex(winner['trace'])
        product, trace = independent_winner(row['class'], winner['challenge'])
        independent_replays += 1
        require(product == prefix[-CELLS * 4:] and trace == proof[-32:], 'independent scalar full winner transcript')
        require(len(row['mutations']) == 2 and [m.get('id') for m in row['mutations']] == list(VARIANTS[1:]),
                'retain both explicit late rejection constructions')
        proofs = {'legal': proof}
        construction = {'legal': 0}
        for mutation in row['mutations']:
            proofs[mutation['id']] = validate_mutation(mutation, proof, challenge, row['target'])
            construction[mutation['id']] = mutation['construction_ns']
            group['mutation_construction_ns'][mutation['id']] += mutation['construction_ns']
            group['fake_ticket_trials'] += len(mutation['ticket_attempts'])
            if proofs[mutation['id']] is None: group['fake_exhausted'] += 1
        expected_arms = []
        for position in range(ARMS):
            arm = (position + row['sample']) % ARMS
            variant, kernel = VARIANTS[arm // len(KERNELS)], KERNELS[arm % len(KERNELS)]
            if proofs[variant] is not None: expected_arms.append((position, variant, kernel))
        require(len(row['measurements']) == len(expected_arms), 'actual ready verification arms cannot be omitted/duplicated')
        for expected_arm, observed in zip(expected_arms, row['measurements']):
            exact(observed, {'position', 'variant', 'kernel', 'proof_sha256', 'elapsed_ns', 'actual_result',
                             'returned_product_sha256', 'probe'}, 'timed verification')
            require(type(observed['position']) is int and
                    (observed['position'], observed['variant'], observed['kernel']) == expected_arm,
                    'twelve-arm exact cyclic invocation order')
            variant, kernel = observed['variant'], observed['kernel']
            require(observed['proof_sha256'] == digest(proofs[variant]), 'timed/probed complete proof identity')
            require(observed['actual_result'] == RESULTS[VARIANTS.index(variant)], 'record actual WorkError, not is_err or inference')
            expected_product = digest(product) if variant == 'legal' else None
            require(observed['returned_product_sha256'] == expected_product, 'only actual complete success returns a product')
            expected_probe = expected_progress(challenge, variant)
            require(type(observed['probe']) is dict and encoded(observed['probe']) == encoded(expected_probe),
                    'non-timed actual probe reaches exact rejection boundary with all callbacks')
            duration = integer(observed['elapsed_ns'], 'actual verifier wall time', minimum=1)
            key = variant + '/' + kernel
            entry = group['variants'].setdefault(key, {'verifications': 0, 'verification_total_ns': 0,
                'matched_construction_total_ns': 0, 'durations_ns': []})
            entry['verifications'] += 1
            entry['verification_total_ns'] += duration
            entry['matched_construction_total_ns'] += construction[variant]
            entry['durations_ns'].append(duration)
            group['positions'][(variant, kernel, observed['position'])] += 1
            measured += 1
    output_groups = []
    for (class_name, target), group in groups.items():
        complete = group['honest_winners'] == SAMPLES and group['fake_exhausted'] == 0
        if complete:
            require(all(group['positions'][(v, k, p)] == 1 for v in VARIANTS for k in KERNELS for p in range(ARMS)),
                    'every ready arm occupies every position exactly once per complete group')
        group.pop('positions')
        for key, entry in group['variants'].items():
            duration_median = median(entry.pop('durations_ns'))
            entry['median_verification_ns'] = ratio(duration_median, 1)
            variant, _ = key.split('/')
            entry['construction_total_ns'] = group['mutation_construction_ns'].get(variant, 0)
            if variant == 'legal':
                entry['honest_acquisition_to_verification_ratio'] = ratio(group['honest_acquisition_ns'], entry['verification_total_ns'])
            else:
                # The same acquisition is a prerequisite scenario, not twelve new
                # independent producer samples and not a from-zero forgery omission.
                entry['first_construction_including_honest_acquisition_ns'] = group['honest_acquisition_ns'] + entry['construction_total_ns']
                entry['rejection_to_first_construction_ratio'] = ratio(entry['verification_total_ns'],
                    entry['first_construction_including_honest_acquisition_ns'])
                entry['rejection_to_existing_proof_mutation_ratio'] = ratio(entry['verification_total_ns'], entry['construction_total_ns'])
        for variant in VARIANTS:
            baseline = group['variants'].get(variant + '/production-full-limb')
            if baseline:
                for kernel in KERNELS:
                    entry = group['variants'].get(variant + '/' + kernel)
                    if entry:
                        entry['kernel_to_production_total_ratio'] = ratio(entry['verification_total_ns'], baseline['verification_total_ns'])
        output_groups.append({'class': class_name, 'target': target, 'complete_balanced_group': complete, **group})
    return {'schema': 'pon-work-rejection-summary-v2', 'raw_schema': SCHEMA,
        'cohorts': len(expected_keys), 'timed_verifications': measured,
        'independent_winning_transcript_replays': independent_replays,
        'projection_sha256': projection_sha256(raw), 'groups': output_groups,
        'clock': 'monotonic wall nanoseconds, not CPU or energy accounting',
        'honest_cost_scope': 'one actual material/task/prepared setup per flow; all proof/ticket attempts and recording overhead charged in search wall',
        'mutation_cost_scope': 'clone and mutation of an already acquired complete honest winner; first-construction denominator includes that acquisition',
        'repeated_proof_scope': 'four kernel timings share each exact proof; same-winner repeated network submission and cross-challenge reuse are not measured',
        'probe_scope': 'all timed arms complete before separate actual-result/progress probes; probes are not timed verification observations',
        'independent_scope': 'full scalar transcript replay for every honest winner; all failed proof bytes/tickets checked, failed transcripts are not independently replayed',
        'ratio_definition': 'sum of actual within-class/target costs; kernels are compared on identical complete proof cases; no missing failures or synthetic amortization',
        **{flag: False for flag in FALSE_FLAGS}}


def git(*args: str) -> str:
    return subprocess.check_output(['git', '--no-replace-objects', *args], cwd=ROOT, text=True).strip()


def source_inventory(paths: set[str]) -> set[str]:
    require(SOURCE_PATHS <= paths, 'collector, oracle and source configuration inputs must be retained')
    return {p for p in paths if p.startswith('trillionnium/') and not p.endswith('.md')} | SOURCE_PATHS


def current_inputs() -> dict[str, str]:
    paths = source_inventory(set(git('ls-files').splitlines()))
    return {p: file_digest(ROOT / p) for p in sorted(paths)}


def write_new(path: Path, raw: bytes) -> None:
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def build_command(architecture: str) -> list[str]:
    return ['cargo', '+1.95.0', 'build', '--locked', '--release', '--manifest-path',
            'trillionnium/Cargo.toml', '--target', ARCHITECTURES[architecture]['target'],
            '-p', 'trnm-crypto-primitives', '--example', EXAMPLE]


def capture(command: list[str], output: Path, stem: str, timeout: int, *, stdout_limit: int = 8 * 1024 * 1024) -> dict:
    """Use the existing native pipe owner, not a second file-polling supervisor.

    These commands require no stdin. Preserve separate exact output streams,
    original limits and successful receipt fields. A failed exchange retains
    bounded prefixes and its actual cleanup exit; exit zero alone is not success.
    The shared owner's failure cleanup uses its existing POSIX group kill/reap.
    This bounds retained output, not child RSS, arbitrary files or physical time.
    """
    started = time.monotonic_ns()
    result = {'command': command, 'cwd': str(ROOT), 'exit_code': None, 'timed_out': False,
        'output_limit_exceeded': False, 'timeout_seconds': timeout, 'stdout_limit_bytes': stdout_limit,
        'stderr_limit_bytes': 8 * 1024 * 1024, 'stdout': stem + '.stdout', 'stderr': stem + '.stderr'}
    # Reserve BOTH create-new destinations before starting the original command.
    # The child receives pipes, never these files, so a burst cannot overshoot
    # their byte limits between polls or keep writing after a successful return.
    with (output / result['stdout']).open('xb') as stdout, (output / result['stderr']).open('xb') as stderr:
        out, err = b'', b''
        try:
            observed = run_bounded(command, b'', timeout=timeout, stdout_limit=stdout_limit,
                                   stderr_limit=result['stderr_limit_bytes'], cwd=ROOT)
        except ProcessFailure as error:
            out, err = error.stdout, error.stderr
            result.update(exit_code=error.returncode,
                timed_out=str(error) == 'NATIVE_EXECUTOR_TIMEOUT',
                output_limit_exceeded=error.stdout_truncated or error.stderr_truncated,
                exchange_error=str(error), stdin_written_bytes=error.stdin_written,
                stdout_truncated=error.stdout_truncated, stderr_truncated=error.stderr_truncated)
        except ValueError as error:
            # The shared owner validates before spawn and reports unavailable
            # executables without claiming that a child ever ran.
            result['launch_error'] = str(error)
        else:
            result['exit_code'] = observed.returncode
            out, err = observed.stdout, observed.stderr
        stdout.write(out)
        stderr.write(err)
        stdout.flush()
        stderr.flush()
        result['stdout_bytes'] = os.fstat(stdout.fileno()).st_size
        result['stderr_bytes'] = os.fstat(stderr.fileno()).st_size
    result['elapsed_ns'] = time.monotonic_ns() - started
    return result


def checked_capture(command: list[str], output: Path, stem: str, timeout: int, observations: list[dict], **kwargs) -> dict:
    observed = capture(command, output, stem, timeout, **kwargs)
    observations.append(observed)
    require(type(observed['exit_code']) is int and observed['exit_code'] == 0 and
            observed['timed_out'] is False and observed['output_limit_exceeded'] is False and 'launch_error' not in observed and 'exchange_error' not in observed,
            stem + ' failed; original stdout/stderr and failure status retained')
    return observed


def collect(output: Path, *, local: bool = False) -> dict:
    output = output.resolve()
    require(not output.is_relative_to(ROOT), 'new output directory must be outside the checkout')
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    observed = []
    report = {'schema': 'pon-work-rejection-execution-v2', 'result': 'FAIL',
        'observed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'execution_context': 'local-native-preflight' if local else 'github-hosted',
        'runner_context': {key: os.environ.get(key) for key in RUNNER_FIELDS},
        'uname': dict(zip(('system', 'node', 'release', 'version', 'machine', 'processor'), platform.uname())),
        'compiler_channel': '1.95.0', 'build_profile': 'release', 'observations': observed,
        'source_before': None, 'source_after': None, 'input_sha256': {}, **{flag: False for flag in FALSE_FLAGS}}
    binary = None
    try:
        report['source_before'] = source()
        require(report['source_before']['source_state'] == 'committed-clean', 'measurement requires complete clean committed source')
        report['input_sha256'] = current_inputs()
        machine = report['uname']['machine']
        candidates = [name for name, spec in ARCHITECTURES.items() if spec['machine'] == machine]
        require(report['uname']['system'] == 'Linux' and len(candidates) == 1, 'observed native Linux architecture')
        architecture = report['architecture'] = candidates[0]
        spec = ARCHITECTURES[architecture]
        report['target'] = spec['target']
        if not local:
            context = report['runner_context']
            require(context['GITHUB_ACTIONS'] == 'true' and context['RUNNER_ARCH'] == spec['runner_arch'] and
                    context['RUNNER_OS'] == 'Linux' and context['TRNM_COST_RUNNER_LABEL'] == spec['runner'],
                    'actual hosted runner must agree with observed native machine')
            require(isinstance(context['GITHUB_RUN_ID'], str) and context['GITHUB_RUN_ID'].isdigit() and
                    int(context['GITHUB_RUN_ID']) > 0 and isinstance(context['GITHUB_RUN_ATTEMPT'], str) and
                    context['GITHUB_RUN_ATTEMPT'].isdigit() and int(context['GITHUB_RUN_ATTEMPT']) > 0,
                    'actual hosted run identity')
        overrides = {key: value for key, value in os.environ.items() if value and (
            key in {'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER',
                    'RUSTC', 'RUSTC_BOOTSTRAP', 'CARGO_BUILD_RUSTFLAGS', 'CARGO_BUILD_RUSTC',
                    'CARGO_BUILD_RUSTC_WRAPPER', 'CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER'} or
            key.startswith('CARGO_PROFILE_RELEASE_') or key.startswith('CARGO_TARGET_') and key != 'CARGO_TARGET_DIR')}
        report['build_environment_overrides'] = overrides
        require(not overrides, 'compiler/profile/target overrides change the measured build contract')
        for command, stem in ((['uname', '-a'], 'uname'), (['rustc', '+1.95.0', '-vV'], 'rustc'),
                              (['cargo', '+1.95.0', '--version'], 'cargo')):
            checked_capture(command, output, stem, REJECTION_IDENTITY_TIMEOUT_SECONDS, observed)
        compiler = (output / 'rustc.stdout').read_text()
        require('\nrelease: 1.95.0\n' in compiler and '\nhost: ' + spec['target'] + '\n' in compiler,
                'actual compiler release and host match pinned native target')
        require((output / 'cargo.stdout').read_text().startswith('cargo 1.95.0 '), 'actual pinned Cargo release')
        shutil.copyfile('/proc/cpuinfo', output / 'cpuinfo.txt')
        checked_capture(build_command(architecture), output, 'build', REJECTION_BUILD_TIMEOUT_SECONDS, observed)
        target_dir = Path(os.environ.get('CARGO_TARGET_DIR', ROOT / 'trillionnium/target')).resolve()
        binary = target_dir / spec['target'] / 'release/examples' / EXAMPLE
        report['binary_elf_machine'] = elf_machine(binary)
        require(report['binary_elf_machine'] == spec['elf_machine'], 'native executable architecture')
        report['binary_sha256_before'] = file_digest(binary)
        shutil.copyfile(binary, output / EXAMPLE)
        checked_capture([str(binary)], output, 'native', REJECTION_CAMPAIGN_TIMEOUT_SECONDS,
                        observed, stdout_limit=RAW_LIMIT)
        raw = load(output / 'native.stdout')
        summary = summarize(raw)
        write_new(output / 'summary.json', encoded(summary))
        report['result'] = 'PASS'
    except (OSError, ValueError, KeyError, TypeError, IndexError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    finally:
        try:
            report['source_after'] = source()
            require(report['source_before'] == report['source_after'] and current_inputs() == report['input_sha256'],
                    'source changed during actual measurement')
            if binary is not None:
                report['binary_sha256_after'] = file_digest(binary)
                require(report['binary_sha256_before'] == report['binary_sha256_after'], 'measured executable changed')
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            report['result'] = 'FAIL'
            report['final_identity_error'] = str(error)
        report['artifact_sha256'] = {p.name: file_digest(p) for p in sorted(output.iterdir()) if p.is_file()}
        write_new(output / 'manifest.json', encoded(report))
    require(report['result'] == 'PASS', report.get('error', report.get('final_identity_error', 'measurement failed')))
    return {'result': 'PASS', 'receipt': str(output), 'architecture': report['architecture'],
            'source': report['source_before'], 'binary_sha256': report['binary_sha256_after'],
            'summary': {'cohorts': summary['cohorts'], 'timed_verifications': summary['timed_verifications']}}


def verify(output: Path, *, require_current: bool = True) -> dict:
    output = output.resolve()
    record = load(output / 'manifest.json')
    exact(record, {'schema', 'result', 'observed_at_utc', 'execution_context', 'runner_context', 'uname',
        'compiler_channel', 'build_profile', 'observations', 'source_before', 'source_after', 'input_sha256',
        'architecture', 'target', 'build_environment_overrides', 'binary_elf_machine',
        'binary_sha256_before', 'binary_sha256_after', 'artifact_sha256', *FALSE_FLAGS}, 'successful execution receipt')
    require(record.get('schema') == 'pon-work-rejection-execution-v2' and record.get('result') == 'PASS',
            'successful actual collection receipt required')
    timestamp = datetime.datetime.fromisoformat(record['observed_at_utc'])
    require(timestamp.utcoffset() == datetime.timedelta(0), 'actual UTC observation timestamp')
    for flag in FALSE_FLAGS: require(record.get(flag) is False, 'receipt acceptance ' + flag)
    required = {stem + suffix for stem in ('uname', 'rustc', 'cargo', 'build', 'native') for suffix in ('.stdout', '.stderr')}
    required |= {EXAMPLE, 'cpuinfo.txt', 'summary.json'}
    require(type(record.get('artifact_sha256')) is dict and set(record['artifact_sha256']) == required,
            'complete original binary/log/raw/summary inventory')
    require({p.name for p in output.iterdir()} == required | {'manifest.json'}, 'no unrecorded collection artifact')
    for name, expected in record['artifact_sha256'].items():
        path = output / name
        require(path.is_file() and not path.is_symlink() and file_digest(path) == hash_text(expected, name),
                'retained original artifact changed ' + name)
    identity = record['source_before']
    require(identity == record['source_after'] and identity['source_state'] == 'committed-clean' and
            identity['tracked_worktree_verified'] is True, 'complete unchanged source observation')
    commit = identity['commit']
    require(type(commit) is str and re.fullmatch('[0-9a-f]{40}', commit) is not None and
            git('rev-parse', commit + '^{tree}') == identity['tree'], 'recorded exact source commit/tree')
    inventory = source_inventory(set(git('ls-tree', '-r', '--name-only', commit).splitlines()))
    require(set(record['input_sha256']) == inventory, 'complete measured source inventory')
    original = source_bytes(ROOT, commit, sorted(inventory))
    require({name: digest(raw) for name, raw in original.items()} == record['input_sha256'], 'measured input bytes match Git source')
    architecture = record['architecture']
    require(architecture in ARCHITECTURES, 'native architecture name')
    spec = ARCHITECTURES[architecture]
    require(record['uname']['system'] == 'Linux' and record['uname']['machine'] == spec['machine'] and
            record['target'] == spec['target'] and record['compiler_channel'] == '1.95.0' and
            record['build_profile'] == 'release' and record['build_environment_overrides'] == {}, 'native build contract')
    require(elf_machine(output / EXAMPLE) == record['binary_elf_machine'] == spec['elf_machine'] and
            record['binary_sha256_before'] == record['binary_sha256_after'] == file_digest(output / EXAMPLE),
            'retained measured executable identity')
    compiler = (output / 'rustc.stdout').read_text()
    require('\nrelease: 1.95.0\n' in compiler and '\nhost: ' + spec['target'] + '\n' in compiler and
            (output / 'cargo.stdout').read_text().startswith('cargo 1.95.0 '), 'actual toolchain output')
    commands = [(['uname', '-a'], 'uname', REJECTION_IDENTITY_TIMEOUT_SECONDS),
                (['rustc', '+1.95.0', '-vV'], 'rustc', REJECTION_IDENTITY_TIMEOUT_SECONDS),
                (['cargo', '+1.95.0', '--version'], 'cargo', REJECTION_IDENTITY_TIMEOUT_SECONDS),
                (build_command(architecture), 'build', REJECTION_BUILD_TIMEOUT_SECONDS),
                (None, 'native', REJECTION_CAMPAIGN_TIMEOUT_SECONDS)]
    require(type(record['observations']) is list and len(record['observations']) == len(commands), 'five actual captured commands')
    observed_roots = {v.get('cwd') for v in record['observations'] if type(v) is dict and type(v.get('cwd')) is str}
    require(len(observed_roots) == 1 and Path(next(iter(observed_roots))).is_absolute(), 'one actual source working directory')
    for observed, (command, stem, timeout) in zip(record['observations'], commands):
        exact(observed, {'command', 'cwd', 'exit_code', 'timed_out', 'output_limit_exceeded', 'timeout_seconds',
            'stdout_limit_bytes', 'stderr_limit_bytes', 'stdout', 'stderr', 'stdout_bytes', 'stderr_bytes', 'elapsed_ns'}, 'actual captured command')
        require(type(observed['cwd']) is str and observed['cwd'] in observed_roots, 'all command source directories remain bound')
        require(type(observed['exit_code']) is int and observed['exit_code'] == 0 and observed['timed_out'] is False and
                observed['output_limit_exceeded'] is False, 'failed/timeout/launch fields cannot be relabeled success')
        require(observed['timeout_seconds'] == timeout and type(observed['timeout_seconds']) is int,
                'actual command timeout contract')
        if command is None:
            require(type(observed['command']) is list and len(observed['command']) == 1 and
                    Path(observed['command'][0]).name == EXAMPLE and
                    Path(observed['command'][0]).parts[-4:-1] == (spec['target'], 'release', 'examples'), 'actual native measured command')
        else:
            require(observed['command'] == command, 'actual tool/build command')
        for stream in ('stdout', 'stderr'):
            require(observed[stream] == stem + '.' + stream, 'actual original log binding')
            limit = RAW_LIMIT if stem == 'native' and stream == 'stdout' else 8 * 1024 * 1024
            require(integer(observed[stream + '_limit_bytes'], 'output cap') == limit, 'output cap contract')
            require(integer(observed[stream + '_bytes'], 'observed output bytes', maximum=limit) ==
                    (output / observed[stream]).stat().st_size, 'actual output byte count')
        integer(observed['elapsed_ns'], 'capture elapsed', minimum=1)
    context = record['runner_context']
    exact(context, set(RUNNER_FIELDS), 'original runner context')
    require(record['execution_context'] in ('github-hosted', 'local-native-preflight'), 'execution context identity')
    if record['execution_context'] == 'github-hosted':
        require(context['GITHUB_ACTIONS'] == 'true' and context['RUNNER_OS'] == 'Linux' and
                context['RUNNER_ARCH'] == spec['runner_arch'] and context['TRNM_COST_RUNNER_LABEL'] == spec['runner'],
                'hosted runner contradicts native observation')
        for name in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'):
            require(type(context[name]) is str and re.fullmatch('[1-9][0-9]*', context[name]) is not None,
                    'actual hosted workflow identity')
    summary = summarize(load(output / 'native.stdout'))
    require(encoded(summary) == (output / 'summary.json').read_bytes(), 'summary must derive exactly from retained raw samples')
    matches = current_inputs() == record['input_sha256']
    if require_current: require(matches, 'measured inputs changed; historical result is retained, not relabeled current')
    return {'result': 'PASS', 'source_commit': commit, 'source_tree': identity['tree'], 'architecture': architecture,
        'runner_context': context, 'execution_context': record['execution_context'], 'input_sha256': record['input_sha256'],
        'current_measured_inputs_match': matches, 'experiment_reexecuted_by_verifier': False,
        'summary': summary, **{flag: False for flag in FALSE_FLAGS}}


def compare(left: Path, right: Path, output: Path, *, expected_source: str | None = None,
            expected_run: str | None = None, expected_attempt: int | None = None) -> dict:
    output = output.resolve()
    require(not output.is_relative_to(ROOT), 'comparison receipt outside checkout')
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = {'schema': 'pon-work-rejection-comparison-v2', 'result': 'FAIL', 'inputs': [str(left), str(right)],
              **{flag: False for flag in FALSE_FLAGS}}
    try:
        values = [verify(left), verify(right)]
        require({v['architecture'] for v in values} == {'x64', 'arm64'}, 'two distinct actual native architectures')
        require(values[0]['source_commit'] == values[1]['source_commit'] and
                values[0]['source_tree'] == values[1]['source_tree'] and values[0]['input_sha256'] == values[1]['input_sha256'],
                'same complete source on both architectures')
        require(values[0]['summary']['projection_sha256'] == values[1]['summary']['projection_sha256'],
                'same task, complete proof/ticket/search, actual errors, progress and invocation-order streams')
        if any(v is not None for v in (expected_source, expected_run, expected_attempt)):
            require(type(expected_source) is str and re.fullmatch('[0-9a-f]{40}', expected_source) is not None and
                    type(expected_run) is str and re.fullmatch('[1-9][0-9]*', expected_run) is not None and
                    type(expected_attempt) is int and expected_attempt > 0, 'complete expected hosted source/run/attempt')
            for value in values:
                context = value['runner_context']
                require(value['execution_context'] == 'github-hosted' and value['source_commit'] == expected_source and
                        context['GITHUB_RUN_ID'] == expected_run and context['GITHUB_RUN_ATTEMPT'] == str(expected_attempt) and
                        context['GITHUB_REPOSITORY'] == 'TrillionniumFoundation/Trillionnium-Chain' and
                        context['GITHUB_JOB'] == 'cross-arch-cost', 'actual same-run hosted artifacts, not env-declared cross compilation')
        report.update(result='PASS', source_commit=values[0]['source_commit'], source_tree=values[0]['source_tree'],
            projection_sha256=values[0]['summary']['projection_sha256'],
            expected_source=expected_source, expected_run=expected_run, expected_attempt=expected_attempt,
            by_architecture={v['architecture']: v['summary'] for v in values},
            scope='deterministic stream equivalence and separate observed hardware costs; no pooled speed claim')
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    write_new(output / 'comparison.json', encoded(report))
    require(report['result'] == 'PASS', report.get('error', 'comparison failed'))
    return {'result': 'PASS', 'receipt': str(output), 'source_commit': report['source_commit'],
            'projection_sha256': report['projection_sha256']}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--run', action='store_true')
    mode.add_argument('--verify', type=Path)
    mode.add_argument('--input', type=Path)
    mode.add_argument('--compare', nargs=2, type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--local', action='store_true', help='actual local native observation, not hosted comparison authority')
    parser.add_argument('--historical', action='store_true', help='verify retained earlier inputs without a current applicability claim')
    parser.add_argument('--expected-source')
    parser.add_argument('--expected-run')
    parser.add_argument('--expected-attempt', type=int)
    args = parser.parse_args()
    try:
        require(not args.local or args.run, '--local applies only to a newly executed local collection')
        require(not args.historical or args.verify is not None, '--historical applies only to retained verification')
        require(args.out is None or args.run or args.compare is not None, '--out applies only to fresh collection/comparison')
        require(args.compare is not None or all(v is None for v in
                (args.expected_source, args.expected_run, args.expected_attempt)),
                'expected hosted context applies only to artifact comparison')
        if args.run:
            require(args.out is not None and not args.historical, '--run requires fresh --out')
            result = collect(args.out, local=args.local)
        elif args.verify:
            result = verify(args.verify, require_current=not args.historical)
            result.pop('input_sha256')
            result.pop('summary')
        elif args.compare:
            require(args.out is not None and not args.local and not args.historical, '--compare requires fresh --out')
            result = compare(*args.compare, args.out, expected_source=args.expected_source,
                             expected_run=args.expected_run, expected_attempt=args.expected_attempt)
        else:
            result = summarize(load(args.input))
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({'result': 'FAIL', 'error': str(error), **{flag: False for flag in FALSE_FLAGS}}, sort_keys=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
