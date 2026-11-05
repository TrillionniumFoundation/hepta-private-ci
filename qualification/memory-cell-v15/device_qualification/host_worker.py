"""Controller-relayed two-host protocol fixture. No network listener or training.

Each invocation is a new process. The authority.py bytes are copied unchanged from
V15. Private Ed25519 keys are generated and retained only on their owning host.
The matrix calculation is a finite integer fixture, not language-model evidence.
"""

import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import resource
import sys
import time
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption

START = time.perf_counter()
STEP = sys.argv[1]
PARAMS = json.loads(sys.stdin.read())
WORK = None


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(name, data):
    path = WORK / name
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(WORK, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def write_json(name, value):
    save(name, encoded(value))


def read_json(name):
    return json.loads((WORK / name).read_bytes())


def private(name):
    return Ed25519PrivateKey.from_private_bytes((WORK / (name + '.key')).read_bytes())


def environment():
    import cryptography
    import sqlite3
    return dict(platform=platform.system(), arch=platform.machine(), python=platform.python_version(),
                crypto=cryptography.__version__, sqlite=sqlite3.sqlite_version,
                node_digest=sha(platform.node().encode()))


def signature(key, value):
    return dict(value, signature=key.sign(encoded(value)).hex())


def receipt_check(value, expected_public):
    assert value['authority'] == expected_public, 'receipt authority mismatch'
    payload = {k: v for k, v in value.items() if k != 'signature'}
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(expected_public)).verify(
        bytes.fromhex(value['signature']), encoded(payload))


def verified(item):
    from authority import COMPONENTS
    assert sha(encoded(item['manifest'])) == item['id'], 'bundle id mismatch'
    assert set(item['objects']) == set(item['manifest']['components']) == COMPONENTS
    objects = {k: bytes.fromhex(v) for k, v in item['objects'].items()}
    assert all(sha(v) == item['manifest']['components'][k] for k, v in objects.items())
    return objects


def calculate(item):
    objects = verified(item)
    assert objects['runtime'] == b'integer-matrix-v1'
    model, memory = json.loads(objects['model']), json.loads(objects['memory'])
    assert model['kind'] == 'integer-matrix-v1'
    assert all(type(v) is int for row in model['weights'] for v in row)
    assert all(type(v) is int for row in memory['inputs'] for v in row)
    outputs = [[sum(w * x for w, x in zip(row, vector)) + bias
                for row, bias in zip(model['weights'], model['bias'])] for vector in memory['inputs']]
    return dict(outputs=outputs, output_digest=sha(encoded(outputs)), kind='finite-integer-matrix-not-language',
                model_hash=sha(objects['model']), memory_hash=sha(objects['memory']))


def fixture_gate(identifier, parents, manifest, objects):
    from authority import GateDecision
    accepted = objects['runtime'] == b'integer-matrix-v1' and json.loads(objects['model'])['kind'] == 'integer-matrix-v1'
    return GateDecision(identifier, parents, accepted, sha(b'lifecycle-fixture-only-no-quality-or-net-benefit-claim'))


def authority():
    from authority import Authority, public
    return Authority(WORK / 'authority.sqlite', private('service'), public(private('admin')), fixture_gate)


def invoke(service, key_name, operation, arguments, suffix):
    from authority import sign
    return service.apply(sign(private(key_name), service.identity, operation, arguments, CONTEXT['run_id'] + '-' + suffix))


def execute():
    global WORK, CONTEXT
    if STEP == 'setup':
        run_id, role = PARAMS['run_id'], PARAMS['role']
        assert re.fullmatch(r'hepta-v15-[a-f0-9]{16}', run_id) and role in ('source', 'target')
        WORK = Path('/tmp') / (run_id + '-' + role)
        os.mkdir(WORK, 0o700)  # Exclusive creation; collisions fail rather than reuse.
        for name in ('authority', 'host_worker'):
            data = base64.b64decode(PARAMS[name + '_base64'], validate=True)
            assert sha(data) == PARAMS[name + '_sha256'], name + ' source mismatch'
            save(name + '.py', data)
        sys.path.insert(0, str(WORK))
        from authority import public
        keys = ('service', 'admin', 'owner') if role == 'source' else ('owner',)
        pubs = {}
        for name in keys:
            key = Ed25519PrivateKey.generate()
            save(name + '.key', key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))
            pubs[name] = public(key)
        CONTEXT = dict(run_id=run_id, role=role, public=pubs, authority_sha256=PARAMS['authority_sha256'],
                       worker_sha256=PARAMS['host_worker_sha256'])
        write_json('context.json', CONTEXT)
        return dict(context=CONTEXT, directory_mode=oct(WORK.stat().st_mode & 0o777),
                    key_modes={k: oct((WORK / (k + '.key')).stat().st_mode & 0o777) for k in keys},
                    private_keys_exported=False, directory_kind='isolated-temporary')
    WORK = Path(__file__).resolve().parent
    CONTEXT = read_json('context.json')
    assert sha((WORK / 'authority.py').read_bytes()) == CONTEXT['authority_sha256'], 'authority source changed'
    assert sha((WORK / 'host_worker.py').read_bytes()) == CONTEXT['worker_sha256'], 'worker source changed'
    from authority import COMPONENTS, Rejected, bundle, public, sign, verify
    if STEP == 'bootstrap':
        assert CONTEXT['role'] == 'source'
        CONTEXT.update(target_public=PARAMS['target_public'], scope=CONTEXT['run_id'], cell='cell', transfer='transfer')
        write_json('context.json', CONTEXT)
        service = authority()
        model = dict(kind='integer-matrix-v1', weights=[[1, 2], [-1, 3]], bias=[0, 1])
        memory = dict(inputs=[[3, 4], [5, -2], [0, 7]], scope='synthetic')
        source = invoke(service, 'admin', 'source', dict(scope=CONTEXT['scope'], id='memory-input', expected_revision=0,
                        active=True, body=encoded(memory).decode()), 'source')['result']
        objects = {k: b'explicit-not-trained-fixture-slot' for k in COMPONENTS}
        objects.update(model=encoded(model), memory=encoded(memory), runtime=b'integer-matrix-v1',
                       routing=encoded(dict(address='fixture', mode='exact')), schema=encoded(dict(version=1, inputs='integer-vectors')))
        item = bundle(CONTEXT['scope'], ['fixture'], [public(private('owner')), PARAMS['target_public']],
                      [{k: source[k] for k in ('id', 'revision', 'hash')}], objects)
        created = invoke(service, 'admin', 'create', dict(cell='cell', owner=public(private('owner')), bundle=item), 'create')
        request = sign(private('owner'), service.identity, 'prepare', dict(cell='cell', epoch=1, expected=item['id'],
                       transfer='transfer', target=PARAMS['target_public']), CONTEXT['run_id'] + '-prepare')
        prepared = service.apply(request)
        write_json('bundle.json', item)
        write_json('prepare_request.json', request)
        write_json('prepare_receipt.json', prepared)
        service.close()
        return dict(bundle=item, create_receipt=created, prepare_request=request, prepare_receipt=prepared,
                    source_result=calculate(item), authority_public=CONTEXT['public']['service'],
                    source_public=CONTEXT['public']['owner'], component_bytes=sum(map(len, objects.values())))
    if STEP == 'persist':
        assert CONTEXT['role'] == 'target'
        request, receipt, item = PARAMS['prepare_request'], PARAMS['prepare_receipt'], PARAMS['bundle']
        verify(request, PARAMS['authority_public'])
        assert request['actor'] == PARAMS['source_public'] and request['args']['target'] == public(private('owner'))
        receipt_check(receipt, PARAMS['authority_public'])
        assert receipt['command_hash'] == sha(encoded(request))
        assert receipt['result']['epoch'] == 2 and receipt['result']['bundle'] == item['id']
        objects = verified(item)
        CONTEXT.update(authority_public=PARAMS['authority_public'], source_public=PARAMS['source_public'],
                       cell='cell', transfer='transfer', prepared_epoch=2, bundle_id=item['id'])
        write_json('context.json', CONTEXT)
        write_json('bundle.json', item)
        write_json('prepare_request.json', request)
        write_json('prepare_receipt.json', receipt)
        value = dict(kind='persisted-stage', actor=public(private('owner')), bundle=item['id'],
                     component_bytes=sum(map(len, objects.values())), transport_bytes=len(encoded(item)),
                     file_fsync=True, directory_fsync=True, component_hashes=item['manifest']['components'])
        return dict(stage_receipt=signature(private('owner'), value))
    if STEP == 'cold_ready':
        assert CONTEXT['role'] == 'target'
        item = read_json('bundle.json')
        verified(item)
        result = calculate(item)
        args = dict(cell='cell', transfer='transfer', epoch=2, expected=item['id'])
        ready = sign(private('owner'), CONTEXT['authority_public'], 'ready', dict(args, bundle=item), CONTEXT['run_id'] + '-ready')
        commit = sign(private('owner'), CONTEXT['authority_public'], 'commit', args, CONTEXT['run_id'] + '-commit')
        write_json('ready_request.json', ready)
        write_json('commit_request.json', commit)
        proof = signature(private('owner'), dict(kind='cold-computation', actor=public(private('owner')),
                          bundle=item['id'], result=result, authority_sha256=CONTEXT['authority_sha256']))
        return dict(ready_request=ready, commit_request=commit, cold_result=proof)
    if STEP in ('accept_ready', 'commit', 'accept_publish'):
        assert CONTEXT['role'] == 'source'
        service = authority()
        before = invoke(service, 'admin', 'status', {'cell': 'cell'}, STEP + '-before')['result']
        outcome = service.apply(PARAMS['request'])
        response = dict(before=before, receipt=outcome)
        if STEP == 'commit':
            try:
                invoke(service, 'owner', 'publish', dict(cell='cell', epoch=3, expected=read_json('bundle.json')['id'],
                                                       bundle=read_json('bundle.json')), 'old-owner-after-commit')
                raise AssertionError('old owner unexpectedly accepted')
            except Rejected as exc:
                assert exc.receipt and 'owner' in exc.receipt['reason']
                response['old_owner_rejection'] = exc.receipt
        if STEP == 'accept_publish':
            response['actual_result'] = calculate(PARAMS['request']['args']['bundle'])
        response['after'] = invoke(service, 'admin', 'status', {'cell': 'cell'}, STEP + '-after')['result']
        service.close()
        return response
    if STEP == 'sign_publish':
        assert CONTEXT['role'] == 'target'
        receipt_check(PARAMS['commit_receipt'], CONTEXT['authority_public'])
        assert PARAMS['commit_receipt']['result']['owner'] == public(private('owner'))
        assert PARAMS['commit_receipt']['result']['epoch'] == 3
        old = read_json('bundle.json')
        objects = verified(old)
        model = json.loads(objects['model'])
        model['bias'][0] += 2
        objects['model'] = encoded(model)
        m = old['manifest']
        updated = bundle(m['scope'], m['addresses'], m['acl'], m['sources'], objects)
        request = sign(private('owner'), CONTEXT['authority_public'], 'publish',
                       dict(cell='cell', epoch=3, expected=old['id'], bundle=updated), CONTEXT['run_id'] + '-publish')
        write_json('updated_bundle.json', updated)
        write_json('publish_request.json', request)
        return dict(request=request, target_updated_result=calculate(updated), component_bytes=sum(map(len, objects.values())))
    raise ValueError('unknown step')


try:
    result = execute()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    peak = usage.ru_maxrss if platform.system() == 'Darwin' else usage.ru_maxrss * 1024
    output = dict(ok=True, step=STEP, run_id=CONTEXT['run_id'], role=CONTEXT['role'], pid=os.getpid(),
                  authority_sha256=CONTEXT['authority_sha256'], worker_sha256=CONTEXT['worker_sha256'],
                  environment=environment(), result=result,
                  measured=dict(process_elapsed_s=time.perf_counter()-START, user_cpu_s=usage.ru_utime,
                                system_cpu_s=usage.ru_stime, process_peak_rss_bytes=peak),
                  unmeasured=dict(energy_joules=None, total_device_memory_bytes=None, network_wire_bytes=None,
                                  storage_physical_bytes=None, amortized_training_cost=None, lifecycle_total_cost=None))
    print(encoded(output).decode())
except Exception as exc:
    message = str(exc)
    if WORK is not None:
        message = message.replace(str(WORK), '<isolated-workspace>')
    print(encoded(dict(ok=False, step=STEP, error=type(exc).__name__, reason=message[:256])).decode())
    sys.exit(1)
