"""Local metadata assembly only; all Library calls remain explicit root actions.

No network client, transfer implementation, science import, or automatic retry.
Execution05 port from restored original bytes; no historical receipt relabeling.
Only --publish-ack can publish the supervisor's actual ACK.json.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
BASE = Path('/workspace/scratch/178ced6a501f')
OPS = BASE / 'fullstudy_execution05_ops'
SOURCE = BASE / 'fullstudy_recovery05_git'
OWN = SOURCE / 'operational/parameter_field_recovery05'
LEGACY_OWN = SOURCE / 'operational/parameter_field_recovery04'
EPISODE = 'execution05_backpressure_20261030'
ROOT = OPS / 'root_archive_io'
PYTHON = '/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3'
VENV = str(BASE / 'runtime_recovery_20261030/venv/bin/python')
HELPERS = BASE / 'executor_recovery_20261030T1152/helpers'
ARCHIVE_SHA = 'dfeee33870f3ca429284542cb8ca9ff8c9471a8fc8ff0339c3de251cabf260da'
SUPERVISOR_SHA = 'e91ddc38e374f37c379618cbf89bb05a46e265a5e9865afbe3d47a585934661b'
EXTERNAL_STEP_SHA = 'fb238cd0f28e331a2e9d4ada5950f436a2d31e579fa9fbd8c36cce70404c2b21'
ORIGINAL_ADAPTER_SHA = '81d5adafc692013dfe29855c1d1d5e6fcc07527942e23c7b936d3308cc508183'
HELPER_SHA = {
    'library_download.py': '7a092c11922d14a5c61ce1a9beb7d1d3af89bd22b3eff4549abf79ac28878989',
    'library_file_transfer.py': 'd0385de4b634c4a6d4c26a83b40ee4ff33461e42473ce8c0387460be2465e314',
    'library_hosted_apps.py': '7958642b88cde925aaca036989de1028c0864eb6d82a9cb175ebf9380cb9677b',
    'library_upload.py': '5bc473dadefe1f68ee8797baaed19d6662642d0ea4bcba128fa12938faa0d767',
}
if hashlib.sha256((LEGACY_OWN / 'durable_archive.py').read_bytes()).hexdigest() != ARCHIVE_SHA:
    raise RuntimeError('Frozen durable_archive.py differs')
sys.path.insert(0, str(SOURCE))
from operational.parameter_field_recovery04.durable_archive import descriptor, read, require, verify_ack, verify_descriptor, write_json


def code_identity():
    archive = descriptor(LEGACY_OWN / 'durable_archive.py')
    supervisor = descriptor(OWN / 'supervisor.py')
    require(archive['sha256'] == ARCHIVE_SHA and supervisor['sha256'] == SUPERVISOR_SHA,
            'Frozen operational verifier source differs')
    external = descriptor(LEGACY_OWN / 'external_step.py')
    require(external['sha256'] == EXTERNAL_STEP_SHA, 'Frozen external engineering wrapper differs')
    helpers = [descriptor(HELPERS / name) for name in sorted(HELPER_SHA)]
    require(all(item['sha256'] == HELPER_SHA[Path(item['path']).name] for item in helpers),
            'Official helper bytes differ from the actual restored helper pins')
    return {'metadata_helper': descriptor(__file__), 'frozen_archive': archive,
            'frozen_supervisor': supervisor, 'frozen_external_step': external,
            'official_library_helpers': helpers}


def stable_process_identity(value):
    return {key: value[key] for key in ('pid', 'start_ticks', 'process_group', 'session')}


def path_in(path, parent):
    p = Path(path).absolute()
    require(p == p.resolve() and p.is_relative_to(parent), 'Path is outside its bound directory or aliases it')
    return p


def same_or_write(path, value):
    if path.exists():
        require(read(path) == value, 'Existing immutable metadata differs: ' + str(path))
        return descriptor(path)
    return write_json(path, value)


def request_value(desc):
    require(set(desc) == {'path', 'bytes', 'sha256'}, 'Use the exact three-field REQUEST descriptor')
    p = path_in(desc['path'], OPS / 'durable')
    require(p.name == 'REQUEST.json', 'Expected a real stage REQUEST.json')
    verify_descriptor(desc)
    req = read(p)
    require(req.get('schema') == 'hepta.fullstudy.library-archive-request.1'
            and req.get('state') == 'AWAITING_EXTERNAL_UPLOAD_AND_REMOTE_READBACK'
            and req.get('required_ack_schema') == 'hepta.fullstudy.library-archive-ack.1',
            'Unsupported or inactive archive request')
    require(req.get('binding', {}).get('execution_episode') == EPISODE, 'Archive request belongs to another execution episode')
    require(isinstance(req.get('items'), list) and bool(req['items']), 'Empty request')
    names = set()
    for item in req['items']:
        q = path_in(item['path'], p.parent)
        require(q.parent == p.parent and q.name not in names, 'Ambiguous archive item path')
        names.add(q.name)
    return req


def awaiting(desc, req):
    require(not (OPS / 'FAILED.json').exists() and not (OPS / 'COMPLETE.json').exists(),
            'Pipeline failed or completed; do not continue this handoff')
    status = read(OPS / 'STATUS.json')
    ack = str(Path(desc['path']).parent / 'ACK.json')
    require(status.get('schema') == 'hepta.fullstudy.execution05-status.1'
            and status.get('execution_episode') == req['binding']['execution_episode']
            and status.get('awaiting_durable') == {'request': desc, 'ack_path': ack},
            'Current supervisor awaiting REQUEST does not exactly match')
    require(not Path(ack).exists(), 'Actual ACK already exists; reconcile instead of publishing again')
    return Path(ack), status


def work_bound(directory):
    work = path_in(directory, ROOT)
    require(work != ROOT, 'Use a separate new directory for each actual stage')
    bound = read(work / 'BOUND_REQUEST.json')
    require(bound.get('execution_code') == code_identity(), 'Bound operational/helper code changed')
    req = request_value(bound['request'])
    require(bound['work_directory'] == str(work), 'Work directory binding differs')
    _, status = awaiting(bound['request'], req)
    require(stable_process_identity(status['identity']) == bound['supervisor_identity'],
            'Supervisor identity differs from this stage binding')
    return work, bound, req


def publish_liveness(status, bound):
    # Only this publication path imports the pinned, pure-stdlib supervisor.
    require(bound['execution_code'] == code_identity(), 'Operational code changed before ACK publication')
    from operational.parameter_field_recovery05.supervisor import process_identity, require_matching_proc_namespace
    require_matching_proc_namespace()
    expected = bound['supervisor_identity']
    require(status.get('pid') == expected['pid']
            and stable_process_identity(status['identity']) == expected,
            'Current STATUS belongs to another supervisor')
    actual = process_identity(expected['pid'])
    require(stable_process_identity(actual) == expected and actual['state'] not in ('Z', 'X', 'x'),
            'Original supervisor is missing, reused, or no longer alive')
    caller_namespace = os.readlink('/proc/self/ns/pid')
    supervisor_namespace = os.readlink('/proc/%s/ns/pid' % expected['pid'])
    require(caller_namespace == supervisor_namespace, 'ACK publisher must share the original host PID namespace')
    return {'schema': 'hepta.execution05.ack-publish-liveness.1',
        'at_utc': datetime.now(timezone.utc).isoformat(), 'request': bound['request'],
        'expected_supervisor_identity': expected, 'observed_supervisor_identity': actual,
        'publisher_identity': process_identity(os.getpid()), 'pid_namespace': caller_namespace,
        'matching_proc_namespace_verified': True, 'frozen_supervisor': bound['execution_code']['frozen_supervisor']}


def step(wait4_path, argv, stdin_desc, stdout_path=None):
    wdesc = descriptor(wait4_path)
    value = read(wait4_path)
    require(not Path(wait4_path).with_name('FAILED.json').exists(), 'Helper failure receipt exists')
    require(value.get('schema') == 'hepta.execution04.root-engineering-wait4.1'
            and value.get('complete') is True and value.get('command_success') is True
            and value.get('child', {}).get('exit_code') == 0, 'Measured helper did not complete successfully')
    verify_descriptor(value['intent'])
    intent = read(value['intent']['path'])
    require(intent.get('schema') == 'hepta.execution04.root-engineering-intent.1'
            and intent.get('argv') == argv and intent.get('stdin') == stdin_desc
            and intent.get('cwd') == str(OPS / 'empty_cwd')
            and intent.get('automatic_retry') is False, 'Helper command or stdin binding differs')
    verify_descriptor(stdin_desc)
    output = verify_descriptor(value['stdout'])
    verify_descriptor(value['stderr'])
    if stdout_path is not None:
        require(output['path'] == str(Path(stdout_path).absolute()), 'Upload stdout path differs from WAIT4')
    return wdesc, output


def remote(row):
    for key in ('file_id', 'file_name', 'library_file_id'):
        require(isinstance(row.get(key), str) and bool(row[key]), 'Missing actual Library identity: ' + key)
    require(Path(row['file_name']).name == row['file_name'] and row['file_name'] not in ('.', '..'),
            'Library filename is not a basename')
    version = row.get('current_version_number')
    require(type(version) is int and version >= 0, 'Actual current_version_number is required; zero is valid')
    return {key: row[key] for key in ('file_id', 'file_name', 'library_file_id')} | {'version': version}


def upload_evidence(work, bound, req, wait4_path, stdout_path=None):
    upload = descriptor(work / 'UPLOAD_REQUEST.json')
    expected = {'uploads': [{'local_path': x['path'], 'purpose': 'create_library_file',
                 'library_artifact_type': 'other', 'directory_id': bound['directory_id']} for x in req['items']]}
    require(read(upload['path']) == expected, 'Ordered upload request changed')
    argv = [PYTHON, '-B', str(HELPERS / 'library_upload.py')]
    wdesc, stdout = step(wait4_path, argv, upload, stdout_path)
    result = read(stdout['path'])
    rows = result.get('results')
    require(isinstance(rows, list) and len(rows) == len(req['items']), 'Upload result count differs')
    verified, ids = [], set()
    for item, row in zip(req['items'], rows):
        require(row.get('local_path') == item['path'] and row.get('purpose') == 'create_library_file'
                and row.get('status') == 'succeeded' and row.get('local_metadata_applied') is True,
                'An ordered upload item is failed, uncertain, or missing local metadata')
        identity = remote(row)
        require(identity['library_file_id'] not in ids, 'Duplicate Library identity in upload results')
        ids.add(identity['library_file_id'])
        verify_descriptor(item)
        require(os.getxattr(item['path'], 'user.library-file-id').decode() == identity['library_file_id'],
                'Original upload local identity xattr differs')
        verified.append({'local': item, 'remote_identity': identity})
    return {'schema': 'hepta.execution05.root-upload-verified.1', 'request': bound['request'],
            'upload_request': upload, 'upload_wait4': wdesc, 'upload_stdout': stdout, 'items': verified}


def prepare_upload(args):
    desc = read(args.request_descriptor)
    req = request_value(desc)
    _, status = awaiting(desc, req)
    require(isinstance(args.directory_id, str) and bool(args.directory_id.strip()), 'Actual returned directory_id required')
    work = path_in(args.work_directory, ROOT)
    require(work != ROOT and not work.exists(), 'Each stage requires a new work directory')
    for item in req['items']:
        verify_descriptor(item)
    work.mkdir(parents=True, mode=0o700, exist_ok=False)
    bound = {'schema': 'hepta.execution05.root-archive-binding.1', 'request': desc,
             'request_descriptor_input': descriptor(args.request_descriptor),
             'execution_code': code_identity(), 'supervisor_identity': stable_process_identity(status['identity']),
             'directory_id': args.directory_id, 'work_directory': str(work)}
    write_json(work / 'BOUND_REQUEST.json', bound)
    result = write_json(work / 'UPLOAD_REQUEST.json', {'uploads': [
        {'local_path': x['path'], 'purpose': 'create_library_file', 'library_artifact_type': 'other',
         'directory_id': args.directory_id} for x in req['items']]})
    print(json.dumps({'upload_request': result, 'item_count': len(req['items']), 'remote_calls_performed': 0}))


def prepare_readback(args):
    work, bound, req = work_bound(args.work_directory)
    evidence = upload_evidence(work, bound, req, args.upload_wait4, args.upload_stdout)
    destination = work / 'readback'
    require(not destination.exists() or not any(destination.iterdir()), 'Use a fresh readback directory')
    calls = {'items': [{k: x['remote_identity'][k] for k in ('file_id', 'file_name', 'library_file_id')}
                       for x in evidence['items']], 'destination': {'directory': str(destination)}}
    require(1 <= len(calls['items']) <= 20, 'One prepare_materialize call supports at most 20 items')
    evidence['materialize_destination'] = str(destination)
    same_or_write(work / 'UPLOAD_VERIFIED.json', evidence)
    result = same_or_write(work / 'MATERIALIZE_ARGS.json', calls)
    print(json.dumps({'materialize_arguments': result, 'item_count': len(calls['items']),
                      'versions_preserved_in': str(work / 'UPLOAD_VERIFIED.json'), 'remote_calls_performed': 0}))


def materialize_payload(path):
    result = read(path)
    require(result.get('isError') is not True, 'Materialization tool reported an error')
    payload = result.get('structuredContent')
    if payload is None:
        blocks = [x['text'] for x in result.get('content', []) if x.get('type') == 'text']
        require(len(blocks) == 1, 'No unambiguous complete materialization result')
        payload = json.loads(blocks[0])
    require(isinstance(payload, dict), 'Materialization payload is not an object')
    payload = payload.get('result', payload)
    require(isinstance(payload, dict) and not payload.get('unavailable_items'), 'Materialization has unavailable items')
    require(not payload.get('warnings'), 'Materialization warnings require root reconciliation')
    return payload


def prepare_transfers(args):
    work, bound, req = work_bound(args.work_directory)
    saved = read(work / 'UPLOAD_VERIFIED.json')
    current = upload_evidence(work, bound, req, saved['upload_wait4']['path'], saved['upload_stdout']['path'])
    current['materialize_destination'] = saved['materialize_destination']
    require(current == saved, 'Verified upload evidence changed')
    payload = materialize_payload(args.materialize_receipt)
    transfers = payload.get('transfers')
    require(isinstance(transfers, list) and len(transfers) == len(saved['items']), 'Transfer count differs')
    by_id = {x.get('library_file_id'): x for x in transfers}
    require(len(by_id) == len(transfers), 'Duplicate transfer Library identities')
    dest = path_in(saved['materialize_destination'], work)
    jobs = []
    for index, item in enumerate(saved['items']):
        expected = item['remote_identity']
        require(expected['library_file_id'] in by_id, 'Expected Library identity missing from transfers')
        transfer = by_id[expected['library_file_id']]
        require(remote(transfer) == expected, 'Materialized file/version differs from the exact upload result')
        if 'size_bytes' in transfer:
            require(transfer['size_bytes'] == item['local']['bytes'], 'Transfer size differs')
        if transfer.get('workspace_path'):
            output = path_in(transfer['workspace_path'], dest)
            action = 'apply-xattrs'
        else:
            require(isinstance(transfer.get('download_url'), str) and bool(transfer['download_url']),
                    'Transfer has neither actual workspace bytes nor a signed download')
            output, action = dest / expected['file_name'], 'materialize'
        require(output.name == expected['file_name'], 'Readback basename differs from returned filename')
        transfer_desc = same_or_write(work / 'transfers' / ('%03d.json' % index), transfer)
        argv = [PYTHON, '-B', str(HELPERS / 'library_file_transfer.py'), action, str(output)]
        directory = work / 'readback_steps' / ('%03d' % index)
        jobs.append({'index': index, **item, 'transfer': transfer_desc, 'helper_argv': argv,
            'expected_output_path': str(output), 'wait4_path': str(directory / 'WAIT4.json'),
            'external_step_argv': [VENV, '-B', str(LEGACY_OWN / 'external_step.py'), '--directory', str(directory),
                '--cwd', str(OPS / 'empty_cwd'), '--stdin-file', transfer_desc['path'], '--', *argv]})
    plan = {'schema': 'hepta.execution05.root-readback-helper-plan.1', 'request': bound['request'],
        'upload_verified': descriptor(work / 'UPLOAD_VERIFIED.json'),
        'materialize_arguments': descriptor(work / 'MATERIALIZE_ARGS.json'),
        'materialize_receipt': descriptor(args.materialize_receipt), 'items': jobs,
        'root_executes_official_helpers_explicitly': True, 'automatic_retry': False}
    result = same_or_write(work / 'READBACK_PLAN.json', plan)
    print(json.dumps({'readback_plan': result, 'item_count': len(jobs), 'remote_calls_performed': 0}))


def make_ack(args):
    work, bound, req = work_bound(args.work_directory)
    saved = read(work / 'UPLOAD_VERIFIED.json')
    evidence = upload_evidence(work, bound, req, saved['upload_wait4']['path'], saved['upload_stdout']['path'])
    evidence['materialize_destination'] = saved['materialize_destination']
    require(evidence == saved, 'Upload evidence changed before ACK')
    plan = read(work / 'READBACK_PLAN.json')
    require(plan['request'] == bound['request'] and len(plan['items']) == len(req['items']), 'Readback plan binding differs')
    for key in ('upload_verified', 'materialize_arguments', 'materialize_receipt'):
        verify_descriptor(plan[key])
    payload = materialize_payload(plan['materialize_receipt']['path'])
    actual_transfers = {x['library_file_id']: x for x in payload['transfers']}
    require(len(payload['transfers']) == len(actual_transfers) == len(req['items']),
            'Materialization identity count changed or contains duplicates')
    ack_items = []
    for expected, uploaded, job in zip(req['items'], saved['items'], plan['items']):
        require(job['local'] == expected and job['remote_identity'] == uploaded['remote_identity'],
                'Ordered readback plan differs')
        verify_descriptor(job['transfer'])
        transfer = read(job['transfer']['path'])
        require(transfer == actual_transfers[job['remote_identity']['library_file_id']]
                and remote(transfer) == job['remote_identity'], 'Transfer object or version changed')
        expected_action = 'apply-xattrs' if transfer.get('workspace_path') else 'materialize'
        expected_output = transfer.get('workspace_path') or str(Path(saved['materialize_destination']) / transfer['file_name'])
        output_path = path_in(expected_output, Path(saved['materialize_destination']))
        argv = [PYTHON, '-B', str(HELPERS / 'library_file_transfer.py'), expected_action, str(output_path)]
        require(job['helper_argv'] == argv and job['expected_output_path'] == str(output_path), 'Official helper plan changed')
        wait4, stdout = step(job['wait4_path'], argv, job['transfer'])
        require(Path(stdout['path']).read_text().strip() == str(output_path), 'Official helper did not return its exact output path')
        actual = verify_descriptor({'path': str(output_path), 'bytes': expected['bytes'], 'sha256': expected['sha256']})
        a, b = os.stat(actual['path']), os.stat(expected['path'])
        require(output_path.resolve() != Path(expected['path']).resolve()
                and (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino), 'Readback is source or hardlink')
        identity = remote(transfer)
        require(os.getxattr(output_path, 'user.library-file-id').decode() == identity['library_file_id'],
                'Readback Library identity xattr is missing or differs')
        ack_items.append({'local': expected, 'upload_item_success': True, 'remote_readback_performed': True,
            'remote_identity': job['remote_identity'], 'readback_remote_identity': identity,
            'upload_receipt': saved['upload_stdout'], 'readback_receipt': plan['materialize_receipt'],
            'readback': actual, 'upload_wait4': saved['upload_wait4'], 'readback_helper_wait4': wait4,
            'readback_helper_stdout': stdout, 'complete_transfer_receipt': job['transfer'],
            'library_file_id_xattr_verified': identity['library_file_id']})
    ack = {'schema': req['required_ack_schema'], 'status': 'VERIFIED_REMOTE_READBACK',
        'unknown_upload_outcome': False, 'request': bound['request'], 'binding': req['binding'], 'items': ack_items,
        'root_operational_binding': descriptor(work / 'BOUND_REQUEST.json'),
        'remote_identity_trust_boundary': 'Actual official Library tool/helper receipts supplied by root; local verifier does not authenticate the service'}
    candidate = work / 'ACK_CANDIDATE.json'
    same_or_write(candidate, ack)
    checked = verify_ack(candidate, bound['request'])
    checked_desc = same_or_write(work / 'ACK_CANDIDATE_VERIFIED.json', checked)
    result = {'candidate': descriptor(candidate), 'frozen_verification': checked_desc, 'actual_ack_published': False}
    if args.publish_ack:
        # Recheck the live handoff after all potentially long byte verification.
        actual_ack, status = awaiting(bound['request'], req)
        liveness = publish_liveness(status, bound)
        result['publish_liveness'] = write_json(work / 'ACK_PUBLISH_LIVENESS.json', liveness)
        result['actual_ack'] = write_json(actual_ack, ack)
        result['actual_ack_published'] = True
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare-upload')
    p.add_argument('--request-descriptor', required=True)
    p.add_argument('--directory-id', required=True)
    p.add_argument('--work-directory', required=True)
    p.set_defaults(run=prepare_upload)
    p = sub.add_parser('prepare-readback')
    p.add_argument('--work-directory', required=True)
    p.add_argument('--upload-wait4', required=True)
    p.add_argument('--upload-stdout', required=True)
    p.set_defaults(run=prepare_readback)
    p = sub.add_parser('prepare-transfers')
    p.add_argument('--work-directory', required=True)
    p.add_argument('--materialize-receipt', required=True)
    p.set_defaults(run=prepare_transfers)
    p = sub.add_parser('ack')
    p.add_argument('--work-directory', required=True)
    p.add_argument('--publish-ack', action='store_true')
    p.set_defaults(run=make_ack)
    args = parser.parse_args()
    args.run(args)


if __name__ == '__main__':
    main()
