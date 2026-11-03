"""Deterministic local malformed-shape tests; NOT physical model evidence."""
import hashlib
import random
import cohort_firewall as module

rng = random.Random(20261022)

def image(n):
    return {
        'source_id': f'coco:val2017:{n}', 'task_id': f'task-{n}',
        'image_sha256': hashlib.sha256(f'image-{n}'.encode()).hexdigest(),
        'decoded_rgb_sha256': hashlib.sha256(f'rgb-{n}'.encode()).hexdigest(),
        'dhash64': f'{int.from_bytes(hashlib.sha256(f"fingerprint-{n}".encode()).digest()[:8], "big"):016x}'
    }

def manifest(n):
    return {'schema': 'hepta.grounded-cohort.v1', 'splits': {
        split: {'count': 1, 'sources': [image(n+i)]}
        for i, split in enumerate(module.SPLITS)
    }}

values = [None, True, False, 0, 1, 1.5, '', [], {}, ['malformed'], {'x': 1}, float('nan'), -1]
fields = ('schema', 'splits', 'split', 'part', 'count', 'sources', 'row', 'source_id', 'task_id', 'image_sha256', 'decoded_rgb_sha256', 'dhash64')
rejected = passed = 0
for index in range(1800):
    candidate, histories = manifest(100), [manifest(0)]
    data = rng.choice((candidate, histories[0]))
    field, value = rng.choice(fields), rng.choice(values)
    try:
        if field in ('schema', 'splits'):
            data[field] = value
        else:
            split = rng.choice(module.SPLITS)
            if field == 'split':
                data['splits'][split] = value
            else:
                part = data['splits'][split]
                if field in ('count', 'sources'):
                    part[field] = value
                elif field == 'part':
                    part['sources'] = [value]
                else:
                    part['sources'][0][field if field != 'row' else 'source_id'] = value
        module.check_cohort(candidate, histories)
        passed += 1
    except module.CohortContractError:
        rejected += 1
    except Exception as error:
        raise AssertionError(f'unexpected unhandled error at mutation #{index} ({field}): {error!r}') from error
print(f'PASS local NDU v2 deterministic mutated-shape matrix: {rejected} denied, {passed} accepted, 0 unexpected exceptions (1800 cases)')
