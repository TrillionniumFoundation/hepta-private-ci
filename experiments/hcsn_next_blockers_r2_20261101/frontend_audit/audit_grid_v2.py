"""Adversarial guard checks on isolated synthetic metadata, without held media."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import sys
import zlib


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
GRID = ROOT / 'experiments/hcsn_grid_frontend_r2_20261101'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def load(path):
    return json.loads(path.read_text())


def main():
    sys.path.insert(0, str(ROOT))
    module = importlib.import_module('experiments.hcsn_grid_frontend_r2_20261101.data_v2')
    freeze = load(GRID / 'SOURCE_FREEZE_V2.json')
    for name, digest in freeze['files'].items():
        assert sha(GRID / name) == digest
    assert sha(GRID / 'data.py') == sha(GRID / 'data_v1.py')
    # Never invoke a network request or real decoder, even if a guard regresses.
    calls = {'network': 0, 'decoder_sentinel': 0}
    def no_network(*args, **kwargs):
        calls['network'] += 1
        raise AssertionError('Unexpected network access')
    def no_decoder(*args, **kwargs):
        calls['decoder_sentinel'] += 1
        raise RuntimeError('SYNTHETIC_DECODER_SENTINEL')
    module.request_range = no_network
    module.subprocess.check_output = no_decoder
    results = []
    with tempfile.TemporaryDirectory(prefix='guard_fixture_', dir=HERE) as name:
        base = Path(name)
        def fixture():
            # The real source function is exercised against a tiny private
            # synthetic registry. These are not valid/accepted scientific inputs.
            current = base / str(len(results))
            module.HERE, module.RAW = current, current / 'raw'
            current.mkdir(parents=True)
            (current / 'data_v2.py').write_bytes((GRID / 'data_v2.py').read_bytes())
            dump(current / 'PROTOCOL.json', {'fixture': 'synthetic metadata only'})
            rows = []
            for speaker, role in ((1, 'train'), (8, 'development'), (10, 'confirmation')):
                raw = f'fixture bytes {role}'.encode()
                rows.append(dict(speaker=speaker, name=f's{speaker}/bfixture.mpg', role=role,
                                 bytes=len(raw), crc32=f'{zlib.crc32(raw) & 0xffffffff:08x}', sentence_target=0))
                path = module.RAW / f's{speaker}' / 'bfixture.mpg'
                path.parent.mkdir(parents=True)
                path.write_bytes(raw)
            dump(current / 'COHORT_SELECTION.json', dict(entries=rows, protocol_sha256=sha(current / 'PROTOCOL.json')))
            identity = dict(files={n: sha(current / n) for n in ('data_v2.py', 'PROTOCOL.json', 'COHORT_SELECTION.json')},
                            admitted_acquisition_sources=[sha(GRID / 'data_v2.py')])
            dump(current / 'SOURCE_FREEZE_V2.json', identity)
            dump(current / 'PUBLICATION_SOURCE_V2.json', dict(source_commit='a' * 40, source_freeze_sha256=sha(current / 'SOURCE_FREEZE_V2.json')))
            for row in rows:
                record = dict(member=row['name'], speaker=row['speaker'], role=row['role'], bytes=row['bytes'], sha256=sha(module.location(row)))
                dump(current / 'inputs' / f"{row['role'].upper()}_ACQUISITION.json", dict(role=row['role'], records=[record],
                    protocol_sha256=sha(current / 'PROTOCOL.json'), cohort_sha256=sha(current / 'COHORT_SELECTION.json'), source_sha256=sha(GRID / 'data_v2.py')))
            candidate = current / 'heads' / 'CANDIDATE_FREEZE.json'
            candidate.parent.mkdir()
            (candidate.parent / 'head.npz').write_bytes(b'synthetic head identity, not a model')
            dump(candidate, dict(protocol_sha256=sha(current / 'PROTOCOL.json'), cohort_sha256=sha(current / 'COHORT_SELECTION.json'),
                source_freeze_sha256=sha(current / 'SOURCE_FREEZE_V2.json'), source_files={'data_v2.py': sha(current / 'data_v2.py')},
                files={'head.npz': sha(candidate.parent / 'head.npz')}))
            def publish():
                dump(current / 'PUBLICATION_CANDIDATE.json', dict(candidate_commit='b' * 40, candidate_sha256=sha(candidate)))
            publish()
            return current, rows, candidate, publish
        def check(name, expected, change, role='confirmation', prefix=False):
            current, rows, candidate, publish = fixture()
            row = copy.deepcopy(next(r for r in rows if r['role'] == role))
            row, candidate = change(current, row, candidate, publish)
            before = dict(calls)
            try:
                value = module.prefix(row, candidate) if prefix else module.input_guard(row, candidate)
            except (ValueError, FileNotFoundError, RuntimeError) as error:
                assert expected is not None and expected in str(error), (name, expected, str(error))
                observed = str(error)
            else:
                assert expected is None, (name, expected)
                observed = 'accepted synthetic fixture identity'
            assert calls['network'] == before['network']
            assert calls['decoder_sentinel'] == before['decoder_sentinel'] + int(expected == 'SYNTHETIC_DECODER_SENTINEL')
            results.append(dict(case=name, expected=expected, observed=observed, passed=True))
        def unchanged(current, row, candidate, publish):
            return row, candidate
        def mutate_json(relative, field, value, republish=False):
            def change(current, row, candidate, publish):
                path = candidate if relative == 'candidate' else current / relative
                record = load(path)
                record[field] = value
                dump(path, record)
                if republish:
                    publish()
                return row, candidate
            return change
        check('valid train does not require candidate', None, lambda c, r, k, p: (r, None), role='train')
        check('valid confirmation identity', None, unchanged)
        check('valid development identity', None, unchanged, role='development')
        for role in ('train', 'confirmation'):
            check(f'valid {role} reaches only synthetic decoder sentinel', 'SYNTHETIC_DECODER_SENTINEL', unchanged, role=role, prefix=True)
        for field, value in (('sentence_target', 1), ('speaker', 999), ('name', 's10/unknown.mpg'), ('role', 'train')):
            def mutate_row(c, r, k, p, field=field, value=value):
                r[field] = value
                return r, k
            check(f'row mutation {field}', 'Unregisteredormutatedcohortmember', mutate_row)
        check('confirmation without candidate', 'Heldprefixrequirespublishedcandidate', lambda c, r, k, p: (r, None), prefix=True)
        check('development without candidate', 'Heldprefixrequirespublishedcandidate', lambda c, r, k, p: (r, None), role='development', prefix=True)
        def remove_publication(c, r, k, p):
            (c / 'PUBLICATION_CANDIDATE.json').unlink()
            return r, k
        check('confirmation publication missing', 'Candidatepublicationmissing', remove_publication, prefix=True)
        for field, value in (('source_commit', 'not-a-commit'), ('source_freeze_sha256', '0' * 64)):
            check(f'source publication {field}', 'Publishedsourcefreezeidentity', mutate_json('PUBLICATION_SOURCE_V2.json', field, value))
        for field, value in (('candidate_commit', 'not-a-commit'), ('candidate_sha256', '0' * 64)):
            check(f'candidate publication {field}', 'Candidatepublicationidentity', mutate_json('PUBLICATION_CANDIDATE.json', field, value))
        for field, expected in (('protocol_sha256', 'Candidatesourcecohortidentity'), ('cohort_sha256', 'Candidatesourcecohortidentity'), ('source_freeze_sha256', 'Candidatesourcefreezeidentity')):
            check(f'candidate {field}', expected, mutate_json('candidate', field, '0' * 64, True))
        check('empty source identity', 'Emptycandidateidentity', mutate_json('candidate', 'source_files', {}, True))
        check('empty head identity', 'Emptycandidateidentity', mutate_json('candidate', 'files', {}, True))
        for relative in ('../escape', '/escape'):
            check(f'source traversal {relative}', 'Candidatesourcefileidentity', mutate_json('candidate', 'source_files', {relative: '0' * 64}, True))
            check(f'head traversal {relative}', 'Candidateheadidentity', mutate_json('candidate', 'files', {relative: '0' * 64}, True))
        check('candidate source hash mismatch', 'Candidatesourcefileidentity', mutate_json('candidate', 'source_files', {'data_v2.py': '0' * 64}, True))
        check('candidate head hash mismatch', 'Candidateheadidentity', mutate_json('candidate', 'files', {'head.npz': '0' * 64}, True))
        ledger_name = 'inputs/CONFIRMATION_ACQUISITION.json'
        for field in ('role', 'protocol_sha256', 'cohort_sha256'):
            check(f'ledger {field}', 'Acquisitioncohortidentity', mutate_json(ledger_name, field, 'wrong'))
        check('unadmitted acquisition source', 'Acquisitionsourceidentity', mutate_json(ledger_name, 'source_sha256', '0' * 64))
        for mode in ('missing', 'duplicate', 'extra'):
            def mutate_coverage(c, r, k, p, mode=mode):
                path = c / ledger_name
                record = load(path)
                if mode == 'missing':
                    record['records'] = []
                elif mode == 'duplicate':
                    record['records'] *= 2
                else:
                    extra = dict(record['records'][0], member='extra.mpg')
                    record['records'].append(extra)
                dump(path, record)
                return r, k
            check(f'ledger coverage {mode}', 'Acquisitionmembercoverage', mutate_coverage)
        for field, value in (('role', 'train'), ('bytes', 1234), ('sha256', 'not-a-sha')):
            def mutate_record(c, r, k, p, field=field, value=value):
                path = c / ledger_name
                record = load(path)
                record['records'][0][field] = value
                dump(path, record)
                return r, k
            check(f'ledger member {field}', 'Acquisitionmemberidentity', mutate_record)
        for mode in ('missing', 'size', 'same_size_corruption', 'symlink'):
            def mutate_raw(c, r, k, p, mode=mode):
                path = module.location(r)
                raw = path.read_bytes()
                if mode == 'missing':
                    path.unlink()
                elif mode == 'size':
                    path.write_bytes(raw + b'x')
                elif mode == 'same_size_corruption':
                    path.write_bytes(b'x' * len(raw))
                else:
                    path.rename(path.with_suffix('.other'))
                    path.symlink_to(path.with_suffix('.other').name)
                return r, k
            check(f'raw {mode}', 'AcquisitionrawSHAidentity', mutate_raw, prefix=True)
    assert calls['network'] == 0 and calls['decoder_sentinel'] == 2
    result = dict(schema='hcsn.grid-v2.independent-guards.v1', source_sha256=sha(GRID / 'data_v2.py'),
        source_freeze_sha256=sha(GRID / 'SOURCE_FREEZE_V2.json'), real_frozen_sources_verified=len(freeze['files']), cases=results,
        passed=len(results), failed=0, real_media_opened=False, held_media_decoded=False, actual_decoder_processes=0, network_requests=0,
        synthetic_decoder_sentinel_probes=calls['decoder_sentinel'],
        scope='Real data_v2 guard functions exercised on isolated synthetic registry/raw/head identities. No media-quality or remote publication verification claim.', all_blockers_closed=False)
    target = HERE / 'REVIEW_GRID_V2.json'
    with target.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(path=str(target.relative_to(ROOT)), sha256=sha(target), passed=len(results), actual_decoder_processes=0, network_requests=0), sort_keys=True))


if __name__ == '__main__':
    main()
