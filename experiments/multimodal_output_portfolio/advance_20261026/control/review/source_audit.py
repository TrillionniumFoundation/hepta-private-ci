"""Independent metadata-only audit; never imports a source loader or a model."""

from collections import Counter
import gzip
import hashlib
import itertools
import json
import lzma
from pathlib import Path
import struct
import time


HERE = Path(__file__).resolve().parent
ADVANCE = HERE.parents[1]
PREVIOUS = ADVANCE.parent / 'next_20261025'
WORKSPACE = ADVANCE.parents[3]
ALLOC = ADVANCE / 'SOURCE_ALLOCATION.json'
EXPECTED = '42d0c47056dda930cb851c9ae59f330747de8bb863f18b79c47eea830f69b262'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def labels(path, wanted=None):
    opener = gzip.open if path.suffix == '.gz' else lzma.open
    result = {}
    with opener(path, 'rb') as stream:
        magic, count, columns = struct.unpack('>III', stream.read(12))
        if magic != 0x00000c02 or columns != 8:
            raise ValueError('Wrong official label format')
        for i in range(count):
            data = stream.read(32)
            if wanted is None or i in wanted:
                result[i] = struct.unpack('>8I', data)
    return result


def run():
    if sha(ALLOC) != EXPECTED:
        raise ValueError('Registered allocation changed before independent review')
    current = json.loads(ALLOC.read_text())
    old = {}
    for rel, digest in current['previous_allocation_sha256'].items():
        if sha(PREVIOUS / rel) != digest: raise ValueError('Old allocation changed')
        old[rel] = json.loads((PREVIOUS / rel).read_text())
    cache = WORKSPACE / 'ndu-next-assets/qmnist'
    archives = {name: sha(cache / name) == digest for name, digest in current['archive_sha256'].items()}
    if not all(archives.values()): raise ValueError('An official compressed source archive differs')
    qtest = labels(cache / 'qmnist-test-labels-idx2-int.gz')
    qtrain = labels(cache / 'qmnist-train-labels-idx2-int.gz')
    selected_x = {r['index'] for r in current['roles']['confirmation']['source_records']}
    xmeta = labels(cache / 'xnist-labels-idx2-int.xz', selected_x)
    old_writers = {m[2] for m in qtrain.values()} | {m[2] for i, m in qtest.items() if i < 10000}
    old_hashes, old_digits = set(), set()
    for role in old['SOURCE_ALLOCATION.json']['roles'].values():
        old_writers.update(role['pair_writer_ids']); old_hashes.update(role['pixel_sha256'])
    for filename in ('XNIST_QUALIFICATION_ALLOCATION.json', 'ACTION_VALUE_ALLOCATION.json'):
        record = old[filename]; old_writers.update(record['pair_writer_ids'])
        if 'pixel_sha256' in record: old_hashes.update(record['pixel_sha256'])
        for row in record.get('source_records', []):
            old_hashes.add(row['pixel_sha256']); old_digits.add(row['nist_digit'])
    for role in old['NATIVE_H2_ALLOCATION.json']['roles'].values():
        old_writers.update(role['pair_writer_ids'])
        old_hashes.update(r['pixel_sha256'] for r in role['source_records'])
        old_digits.update(r['nist_digit'] for r in role['source_records'])
    old_audio = [r for rows in old['media/AUDIO_SOURCE_ALLOCATION.json']['roles'].values() for r in rows]
    old_audio += old['media/EVENT_QUALIFICATION_SOURCES.json']['recordings']
    old_audio += old['media/ENSEMBLE_QUALIFICATION_SOURCES_V3.json']['recordings']
    audio_root = WORKSPACE / 'ndu-next-assets/media/new-assets/speech-commands-v002-digits'
    manifest_path = audio_root / 'manifest.json'
    if sha(manifest_path) != current['audio_manifest_sha256']: raise ValueError('Audio metadata changed')
    audio_manifest = {r['path']: r for r in json.loads(manifest_path.read_text())['files']}
    used_speakers = {r['speaker'] for r in old_audio}
    used_audio_sha = {r['sha256'] for r in old_audio}
    roles, collections = {}, {}
    for name, role in current['roles'].items():
        records = role.get('source_records', [])
        sounds = role.get('audio_rows_by_source_digit', role.get('recordings', []))
        writers = {r['writer'] for r in records}; speakers = {r['speaker'] for r in sounds}
        pixels = {r['pixel_sha256'] for r in records}; audio = {r['sha256'] for r in sounds}
        if writers & old_writers or pixels & old_hashes or speakers & used_speakers or audio & used_audio_sha:
            raise ValueError('New role overlaps a previously allocated role')
        for row in records:
            m = xmeta[row['index']] if row['dataset'] == 'xnist' else qtest[row['index']]
            if (m[0], m[2], m[5]) != (row['label'], row['writer'], row['nist_digit']):
                raise ValueError('Actual official metadata disagrees with selected source')
            if row['dataset'] == 'xnist' and (m[6] != 0 or m[2] in {r[2] for r in qtest.values()}):
                raise ValueError('XNIST selection does not exclude the full QMNIST writer census')
        for row in sounds:
            original = audio_manifest[row['path']]
            if original['sha256'] != row['sha256'] or original['bytes'] != row['bytes']:
                raise ValueError('Selected audio differs from official source metadata')
        if records:
            if len(records) != 2 * role['pair_count'] or len(sounds) != len(records):
                raise ValueError('Source pair/audio census differs')
            for i, (image, sound) in enumerate(zip(records, sounds)):
                if image['label'] != sound['label'] or sound['speaker'] != role['speaker_by_writer'][str(image['writer'])]:
                    raise ValueError('Audio pair is not aligned with source labels and fixed speaker')
                if image['writer'] != role['pair_writer_ids'][i // 2]:
                    raise ValueError('A pair crosses writer boundaries')
            if len(writers) != len(speakers) or len(set(role['speaker_by_writer'].values())) != len(writers):
                raise ValueError('Writer/speaker mapping is not one-to-one')
            counts = Counter(role['pair_writer_ids'])
            expected = 2 if name == 'confirmation' else 4
            if set(counts.values()) != {expected}: raise ValueError('Unequal pair count per writer')
        roles[name] = {'source_digits': len(records), 'source_pairs': len(records) // 2,
            'writers': len(writers), 'speakers': len(speakers), 'unique_pixel_hashes': len(pixels),
            'registered_audio_rows': len(sounds), 'unique_audio_hashes': len(audio),
            'within_cluster_repeated_audio_preserved': len(sounds) - len(audio)}
        collections[name] = {'writers': writers, 'speakers': speakers, 'pixels': pixels, 'audio': audio}
    overlaps = []
    for a, b in itertools.combinations(collections, 2):
        values = {field: len(collections[a][field] & collections[b][field]) for field in collections[a]}
        if any(values.values()): raise ValueError('Two new roles overlap')
        overlaps.append({'first': a, 'second': b, **values})
    reserved = set(old['SOURCE_ALLOCATION.json']['reserved_writer_ids'])
    if collections['qualification_id']['writers'] != reserved:
        raise ValueError('New ID qualification is not exactly the ten reserved writers')
    allocator = ADVANCE / 'sources.py'
    if sha(allocator) != current['allocator_sha256']: raise ValueError('Allocator source differs')
    report = {'schema': 'hepta.advance.independent-source-review.v1', 'status': 'passed_with_scope_limits',
        'recorded_unix_ns': time.time_ns(), 'allocation_sha256': sha(ALLOC), 'review_source_sha256': sha(__file__),
        'allocator_sha256': sha(allocator), 'official_compressed_archive_hashes_match': archives,
        'actual_official_label_metadata_matched': True, 'new_pixel_bytes_redecoded_by_this_review': False,
        'new_audio_waveforms_read_by_this_review': False, 'models_or_new_role_loader_called': False,
        'roles': roles, 'between_role_intersections': overlaps,
        'prior_source_overlap': {'writers': 0, 'declared_pixel_sha': 0, 'speakers': 0, 'declared_audio_sha': 0},
        'original_pixel_identity_scope': 'This audit independently checks official compressed archives, actual label metadata and declared SHA intersections. The allocator/loader separately recompute selected pixel bytes; this review does not duplicate their full pixel census.',
        'source_guard_static_review': ['load_rows requires named allowed role, nonempty frozen candidate pins, exact allocation and allocator SHA, immutable previous ledger identities, and actual SHA for every listed absolute pin.',
            'load_images additionally hashes official archives and verifies actual selected pixel SHA and label/writer/digit metadata.',
            'Caller remains responsible for freezing a complete executable dependency closure and not opening a role before that registration.'],
        'guard_runtime_negative_cases_executed_in_this_review': False,
        'statistical_limits': ['The same final panel is shared across studies; repeated routes, policies and seeds do not create new independent units.',
            'Repeated same-digit recordings within a writer/speaker remain in that cluster; there is no result-dependent deduplication.',
            '600 all-missing OOD speaker identities are not automatically 600 distinct informative model inputs. Exact public-input/initial-state/RNG duplicates must be recorded; a population binomial interpretation needs its sampling/randomization assumptions. This is not natural-OOD coverage.',
            'Public dataset identities do not certify unknown external ASR pretraining-disjointness.'],
        'no_allocation_or_candidate_modified': True}
    destination = HERE / 'SOURCE_REVIEW.json'
    with destination.open('x') as stream:
        json.dump(report, stream, sort_keys=True, indent=2); stream.write('\n')
    print(json.dumps({'status': report['status'], 'roles': roles, 'report_sha256': sha(destination)}))


if __name__ == '__main__':
    run()
