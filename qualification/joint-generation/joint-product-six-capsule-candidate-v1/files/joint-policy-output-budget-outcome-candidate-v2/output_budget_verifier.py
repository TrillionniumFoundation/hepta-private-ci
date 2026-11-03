"""Non-authorizing inspection of a known output-budget rejection or reservation.

Only saved bytes and external pins are inspected. No model, Attempt, liveness
parser, inferred retry permission, or diagnostic-result adoption. This function
has no filesystem root argument: root_instance is structurally bound by the
external manifest pin, not freshly stat/host authenticated by this inspector.
"""
import json

from output_budget_pure import (MAX_BYTES, PROFILE, POLICY, canonical, sha,
                               _derive, _route, _parse, _keys, _eq, _int,
                               _digest, _instance, _rgb)

REJECTION_SCHEMA = 'local-output-budget-rejected-v1'
REJECTION_MAX_BYTES = 256 * 2**10
REQUIRED_BYTES = 34808
ALLOWED_BYTES = 34807
WORDS = ('T-shirt/top', 'Trouser', 'Pullover', 'Dress', 'Coat', 'Sandal',
         'Shirt', 'Sneaker', 'Bag', 'Ankle boot')


def _parts_total(wire):
    """Reconstruct the two transport payloads without a transport/model call."""
    value = _parse(wire, 256 * 2**10)
    _keys(value, ('schema', 'rows'), 'pinned output wire')
    if value['schema'] != 'hepta.fashion-mnist.output-batch.v1':
        raise ValueError('output wire schema')
    if type(value['rows']) is not list or len(value['rows']) != 1:
        raise ValueError('one output row required')
    row = value['rows'][0]
    _keys(row, ('text', 'image'), 'output row')
    _keys(row['text'], ('encoding', 'text'), 'output text')
    text = row['text']['text']
    if row['text']['encoding'] != 'utf-8' or type(text) is not str or text not in WORDS:
        raise ValueError('qualified output category text')
    if not 1 <= len(text.encode('utf-8')) <= 4096:
        raise ValueError('output text byte bound')
    _keys(row['image'], ('dtype', 'color_space', 'pixels'), 'output image')
    if row['image']['dtype'] != 'float32' or row['image']['color_space'] != 'RGB':
        raise ValueError('output float32 RGB')
    _rgb(row['image']['pixels'])
    sizes = {mode: len(canonical(row[mode])) for mode in ('text', 'image')}
    return sizes, sum(sizes.values())


def verify(raw_request, artifact_payload, source_freeze, manifest,
           manifest_pin, epoch, reserved_raw, reserved_ref,
           rejection_raw_or_none, old_wire, old_route):
    """Return an audit dict only; even known rejection authorizes no execution.

    The caller independently holds exact raw-request/artifact/reference pins.
    Complete reservation validity is checked before the unknown path returns.
    A present malformed rejection raises rather than being downgraded to unknown.
    """
    derived = _derive(raw_request, artifact_payload, source_freeze)
    identity, spec = derived['identity'], derived['spec']
    artifact, namespace = derived['artifact_sha256'], derived['namespace']
    if spec['budget']['output_bytes'] != ALLOWED_BYTES:
        raise ValueError('fixed request output budget')
    _digest(manifest_pin)
    _keys(manifest, ('schema', 'run_epoch', 'origin_ns', 'deadline_ns',
                     'request_sha256', 'artifact_sha256', 'namespace',
                     'source_freeze', 'root_instance'), 'clock manifest')
    if type(epoch) is not str or len(epoch) != 32 or any(c not in '0123456789abcdef' for c in epoch):
        raise ValueError('external clock epoch')
    origin, deadline = _int(manifest['origin_ns']), _int(manifest['deadline_ns'], 1)
    _instance(manifest['root_instance'])
    if origin >= deadline or deadline != spec['deadline_ns']:
        raise ValueError('request/clock deadline binding')
    expected_manifest = {'schema': 'local-live-control-v1', 'run_epoch': epoch,
                         'origin_ns': origin, 'deadline_ns': deadline,
                         'request_sha256': sha(raw_request), 'artifact_sha256': artifact,
                         'namespace': namespace, 'source_freeze': source_freeze,
                         'root_instance': manifest['root_instance']}
    _eq(manifest, expected_manifest, 'request/source/epoch manifest binding')
    if sha(canonical(manifest)) != manifest_pin:
        raise ValueError('external clock manifest pin')

    reservation = _parse(reserved_raw, MAX_BYTES)
    _keys(reserved_ref, ('namespace', 'name', 'bytes', 'sha256'), 'reserved reference')
    _int(reserved_ref['bytes'], 1, MAX_BYTES); _digest(reserved_ref['sha256'])
    expected_reserved_ref = {'namespace': namespace, 'name': 'reserved.json',
                             'bytes': len(reserved_raw), 'sha256': sha(reserved_raw)}
    _eq(reserved_ref, expected_reserved_ref, 'reserved reference binding')
    _keys(reservation, ('payload', 'sha256'), 'reserved envelope')
    _digest(reservation['sha256'])
    payload = reservation['payload']
    _keys(payload, ('schema', 'identity', 'observed_ns', 'session', 'phase',
                    'reservations', 'wire_hex', 'route', 'next_index',
                    'pending_chunk'), 'reserved payload')
    if sha(canonical(payload)) != reservation['sha256']:
        raise ValueError('reserved checksum')
    reserved_ns = _int(payload['observed_ns'], origin)
    if reserved_ns >= deadline:
        raise ValueError('reserved historical observation expired')
    session_payload = {'spec': spec, 'spent': {'controller': 1, 'generator': 1},
                       'prefixes': {'text': '', 'image': ''}, 'cancelled': False}
    session = {'payload': session_payload, 'sha256': sha(canonical(session_payload))}
    expected_reserved = {'schema': 'local-actor-route-attempt-v1',
                         'identity': identity, 'observed_ns': reserved_ns,
                         'session': session, 'phase': 'reserved', 'reservations': 1,
                         'wire_hex': None, 'route': None, 'next_index': 0,
                         'pending_chunk': None}
    _eq(payload, expected_reserved, 'complete reserved state')
    base = {'schema': 'saved-output-budget-audit-v1', 'authorized': False,
            'may_retry': False, 'model_restore_authorized': False,
            'manifest_sha256': manifest_pin, 'source_freeze': source_freeze,
            'artifact_sha256': artifact, 'identity_sha256': sha(canonical(identity)),
            'namespace': namespace, 'run_epoch': epoch,
            'root_instance': list(manifest['root_instance']),
            'reserved_record': expected_reserved_ref, 'reserved_observed_ns': reserved_ns,
            'deadline_ns': deadline, 'spent': {'controller': 1, 'generator': 1},
            'output_bytes': 0, 'allowed_output_bytes': ALLOWED_BYTES,
            'authority': 'none; saved audit only, no publication/retry permission',
            'root_scope': 'external manifest pin only; no fresh filesystem stat'}
    if rejection_raw_or_none is None:
        return {**base, 'classification': 'model_result_uncommitted_unknown',
                'known_generated_result': False, 'rejection_record': None,
                'diagnostics_adopted': False}

    rejection = _parse(rejection_raw_or_none, REJECTION_MAX_BYTES)
    fields = ('schema', 'identity', 'manifest_sha256', 'reserved_record',
              'session', 'route', 'wire_hex', 'required_output_bytes',
              'allowed_output_bytes', 'observed_ns', 'classification')
    _keys(rejection, fields, 'output rejection')
    if rejection['schema'] != REJECTION_SCHEMA or rejection['classification'] != 'known_generation_publication_rejected':
        raise ValueError('known output-budget rejection classification')
    _eq(rejection['identity'], identity, 'rejection request identity')
    if rejection['manifest_sha256'] != manifest_pin:
        raise ValueError('rejection clock pin')
    _eq(rejection['reserved_record'], expected_reserved_ref, 'rejection reserved reference binding')
    _eq(rejection['session'], session, 'rejection full charged session')
    observed_ns = _int(rejection['observed_ns'], reserved_ns)
    if observed_ns >= deadline:
        raise ValueError('rejection sampled admission expired')
    if type(old_wire) is not bytes or not 1 <= len(old_wire) <= 256 * 2**10:
        raise ValueError('bounded pinned output')
    if type(rejection['wire_hex']) is not str or rejection['wire_hex'] != old_wire.hex():
        raise ValueError('rejection exact generated wire')
    route = _route(old_route, identity, artifact,
                   derived['input_pixels_sha256'], old_wire)
    _eq(rejection['route'], route, 'rejection exact route')
    sizes, required = _parts_total(old_wire)
    allowed = _int(rejection['allowed_output_bytes'], 1, 2**20)
    stated_required = _int(rejection['required_output_bytes'], 1, 2**20)
    if allowed != spec['budget']['output_bytes']:
        raise ValueError('rejection allowed output budget binding')
    if required != REQUIRED_BYTES or stated_required != required or required <= allowed:
        raise ValueError('rejection required payload byte arithmetic')
    return {**base, 'classification': 'known_generation_publication_rejected',
            'known_generated_result': True, 'diagnostics_adopted': False,
            'required_output_bytes': required, 'payload_bytes_by_modality': sizes,
            'wire_bytes': len(old_wire), 'wire_sha256': sha(old_wire),
            'route_sha256': sha(canonical(route)), 'observed_ns': observed_ns,
            'rejection_record': {'namespace': namespace, 'name': 'output-budget-rejected.json',
                                 'bytes': len(rejection_raw_or_none),
                                 'sha256': sha(rejection_raw_or_none)}}
