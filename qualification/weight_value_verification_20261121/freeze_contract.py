"""Freeze a separate source/input/resource contract using byte reads and metadata only."""
import argparse
import importlib.metadata
from pathlib import Path
import platform
import sys

from stage_contract import (FITS, FORBIDDEN_NEW_WORK, LIMITS, ORIGINAL_PROTOCOL_SHA, ORIGINAL_READER_SHA,
                            OVERRIDES, SCHEMA, SOURCE_FILES, check_execution_admission, embedded_pins, load_json, pin, require, save_new,
                            source_ast_identities, utc, verify_pin)


def main(args):
    old_root, stage_root = args.old_root.resolve(), args.stage_root.resolve()
    source_root = Path(__file__).resolve().parent
    require(source_root.parent == stage_root, 'stage source and output ownership')
    require(not (stage_root / 'attempt001').exists(), 'attempt already consumed')
    output = stage_root / ('PROTOCOL_FROZEN.json' if args.mode == 'freeze' else 'PROTOCOL_DRAFT.json')
    require(not output.exists(), 'contract is create-only')
    protocol_pin = pin(old_root / 'value/PROTOCOL_FROZEN.json')
    require(protocol_pin['sha256'] == ORIGINAL_PROTOCOL_SHA, 'exact original protocol required')
    protocol = load_json(protocol_pin['path'])
    main_root, conf_root, failed_root = (old_root / 'value' / name for name in
                                       ('main_attempt001', 'confirmation_attempt001', 'reader_attempt001'))
    main_result = load_json(main_root / 'output/RESULTS.json')
    conf_result = load_json(conf_root / 'output/RESULTS.json')
    require(main_result['status'] == conf_result['status'] == 'COMPLETED', 'completed original producer results')
    require(not (failed_root / 'output/READER_RESULTS.json').exists(), 'preserve incomplete original reader')
    prior_failure = {key: pin(failed_root / name) for key, name in
                     [('launch', 'LAUNCH.json'), ('process', 'PROCESS.json'), ('failure', 'output/FAILED.json')]}
    require(load_json(prior_failure['process']['path'])['status'] == 'FAILED_OR_UNKNOWN', 'prior failure retained')
    original = dict(protocol=protocol_pin, reader_source=protocol['source_pins']['verify_records.py'],
        main_results=pin(main_root / 'output/RESULTS.json'), main_launch=pin(main_root / 'LAUNCH.json'),
        main_process=pin(main_root / 'PROCESS.json'), selection_seal=main_result['candidate_selection_seal_pin'],
        diagnostics_seal=main_result['diagnostic_seal_pin'], confirmation_results=pin(conf_root / 'output/RESULTS.json'),
        confirmation_launch=pin(conf_root / 'LAUNCH.json'), confirmation_process=pin(conf_root / 'PROCESS.json'),
        entropy=conf_result['entropy_pin'], worlds_seal=conf_result['worlds_seal_pin'], prior_failure=prior_failure,
        analysis_provenance=pin(old_root / 'delivery/aggregation_attempt001/output/ANALYSIS_PROVENANCE.json'),
        proposal=pin(old_root / 'delivery/VERIFICATION_ONLY_NEXT_STEP.json'))
    require(original['reader_source']['sha256'] == ORIGINAL_READER_SHA, 'exact original reader required')
    closure = {}
    def add(expected):
        actual = verify_pin(expected)
        require(actual['path'] not in closure or closure[actual['path']] == actual, 'conflicting input identity')
        closure[actual['path']] = actual
    # Every existing attempt member is bound, including JSON, arrays, graphs,
    # proposals, failures and logs. No array or checkpoint body is deserialized.
    attempt_members = []
    for directory in (main_root, conf_root, failed_root):
        for path in sorted(directory.rglob('*')):
            if path.is_file():
                add(pin(path))
                attempt_members.append(str(path.resolve()))
    for expected in list(embedded_pins(protocol)) + list(embedded_pins(original)):
        add(expected)
    for expected in protocol['review_pins']:
        add(expected)
    require(pin(sys.executable) == protocol['environment']['executable_pin'], 'same Python executable')
    versions = {name: importlib.metadata.version(name) for name in protocol['environment']['packages']}
    require(versions == protocol['environment']['packages'], 'same original package versions')
    evidence = [pin(path) for path in args.evidence]
    require(evidence or args.mode == 'draft', 'freeze requires explicit pre-execution review/qualification evidence')
    sources = {name: pin(source_root / name) for name in SOURCE_FILES}
    admission_pin = pin(args.admission) if args.admission is not None else None
    if args.mode == 'freeze':
        require(admission_pin is not None, 'typed execution admission required')
        check_execution_admission(admission_pin, sources, str(stage_root / 'attempt001'))
    proof = dict(schema='hepta-verification-source-reuse-proof-v1', original_reader_pin=original['reader_source'],
        original_function_AST_sha256=source_ast_identities(original['reader_source']['path']),
        original_main_and_mathematical_functions_rewritten=False,
        only_replaced_module_bindings=list(OVERRIDES), all_original_function_objects_retained=True,
        source_only_loader='Pinned original Python files are compile/exec loaded; no original pyc is consumed.',
        persistence='CONF return only sets pending. Flush occurs at next original main budget boundary or primary entry, after both original CONF-tail chronology checks.',
        no_signal_handler_fit_flush=True, old_resource_contract_modified=False,
        original_result_alone_not_admitted=True)
    proof_path = stage_root / ('SOURCE_REUSE_PROOF.json' if args.mode == 'freeze' else 'SOURCE_REUSE_PROOF_DRAFT.json')
    proof_pin = save_new(proof_path, proof)
    contract = dict(schema=SCHEMA, status='FROZEN' if args.mode == 'freeze' else 'DRAFT_NOT_EXECUTED',
        stage_id='hepta-value-verification-only-20261121-attempt001', created_utc=utc(),
        original=original, original_source_head='4611ddeb4d714708f2de4c6c5bcee4d18d5f368d',
        fits=list(FITS), limits=LIMITS, forbidden_new_work=FORBIDDEN_NEW_WORK,
        allowed_binding_overrides=list(OVERRIDES), mathematics_and_thresholds_unchanged=True,
        source_pins=sources,
        input_closure=sorted(closure.values(), key=lambda item: item['path']),
        original_attempt_members=sorted(attempt_members),
        forbidden_prior_reader_result=str(failed_root / 'output/READER_RESULTS.json'),
        source_reuse_proof=proof_pin, pre_execution_evidence=evidence,
        execution_admission_pin=admission_pin,
        attempt_root=str(stage_root / 'attempt001'), environment=dict(protocol['environment'],
            observed_current_python=sys.version, observed_current_platform=platform.platform(),
            observed_current_package_versions=versions),
        acceptance='Five durable FIT_COMPLETE records, unchanged original global checks, child exit0, parent PROCESS COMPLETED and FINAL_VERIFICATION PASS are all required.',
        original_reader_failure_reclassified=False, production_admission=False,
        further_candidate_search_authorized_by_this_contract=False)
    result = save_new(output, contract)
    print('{"status":"' + contract['status'] + '","input_closure_count":' + str(len(closure)) +
          ',"contract_sha256":"' + result['sha256'] + '","scientific_calls":0}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--old-root', type=Path, required=True)
    parser.add_argument('--stage-root', type=Path, required=True)
    parser.add_argument('--mode', choices=('draft', 'freeze'), required=True)
    parser.add_argument('--evidence', type=Path, action='append', default=[])
    parser.add_argument('--admission', type=Path)
    main(parser.parse_args())
