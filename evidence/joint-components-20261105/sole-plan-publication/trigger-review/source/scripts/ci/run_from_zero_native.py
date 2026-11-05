#!/usr/bin/env python3
"""Build and execute exact from-zero tests inside the existing protocol lane.

Keep failed builds, named nonzero test executions, full reports and the actual
binary. No old artifact can satisfy this source build, and no extra CI lane is
introduced. Process CPU encloses the entire test, not a per-actor cost allocation.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

from check_required_native_test import validate
from replay_pinned_native import digest, json_load, require, run_child
from verify_ci_source import verify as verify_source

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from pon_public_v3_phase_read import (
    validate_history_import_observation, validate_v4_record,
)
# Reuse the existing wire owner for bounded metadata consistency. This reader
# does not verify work, signatures, state transitions or operator independence.
sys.path.insert(0, str(ROOT / 'formal/pon-nakamoto-v1'))
from contract_wire import H, header_decode, tx_decode
TARGET = 'public_v3_from_zero'
SOURCE = 'trillionnium/crates/trnm-pon-node/tests/' + TARGET + '.rs'
FORMAT_SUPPORT = 'trillionnium/crates/trnm-pon-node/examples/support/w1_from_zero.rs'
FORMAT_TEST_MODULES = ('public_v3_from_zero/fresh_challenge.rs',)
TESTS = (
    'caller_cpu_clock_keeps_missing_overflow_and_wrong_owner_distinct',
    'from_zero_search_preserves_misses_exhaustion_and_full_replay_rejection',
    'four_from_zero_w1_traces_keep_native_state_and_chainwork_unchanged',
    'from_zero_service_shares_cpu_with_honest_work_and_reopened_owner',
    'from_zero_signed_business_reports_confirmation_in_original_pressure_window_against_same_packet_baseline',
)
REPORT_PATHS = {
    'service_report': 'native/report.json',
    'sustained_report': 'native/sustained/report.json',
    'confirmation_report': 'confirmation/report.json',
}


def source_identity() -> dict:
    def git(*args: str) -> str:
        return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()
    head = git('rev-parse', 'HEAD')
    tracked = verify_source('head', head, root=ROOT)
    return {'commit': head, 'tree': git('rev-parse', 'HEAD^{tree}'),
            'tracked_source_identity': tracked,
            'test_sha256': digest((ROOT / SOURCE).read_bytes())}


def native_build_command() -> list[str]:
    """One exact source-build command for CI preparation and original execution."""
    return ['cargo', 'test', '--locked', '--release', '--manifest-path',
            'trillionnium/Cargo.toml', '-p', 'trnm-pon-node', '--test', TARGET,
            '--no-run', '--message-format=json']


def select_binary(lines: list[str]) -> Path:
    paths = []
    for line in lines:
        if not line.startswith('{'):
            continue
        row = json_load(line)
        if row.get('reason') == 'compiler-artifact' and row.get('target', {}).get('name') == TARGET:
            if row.get('profile', {}).get('test') is True and row.get('executable'):
                path = Path(row['executable'])
                require(not path.is_symlink(), 'REGULAR_BINARY_REQUIRED')
                paths.append(path.resolve())
    require(len(paths) == 1, 'EXACT_NEW_NATIVE_TEST_BINARY_REQUIRED')
    return paths[0]



def stage_format_copy(test_source: Path, support_source: Path, out: Path) -> Path:
    """Preserve the original #[path] module layout in a disposable rustfmt copy.

    Retain both the shared support and test-local modules; flattening the test
    or copying only its entry point gives rustfmt a missing-module error.
    This is only diagnostic:
    cargo fmt --check and all real native acceptance gates are unchanged.
    """
    root = out / 'format-copy-source'
    tests = root / 'tests'
    support = root / 'examples' / 'support'
    tests.mkdir(parents=True, exist_ok=True)
    support.mkdir(parents=True, exist_ok=True)
    staged = tests / test_source.name
    shutil.copyfile(test_source, staged)
    shutil.copyfile(support_source, support / support_source.name)
    for relative in FORMAT_TEST_MODULES:
        copied = tests / relative
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(test_source.parent / relative, copied)
    return staged


# Bounded report consistency, not a second W1/state oracle or public qualification.
# The native source fixes two phases with eight constructions and eight probes.
REPORT_LIMIT = 32 * 1024 * 1024


def observer_cpu_scope(captured: dict) -> None:
    """Keep historical dispatch scope distinct from the r11/r12 paid envelope.

    The v3 observer scope alone does not identify a signed resource revision.
    """
    if captured.get('schema') in ('public-v3-local-request-resource-observation-v3',
                                 'public-v3-local-request-resource-observation-v4'):
        require(captured.get('cpu_includes_reactor_authentication_or_response_signing') is True
                and captured.get('cpu_includes_reactor_authentication') is False
                and captured.get('dispatch_cpu_includes_paid_body_decode') is True
                and captured.get('dispatch_cpu_includes_response_signing') is True,
                'OBSERVER_PAID_ENVELOPE_SCOPE')
        if captured['schema'].endswith('-v4'):
            require(all(captured.get(key) is True for key in (
                'phase_parent_links_are_inclusive', 'cpu_wait_is_outside_dispatch',
                'monotonic_epoch_is_observer_local')), 'OBSERVER_V4_INCLUSIVE_SCOPE')
            records = captured.get('records')
            require(isinstance(records, list) and len(records) <= 16384, 'OBSERVER_V4_RECORD_BOUND')
            for record in records:
                validate_v4_record(record)
    else:
        require(captured.get('schema') in ('public-v3-local-request-resource-observation-v1',
                                          'public-v3-local-request-resource-observation-v2')
                and captured.get('cpu_includes_reactor_authentication_or_response_signing') is False,
                'OBSERVER_HISTORICAL_CPU_SCOPE')


def validate_service_report(path: Path) -> dict:
    require(path.is_file() and not path.is_symlink(), 'NATIVE_SERVICE_REPORT_REQUIRED')
    with path.open('rb') as stream:
        raw = stream.read(REPORT_LIMIT + 1)
    require(len(raw) <= REPORT_LIMIT, 'NATIVE_SERVICE_REPORT_LIMIT')
    doc = json_load(raw)
    require(isinstance(doc, dict) and doc.get('schema') == 'public-v3-local-from-zero-service-v2',
            'NATIVE_SERVICE_REPORT_SCHEMA')
    for key in ('network', 'parameters', 'genesis', 'target', 'policy_id'):
        require(isinstance(doc.get(key), str) and re.fullmatch('[0-9a-f]{64}', doc[key]) is not None,
                'NATIVE_SERVICE_CONTEXT')
    for key in ('reopen_state_equal', 'cpu_domain_retained_across_owner_reopen',
                'all_requested_reads_required_on_time', 'finite_target_met'):
        require(doc.get(key) is True, 'NATIVE_SERVICE_TARGET')
    for key in ('budget_depletion_demonstrated', 'public_network_ready', 'independent_accepted',
                'work_profile_qualified', 'resource_fairness_qualified',
                'physical_power_loss', 'production_activation'):
        require(doc.get(key) is False, 'NATIVE_SERVICE_SCOPE_PROMOTION')
    phases = doc.get('phases')
    require(isinstance(phases, list) and len(phases) == 2, 'NATIVE_SERVICE_PHASES')

    def number(value):
        require(type(value) is int and 0 <= value < 1 << 64, 'NATIVE_SERVICE_NUMBER')
        return value

    for index, phase in enumerate(phases):
        require(isinstance(phase, dict) and type(phase.get('phase')) is int
                and phase['phase'] == index, 'NATIVE_SERVICE_PHASES')
        for key in ('complete_denominators', 'attacker_and_client_cpu_known',
                    'no_attack_accepted', 'cpu_measurements_known',
                    'all_started_work_finished', 'full_native_state_equal', 'finite_target_met'):
            require(phase.get(key) is True, 'NATIVE_SERVICE_PHASE_TARGET')
        attacks, reads = phase.get('from_zero'), phase.get('honest_reads')
        require(isinstance(attacks, list) and isinstance(reads, list)
                and len(attacks) == len(reads) == number(phase.get('construction_count')) == 8,
                'NATIVE_SERVICE_DENOMINATORS')
        hits = exhausted = submitted = late = 0
        for row in attacks:
            require(isinstance(row, dict) and isinstance(row.get('construction'), dict),
                    'NATIVE_SERVICE_CONSTRUCTION')
            status = row['construction'].get('status')
            require(status in ('target_hit_unverified', 'exhausted'), 'NATIVE_SERVICE_CONSTRUCTION')
            number(row['construction'].get('attacker_cpu_ns'))
            require('call' in row, 'NATIVE_SERVICE_CONSTRUCTION')
            call = row['call']
            if status == 'exhausted':
                exhausted += 1
                require(call is None, 'NATIVE_SERVICE_EXHAUSTION_DISPATCH')
            else:
                hits += 1
                require(isinstance(call, dict) and call.get('status') != 'ok',
                        'NATIVE_SERVICE_ATTACK_ACCEPTED')
                number(call.get('client_thread_cpu_ns'))
                submitted += 1
                if call.get('status') == 'refused':
                    response = call.get('response')
                    require(isinstance(response, dict) and isinstance(response.get('value'), dict),
                            'NATIVE_SERVICE_RESPONSE')
                    late += response['value'].get('error') == 'WORK:Transcript'
        require((hits, exhausted, submitted, late) == tuple(number(phase.get(key)) for key in (
            'constructed_hits', 'exhausted_searches', 'submitted_attacks', 'late_transcript_rejections'))
                and late > 0, 'NATIVE_SERVICE_DENOMINATORS')
        for call in [*reads, phase.get('honest_submit')]:
            require(isinstance(call, dict) and call.get('status') == 'ok'
                    and call.get('returned_after_deadline') is False, 'NATIVE_SERVICE_HONEST_GAP')
            number(call.get('client_thread_cpu_ns'))
        require(number(phase.get('honest_read_successes')) == 8
                and phase.get('honest_build_error', 'missing') is None, 'NATIVE_SERVICE_HONEST_GAP')
        preparation = number(phase.get('all_preparation_thread_cpu_ns'))
        worker = number(phase.get('attacker_worker_cpu_ns'))
        require(number(phase.get('attacker_preparation_and_worker_cpu_ns')) == preparation + worker,
                'NATIVE_SERVICE_CPU_SUM')
        require('honest_build_aggregate_cpu_ns' in phase and phase['honest_build_aggregate_cpu_ns'] is None
                and phase.get('honest_worker_cpu_measured_by_this_clock') is False,
                'NATIVE_SERVICE_SCOPE_PROMOTION')
        service = phase.get('service')
        require(isinstance(service, dict) and service.get('error', 'missing') is None
                and isinstance(service.get('metrics'), dict), 'NATIVE_SERVICE_OUTCOME')
        metrics = service['metrics']
        started = number(metrics.get('work_started'))
        require(started > late and number(metrics.get('work_finished')) == started
                and number(metrics.get('work_failed')) >= late, 'NATIVE_SERVICE_UNJOINED_WORK')
        work_cpu = number(metrics.get('mutation_full_work_cpu_ns'))
        require(number(metrics.get('mutation_cpu_clock_failures')) == 0 and work_cpu > 0
                and number(metrics.get('mutation_cpu_charged_ns')) >= work_cpu,
                'NATIVE_SERVICE_CPU_SUM')
    return {'sha256': digest(raw), 'schema': doc['schema'], 'phases': len(phases),
            'scope': 'retained finite native report consistency; no independent work or state oracle'}


def validate_sustained_report(path: Path) -> dict:
    """Recompute finite observation consistency, never work/state truth or fairness."""
    require(path.is_file() and not path.is_symlink(), 'SUSTAINED_REPORT_REQUIRED')
    with path.open('rb') as stream:
        raw = stream.read(REPORT_LIMIT + 1)
    require(len(raw) <= REPORT_LIMIT, 'SUSTAINED_REPORT_LIMIT')
    doc = json_load(raw)
    require(isinstance(doc, dict) and doc.get('schema') == 'public-v3-sustained-local-from-zero-v1',
            'SUSTAINED_SCHEMA')

    def number(value):
        require(type(value) is int and 0 <= value < 1 << 64, 'SUSTAINED_NUMBER')
        return value

    def flags(value, yes=(), no=()):
        require(isinstance(value, dict), 'SUSTAINED_OBJECT')
        require(all(value.get(key) is True for key in yes), 'SUSTAINED_TARGET')
        require(all(value.get(key) is False for key in no), 'SUSTAINED_SCOPE')

    def meter(value):
        require(isinstance(value, dict) and value.get('schema') == 'public-v3-local-stored-cpu-budget-v1',
                'SUSTAINED_METER')
        require(type(value.get('stored_credit_ns')) is int
                and -(1 << 127) <= value['stored_credit_ns'] <= 2_000_000_000,
                'SUSTAINED_METER')
        require(number(value.get('in_flight')) <= 2
                and type(value.get('accounting_unavailable')) is bool, 'SUSTAINED_METER')
        require(tuple(number(value.get(key)) for key in (
            'burst_ns', 'refill_ns_per_second', 'start_reserve_ns', 'worker_limit'))
                == (2_000_000_000, 250_000_000, 100_000_000, 2), 'SUSTAINED_POLICY_CHANGED')
        return value['stored_credit_ns']

    def call(value):
        require(isinstance(value, dict) and value.get('status') in ('ok', 'refused', 'error'),
                'SUSTAINED_CALL')
        number(value.get('client_thread_cpu_ns'))
        start, end = number(value.get('started_ns')), number(value.get('ended_ns'))
        require(start <= end and type(value.get('returned_after_deadline')) is bool,
                'SUSTAINED_CALL')
        elapsed = number(value.get('elapsed_wall_ns'))
        require(number(value.get('deadline_ms')) == 2000 and elapsed >= end - start
                and value['returned_after_deadline'] == (elapsed > 2_000_000_000),
                'SUSTAINED_CALL_TIME')
        return value['status'] == 'ok' and value['returned_after_deadline'] is False

    for key in ('network', 'parameters', 'genesis', 'policy_id'):
        require(type(doc.get(key)) is str and re.fullmatch('[0-9a-f]{64}', doc[key]), 'SUSTAINED_CONTEXT')
    flags(doc, ('reopen_state_equal', 'same_stored_cpu_meter_across_reopen', 'finite_service_target_met'),
          ('public_network_ready', 'resource_fairness_qualified', 'work_profile_qualified',
           'production_activation', 'ordinary_hepta_entry', 'independent_accepted', 'physical_power_loss'))
    number(doc.get('reopen_wall_ns'))
    phases = doc.get('phases')
    require(isinstance(phases, list) and len(phases) == 2, 'SUSTAINED_PHASES')
    observations = []
    for index, phase in enumerate(phases):
        flags(phase, ('attempt_caps_not_reached', 'no_attack_accepted', 'accounting_closed',
                      'full_native_state_equal', 'service_target_met', 'invariant_target_met'),
              ('public_network_ready', 'resource_fairness_qualified', 'work_profile_qualified',
               'production_activation', 'strongest_honest_producer_used'))
        require(type(phase.get('phase')) is int and phase['phase'] == index, 'SUSTAINED_PHASES')
        require(phase.get('target') == '7f' + 'ff' * 31, 'SUSTAINED_CONTEXT')
        require('client_confirmed_transactions' in phase and phase['client_confirmed_transactions'] is None
                and 'honest_build_aggregate_cpu_ns' in phase and phase['honest_build_aggregate_cpu_ns'] is None,
                'SUSTAINED_SCOPE')
        require(number(phase.get('requested_window_ns')) == 4_000_000_000
                and number(phase.get('traffic_and_join_wall_ns')) >= 4_000_000_000, 'SUSTAINED_WINDOW')
        for key in ('preparation_wall_ns', 'diagnostic_verification_wall_ns', 'reader_cpu_ns',
                    'honest_build_wall_ns', 'honest_build_calling_thread_cpu_ns'):
            number(phase.get(key))
        constructions = phase.get('construction')
        require(isinstance(constructions, list) and len(constructions) == 16, 'SUSTAINED_CONSTRUCTION')
        for item in constructions:
            require(isinstance(item, dict) and item.get('status') in ('target_hit_unverified', 'exhausted'),
                    'SUSTAINED_CONSTRUCTION')
            number(item.get('attacker_cpu_ns'))
            attempts = item.get('attempts')
            require(isinstance(attempts, list) and 0 < len(attempts) <= 4096
                    and number(item.get('attempt_budget')) == 4096, 'SUSTAINED_SEARCH')
            for ordinal, attempt in enumerate(attempts):
                require(isinstance(attempt, dict) and number(attempt.get('nonce')) == ordinal
                        and type(attempt.get('target_hit')) is bool, 'SUSTAINED_SEARCH')
            hit = item['status'] == 'target_hit_unverified'
            require(not any(a['target_hit'] for a in attempts[:-1])
                    and attempts[-1]['target_hit'] == hit, 'SUSTAINED_SEARCH')
            if hit:
                require(number(item.get('winner_nonce')) == len(attempts) - 1
                        and type(item.get('packet')) is str and bool(item['packet']), 'SUSTAINED_SEARCH')
            else:
                require(len(attempts) == 4096 and item.get('winner_nonce', 'missing') is None
                        and item.get('packet', 'missing') is None, 'SUSTAINED_SEARCH')
        workers = phase.get('attacks')
        require(isinstance(workers, list) and len(workers) == 16, 'SUSTAINED_WORKERS')
        worker_cpu, attack_count, late = 0, 0, 0
        for ordinal, worker in enumerate(workers):
            require(isinstance(worker, dict) and number(worker.get('worker')) == ordinal
                    and number(worker.get('attempt_cap')) == 1024, 'SUSTAINED_WORKERS')
            calls = worker.get('calls')
            require(isinstance(calls, list) and 0 < len(calls) < 1024
                    and worker.get('attempt_cap_reached') is False, 'SUSTAINED_CAP')
            worker_cpu += number(worker.get('calling_thread_cpu_ns'))
            for row in calls:
                require(isinstance(row, dict), 'SUSTAINED_CALL')
                packet_index = number(row.get('packet_index'))
                require(packet_index < 16, 'SUSTAINED_CONSTRUCTION')
                if row.get('status') == 'not_submitted_exhausted':
                    require(set(row) == {'status', 'packet_index'}
                            and constructions[packet_index]['status'] == 'exhausted',
                            'SUSTAINED_EXHAUSTED_DISPATCH')
                    # This attempt consumed construction/worker CPU but opened
                    # no connection. Keep it without inventing client timing.
                    continue
                call(row)
                require(row['status'] != 'ok', 'SUSTAINED_ATTACK_ACCEPTED')
                require(constructions[packet_index]['status'] == 'target_hit_unverified',
                        'SUSTAINED_EXHAUSTED_DISPATCH')
                attack_count += 1
                response = row.get('response')
                if response is not None:
                    require(isinstance(response, dict) and isinstance(response.get('value'), dict),
                            'SUSTAINED_CALL')
                    late += response['value'].get('error') == 'WORK:Transcript'
        require(late > 0, 'SUSTAINED_NO_LATE_REJECTION')
        require(number(phase.get('attacker_preparation_plus_workers_cpu_ns'))
                == number(phase.get('preparation_cpu_ns')) + worker_cpu, 'SUSTAINED_CPU_SUM')
        reads, submits = phase.get('honest_reads'), phase.get('honest_submissions')
        require(isinstance(reads, list) and 0 < len(reads) <= 256
                and isinstance(submits, list) and 0 < len(submits) <= 16, 'SUSTAINED_HONEST_COUNT')
        require(all(call(row) for row in reads) and sum(call(row) for row in submits) == 1
                and number(phase.get('reads_on_time')) == len(reads)
                and call(phase.get('post_pressure_head')), 'SUSTAINED_HONEST_GAP')
        meter(phase.get('initial_meter'))
        meter(phase.get('meter_at_traffic_end'))
        samples = phase.get('meter_samples')
        require(isinstance(samples, list) and 0 < len(samples) <= 256, 'SUSTAINED_METER')
        credit = [meter(row.get('meter')) for row in samples]
        elapsed = [number(row.get('elapsed_ns')) for row in samples]
        require(elapsed == sorted(elapsed) and elapsed[-1] <= phase['traffic_and_join_wall_ns'], 'SUSTAINED_WINDOW')
        require(type(phase.get('stored_credit_below_start_reserve_observed')) is bool
                and phase['stored_credit_below_start_reserve_observed'] == any(v < 100_000_000 for v in credit)
                and type(phase.get('negative_stored_credit_observed')) is bool
                and phase['negative_stored_credit_observed'] == any(v < 0 for v in credit), 'SUSTAINED_DEPLETION_CLAIM')
        service = phase.get('service')
        require(isinstance(service, dict) and service.get('error', 'missing') is None, 'SUSTAINED_SERVICE')
        metrics = service.get('metrics')
        require(isinstance(metrics, dict), 'SUSTAINED_SERVICE')
        total = number(metrics.get('mutation_cpu_charged_ns'))
        work = number(metrics.get('mutation_full_work_cpu_ns'))
        rest = number(metrics.get('mutation_dispatch_excluding_work_cpu_ns'))
        require(total == work + rest and work > 0 and number(metrics.get('mutation_cpu_clock_failures')) == 0
                and number(metrics.get('mutation_cpu_in_flight_after_shutdown')) == 0
                and metrics.get('mutation_cpu_unavailable_after_shutdown') is False, 'SUSTAINED_CPU_SUM')
        require(number(metrics.get('work_started')) == number(metrics.get('work_finished'))
                and metrics['work_started'] > late and number(metrics.get('work_failed')) >= late,
                'SUSTAINED_UNJOINED_WORK')
        captured = phase.get('observations')
        flags(captured, ('cpu_intervals_are_nested_not_additive',),
              ('counter_overflow', 'observation_has_consensus_authority'))
        observer_cpu_scope(captured)
        records = captured.get('records')
        require(isinstance(records, list) and len(records) <= number(captured.get('capacity')) == 16384
                and number(captured.get('records_not_retained')) == 0
                and number(captured.get('measurement_failures')) == 0, 'SUSTAINED_CAPTURE')
        connections = attack_count + len(reads) + len(submits) + 1
        require(number(captured.get('accepted_connections_seen')) == len(records) == connections
                and number(metrics.get('accepted_connections')) == connections, 'SUSTAINED_CAPTURE')
        seen = set()
        for record in records:
            flags(record, ('complete', 'connection_closed'), ('observation_failed',))
            connection = number(record.get('connection_id'))
            require(connection not in seen and connection > 0, 'SUSTAINED_CAPTURE')
            seen.add(connection)
            require(record.get('task_created') is False or record.get('task_closed') is True,
                    'SUSTAINED_UNJOINED_WORK')
        observations.append({'phase': index, 'attacks': attack_count, 'late_rejections': late,
            'honest_reads': len(reads), 'honest_submissions': len(submits), 'connections': connections,
            'mutation_cpu_refusals': number(metrics.get('mutation_cpu_refusals')),
            'minimum_sampled_stored_credit_ns': min(credit)})
    meter(doc.get('meter_before_reopen'))
    meter(doc.get('meter_after_reopen'))
    require(doc['meter_before_reopen'] == doc['meter_after_reopen'] == phases[1]['initial_meter'],
            'SUSTAINED_REOPEN')
    return {'sha256': digest(raw), 'schema': doc['schema'], 'phases': observations,
            'scope': 'retained local report consistency; no independent work/state oracle, saturation or fairness qualification'}


class ConfirmationReportChecks:
    """Shared unchanged wire, timing and scalar report predicates."""

    @staticmethod
    def number(value):
        require(type(value) is int and 0 <= value < 1 << 64, 'CONFIRMATION_NUMBER')
        return value

    @staticmethod
    def flags(value, yes=(), no=()):
        require(isinstance(value, dict), 'CONFIRMATION_OBJECT')
        require(all(value.get(key) is True for key in yes), 'CONFIRMATION_TARGET')
        require(all(value.get(key) is False for key in no), 'CONFIRMATION_SCOPE_PROMOTION')

    @staticmethod
    def hexadecimal(value, width=None):
        require(isinstance(value, str) and len(value) % 2 == 0
                and (width is None or len(value) == width * 2)
                and re.fullmatch('[0-9a-f]+', value) is not None, 'CONFIRMATION_HEX')
        return bytes.fromhex(value)

    @staticmethod
    def packet_metadata(value):
        hexadecimal = ConfirmationReportChecks.hexadecimal
        data = hexadecimal(value)
        require(318 + 2 + 49188 <= len(data) <= 1048576, 'CONFIRMATION_PACKET_LIMIT')
        header = header_decode(data[:318])
        count = struct.unpack_from('<H', data, 318)[0]
        require(count <= 256, 'CONFIRMATION_PACKET_LIMIT')
        position, transactions = 320, []
        for _ in range(count):
            require(position + 2 <= len(data), 'CONFIRMATION_PACKET_LIMIT')
            size = struct.unpack_from('<H', data, position)[0]
            position += 2
            require(159 <= size <= 2048 and position + size <= len(data), 'CONFIRMATION_PACKET_LIMIT')
            transaction = data[position:position + size]
            tx_decode(transaction)  # canonical grammar only, never signature authority
            transactions.append(transaction)
            position += size
        require(len(data) - position == 49188 and data[position:position + 4] == b'PNW1',
                'CONFIRMATION_PACKET_LIMIT')
        proof = data[position:]
        require(H('task', proof[4:16388], proof[16388:32772]) == header['work_task'],
                'CONFIRMATION_TASK_BINDING')
        return header, transactions, H('block', data[:318], proof[-32:])

    @staticmethod
    def call(value, window):
        number = ConfirmationReportChecks.number
        require(isinstance(value, dict) and value.get('status') in ('ok', 'refused', 'error'),
                'CONFIRMATION_CALL')
        start, end = number(value.get('started_ns')), number(value.get('ended_ns'))
        elapsed = number(value.get('elapsed_wall_ns'))
        number(value.get('client_thread_cpu_ns'))
        require(start <= end and elapsed >= end - start and number(value.get('deadline_ms')) == 2000
                and value.get('returned_after_deadline') is (elapsed > 2_000_000_000)
                and type(value.get('returned_after_window')) is bool, 'CONFIRMATION_CALL')
        # The recorded flag uses the calling thread after its end stamp. A stamp
        # beyond the window can never be represented as an in-window success.
        require(end < window or value['returned_after_window'] is True, 'CONFIRMATION_LATE_CALL')
        if value['status'] == 'ok':
            require(value.get('error') is None, 'CONFIRMATION_CALL')
        return value['status'] == 'ok' and value['returned_after_deadline'] is False \
            and value['returned_after_window'] is False and end < window

    @staticmethod
    def compact_request(value, request, packet_index):
        number = ConfirmationReportChecks.number
        hexadecimal = ConfirmationReportChecks.hexadecimal
        # compact_pressure_call serializes the request after converting it to a
        # serde_json Value, whose default object map sorts keys. This is the
        # recorded-request domain, not the transport response body digest.
        encoded = json.dumps(request, sort_keys=True, separators=(',', ':')).encode()
        if packet_index is None:
            require(value.get('packet_index', 'missing') is None, 'CONFIRMATION_REQUEST_BINDING')
        else:
            require(number(value.get('packet_index')) == packet_index, 'CONFIRMATION_REQUEST_BINDING')
        require(number(value.get('recorded_request_bytes')) == len(encoded)
                and hexadecimal(value.get('recorded_request_digest'), 32)
                == H('pressure-recorded-request-v1', encoded), 'CONFIRMATION_REQUEST_BINDING')


def validate_confirmation_phases(doc, context, packets, metadata, resolve_attack):
    """Original full phase checks shared by retained and fresh attack sources.

    The caller validates its construction namespace and resolves each exact
    attack packet; all business, timing, overlap, CPU and observer checks
    below remain common. This is consistency, not a native State oracle.
    """
    number = ConfirmationReportChecks.number
    flags = ConfirmationReportChecks.flags
    hexadecimal = ConfirmationReportChecks.hexadecimal
    packet_metadata = ConfirmationReportChecks.packet_metadata
    call = ConfirmationReportChecks.call
    compact_request = ConfirmationReportChecks.compact_request

    parent = metadata[-1][2]
    transaction_id = H('tx-id', metadata[0][1][0]).hex()
    phases = doc.get('phases')
    require(isinstance(phases, list) and len(phases) == 2, 'CONFIRMATION_PHASES')
    observations = []
    for index, phase in enumerate(phases):
        require(isinstance(phase, dict)
                and phase.get('mode') == ('attack-free-baseline' if index == 0 else 'from-zero-pressure')
                and number(phase.get('workers')) == (0 if index == 0 else 16), 'CONFIRMATION_PHASES')
        require(phase.get('target') == doc['target'] and phase.get('task') == doc['task']
                and phase.get('initial_tip') == doc['genesis'], 'CONFIRMATION_CONTEXT')
        flags(phase, yes=('invariant_target_met', 'finite_business_target_met', 'no_attack_accepted',
              'accounting_closed', 'full_native_state_equal', 'receiver_matches_valid_honest_prefix',
              'client_confirmed_before_original_window_end', 'overlap_demonstrated'),
              no=('public_network_ready', 'independent_operator_accepted', 'work_profile_qualified',
                  'resource_fairness_qualified', 'production_activation'))
        window = number(phase.get('requested_window_ns'))
        start, end = number(phase.get('business_started_ns')), number(phase.get('confirmation_ended_ns'))
        require(window == 4_000_000_000 and start < end < window
                and number(phase.get('client_confirmation_latency_ns')) == end - start,
                'CONFIRMATION_OUTSIDE_ORIGINAL_WINDOW')
        require(number(phase.get('client_confirmed_transactions')) == 1, 'CONFIRMATION_BUSINESS_COUNT')
        number(phase.get('independent_replay_and_confirmation_cpu_ns'))
        number(phase.get('independent_replay_and_confirmation_wall_ns'))
        require(phase.get('verification_errors') == [], 'CONFIRMATION_VERIFICATION_ERRORS')
        confirmed = phase.get('independent_client_confirmation')
        flags(confirmed, yes=('confirmed',), no=('reorged', 'finalized', 'execution_authority'))
        require(all(confirmed.get(key) == doc[key] for key in ('network', 'parameters', 'genesis'))
                and confirmed.get('transaction') == transaction_id
                and confirmed.get('included_block') == metadata[0][2].hex()
                and confirmed.get('observed_tip') == metadata[-1][2].hex()
                and number(confirmed.get('included_height')) == 1
                and number(confirmed.get('observed_height')) == 7
                and number(confirmed.get('depth')) == 6, 'CONFIRMATION_NATIVE_OBSERVATION')
        required = (6 * ((1 << 256) // (int.from_bytes(context['target'], 'big') + 1))).to_bytes(64, 'big')
        require(hexadecimal(confirmed.get('required_work_delta'), 64) == required
                and hexadecimal(confirmed.get('work_delta'), 64) == required,
                'CONFIRMATION_NATIVE_OBSERVATION')
        submissions = phase.get('honest_submissions')
        histories = phase.get('honest_history')
        require(isinstance(submissions, list) and 7 <= len(submissions) <= 64
                and isinstance(histories, list) and 1 <= len(histories) <= 16, 'CONFIRMATION_CALLS_REQUIRED')
        successful, previous_end, next_packet = [], start, 0
        for row in submissions:
            on_time = call(row, window)
            require(previous_end <= row['started_ns'] <= row['ended_ns'] <= end,
                    'CONFIRMATION_BUSINESS_CHRONOLOGY')
            require(next_packet < len(packets) and number(row.get('height')) == next_packet + 1,
                    'CONFIRMATION_SIGNED_SUBMISSIONS')
            compact_request(row, {'op': 'submit', 'packet': packets[next_packet]}, next_packet)
            previous_end = row['ended_ns']
            if on_time:
                successful.append(row)
                next_packet += 1
        require([row.get('height') for row in successful] == list(range(1, 8)), 'CONFIRMATION_SIGNED_SUBMISSIONS')
        imported, after = [], doc['genesis']
        # Independently bind optional CPU observations to the exact preserved
        # History call and canonical next cursor, not to a report summary.
        expected_replays = []
        for history_call_index, row in enumerate(histories):
            on_time = call(row, window)
            require(previous_end <= row['started_ns'] <= row['ended_ns'] <= end,
                    'CONFIRMATION_BUSINESS_CHRONOLOGY')
            require(row.get('request') == {'op': 'history', 'tip': parent.hex(), 'after': after},
                    'CONFIRMATION_REQUEST_BINDING')
            previous_end = row['ended_ns']
            if not on_time:
                continue
            response = row.get('response')
            require(isinstance(response, dict), 'CONFIRMATION_HISTORY_CONTEXT')
            page = response.get('value')
            require(isinstance(page, dict) and page.get('schema') == 'pon-native-history-v1'
                    and page.get('after') == after and page.get('tip') == parent.hex()
                    and all(page.get(key) == doc[key] for key in ('network', 'parameters', 'genesis')),
                    'CONFIRMATION_HISTORY_CONTEXT')
            chunk = page.get('packets')
            require(isinstance(chunk, list) and chunk and len(chunk) <= 16, 'CONFIRMATION_HISTORY_PACKETS')
            previous_after = after
            imported.extend(chunk)
            after = packet_metadata(chunk[-1])[2].hex()
            require(page.get('next') == after and page.get('complete') is (after == parent.hex()),
                    'CONFIRMATION_HISTORY_CONTEXT')
            expected_replays.append((history_call_index, row['ended_ns'], previous_after, after))
        require(imported == packets and after == parent.hex(), 'CONFIRMATION_HISTORY_PACKETS')
        stages = phase.get('independent_history_page_replay')
        require(isinstance(stages, list) and len(stages) == len(expected_replays),
                'CONFIRMATION_REPLAY_STAGES')
        previous_replay_end = 0
        measured_page_cpu = 0
        for stage, (call_index, response_end, prior, next_after) in zip(stages, expected_replays):
            require(isinstance(stage, dict) and number(stage.get('history_call_index')) == call_index
                    and number(stage.get('history_request_ended_ns')) == response_end
                    and stage.get('prior_after') == prior and stage.get('next_after') == next_after
                    and stage.get('replay_accepted') is True,
                    'CONFIRMATION_REPLAY_BINDING')
            started = number(stage.get('replay_started_ns'))
            ended = number(stage.get('replay_ended_ns'))
            require(response_end <= started <= ended < window and previous_replay_end <= started
                    and number(stage.get('replay_wall_ns')) == ended - started,
                    'CONFIRMATION_REPLAY_TIMELINE')
            if call_index + 1 < len(histories):
                require(ended <= number(histories[call_index + 1].get('started_ns')),
                        'CONFIRMATION_REPLAY_TIMELINE')
            previous_replay_end = ended
            cpu = stage.get('replay_thread_cpu_ns')
            if cpu is not None:
                measured_page_cpu += number(cpu)
            require(stage.get('clock_scope') ==
                    'independent verifier caller thread; wall spans all waits, CPU only this thread',
                    'CONFIRMATION_REPLAY_SCOPE')
            if 'native_import_observation' in stage:
                native_observation = stage['native_import_observation']
                validate_history_import_observation(native_observation)
                if native_observation['measurement_failures'] == 0:
                    imported_packets = histories[call_index]['response']['value']['packets']
                    native_span = next(row for row in native_observation['phases']
                                       if row['phase'] == 'history_import')
                    require(native_observation['tip'] == list(parent)
                            and native_observation['after'] == list(bytes.fromhex(prior))
                            and native_observation['supplied_packets'] == len(imported_packets)
                            and native_span['completed'] and native_span['accepted'] is True
                            and [row['packet_id'] for row in native_observation['packets']]
                                == [list(packet_metadata(packet)[2]) for packet in imported_packets],
                            'CONFIRMATION_NATIVE_IMPORT_BINDING')
        final = phase.get('independent_final_confirmation_stage')
        require(isinstance(final, dict) and final.get('observation_returned') is True
                and final.get('clock_scope') ==
                'independent verifier caller thread; no consensus/host time claim',
                'CONFIRMATION_REPLAY_FINAL')
        final_start = number(final.get('confirmation_started_ns'))
        final_end = number(final.get('confirmation_ended_ns'))
        require(previous_replay_end <= final_start <= final_end <= end
                and number(final.get('confirmation_wall_ns')) == final_end - final_start,
                'CONFIRMATION_REPLAY_TIMELINE')
        final_cpu = final.get('confirmation_thread_cpu_ns')
        if final_cpu is not None:
            measured_page_cpu += number(final_cpu)
        total_replay_cpu = phase.get('independent_replay_and_confirmation_cpu_ns')
        if total_replay_cpu is not None:
            require(measured_page_cpu <= number(total_replay_cpu), 'CONFIRMATION_REPLAY_CPU_SCOPE')
        require(number(phase.get('independent_replay_and_confirmation_wall_ns'))
                >= final_end - number(stages[0].get('replay_started_ns')),
                'CONFIRMATION_REPLAY_TIMELINE')
        workers = phase.get('attacks')
        require(isinstance(workers, list) and len(workers) == phase['workers'], 'CONFIRMATION_ATTACKS')
        attack_calls, worker_cpu = [], 0
        for worker_index, worker in enumerate(workers):
            require(isinstance(worker, dict) and number(worker.get('worker')) == worker_index
                    and worker.get('attempt_cap_reached') is False,
                    'CONFIRMATION_ATTACKS')
            worker_cpu += number(worker.get('calling_thread_cpu_ns'))
            rows = worker.get('calls')
            require(isinstance(rows, list) and len(rows) < 1024, 'CONFIRMATION_ATTACKS')
            previous_end = 0
            for attempt_index, row in enumerate(rows):
                require(isinstance(row, dict), 'CONFIRMATION_ATTACKS')
                construction, packet_index = resolve_attack(worker_index, attempt_index, row)
                if row.get('status') == 'not_submitted_exhausted':
                    require(construction['status'] == 'exhausted', 'CONFIRMATION_CONSTRUCTIONS')
                    continue
                call(row, window)
                require(construction['status'] == 'target_hit_unverified', 'CONFIRMATION_CONSTRUCTIONS')
                compact_request(row, {'op': 'submit', 'packet': construction['packet']}, packet_index)
                require(previous_end <= row['started_ns'], 'CONFIRMATION_ATTACK_CHRONOLOGY')
                previous_end = row['ended_ns']
                require(row['status'] != 'ok', 'CONFIRMATION_ATTACK_ACCEPTED')
                attack_calls.append(row)
        require(number(phase.get('attacker_workers_cpu_ns')) == worker_cpu, 'CONFIRMATION_CPU_SUM')
        overlapping = sum(row['started_ns'] < end and row['ended_ns'] > start for row in attack_calls)
        require(number(phase.get('overlapping_false_calls')) == overlapping, 'CONFIRMATION_NO_OVERLAP')
        before = number(phase.get('completed_false_calls_before_business'))
        during = number(phase.get('completed_false_calls_at_confirmation'))
        # The pre-business atomic counter is sampled before the business stamp,
        # and a call's end stamp precedes its counter increment. Its value can
        # lag the retained end stamps but cannot count a later call. The other
        # counter is sampled after the confirmation stamp: no equality to that
        # timestamp is inferred here.
        require(before <= sum(row['ended_ns'] <= start for row in attack_calls),
                'CONFIRMATION_COMPLETION_COUNTER')
        require((not index and before == during == overlapping == 0) or
                (index and overlapping > 0 and 0 < before < during <= len(attack_calls)),
                'CONFIRMATION_NO_OVERLAP')
        heads = phase.get('honest_heads')
        require(isinstance(heads, list) and 0 < len(heads) <= 256, 'CONFIRMATION_HEADS')
        successful_heads, previous_end = [], 0
        for row in heads:
            on_time = call(row, window)
            compact_request(row, {'op': 'head'}, None)
            require(previous_end <= row['started_ns'], 'CONFIRMATION_HEAD_CHRONOLOGY')
            previous_end = row['ended_ns']
            if on_time:
                successful_heads.append(row)
        require(number(phase.get('honest_head_successes_in_window')) == len(successful_heads),
                'CONFIRMATION_HEADS')
        previous, maximum = 0, 0
        for row in heads:
            if row['status'] == 'ok' and row['returned_after_window'] is False:
                maximum = max(maximum, row['ended_ns'] - previous)
                previous = row['ended_ns']
        maximum = max(maximum, window - min(previous, window))
        require(number(phase.get('maximum_honest_head_gap_ns')) == maximum, 'CONFIRMATION_HEAD_GAP')
        service = phase.get('service')
        require(isinstance(service, dict) and service.get('error', 'missing') is None
                and isinstance(service.get('metrics'), dict), 'CONFIRMATION_SERVICE_ERRORS')
        metrics = service['metrics']
        require(number(metrics.get('mutation_cpu_charged_ns')) == number(metrics.get('mutation_full_work_cpu_ns'))
                + number(metrics.get('mutation_dispatch_excluding_work_cpu_ns'))
                and number(metrics.get('mutation_cpu_clock_failures')) == 0, 'CONFIRMATION_CPU_SUM')
        started_work = number(metrics.get('work_started'))
        finished_work = number(metrics.get('work_finished'))
        failed_work = number(metrics.get('work_failed'))
        require(started_work == finished_work and failed_work <= finished_work
                and finished_work - failed_work >= 7
                and (not index or failed_work > 0), 'CONFIRMATION_WORK_CLOSURE')
        captured = phase.get('observations')
        flags(captured, yes=('cpu_intervals_are_nested_not_additive',),
              no=('counter_overflow', 'observation_has_consensus_authority',
                  'stream_bytes_are_physical_network_bytes'))
        observer_cpu_scope(captured)
        records = captured.get('records')
        require(isinstance(records, list) and len(records) <= number(captured.get('capacity')) == 16384
                and number(captured.get('accepted_connections_seen')) == len(records)
                and number(captured.get('records_not_retained')) == 0
                and number(captured.get('measurement_failures')) == 0
                and all(isinstance(row, dict) and row.get('complete') is True
                        and row.get('observation_failed') is False for row in records),
                'CONFIRMATION_OBSERVATION_COMPLETENESS')
        observations.append({'mode': phase['mode'], 'latency_ns': end - start,
                             'attacks': len(attack_calls), 'overlapping_false_calls': overlapping})
    return observations


def validate_confirmation_report(path: Path) -> dict:
    """Recompute bounded report consistency; native owners retain all authority."""
    require(path.is_file() and not path.is_symlink(), 'CONFIRMATION_REPORT_REQUIRED')
    with path.open('rb') as stream:
        raw = stream.read(REPORT_LIMIT + 1)
    require(len(raw) <= REPORT_LIMIT, 'CONFIRMATION_REPORT_LIMIT')
    doc = json_load(raw)
    require(isinstance(doc, dict) and doc.get('schema') == 'public-v3-signed-confirmation-pressure-v1',
            'CONFIRMATION_SCHEMA')

    number = ConfirmationReportChecks.number
    flags = ConfirmationReportChecks.flags
    hexadecimal = ConfirmationReportChecks.hexadecimal
    packet_metadata = ConfirmationReportChecks.packet_metadata
    call = ConfirmationReportChecks.call
    compact_request = ConfirmationReportChecks.compact_request

    flags(doc, yes=('finite_target_met', 'invariant_target_met', 'same_packet_sequence_in_both_runs'),
          no=('public_network_ready', 'work_profile_qualified', 'production_activation',
              'strongest_honest_producer_used'))
    context = {key: hexadecimal(doc.get(key), 32) for key in (
        'network', 'parameters', 'genesis', 'target', 'task', 'policy_id')}
    require(context['target'] != bytes(32), 'CONFIRMATION_CONTEXT')
    require(doc.get('honest_chain_aggregate_cpu_ns', 'missing') is None, 'CONFIRMATION_SCOPE_PROMOTION')
    number(doc.get('honest_chain_acquisition_wall_ns'))
    number(doc.get('attacker_construction_cpu_ns'))
    number(doc.get('attacker_construction_wall_ns'))
    # Optional successor reports separately measure whole-process acquisition.
    if 'honest_chain_process_cpu_ns' in doc:
        if doc['honest_chain_process_cpu_ns'] is not None:
            number(doc['honest_chain_process_cpu_ns'])
        require(isinstance(doc.get('honest_chain_process_cpu_scope'), str)
                and 0 < len(doc['honest_chain_process_cpu_scope']) <= 2048, 'CONFIRMATION_CPU_SCOPE')
    packets = doc.get('signed_honest_packets')
    require(isinstance(packets, list) and len(packets) == 7, 'CONFIRMATION_PACKET_SEQUENCE')
    metadata = [packet_metadata(packet) for packet in packets]
    parent = context['genesis']
    for height, (header, transactions, block_id) in enumerate(metadata, 1):
        require(header['network'] == context['network'] and header['parameters'] == context['parameters']
                and header['target'] == context['target'] and header['work_task'] == context['task'],
                'CONFIRMATION_CONTEXT')
        require(header['height'] == height and header['parent'] == parent
                and len(transactions) == (1 if height == 1 else 0), 'CONFIRMATION_PACKET_SEQUENCE')
        parent = block_id
    transaction_id = H('tx-id', metadata[0][1][0]).hex()
    constructions = doc.get('from_zero_construction')
    require(isinstance(constructions, list) and len(constructions) == 16, 'CONFIRMATION_CONSTRUCTIONS')
    for construction in constructions:
        require(isinstance(construction, dict) and construction.get('status') in (
            'target_hit_unverified', 'exhausted'), 'CONFIRMATION_CONSTRUCTIONS')
        header_bytes = hexadecimal(construction.get('header'), 318)
        header = header_decode(header_bytes)
        require(header['target'] == context['target'] and header['work_task'] == context['task']
                and header['network'] == context['network'] and header['parameters'] == context['parameters'],
                'CONFIRMATION_CONTEXT')
        require(header['height'] == 1 and header['parent'] == context['genesis'],
                'CONFIRMATION_CONSTRUCTIONS')
        challenge = H('challenge', header_bytes)
        require(hexadecimal(construction.get('challenge'), 32) == challenge
                and number(construction.get('attempt_budget')) == 4096
                and number(construction.get('setup_calls')) == 1, 'CONFIRMATION_CONSTRUCTIONS')
        attempts = construction.get('attempts')
        require(isinstance(attempts, list) and 0 < len(attempts) <= 4096,
                'CONFIRMATION_CONSTRUCTIONS')
        for ordinal, attempt in enumerate(attempts):
            require(isinstance(attempt, dict) and number(attempt.get('nonce')) == ordinal,
                    'CONFIRMATION_CONSTRUCTIONS')
            trace = H('public-v3-from-zero-v1', challenge, struct.pack('<Q', ordinal))
            ticket = H('ticket', challenge, trace)
            require(hexadecimal(attempt.get('trace'), 32) == trace
                    and hexadecimal(attempt.get('ticket'), 32) == ticket
                    and attempt.get('target_hit') is (ticket <= context['target']),
                    'CONFIRMATION_CONSTRUCTIONS')
        hit = construction['status'] == 'target_hit_unverified'
        require(not any(attempt['target_hit'] for attempt in attempts[:-1])
                and attempts[-1]['target_hit'] is hit, 'CONFIRMATION_CONSTRUCTIONS')
        if hit:
            require(number(construction.get('winner_nonce')) == len(attempts) - 1,
                    'CONFIRMATION_CONSTRUCTIONS')
            packet_header, transactions, _ = packet_metadata(construction.get('packet'))
            require(packet_header == header and not transactions
                    and hexadecimal(construction['packet'])[-32:]
                    == hexadecimal(attempts[-1]['trace'], 32), 'CONFIRMATION_CONSTRUCTION_PACKET')
        else:
            require(construction.get('packet', 'missing') is None
                    and construction.get('winner_nonce', 'missing') is None
                    and len(attempts) == 4096, 'CONFIRMATION_CONSTRUCTIONS')
    def resolve_attack(worker_index, _attempt_index, row):
        packet_index = number(row.get('packet_index'))
        require(packet_index == worker_index, 'CONFIRMATION_REQUEST_BINDING')
        return constructions[packet_index], packet_index

    observations = validate_confirmation_phases(doc, context, packets, metadata, resolve_attack)
    result = {'sha256': digest(raw), 'schema': doc['schema'], 'phases': observations,
              'finite_target_met': True, 'scope': 'bounded native report consistency; no independent work/state oracle, WAN, fairness or scientific acceptance'}
    if 'honest_chain_process_cpu_ns' in doc:
        result['honest_chain_process_cpu_ns'] = doc['honest_chain_process_cpu_ns']
        result['honest_chain_process_cpu_scope'] = doc['honest_chain_process_cpu_scope']
    return result


def save_manifest(out: Path, result: dict) -> None:
    temporary = out / 'manifest.json.next'
    with temporary.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(result, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, out / 'manifest.json')


def validate_request_lifecycle(row: dict) -> bool:
    """Validate optional local owner clocks, without ordering the two owners."""
    if 'lifecycle' not in row:
        return False
    value = row['lifecycle']
    require(type(value) is dict and set(value) == {'schema', 'accepted_ns', 'connection_closed_ns',
            'task_closed_ns', 'clock_is_observer_local', 'has_control_authority'}
            and value['schema'] == 'public-v3-request-lifecycle-v1'
            and value['clock_is_observer_local'] is True and value['has_control_authority'] is False,
            'CONFIRMATION_LIFECYCLE_SCHEMA')
    for name in ('accepted_ns', 'connection_closed_ns', 'task_closed_ns'):
        require(value[name] is None or (type(value[name]) is int and 0 <= value[name] < 1 << 64),
                'CONFIRMATION_LIFECYCLE_NUMBER')
    require(all(type(row.get(key)) is bool for key in ('connection_closed', 'task_created',
            'task_closed', 'observation_failed', 'complete')), 'CONFIRMATION_LIFECYCLE_OWNER_FLAGS')
    accepted, disconnected, task_closed = (value[name] for name in
                                          ('accepted_ns', 'connection_closed_ns', 'task_closed_ns'))
    require(accepted is not None or row['observation_failed'], 'CONFIRMATION_LIFECYCLE_RECEIVE_UNKNOWN')
    require(disconnected is None or row['connection_closed'], 'CONFIRMATION_LIFECYCLE_CONNECTION_OWNER')
    require(not row['connection_closed'] or disconnected is not None or row['observation_failed'],
            'CONFIRMATION_LIFECYCLE_CONNECTION_CLOCK')
    require(row['task_created'] or (not row['task_closed'] and task_closed is None),
            'CONFIRMATION_LIFECYCLE_TASK_NOT_CREATED')
    require(task_closed is None or row['task_closed'], 'CONFIRMATION_LIFECYCLE_TASK_OWNER')
    require(not row['task_closed'] or task_closed is not None or row['observation_failed'],
            'CONFIRMATION_LIFECYCLE_TASK_CLOCK')
    require(all(accepted is None or ended is None or accepted <= ended
                for ended in (disconnected, task_closed)), 'CONFIRMATION_LIFECYCLE_CHRONOLOGY')
    require(row['complete'] is (row['connection_closed'] and (not row['task_created'] or row['task_closed'])
                               and not row['observation_failed']), 'CONFIRMATION_LIFECYCLE_COMPLETION')
    return True


def validate_v2_confirmed_observation(doc: dict, phase: dict) -> bool:
    """Bind a positive v2 observation to this phase's actual required business.

    This deliberately does not require the other phase or the complete hostile
    gate to pass. A malformed positive claim is refused instead of being turned
    into either a successful rate/latency or a fabricated measured zero. Zero and
    missing counts retain the existing failed/unknown observation semantics.
    These are report consistency checks, not native signature/work verification.
    """
    if phase.get('client_confirmed_transactions') != 1:
        return False
    number = ConfirmationReportChecks.number
    hexadecimal = ConfirmationReportChecks.hexadecimal
    require(type(phase['client_confirmed_transactions']) is int
            and phase.get('client_confirmed_before_original_window_end') is True,
            'CONFIRMATION_V2_POSITIVE_COUNT')
    start, end = number(phase.get('business_started_ns')), number(phase.get('confirmation_ended_ns'))
    require(number(phase.get('requested_window_ns')) == 4_000_000_000 and start < end < 4_000_000_000
            and number(phase.get('client_confirmation_latency_ns')) == end - start,
            'CONFIRMATION_V2_POSITIVE_TIME')
    context = {key: hexadecimal(doc.get(key), 32) for key in
               ('network', 'parameters', 'genesis', 'target', 'task')}
    require(context['target'] != bytes(32) and phase.get('target') == doc['target']
            and phase.get('task') == doc['task'] and phase.get('initial_tip') == doc['genesis'],
            'CONFIRMATION_V2_CONTEXT')
    packets = doc.get('signed_honest_packets')
    require(isinstance(packets, list) and len(packets) == 7, 'CONFIRMATION_V2_REQUIRED_PACKETS')
    metadata = [ConfirmationReportChecks.packet_metadata(packet) for packet in packets]
    parent = context['genesis']
    for height, (header, transactions, block_id) in enumerate(metadata, 1):
        require(all(header[key] == context[key] for key in ('network', 'parameters', 'target'))
                and header['work_task'] == context['task'] and header['height'] == height
                and header['parent'] == parent and len(transactions) == (1 if height == 1 else 0),
                'CONFIRMATION_V2_REQUIRED_PACKETS')
        parent = block_id
    native = phase.get('independent_client_confirmation')
    require(isinstance(native, dict) and native.get('confirmed') is True
            and all(native.get(key) is False for key in ('reorged', 'finalized', 'execution_authority')),
            'CONFIRMATION_V2_NATIVE_STATUS')
    require(all(native.get(key) == doc[key] for key in ('network', 'parameters', 'genesis'))
            and native.get('transaction') == H('tx-id', metadata[0][1][0]).hex()
            and native.get('included_block') == metadata[0][2].hex()
            and native.get('observed_tip') == metadata[-1][2].hex()
            and number(native.get('included_height')) == 1
            and number(native.get('observed_height')) == 7 and number(native.get('depth')) == 6,
            'CONFIRMATION_V2_NATIVE_BINDING')
    required = (6 * ((1 << 256) // (int.from_bytes(context['target'], 'big') + 1))).to_bytes(64, 'big')
    require(hexadecimal(native.get('required_work_delta'), 64) == required
            and hexadecimal(native.get('work_delta'), 64) == required, 'CONFIRMATION_V2_NATIVE_WORK')
    final = phase.get('independent_final_confirmation_stage')
    require(isinstance(final, dict) and final.get('observation_returned') is True
            and final.get('clock_scope') == 'independent verifier caller thread; no consensus/host time claim',
            'CONFIRMATION_V2_FINAL_RETURN')
    final_start, final_end = (number(final.get(key)) for key in
                              ('confirmation_started_ns', 'confirmation_ended_ns'))
    require(start <= final_start <= final_end <= end
            and number(final.get('confirmation_wall_ns')) == final_end - final_start,
            'CONFIRMATION_V2_FINAL_TIME')
    replays = phase.get('independent_history_page_replay')
    require(isinstance(replays, list) and 1 <= len(replays) <= 16 and isinstance(replays[-1], dict)
            and replays[-1].get('replay_accepted') is True
            and replays[-1].get('next_after') == metadata[-1][2].hex()
            and number(replays[-1].get('replay_ended_ns')) <= final_start,
            'CONFIRMATION_V2_FINAL_REPLAY_BINDING')
    return True


def business_receive_observation(doc: dict, phase: dict, receiver: dict | None,
                                 *, confirmed: bool) -> dict | None:
    """Bind an optional same-process clock to all matching Hello claims.

    Hello is peer-controlled. Even a fully covered matching-claim clock does not
    authenticate the complete request body, sender, durable effect or operator.
    A record lost before identity binding can be an earlier retry, so its absence
    prevents an exact earliest-claim latency rather than shortening that latency.
    """
    if 'business_receive_clock' not in phase:
        return None
    value = phase['business_receive_clock']
    require(type(value) is dict and set(value) == {'schema', 'clock_scope',
            'traffic_epoch_in_observer_ns', 'first_business_packet_body_digest',
            'independent_confirmation_in_observer_ns', 'request_binding_stage', 'has_control_authority'}
            and value['schema'] == 'public-v3-business-receive-clock-v1'
            and value['clock_scope'] == 'same-process-monotonic-observer'
            and value['request_binding_stage'] == 'hello-claimed-body-digest'
            and value['has_control_authority'] is False, 'CONFIRMATION_RECEIVE_CLOCK_SCHEMA')

    def optional_time(time):
        require(time is None or (type(time) is int and 0 <= time < 1 << 64),
                'CONFIRMATION_RECEIVE_CLOCK_NUMBER')
        return time

    offset = optional_time(value['traffic_epoch_in_observer_ns'])
    final = optional_time(value['independent_confirmation_in_observer_ns'])
    ended = optional_time(phase.get('confirmation_ended_ns'))
    translated = offset + ended if offset is not None and ended is not None else None
    overflowed = translated is not None and translated >= 1 << 64
    require(final == (None if overflowed else translated), 'CONFIRMATION_RECEIVE_CLOCK_TRANSLATION')
    packets = doc.get('signed_honest_packets')
    require(isinstance(packets, list) and len(packets) == 7 and isinstance(packets[0], str)
            and len(packets[0]) % 2 == 0 and re.fullmatch('[0-9a-f]+', packets[0]) is not None,
            'CONFIRMATION_RECEIVE_CLOCK_PACKET')
    expected = H('public-request-body-v3', json.dumps(
        {'op': 'submit', 'packet': packets[0]}, separators=(',', ':')).encode())
    require(value['first_business_packet_body_digest'] == expected.hex(), 'CONFIRMATION_RECEIVE_CLOCK_DIGEST')
    captured = phase.get('observations')
    require(captured is None or captured.get('schema') == 'public-v3-local-request-resource-observation-v4',
            'CONFIRMATION_RECEIVE_CLOCK_OBSERVER')
    records = captured['records'] if captured is not None else []
    identities, matched, missing_binding, missing_lifecycle, missing_receive_clock = set(), [], 0, 0, 0
    for row in records:
        identity = row.get('connection_id')
        optional_time(identity)
        if identity is not None:
            require(identity not in identities, 'CONFIRMATION_RECEIVE_CLOCK_DUPLICATE_IDENTITY')
            identities.add(identity)
        op, body = row.get('operation'), row.get('body_digest')
        require(op is None or (type(op) is int and 0 <= op <= 255), 'CONFIRMATION_RECEIVE_CLOCK_OPERATION')
        require(body is None or (type(body) is list and len(body) == 32
                and all(type(byte) is int and 0 <= byte <= 255 for byte in body)),
                'CONFIRMATION_RECEIVE_CLOCK_BODY_DIGEST')
        missing_binding += identity is None or op is None or body is None
        lifecycle = row.get('lifecycle')
        if lifecycle is None:
            missing_lifecycle += 1
            received = None
        else:
            validate_request_lifecycle(row)
            received = lifecycle['accepted_ns']
        missing_receive_clock += received is None
        if op == 1 and body == list(expected):
            matched.append(received)
    known_receives = [time for time in matched if time is not None]
    earliest = min(known_receives) if known_receives else None
    observed_final_latency = final - earliest if final is not None and earliest is not None and final >= earliest else None
    covered = (receiver is not None and receiver['all_seen_records_closed_and_retained']
               and not missing_binding and not missing_lifecycle and not missing_receive_clock and bool(matched))
    return {
        'schema': value['schema'], 'request_binding_stage': value['request_binding_stage'],
        'traffic_epoch_in_observer_ns': offset, 'final_observation_in_observer_ns': final,
        'clock_translation_overflowed': overflowed, 'epochs_correlated': offset is not None,
        'retained_records': len(records), 'matched_claim_records': len(matched),
        'matching_claims_without_receive_clock': len(matched) - len(known_receives),
        'records_without_complete_identity_binding': missing_binding,
        'records_without_lifecycle': missing_lifecycle, 'records_without_receive_clock': missing_receive_clock,
        'earliest_matched_claim_received_ns': earliest,
        'observed_matched_claim_to_final_observation_ns': observed_final_latency,
        'observed_matched_claim_to_confirmation_ns': observed_final_latency if confirmed else None,
        'confirmation_observed_in_original_window': confirmed,
        'exact_claim_cohort_covered': covered,
        'body_or_sender_authenticated_by_clock': False, 'has_control_authority': False,
        'scope': 'same-process receive time for the peer-claimed first business packet, including failed retries; '
                 'an Ok final observation is not necessarily confirmation; no full-body validation, sender or operator '
                 'independence is inferred; unknown bindings or lost records prevent an exact earliest-claim latency',
    }


def complete_confirmation_observation(doc: dict, report: dict) -> dict:
    """Add v2 accounting from existing facts without correlating distinct clocks.

    Caller returns, receiver dispatch and receiver record closure are different
    observations. A cancellation after dispatch cannot undo a native effect, and
    an error's display text is not the receiver's typed cancellation/deadline.
    Missing snapshots/resources remain unknown; no source of this report measures
    release download, token generation or complete machine resource consumption.
    """
    number = ConfirmationReportChecks.number

    def optional_number(value):
        return None if value is None else number(value)

    def samples(values):
        known = [number(value) for value in values if value is not None]
        return {'known_count': len(known), 'missing_count': len(values) - len(known),
                'known_sum': sum(known) if known else None,
                'max_known': max(known) if known else None}

    def text_counts(values):
        require(all(value is None or isinstance(value, str) for value in values),
                'CONFIRMATION_DIAGNOSTIC_TEXT')
        return dict(Counter(value for value in values if value is not None))

    def client_detail(rows, window):
        for row in rows:
            require(number(row.get('deadline_ms')) == 2000
                    and row['returned_after_deadline'] is (row['elapsed_wall_ns'] > 2_000_000_000)
                    and (row['ended_ns'] < window or row['returned_after_window'] is True),
                    'CONFIRMATION_CALL_DEADLINE_FACT')
        statuses = [row.get('status') for row in rows]
        refusals = []
        for row in rows:
            response = row.get('response')
            value = response.get('value') if isinstance(response, dict) else None
            refusals.append(value.get('error') if isinstance(value, dict) else None)
        return {'status_counts': text_counts(statuses),
                'status_missing': sum(value is None for value in statuses),
                'raw_client_error_counts': text_counts([row.get('error') for row in rows]),
                'raw_refusal_error_counts': text_counts(refusals),
                'returned_after_call_deadline': sum(row['returned_after_deadline'] for row in rows),
                'returned_after_original_window': sum(row['returned_after_window'] for row in rows),
                'diagnostic_text_is_typed_error': False,
                'unobserved_attempts': None,
                'scope': 'observed client returns only; retries and polls are not unique business transactions; '
                         'late flags overlap status counts; missing calls cannot be reconstructed'}

    for phase, measured in zip(doc['phases'], report['phases']):
        confirmed = validate_v2_confirmed_observation(doc, phase)
        for source, destination in (('honest_submissions', 'signed_submit_ack'),
                                    ('honest_history', 'history_response'),
                                    ('honest_heads', 'head_response')):
            measured[destination]['outcome_detail'] = client_detail(phase[source], measured['window_ns'])

        captured = phase.get('observations')
        receiver = None
        records = None
        if captured is not None:
            require(isinstance(captured, dict), 'CONFIRMATION_RECEIVER_SNAPSHOT')
            records = captured.get('records')
            require(isinstance(records, list) and len(records) <= 16384
                    and all(isinstance(row, dict) for row in records), 'CONFIRMATION_RECEIVER_RECORDS')
            seen = number(captured.get('accepted_connections_seen'))
            omitted = number(captured.get('records_not_retained'))
            failures = number(captured.get('measurement_failures'))
            require(type(captured.get('counter_overflow')) is bool
                    and len(records) + omitted <= seen, 'CONFIRMATION_RECEIVER_DENOMINATOR')
            current = captured.get('schema') == 'public-v3-local-request-resource-observation-v4'
            if current:
                for row in records:
                    validate_v4_record(row)
            for row in records:
                validate_request_lifecycle(row)
                require(all(row.get(key) is None or type(row[key]) is bool for key in
                            ('complete', 'observation_failed', 'dispatch_started', 'dispatch_accepted',
                             'full_work_started')), 'CONFIRMATION_RECEIVER_BOOLEAN')
                for key in ('terminal_error_code', 'dispatch_error_code'):
                    value = row.get(key)
                    require(value is None or (isinstance(value, str)
                            and re.fullmatch('[A-Z][A-Z0-9_]*', value) is not None),
                            'CONFIRMATION_RECEIVER_TYPED_ERROR')
            # No precedence between dispatch and terminal causes: an accepted
            # dispatch can be followed by response cancellation. Keep both.
            cancelled = sum(current and any(row.get(key) == 'PUBLIC_REQUEST_CANCELLED'
                            for key in ('terminal_error_code', 'dispatch_error_code')) for row in records)
            timed_out = sum(current and any(row.get(key) == 'PUBLIC_REQUEST_DEADLINE'
                            for key in ('terminal_error_code', 'dispatch_error_code')) for row in records)
            lifecycle = {name: sum(row.get('complete') is value for row in records)
                         for name, value in (('closed', True), ('unfinished', False), ('unknown', None))}
            receiver = {
                'accepted_connections_seen': seen, 'retained_records': len(records),
                'records_not_retained': omitted,
                'seen_without_snapshot_or_omission_record': seen - len(records) - omitted,
                'measurement_failures': failures, 'counter_overflow': captured['counter_overflow'],
                'record_lifecycle': lifecycle,
                'record_observation_failed': sum(row.get('observation_failed') is True for row in records),
                'dispatch_outcomes': {name: sum(row.get('dispatch_accepted') is value for row in records)
                                      for name, value in (('accepted', True), ('rejected', False), ('unknown', None))},
                'typed_terminal_error_counts': text_counts([row.get('terminal_error_code') for row in records]) if current else None,
                'typed_dispatch_error_counts': text_counts([row.get('dispatch_error_code') for row in records]) if current else None,
                'missing_terminal_error_slots': sum('terminal_error_code' not in row for row in records),
                'typed_cancelled_records': cancelled if current else None,
                'typed_deadline_records': timed_out if current else None,
                'typed_causes_are_disjoint_outcomes': False,
                'all_seen_records_closed_and_retained': seen == len(records) and not omitted
                    and not failures and not captured['counter_overflow'] and lifecycle['closed'] == len(records)
                    and all(row.get('observation_failed') is False for row in records),
                'unobserved_client_attempts': None,
                'scope': 'receiver connections, not transactions; complete means observation closure, not execution success; '
                         'unfinished may include measurement failure; typed causes require the v4 source namespace',
            }
        measured['receiver_requests'] = receiver

        resources = {'all_worker_cpu_ns': None, 'physical_network_bytes': None, 'disk_growth_bytes': None,
                     'request_peak_rss_bytes': samples([None] * len(records)) if records is not None else None,
                     'unretained_receiver_records': receiver['accepted_connections_seen'] - len(records)
                        if records is not None else None,
                     'scope': 'source-report coverage only; full-work CPU is nested inside dispatch CPU; '
                              'neither is complete worker/process CPU; stream bytes are not physical network bytes; '
                              'receiver samples cover retained records only; unretained records remain unmeasured; '
                              'RSS and disk growth are not captured by this source; missing values are not zero'}
        for started, field, output in (
                ('dispatch_started', 'dispatch_thread_cpu_ns', 'receiver_dispatch_thread_cpu_ns'),
                ('full_work_started', 'full_work_thread_cpu_ns', 'receiver_full_work_thread_cpu_ns')):
            resources[output] = None if records is None else {
                **samples([row.get(field) for row in records if row.get(started) is True]),
                'unentered_or_start_unknown_records': sum(row.get(started) is not True for row in records)}
        for field in ('application_bytes_read', 'application_bytes_written'):
            resources[field] = None if records is None else samples([row.get(field) for row in records])
        workers = phase.get('attacks')
        require(workers is None or (isinstance(workers, list) and len(workers) <= 16
                and all(isinstance(worker, dict) for worker in workers)), 'CONFIRMATION_ATTACKER_CPU_ROWS')
        roster = {}
        for worker in workers or []:
            identity = number(worker.get('worker'))
            require(identity < phase['workers'] and identity not in roster, 'CONFIRMATION_ATTACKER_CPU_IDENTITY')
            roster[identity] = worker.get('calling_thread_cpu_ns')
        resources['attacker_workers_calling_thread_cpu_ns'] = {
            **samples([roster.get(index) for index in range(phase['workers'])]),
            'scheduled_workers': phase['workers'], 'observed_worker_records': len(roster),
            'worker_roster_observed': workers is not None}
        measured['resource_coverage'] = resources

        business = measured['business']
        in_window = business['reported_independently_confirmed_in_window'] == 1
        measured['request_clock'] = {
            'clock_scope': 'client phase-local monotonic epoch; original pressure window begins at zero',
            'business_started_ns': phase['business_started_ns'],
            'reported_final_observation_ended_ns': optional_number(phase.get('confirmation_ended_ns')),
            'original_window_to_independent_confirmation_ns': phase['confirmation_ended_ns'] if in_window else None,
            'business_start_to_independent_confirmation_ns': business['observed_success_latency_ns'],
            'receiver_to_independent_confirmation_ns': None,
            'receiver_and_client_epochs_correlated': False,
            'scope': 'in-window independent confirmation only; reported late returns retain their timestamp without success credit; '
                     'no receiver arrival can be joined to the client confirmation from this report',
        }
        receive = business_receive_observation(doc, phase, receiver, confirmed=confirmed)
        measured['request_clock']['business_receive_observation'] = receive
        if receive is not None:
            measured['request_clock'].update(
                receiver_and_client_epochs_correlated=receive['epochs_correlated'],
                receiver_to_independent_confirmation_ns=receive['observed_matched_claim_to_confirmation_ns']
                    if receive['exact_claim_cohort_covered'] else None,
                scope='original client window and optional same-process receiver epoch; exact receive latency '
                      'is for a completely observed Hello-claim cohort, not authenticated sender/body attribution; '
                      'failed, late or unconfirmed returns never receive successful-confirmation credit')
        measured['product_metrics'] = {
            'confirmation': {'finite_offer_transactions_per_second':
                                 business['independent_confirmed_transactions_per_window_second'],
                             'required_unique_transactions': 1, 'window_ns': measured['window_ns'],
                             'saturated_capacity_tps': None,
                             'scope': 'one original signed business transaction, not ACKs, blocks or saturated TPS'},
            **{name: {'status': 'not_observed_by_this_report', 'value': None, 'unit': unit}
               for name, unit in (('complete_release_download', 'verified-release-bytes/second'),
                                  ('first_token', 'nanoseconds'), ('inference', 'tokens/second'),
                                  ('model_net_benefit_per_cost', 'net-model-utility/cost-unit'))},
        }
    report['schema'] = 'trnm-original-confirmation-observation-v2'
    return report


def summarize_confirmation_report(path: Path, *, observation_version: int = 2) -> dict:
    """Describe both passing and failing original reports; never confer authority.

    ACK and page response counts have separate denominators from the one signed
    business transaction. Missing confirmation is unknown, not a measured zero.
    Successful latency samples exclude failed/late calls; incomplete business
    keeps its denominator and the lower bound supported by actual timestamps.
    """
    require(type(observation_version) is int and observation_version in (1, 2),
            'CONFIRMATION_OBSERVATION_VERSION')
    require(path.is_file() and not path.is_symlink(), 'CONFIRMATION_REPORT_REQUIRED')
    with path.open('rb') as stream:
        raw = stream.read(REPORT_LIMIT + 1)
    require(len(raw) <= REPORT_LIMIT, 'CONFIRMATION_REPORT_LIMIT')
    doc = json_load(raw)
    require(isinstance(doc, dict)
            and doc.get('schema') == 'public-v3-signed-confirmation-pressure-v1',
            'CONFIRMATION_SCHEMA')
    phases = doc.get('phases')
    require(isinstance(phases, list) and len(phases) == 2, 'CONFIRMATION_PHASES')

    def number(value):
        require(type(value) is int and 0 <= value < 1 << 64, 'CONFIRMATION_NUMBER')
        return value

    def distribution(values, missing=0):
        values = sorted(values)
        n = len(values)
        # A small sample's maximum must not masquerade as p95/p99. These
        # minimum ranks match the public-readiness reader's tail resolution;
        # they do not establish independence or population confidence. Count
        # successful, failed/late and missing-CPU samples separately below.
        minimum = {50: 2, 95: 20, 99: 100}
        return {'samples': n, 'missing_samples': missing,
                'min_ns': values[0] if n else None,
                'max_ns': values[-1] if n else None,
                'minimum_samples': {f'p{percent}': count for percent, count in minimum.items()},
                'method': 'nearest-rank; descriptive only; p50 needs 2, p95 20, p99 100 samples; '
                          'independence and confidence are not established',
                **{f'p{percent}_ns': values[(n * percent + 99) // 100 - 1]
                   if n >= required else None for percent, required in minimum.items()}}

    output = []
    for index, phase in enumerate(phases):
        require(isinstance(phase, dict)
                and phase.get('mode') == ('attack-free-baseline' if index == 0 else 'from-zero-pressure')
                and number(phase.get('workers')) == 16 * index, 'CONFIRMATION_PHASES')
        window = number(phase.get('requested_window_ns'))
        start = number(phase.get('business_started_ns'))
        require(window == 4_000_000_000, 'CONFIRMATION_OUTSIDE_ORIGINAL_WINDOW')
        # The native caller samples this after its start barrier and pressure
        # wait. Scheduling or admission can consume the complete original
        # window before any honest submission starts. Keep that failed offer
        # in the denominator; only the strict acceptance path requires an
        # in-window start and confirmation. Never restart or extend its clock.
        observed_ends = []

        def calls(rows, maximum):
            require(isinstance(rows, list) and len(rows) <= maximum, 'CONFIRMATION_CALLS_REQUIRED')
            success, terminal, cpu, missing_cpu = [], [], [], 0
            for row in rows:
                require(isinstance(row, dict), 'CONFIRMATION_CALLS_REQUIRED')
                begin, end = number(row.get('started_ns')), number(row.get('ended_ns'))
                duration = number(row.get('elapsed_wall_ns'))
                # Original caller samples elapsed after its end timestamp.
                require(begin <= end and duration >= end - begin, 'CONFIRMATION_CALL_TIME')
                require(type(row.get('returned_after_window')) is bool
                        and type(row.get('returned_after_deadline')) is bool,
                        'CONFIRMATION_CALL_TIME')
                observed_ends.append(end)
                on_time = (row.get('status') == 'ok' and not row['returned_after_window']
                           and not row['returned_after_deadline'] and end < window)
                if on_time:
                    success.append(duration)
                else:
                    terminal.append(duration)
                value = row.get('client_thread_cpu_ns')
                if value is None:
                    missing_cpu += 1
                else:
                    cpu.append(number(value))
            return {'attempts': len(rows), 'successful_in_original_window': len(success),
                    'failed_or_late': len(terminal),
                    'successful_latency': distribution(success),
                    'failed_or_late_terminal_duration': distribution(terminal),
                    'calling_thread_cpu': distribution(cpu, missing_cpu)}

        submits = calls(phase.get('honest_submissions'), 64)
        histories = calls(phase.get('honest_history'), 16)
        heads = calls(phase.get('honest_heads'), 256)
        replays = phase.get('independent_history_page_replay')
        replay_summary = None
        if replays is not None:
            require(isinstance(replays, list) and len(replays) <= 16, 'CONFIRMATION_REPLAY_STAGES')
            walls, failures, cpus, missing_cpu = [], [], [], 0
            native_observed = 0
            for row in replays:
                require(isinstance(row, dict) and type(row.get('replay_accepted')) is bool,
                        'CONFIRMATION_REPLAY_STAGES')
                begin, end = number(row.get('replay_started_ns')), number(row.get('replay_ended_ns'))
                wall = number(row.get('replay_wall_ns'))
                require(begin <= end and wall == end - begin, 'CONFIRMATION_REPLAY_STAGES')
                observed_ends.append(end)
                (walls if row['replay_accepted'] and end < window else failures).append(wall)
                value = row.get('replay_thread_cpu_ns')
                if value is None:
                    missing_cpu += 1
                else:
                    cpus.append(number(value))
                if 'native_import_observation' in row:
                    validate_history_import_observation(row['native_import_observation'])
                    native_observed += 1
            replay_summary = {'attempts': len(replays), 'accepted_in_original_window': len(walls),
                              'failed_or_late': len(failures),
                              'accepted_wall': distribution(walls),
                              'failed_or_late_wall': distribution(failures),
                              'calling_thread_cpu': distribution(cpus, missing_cpu),
                              'known_calling_thread_cpu_sum_ns': sum(cpus),
                              'cpu_scope': 'caller thread only; excludes separately owned worker CPU',
                              'native_stage_snapshots_retained': native_observed,
                              'native_stage_snapshots_missing': len(replays) - native_observed,
                              'native_stage_scope': 'optional local snapshots; old absence remains unknown; Host/native/packet intervals are nested, not added to replay CPU'}

        count = phase.get('client_confirmed_transactions')
        latency = None
        if count is not None:
            require(number(count) <= 1, 'CONFIRMATION_BUSINESS_COUNT')
        if count == 1:
            end = number(phase.get('confirmation_ended_ns'))
            latency = number(phase.get('client_confirmation_latency_ns'))
            native = phase.get('independent_client_confirmation')
            require(start < end < window and latency == end - start
                    and phase.get('client_confirmed_before_original_window_end') is True
                    and isinstance(native, dict) and native.get('confirmed') is True
                    and native.get('finalized') is False and native.get('execution_authority') is False
                    and number(native.get('depth')) == 6, 'CONFIRMATION_NATIVE_OBSERVATION')
            observed_ends.append(end)
        elif count == 0:
            require(phase.get('client_confirmed_before_original_window_end') is False,
                    'CONFIRMATION_BUSINESS_COUNT')
        # The lower bound is conservative: only real recorded event timestamps
        # establish observation coverage, not the configured window by itself.
        observed_until = min(window, max(observed_ends, default=start))
        output.append({
            'mode': phase['mode'], 'workers': phase['workers'], 'window_ns': window,
            'business': {'required_signed_transactions': 1,
                         'business_start_delay_ns': start,
                         'business_started_before_original_window_end': start < window,
                         'original_window_remaining_at_business_start_ns': max(0, window - start),
                         'pre_business_window_overrun_ns': max(0, start - window),
                         'reported_independently_confirmed_in_window': count,
                         'unconfirmed': 1 - count if count is not None else None,
                         'unknown': int(count is None),
                         'independent_confirmed_transactions_per_window_second':
                             count * 1_000_000_000 / window if count is not None else None,
                         'observed_success_latency_ns': latency,
                         'successful_latency': distribution([] if latency is None else [latency]),
                         'unconfirmed_latency_lower_bound_ns':
                             max(0, observed_until - start) if count == 0 else None,
                         'lower_bound_reaches_original_window_end':
                             observed_until == window if count == 0 else None,
                         'reported_finite_business_target_met': phase.get('finite_business_target_met')},
            'signed_submit_ack': {**submits,
                                  'acknowledgements_per_window_second':
                                      submits['successful_in_original_window'] * 1_000_000_000 / window},
            'history_response': histories, 'independent_page_replay': replay_summary,
            'head_response': heads, 'verification_errors': phase.get('verification_errors'),
            'service_totals': phase.get('service', {}).get('metrics'),
            'service_totals_scope': 'whole service including shutdown; not per-request p99 or in-window proof/s',
        })
    error = None
    try:
        accepted = validate_confirmation_report(path)
        require(accepted['sha256'] == digest(raw), 'CONFIRMATION_REPORT_CHANGED')
    except (OSError, ValueError, TypeError, KeyError) as failure:
        error = str(failure)
    report = {'schema': 'trnm-original-confirmation-observation-v1', 'sha256': digest(raw),
            'original_gate_validated': error is None, 'original_gate_validation_error': error,
            'simulated_control': doc.get('simulated_control') is True,
            'phases': output, 'network_capacity_qualified': False,
            'tail_latency_qualified': False, 'production_activation': False,
            'scope': 'same original finite offer, 1 signed transaction per 4s phase; not saturated chain TPS; '
                     'reported native observations only, no independent proof/state oracle'}
    return complete_confirmation_observation(doc, report) if observation_version == 2 else report


def report_file_identity(path: Path) -> dict:
    """Identify bounded retained bytes without parsing or accepting their claims."""
    identity = {'state': 'unavailable', 'bytes': None, 'sha256': None}
    try:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            identity['state'] = 'not_regular'
        elif not path.exists():
            identity['state'] = 'missing'
        else:
            with path.open('rb') as stream:
                raw = stream.read(REPORT_LIMIT + 1)
            if len(raw) > REPORT_LIMIT:
                identity.update(state='over_limit', bytes_at_least=len(raw))
            else:
                identity.update(state='present', bytes=len(raw), sha256=digest(raw))
    except OSError as error:
        identity['error'] = str(error)
    return identity


def run(out: Path) -> dict:
    out = out.resolve()
    require(not out.is_relative_to(ROOT), 'OUTPUT_MUST_BE_OUTSIDE_CHECKOUT')
    identity = source_identity()
    out.mkdir(parents=True, exist_ok=False)
    terminal = {
        'schema': 'trnm-from-zero-native-terminal-v1',
        'scope': 'child process terminals and original sequential report acceptance; '
                 'diagnostic readback grants no acceptance or subsequent CI execution',
        'legacy_execution_finished_scope': 'original native execution and report validation '
                                           'sequence reached its end; not process liveness or overall acceptance',
        'native_execution_completed': False,
        'native_execution_completed_scope': 'all planned child invocations returned without timeout; '
                                            'not named-test or business acceptance',
        'native_invocations': [{'name': name, 'status': 'not_executed',
                                'exit_code': None, 'timed_out': None} for name in TESTS],
        'unexecuted_native_tests': list(TESTS),
        'acceptance_stages': {
            key: {'path': path, 'status': 'not_executed', 'error': None,
                  'before_validation': None, 'retained_report': None,
                  'retained_matches_before_validation': None}
            for key, path in REPORT_PATHS.items()},
        'unexecuted_acceptance_stages': list(REPORT_PATHS),
        'acceptance_passed': False, 'finalization_completed': False,
        'subsequent_ci_steps_observed': False,
    }
    result = {'schema': 'trnm-from-zero-native-execution-v3', 'source_before': identity,
              'source_after': None, 'source_recompiled': False, 'all_named_tests_passed': False,
              'format_passed': False, 'runs': [], 'failures': [],
              'independent_wan_accepted': False, 'work_hardness_accepted': False,
              'production_activation': False, 'passed': False, 'execution_finished': False,
              'service_report': None, 'sustained_report': None, 'confirmation_report': None,
              'confirmation_observation': None, 'terminal': terminal}
    previous_output = os.environ.get('TRNM_PUBLIC_V3_FROM_ZERO_DIR')
    previous_confirmation_output = os.environ.get('TRNM_PUBLIC_V3_CONFIRMATION_DIR')
    previous_cwd = Path.cwd()
    save_manifest(out, result)  # An interrupted launch retains an incomplete, non-passing receipt.
    try:
        os.chdir(ROOT)
        os.environ['TRNM_PUBLIC_V3_FROM_ZERO_DIR'] = str(out / 'native')
        os.environ['TRNM_PUBLIC_V3_CONFIRMATION_DIR'] = str(out / 'confirmation')
        result['rustc'] = subprocess.check_output(['rustc', '-Vv'], text=True, timeout=30)
        result['cargo'] = subprocess.check_output(['cargo', '-V'], text=True, timeout=30).strip()
        result['build_env'] = {key: os.environ.get(key) for key in (
            'CARGO_BUILD_JOBS', 'CARGO_TARGET_DIR', 'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS')}
        # Stage the actual relative #[path] module before formatting the copy.
        # The original checkout and authoritative cargo fmt --check stay untouched.
        format_source = stage_format_copy(ROOT / SOURCE, ROOT / FORMAT_SUPPORT, out)
        result['format_copy'] = run_child(
            ['rustfmt', '--edition', '2021', str(format_source)], out / 'format-copy', 60)
        shutil.copyfile(format_source, out / 'formatted.rs')
        require(result['format_copy']['timed_out'] is False, 'NATIVE_TIMEOUT_STOPS_CAMPAIGN')
        result['format'] = run_child(
            ['cargo', 'fmt', '--manifest-path', 'trillionnium/Cargo.toml', '--all', '--', '--check'],
            out / 'format-check', 60)
        result['format_passed'] = result['format']['exit_code'] == 0 and not result['format']['timed_out']
        require(result['format']['timed_out'] is False, 'NATIVE_TIMEOUT_STOPS_CAMPAIGN')
        result['build'] = run_child(native_build_command(), out / 'build', 900)
        require(result['build']['exit_code'] == 0 and not result['build']['timed_out'], 'NATIVE_BUILD_FAILED')
        binary = select_binary((out / 'build/stdout').read_text().splitlines())
        require(binary.is_file() and not binary.is_symlink(), 'REGULAR_BINARY_REQUIRED')
        result['source_recompiled'] = True
        result['binary_sha256_before'] = digest(binary.read_bytes())
        shutil.copy2(binary, out / TARGET)
        for index, name in enumerate(TESTS):
            folder = out / name
            invocation = terminal['native_invocations'][index]
            invocation['status'] = 'invoked_without_terminal'
            observed = run_child([str(binary), name, '--exact', '--nocapture', '--test-threads=1'], folder, 90)
            # Keep the returned child status even if a later log read or report
            # validator fails. A returned process is not a passing native test.
            invocation.update(status='returned', exit_code=observed['exit_code'],
                              timed_out=observed['timed_out'])
            row = {'name': name, 'process': observed, 'passed': False,
                   'stdout_sha256': digest((folder / 'stdout').read_bytes()),
                   'stderr_sha256': digest((folder / 'stderr').read_bytes())}
            result['runs'].append(row)
            try:
                require(observed['exit_code'] == 0 and not observed['timed_out'], 'NATIVE_TEST_FAILED')
                row['named_execution'] = validate((folder / 'stdout').read_text().splitlines(), name)
                row['passed'] = True
            except (ValueError, OSError, UnicodeError) as error:
                row['failure'] = str(error)
                result['failures'].append(name + ': ' + str(error))
            print(json.dumps(row, sort_keys=True), flush=True)
            require(observed['timed_out'] is False, 'NATIVE_TIMEOUT_STOPS_CAMPAIGN')
        result['binary_sha256_after'] = digest(binary.read_bytes())
        require(result['binary_sha256_before'] == result['binary_sha256_after']
                == digest((out / TARGET).read_bytes()), 'NATIVE_BINARY_CHANGED')
        result['all_named_tests_passed'] = len(result['runs']) == len(TESTS) and all(r['passed'] for r in result['runs'])
        for key, validator in (
                ('service_report', validate_service_report),
                ('sustained_report', validate_sustained_report),
                ('confirmation_report', validate_confirmation_report)):
            stage = terminal['acceptance_stages'][key]
            stage['status'] = 'invoked_without_terminal'
            stage['before_validation'] = report_file_identity(out / stage['path'])
            try:
                result[key] = validator(out / stage['path'])
            except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
                stage.update(status='failed', error=str(error))
                raise  # Preserve the original error and stop the same later stages.
            stage['status'] = 'passed'
        # v3 compatibility: this means the original sequence including report
        # validation reached its end, not that a child is still alive otherwise.
        result['execution_finished'] = True
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        result['failures'].append(str(error))
    finally:
        if previous_output is None:
            os.environ.pop('TRNM_PUBLIC_V3_FROM_ZERO_DIR', None)
        else:
            os.environ['TRNM_PUBLIC_V3_FROM_ZERO_DIR'] = previous_output
        if previous_confirmation_output is None:
            os.environ.pop('TRNM_PUBLIC_V3_CONFIRMATION_DIR', None)
        else:
            os.environ['TRNM_PUBLIC_V3_CONFIRMATION_DIR'] = previous_confirmation_output
        if (out / 'confirmation/report.json').exists():
            try:
                result['confirmation_observation'] = summarize_confirmation_report(out / 'confirmation/report.json')
            except (OSError, ValueError, TypeError, KeyError) as error:
                result['failures'].append('CONFIRMATION_OBSERVATION: ' + str(error))
        try:
            result['source_after'] = source_identity()
        except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
            result['failures'].append(str(error))
        # Retain report identities independently of acceptance, including files
        # whose validator failed or was never reached. Keep the before-validation
        # snapshot separately; validated summaries retain their own exact hashes.
        for stage in terminal['acceptance_stages'].values():
            stage['retained_report'] = report_file_identity(out / stage['path'])
            before = stage['before_validation']
            if before is not None and before['sha256'] is not None:
                stage['retained_matches_before_validation'] = (
                    before['sha256'] == stage['retained_report']['sha256'])
        try:
            for row in result['runs']:
                for channel in ('stdout', 'stderr'):
                    require(digest((out / row['name'] / channel).read_bytes()) == row[channel + '_sha256'],
                            'NATIVE_LOG_CHANGED')
            if result['service_report'] is not None:
                require(digest((out / 'native/report.json').read_bytes()) == result['service_report']['sha256'],
                        'NATIVE_SERVICE_REPORT_CHANGED')
            if result['sustained_report'] is not None:
                require(digest((out / 'native/sustained/report.json').read_bytes()) == result['sustained_report']['sha256'],
                        'SUSTAINED_REPORT_CHANGED')
            if result['confirmation_report'] is not None:
                require(digest((out / 'confirmation/report.json').read_bytes()) == result['confirmation_report']['sha256'],
                        'CONFIRMATION_REPORT_CHANGED')
            if result['confirmation_observation'] is not None:
                require(digest((out / 'confirmation/report.json').read_bytes())
                        == result['confirmation_observation']['sha256'], 'CONFIRMATION_OBSERVATION_CHANGED')
            result['files'] = {p.relative_to(out).as_posix(): digest(p.read_bytes())
                               for p in sorted(out.rglob('*'))
                               if p.is_file() and p != out / 'manifest.json'}
        except (OSError, ValueError) as error:
            result['failures'].append(str(error))
        finally:
            os.chdir(previous_cwd)
        # A failed format check is a named gate failure even when every
        # native test ran successfully. Keep the actual build/test receipts.
        if result.get('format') is not None and not result['format_passed']:
            result['failures'].append('NATIVE_FORMAT_CHECK_FAILED')
        result['passed'] = (result['source_before'] == result['source_after']
                            and result['source_recompiled'] and result['format_passed']
                            and result['all_named_tests_passed'] and result['execution_finished']
                            and result['service_report'] is not None and result['sustained_report'] is not None
                            and result['confirmation_report'] is not None
                            and not result['failures'])
        terminal['native_execution_completed'] = all(
            row['status'] == 'returned' and type(row['exit_code']) is int and row['timed_out'] is False
            for row in terminal['native_invocations'])
        terminal['unexecuted_native_tests'] = [
            row['name'] for row in terminal['native_invocations'] if row['status'] == 'not_executed']
        terminal['unexecuted_acceptance_stages'] = [
            key for key, stage in terminal['acceptance_stages'].items()
            if stage['status'] == 'not_executed']
        terminal['acceptance_passed'] = result['passed']
        terminal['finalization_completed'] = True
        save_manifest(out, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--out', type=Path)
    action.add_argument('--summarize-confirmation', type=Path,
                        help='read an original raw report, retaining business failures and missing samples')
    parser.add_argument('--observation-version', type=int, choices=(1, 2), default=2,
                        help='read-only summary schema; v1 reproduces historical output, default v2 retains complete outcome coverage')
    args = parser.parse_args(argv)
    if args.summarize_confirmation is not None:
        observation = summarize_confirmation_report(args.summarize_confirmation,
                                                     observation_version=args.observation_version)
        print(json.dumps(observation, indent=2, sort_keys=True))
        return 0 if observation['original_gate_validated'] else 1
    if args.observation_version != 2:
        parser.error('--observation-version 1 is only for --summarize-confirmation historical readback')
    receipt = run(args.out)
    print(json.dumps({'passed': receipt['passed'], 'failures': receipt['failures']}))
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
