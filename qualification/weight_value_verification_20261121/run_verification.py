"""Execute the frozen reader checks under a distinct one-shot resource contract."""
import argparse
import os
from pathlib import Path
import resource
import signal
import sys
import time
import traceback
from types import SimpleNamespace

from fit_journal import FitJournal
from source_loader import load_original
from stage_contract import (LIMITS, check_binding_reuse, check_contract, function_bindings,
                            load_json, pin, require, save_new, utc)


def budget_check(journal, start_wall):
    # Pending is set only AFTER original confirmation_fit_check returns. The frozen
    # main has no budget call inside its subsequent two CONF-tail chronology checks.
    journal.flush('budget_after_original_CONF_tail')
    if time.process_time() >= LIMITS['CPU_soft'] or time.perf_counter()-start_wall >= LIMITS['wall_hard']:
        raise TimeoutError('verification-only resource cap; one execution, no retry')


def configure_stage_budget(protocol, start_wall, journal):
    require(protocol['resources']['reader'] == dict(CPU_soft=55, CPU_hard=60, wall_hard=120),
            'original reader contract must remain unchanged')
    require(protocol['resources']['affinity_CPU'] == 7 and
            protocol['resources']['address_space_bytes'] == 536870912, 'original hardware contract')
    os.sched_setaffinity(0, {7})
    resource.setrlimit(resource.RLIMIT_AS, (LIMITS['address_space_bytes'],) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (LIMITS['CPU_soft'], LIMITS['CPU_hard']))
    def exhausted(*unused):
        # A signal can occur inside the chronology tail: never flush a pending fit here.
        raise TimeoutError('verification-only signal resource cap; no retry')
    signal.signal(signal.SIGXCPU, exhausted)
    signal.signal(signal.SIGALRM, exhausted)
    signal.alarm(LIMITS['wall_hard'])
    return lambda: budget_check(journal, start_wall)


def install_wrappers(reader, contract, contract_pin, output):
    original = function_bindings(reader)
    journal = FitJournal(reader, original, contract, contract_pin, output)
    replacements = dict(configure_budget=lambda protocol, start_wall:
                        configure_stage_budget(protocol, start_wall, journal),
                        main_fit_check=journal.main_fit,
                        confirmation_fit_check=journal.confirmation_fit,
                        primary_check=journal.primary)
    for name, function in replacements.items():
        setattr(reader, name, function)
    check_binding_reuse(reader, original, replacements)
    return original, replacements, journal


def main(args):
    started, created = time.perf_counter(), utc()
    contract, contract_pin = check_contract(args.contract)
    require(pin(__file__) == contract['source_pins']['run_verification.py'], 'actual child source identity')
    require(pin(sys.executable) == contract['environment']['executable_pin'], 'actual child interpreter')
    attempt = Path(contract['attempt_root'])
    output = attempt / 'output'
    require(args.output.resolve() == output and attempt.is_dir(), 'only fixed launched destination allowed')
    require(not output.exists(), 'attempt output already exists; no retry')
    launch = load_json(attempt / 'LAUNCH.json')
    require(launch['stage_contract_pin'] == contract_pin and launch['limits'] == LIMITS and
            launch['actual_entry_pin'] == contract['source_pins']['run_verification.py'] and
            launch['actual_supervisor_pin'] == contract['source_pins']['supervise_verification.py'] and
            launch['retry_permitted'] is False, 'matching parent launch required')
    save_new(attempt / 'CHILD_STAGE_STARTED.json', dict(schema='hepta-verification-child-started-v1',
        created_utc=created, stage_contract_pin=contract_pin, original=contract['original'],
        limits=LIMITS, retry_permitted=False))
    reader, original, replacements, journal = None, None, None, None
    try:
        old_protocol = load_json(contract['original']['protocol']['path'])
        reader = load_original(old_protocol['source_pins'])
        original, replacements, journal = install_wrappers(reader, contract, contract_pin, output)
        original['main'](SimpleNamespace(protocol=Path(contract['original']['protocol']['path']),
            main=Path(contract['original']['main_results']['path']).parent,
            confirmation=Path(contract['original']['confirmation_results']['path']).parent,
            output=output))
        check_binding_reuse(reader, original, replacements)
        raw_pin = pin(output / 'READER_RESULTS.json')
        raw_result = load_json(raw_pin['path'])
        fit_receipts = journal.finish(raw_result)
        check_contract(args.contract)
        require(pin(args.contract) == contract_pin, 'new contract changed during execution')
        budget_check(journal, started)
        record = dict(schema='hepta-verification-only-child-results-v1',
            status='VERIFIED_PENDING_PARENT', created_utc=created, completed_utc=utc(),
            stage_contract_pin=contract_pin, original_protocol_pin=contract['original']['protocol'],
            original_reader_source_pin=contract['original']['reader_source'],
            original_failed_reader=contract['original']['prior_failure'],
            source_pins=contract['source_pins'], raw_original_reader_results_pin=raw_pin,
            fit_receipts=fit_receipts, counts=raw_result['counts'],
            mathematical_thresholds_unchanged=True, bindings_reuse_checked=True,
            original_global_source_phase_entropy_exclusion_primary_checks_completed=True,
            resources=dict(CPU_seconds=time.process_time(), wall_seconds_from_entry=time.perf_counter()-started),
            full_PASS_requires_parent_process_COMPLETED=True,
            original_raw_result_alone_is_not_new_stage_acceptance=True,
            existing_native_exporter_compatibility=False,
            new_candidates=0, new_publics=0, new_quality_comparisons=0, production_admission=False)
        save_new(output / 'STAGE_RESULTS.json', record)
        print('{"status":"VERIFIED_PENDING_PARENT","production_admission":false}', flush=True)
    except BaseException as error:
        save_new(attempt / 'STAGE_FAILED.json', dict(schema='hepta-verification-stage-failure-v1',
            status='FAILED', created_utc=utc(), stage_contract_pin=contract_pin,
            error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc(),
            fit_receipts=[] if journal is None else journal.receipts,
            counts=None if reader is None else reader.COUNTS,
            retry_permitted=False, production_admission=False,
            resources=dict(CPU_seconds=time.process_time(), wall_seconds_from_entry=time.perf_counter()-started)))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args())
