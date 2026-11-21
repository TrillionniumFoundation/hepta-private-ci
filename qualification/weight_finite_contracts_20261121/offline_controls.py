"""Cache safety controls; no serving demand or numerical model evaluation."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import time
from cache_contract import (CacheRejected, ContentStore, context, context_key,
                            payload_bytes, sha, strict_json, typed_bytes)

CONTROL_NAMES = [
    'exact_disk_cold_restore', 'changed_checkpoint', 'changed_initial_joint',
    'changed_schedule', 'changed_observation_history', 'changed_arithmetic',
    'changed_decoder', 'missing_identity_coordinate', 'unknown_object_kind',
    'signed_zero_distinct', 'integer_float_distinct', 'duplicate_JSON_rejected',
    'nonfinite_JSON_rejected', 'wrong_external_pin_rejected',
    'tampered_payload_rejected', 'partial_entry_rejected',
]


def run_controls(folder, original_context, original_payload):
    folder = Path(folder)
    folder.mkdir()
    store = ContentStore(folder / 'store')
    pin = sha(original_payload)
    key = store.put(original_context, original_payload, pin)
    records = []

    def check(name, fn, reject=False):
        cpu, wall = time.process_time(), time.perf_counter()
        try:
            result = fn()
        except CacheRejected as error:
            if not reject:
                raise
            detail = str(error)
        else:
            if reject or result is not True:
                raise AssertionError('control did not meet frozen expectation: ' + name)
            detail = 'expected condition observed'
        records.append(dict(control=name, status='PASS', detail=detail,
                            CPU_seconds=time.process_time()-cpu,
                            wall_seconds=time.perf_counter()-wall,
                            serving_request=False))

    check('exact_disk_cold_restore', lambda: ContentStore(folder/'store').get(
          original_context, pin) == original_payload)
    fields = ['checkpoint_decoded_sha256', 'initial_joint_sha256', 'schedule_sha256',
              'action_observation_sha256', 'arithmetic_sha256', 'decoder_sha256']
    names = CONTROL_NAMES[1:7]
    for name, field in zip(names, fields):
        changed = deepcopy(original_context)
        changed['bindings'][field] = sha(('qualification change:' + field).encode())
        check(name, lambda changed=changed: context_key(changed) != key
              and store.get(changed, pin) is None)
    missing = deepcopy(original_context)
    del missing['bindings']['initial_joint_sha256']
    check('missing_identity_coordinate', lambda: context_key(missing), reject=True)
    unknown = deepcopy(original_context)
    unknown['kind'] = 'unknown_tensor_shape_cache'
    check('unknown_object_kind', lambda: context_key(unknown), reject=True)
    check('signed_zero_distinct', lambda: typed_bytes(-0.0) != typed_bytes(0.0))
    check('integer_float_distinct', lambda: typed_bytes(1) != typed_bytes(1.0))
    check('duplicate_JSON_rejected', lambda: strict_json('{"a":1,"a":2}'), reject=True)
    check('nonfinite_JSON_rejected', lambda: strict_json('{"a":NaN}'), reject=True)
    check('wrong_external_pin_rejected', lambda: store.get(original_context, sha(b'wrong pin')), reject=True)
    # Tamper only the qualification store. Keep it as a negative artifact.
    target = folder / 'store' / key / 'payload.bin'
    target.write_bytes(original_payload + b'!')
    check('tampered_payload_rejected', lambda: store.get(original_context, pin), reject=True)
    partial = deepcopy(original_context)
    partial['bindings']['schedule_sha256'] = sha(b'partial entry qualification')
    (folder/'store'/context_key(partial)).mkdir()
    check('partial_entry_rejected', lambda: store.get(partial, pin), reject=True)
    if [r['control'] for r in records] != CONTROL_NAMES:
        raise AssertionError('qualification control schedule changed')
    return records


def main():
    fields = {name:sha(name.encode()) for name in [
        'checkpoint_gzip_sha256','checkpoint_decoded_sha256','source_contract_sha256',
        'basis_sha256','arithmetic_sha256','generator_set_sha256','initial_joint_sha256',
        'schedule_sha256','action_observation_sha256','decoder_sha256']}
    fixture = context('history_result', **fields, horizon_intervals=6)
    with tempfile.TemporaryDirectory(prefix='hepta-contract-offline-') as work:
        records = run_controls(Path(work)/'controls', fixture, payload_bytes({'qualification_only':True}))
    print(json.dumps(dict(status='PASS',controls=len(records),serving_requests=0,
                          model_calls=0, scientific_quality_claim=False)))


if __name__ == '__main__':
    main()
