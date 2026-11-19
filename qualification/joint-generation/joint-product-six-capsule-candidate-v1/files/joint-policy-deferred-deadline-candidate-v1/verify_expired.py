"""Saved-only verifier for this expired, zero-prefix cancellation qualification.

Pure stdlib; no liveness parser, fake time, model, mutable Attempt or grant. The
caller supplies trusted exact request/artifact/reference pins. File verification
assumes a cooperating writer has terminated; this is not a hostile-FS TOCTOU or
production authentication guarantee. verify_records validates detached evidence.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import sys

MAX_BYTES = 2 * 2**20
PROFILE = 'fashion-j-actor-selective-v1'
POLICY = 'actor-J-v1'
FILES = ('claim.json', 'reserved.json', 'generated.json',
         'control-observed.json', 'cancel-intent.json', 'cancelled.json',
         'control-ack.json')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('ascii')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _keys(value, keys, what):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(what + ' schema')


def _eq(value, expected, what):
    if canonical(value) != canonical(expected):
        raise ValueError(what)


def _int(value, low=0, high=2**63 - 1):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('strict integer bound')
    return value


def _digest(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('strict digest')
    return value


def _id(value):
    if type(value) is not str or re.fullmatch('[A-Za-z0-9][A-Za-z0-9:._/-]{0,127}', value) is None:
        raise ValueError('strict request identity')
    return value


def _instance(value):
    if type(value) is not list or len(value) != 2:
        raise ValueError('root instance schema')
    for item in value:
        _int(item)
    return value


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


def _bad_constant(value):
    raise ValueError('nonfinite JSON constant')


def _parse(raw, maximum=MAX_BYTES):
    if type(raw) is not bytes or not 1 <= len(raw) <= maximum:
        raise ValueError('bounded canonical evidence bytes')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique,
                       parse_constant=_bad_constant)
    if canonical(value) != raw:
        raise ValueError('noncanonical evidence')
    return value


def _rgb(value):
    """Closed 28x28 gray RGB structural profile; reproduces float32 cast."""
    if type(value) is not list or len(value) != 28:
        raise ValueError('28 input rows')
    gray = []
    for row in value:
        if type(row) is not list or len(row) != 28:
            raise ValueError('28 input columns')
        for pixel in row:
            if type(pixel) is not list or len(pixel) != 3:
                raise ValueError('three RGB channels')
            converted = []
            for channel in pixel:
                if type(channel) not in (int, float) or not math.isfinite(channel) or not 0 <= channel <= 1:
                    raise ValueError('finite normalized pixel')
                converted.append(struct.unpack('<f', struct.pack('<f', channel))[0])
            if converted[0] != converted[1] or converted[0] != converted[2]:
                raise ValueError('gray replicated RGB')
            gray.append(converted[0])
    order = '<' if sys.byteorder == 'little' else '>'
    raw = struct.pack(order + '784d', *gray)
    return sha(canonical({'dtype': order + 'f8', 'shape': [1, 784], 'sha256': sha(raw)}))


def _derive(raw, artifact_payload, source_freeze):
    """Derive closed structural identity without deciding whether time is live."""
    _digest(source_freeze)
    if type(artifact_payload) is not dict:
        raise ValueError('artifact payload')
    if (artifact_payload.get('schema') != 'paired-content-actor-serving-v1'
            or artifact_payload.get('profile') != PROFILE
            or artifact_payload.get('policy') != POLICY
            or artifact_payload.get('source_freeze') != source_freeze):
        raise ValueError('artifact source/profile binding')
    artifact = sha(canonical(artifact_payload))
    request = _parse(raw, 256 * 2**10)
    _keys(request, ('schema', 'objective_id', 'run_id', 'artifact_sha256',
                    'budget', 'deadline_ns', 'decoding', 'outputs', 'streams',
                    'sync_tolerance_ns'), 'request')
    if request['schema'] != 'hepta.joint-generation.media-envelope.v1':
        raise ValueError('media schema')
    _id(request['objective_id']); _id(request['run_id'])
    if _digest(request['artifact_sha256']) != artifact:
        raise ValueError('request artifact')
    _int(request['deadline_ns'], 1)
    _keys(request['budget'], ('compute_units', 'input_bytes', 'output_bytes'), 'budget')
    _int(request['budget']['compute_units'], 2, 10**9)
    _int(request['budget']['input_bytes'], 9408, 8 * 2**20)
    _int(request['budget']['output_bytes'], 1, 2**20)
    _eq(request['decoding'], {'mode': 'greedy', 'seed': 0}, 'qualified decoding')
    _eq(request['outputs'], ['text', 'image'], 'qualified ordered output modalities')
    _int(request['sync_tolerance_ns'], 0, 10**9)
    if type(request['streams']) is not list or len(request['streams']) != 1:
        raise ValueError('one stream')
    stream = request['streams'][0]
    _keys(stream, ('stream_id', 'modality', 'timing', 'payload'), 'stream')
    _id(stream['stream_id'])
    if stream['modality'] != 'image':
        raise ValueError('image input profile')
    timing = stream['timing']
    _keys(timing, ('clock_id', 'sync_group', 'start_ns', 'end_ns'), 'timing')
    _id(timing['clock_id']); _id(timing['sync_group'])
    if _int(timing['end_ns']) <= _int(timing['start_ns']):
        raise ValueError('media interval')
    payload = stream['payload']
    _keys(payload, ('dtype', 'color_space', 'pixels'), 'image')
    if payload['dtype'] != 'float32' or payload['color_space'] != 'RGB':
        raise ValueError('float32 RGB input')
    pixel_digest = _rgb(payload['pixels'])
    spec = {'objective_id': request['objective_id'], 'run_id': request['run_id'],
            'artifact_sha256': artifact, 'modalities': ['text', 'image'],
            'budget': {key: request['budget'][key] for key in ('compute_units', 'output_bytes')},
            'deadline_ns': request['deadline_ns']}
    identity = {'raw_request_sha256': sha(raw),
                'qualified_request_identity_sha256': sha(PROFILE.encode() + b'\0' + POLICY.encode() + b'\0' + raw),
                'sequence': POLICY, 'spec': spec}
    namespace = sha(canonical({'objective_id': spec['objective_id'], 'run_id': spec['run_id']}))
    return {'identity': identity, 'namespace': namespace, 'artifact_sha256': artifact,
            'spec': spec, 'input_pixels_sha256': pixel_digest}


def expected_identity(raw, artifact_payload, source_freeze):
    """Return only the structurally derived identity dict, never an Attempt."""
    return _derive(raw, artifact_payload, source_freeze)['identity']


def _route(old_route, identity, artifact, pixel_digest, wire):
    if type(old_route) is bytes:
        old_route = _parse(old_route, 8192)
    route = json.loads(canonical(old_route))
    route['artifact_sha256'] = artifact
    route['request_identity_sha256'] = sha(canonical(identity))
    _keys(route, ('schema', 'profile', 'policy', 'request_identity_sha256',
                  'artifact_sha256', 'input_pixels_sha256', 'features',
                  'actor_values', 'selected_index', 'sequence',
                  'executed_actions', 'wire_sha256'), 'route')
    if len(canonical(route)) > 8192 or route['schema'] != 'bound-actor-route-v1' or route['profile'] != PROFILE or route['policy'] != POLICY:
        raise ValueError('route profile')
    if route['input_pixels_sha256'] != pixel_digest or route['wire_sha256'] != sha(wire):
        raise ValueError('route input/wire binding')
    for key, length in (('features', 32), ('actor_values', 3)):
        if type(route[key]) is not list or len(route[key]) != length or any(type(x) is not float or not math.isfinite(x) for x in route[key]):
            raise ValueError('strict finite route vector')
    index = _int(route['selected_index'], 0, 2)
    if index != max(range(3), key=lambda i: route['actor_values'][i]):
        raise ValueError('first-index argmax')
    action = ('T', 'I', 'J')[index]
    _eq(route['executed_actions'], ['J', action], 'route actions')
    if route['sequence'] != 'J' + action:
        raise ValueError('route sequence')
    return route


def verify_records(manifest, manifest_pin, epoch, raw, artifact_payload,
                   source_freeze, actual_root_instance, packet, records,
                   old_wire, old_route):
    """Validate detached complete record bytes, returning an audit summary only."""
    _keys(records, FILES, 'fixed terminal record inventory')
    values = {name: _parse(records[name]) for name in FILES}
    derived = _derive(raw, artifact_payload, source_freeze)
    identity, namespace = derived['identity'], derived['namespace']
    artifact, spec = derived['artifact_sha256'], derived['spec']
    _instance(actual_root_instance); _digest(manifest_pin)
    _keys(manifest, ('schema', 'run_epoch', 'origin_ns', 'deadline_ns',
                     'request_sha256', 'artifact_sha256', 'namespace',
                     'source_freeze', 'root_instance'), 'clock manifest')
    if type(epoch) is not str or re.fullmatch('[0-9a-f]{32}', epoch) is None:
        raise ValueError('external epoch')
    origin, deadline = _int(manifest['origin_ns']), _int(manifest['deadline_ns'], 1)
    if origin >= deadline or deadline != spec['deadline_ns']:
        raise ValueError('manifest request/source/root binding')
    expected_manifest = {'schema': 'local-live-control-v1', 'run_epoch': epoch,
                         'origin_ns': origin, 'deadline_ns': deadline,
                         'request_sha256': sha(raw), 'artifact_sha256': artifact,
                         'namespace': namespace, 'source_freeze': source_freeze,
                         'root_instance': actual_root_instance}
    _eq(manifest, expected_manifest, 'manifest request/source/root binding')
    if sha(canonical(manifest)) != manifest_pin:
        raise ValueError('external manifest pin')
    _eq(values['claim.json'], identity, 'claim identity')
    if type(old_wire) is not bytes or not 1 <= len(old_wire) <= 256 * 2**10:
        raise ValueError('bounded pinned wire')
    route = _route(old_route, identity, artifact, derived['input_pixels_sha256'], old_wire)

    def reference(ref, name):
        _keys(ref, ('namespace', 'name', 'bytes', 'sha256'), 'fixed reference')
        _int(ref['bytes'], 1, MAX_BYTES); _digest(ref['sha256'])
        _eq(ref, {'namespace': namespace, 'name': name,
                  'bytes': len(records[name]), 'sha256': sha(records[name])},
            'generated record binding' if name == 'generated.json' else 'fixed reference bytes/hash: ' + name)

    def snapshot(name, phase, cancelled, known_wire):
        value = values[name]
        _keys(value, ('payload', 'sha256'), 'attempt envelope')
        _digest(value['sha256'])
        payload = value['payload']
        _keys(payload, ('schema', 'identity', 'observed_ns', 'session', 'phase',
                        'reservations', 'wire_hex', 'route', 'next_index',
                        'pending_chunk'), 'attempt payload')
        if sha(canonical(payload)) != value['sha256']:
            raise ValueError('attempt checksum')
        observed = _int(payload['observed_ns'], origin)
        session_payload = {'spec': spec, 'spent': {'controller': 1, 'generator': 1},
                           'prefixes': {'text': '', 'image': ''}, 'cancelled': cancelled}
        expected = {'schema': 'local-actor-route-attempt-v1', 'identity': identity,
                    'observed_ns': observed,
                    'session': {'payload': session_payload, 'sha256': sha(canonical(session_payload))},
                    'phase': phase, 'reservations': 1,
                    'wire_hex': old_wire.hex() if known_wire else None,
                    'route': route if known_wire else None,
                    'next_index': 0, 'pending_chunk': None}
        _eq(payload, expected, 'exact zero-prefix charged snapshot: ' + name)
        return observed

    reserved_ns = snapshot('reserved.json', 'reserved', False, False)
    generated_ns = snapshot('generated.json', 'generated', False, True)
    intent_ns = snapshot('cancel-intent.json', 'generated', False, True)
    final_ns = snapshot('cancelled.json', 'cancelled', True, True)
    if not origin <= reserved_ns < deadline <= generated_ns:
        raise ValueError('reserved live / generated expired chronology')
    _keys(packet, ('ack', 'ack_record', 'final_record'), 'ACK packet')
    ack = packet['ack']
    _keys(ack, ('schema', 'manifest_sha256', 'command_sha256', 'observed_ns',
                'intent_return_ns', 'ack_pre_send_ns', 'observed_record',
                'intent_record', 'final_record'), 'ACK')
    expected_command = {'schema': 'local-cancel-v1', 'manifest_sha256': manifest_pin,
                        'run_epoch': epoch, 'request_sha256': sha(raw),
                        'artifact_sha256': artifact, 'namespace': namespace,
                        'sequence': 1, 'reason': 'deadline_expired'}
    if ack['schema'] != 'local-cancel-ack-v1' or ack['manifest_sha256'] != manifest_pin or ack['command_sha256'] != sha(canonical(expected_command)):
        raise ValueError('deadline command binding')
    observed_ns = _int(ack['observed_ns'], deadline)
    intent_return_ns = _int(ack['intent_return_ns'], deadline)
    ack_pre_send_ns = _int(ack['ack_pre_send_ns'], deadline)
    if not generated_ns <= observed_ns <= intent_ns <= intent_return_ns <= final_ns <= ack_pre_send_ns:
        raise ValueError('generated/observation/intent/final/ACK chronology')
    reference(ack['observed_record'], 'control-observed.json')
    reference(ack['intent_record'], 'cancel-intent.json')
    reference(ack['final_record'], 'cancelled.json')
    reference(packet['ack_record'], 'control-ack.json')
    reference(packet['final_record'], 'cancelled.json')
    _eq(values['control-ack.json'], ack, 'persisted ACK')
    observation = values['control-observed.json']
    _keys(observation, ('identity', 'manifest_sha256', 'message', 'observed_ns',
                        'prior_record'), 'control observation')
    reference(observation['prior_record'], 'generated.json')
    expected_observation = {'identity': identity, 'manifest_sha256': manifest_pin,
                            'message': expected_command, 'observed_ns': observed_ns,
                            'prior_record': observation['prior_record']}
    _eq(observation, expected_observation, 'deadline observation identity/reason')
    return {'schema': 'saved-expired-cancellation-audit-v1', 'phase': 'cancelled',
            'manifest_sha256': manifest_pin, 'run_epoch': epoch,
            'root_instance': list(actual_root_instance), 'namespace': namespace,
            'artifact_sha256': artifact, 'identity_sha256': sha(canonical(identity)),
            'wire_sha256': sha(old_wire), 'route_sha256': sha(canonical(route)),
            'known_prefix_bytes': 0, 'output_bytes': 0, 'spent': {'controller': 1, 'generator': 1},
            'deadline_ns': deadline, 'reserved_ns': reserved_ns,
            'generated_ns': generated_ns, 'observed_ns': observed_ns,
            'intent_ns': intent_ns, 'intent_return_ns': intent_return_ns,
            'cancelled_ns': final_ns, 'ack_pre_send_ns': ack_pre_send_ns,
            'records': {name: {'bytes': len(records[name]), 'sha256': sha(records[name])}
                        for name in FILES},
            'authority': 'none; expired saved evidence only, not publishable recovery'}


def read_records(root_path, namespace):
    """Read bounded canonical-evidence bytes only; does not approve a state."""
    root = Path(root_path)
    _digest(namespace)
    st = os.stat(root, follow_symlinks=False)
    if not stat.S_ISDIR(st.st_mode):
        raise ValueError('regular delivery directory required')
    directory = root / namespace
    dst = os.stat(directory, follow_symlinks=False)
    if not stat.S_ISDIR(dst.st_mode) or {p.name for p in directory.iterdir()} != set(FILES):
        raise ValueError('complete fixed zero-prefix namespace inventory')
    records = {}
    for name in FILES:
        path = directory / name
        item = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(item.st_mode) or not 1 <= item.st_size <= MAX_BYTES:
            raise ValueError('bounded regular evidence file')
        with path.open('rb') as file:
            records[name] = file.read(MAX_BYTES + 1)
        if len(records[name]) != item.st_size:
            raise ValueError('evidence file changed while reading')
    current = os.stat(root, follow_symlinks=False)
    if (current.st_dev, current.st_ino) != (st.st_dev, st.st_ino):
        raise ValueError('delivery root changed')
    return records


def verify(manifest, manifest_pin, epoch, raw, artifact_payload, source_freeze,
           root_path, packet, old_wire, old_route):
    """Read seven bounded fixed files after producer termination, then audit."""
    root = Path(root_path)
    st = os.stat(root, follow_symlinks=False)
    derived = _derive(raw, artifact_payload, source_freeze)
    records = read_records(root, derived['namespace'])
    current = os.stat(root, follow_symlinks=False)
    if (current.st_dev, current.st_ino) != (st.st_dev, st.st_ino):
        raise ValueError('delivery root changed')
    return verify_records(manifest, manifest_pin, epoch, raw, artifact_payload,
                          source_freeze, [st.st_dev, st.st_ino], packet, records,
                          old_wire, old_route)
