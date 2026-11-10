"""Archive independent review outputs and verify exact original-member coverage."""

import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED


ORIGINAL_SHA = '6ae9028ce67b0b827abc7e25654dcede356f4562d1f632f5ceb616e0585dc304'
ORIGINAL_MANIFEST_SHA = 'aae3651571a46411e80e8253af769710897ca3587c5e4df5eb6a74d7357fdb15'
INPUT_SHA = '0fbda8a006c48e5a04f14a31e10a675cfeea37c872ed69bba9bc314bf1523036'


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_archive(archive):
    names = archive.namelist()
    require(len(names) == len(set(names)), 'duplicate archive member')
    for info in archive.infolist():
        name = PurePosixPath(info.filename)
        require(not name.is_absolute() and '..' not in name.parts and '\\' not in info.filename,
                'unsafe archive path')
        require(not stat.S_ISLNK(info.external_attr >> 16), 'symlink archive member')
        require(not info.is_dir(), 'this archive contract contains files only')
    require(archive.testzip() is None, 'archive CRC failure')


def check_manifest(archive, name):
    manifest = json.loads(archive.read(name))
    for member, expected in manifest['files'].items():
        require(identity(archive.read(member)) == expected, 'manifest identity mismatch: '+member)
    require(set(manifest['files']) | {name} == set(archive.namelist()), 'unlisted archive member')


def is_independent_output(name):
    return name.startswith(('attention-cpu-path-', 'plif-independent-review-'))


def verify(input_archive, review_archive, combined_archive=None, restore_dir=None):
    with ExitStack() as stack:
        inputs = stack.enter_context(ZipFile(input_archive))
        review = stack.enter_context(ZipFile(review_archive))
        original = stack.enter_context(ZipFile(combined_archive)) if combined_archive else None
        for archive in [inputs, review] + ([original] if original else []):
            check_archive(archive)
        check_manifest(inputs, 'ARCHIVE_MANIFEST.json')
        check_manifest(review, 'MANIFEST.json')
        mapping = json.loads(review.read('UNION-COVERAGE.json'))
        require(identity(Path(input_archive).read_bytes()) == mapping['existing_input_archive'],
                'existing input archive differs')
        require(mapping['original_combined_archive']['sha256'] == ORIGINAL_SHA, 'wrong combined origin')
        if original:
            require(identity(Path(combined_archive).read_bytes()) == mapping['original_combined_archive'],
                    'original archive differs')
            check_manifest(original, 'MANIFEST.json')
        members = mapping['members']
        require(len(members) == 75 and len({r['original_member'] for r in members}) == 75,
                'combined member roster differs')
        manifest_raw = review.read('original/MANIFEST.json')
        require(identity(manifest_raw)['sha256'] == ORIGINAL_MANIFEST_SHA,
                'embedded original manifest is not the previously verified identity')
        original_manifest = json.loads(manifest_raw)
        require({r['original_member'] for r in members} == set(original_manifest['files']) | {'MANIFEST.json'},
                'coverage does not recover original manifest roster')
        restored = Path(restore_dir) if restore_dir else None
        if restored:
            restored.mkdir(parents=True, exist_ok=False)
        for row in members:
            original_name = PurePosixPath(row['original_member'])
            require(not original_name.is_absolute() and '..' not in original_name.parts
                    and '\\' not in row['original_member'], 'unsafe restored member path')
            require(row['provider'] in ('existing_inputs', 'independent_review_outputs'), 'unknown provider')
            source = inputs if row['provider'] == 'existing_inputs' else review
            raw = source.read(row['provider_member'])
            require(identity(raw) == row['identity'], 'union member identity mismatch')
            if row['original_member'] != 'MANIFEST.json':
                require(row['identity'] == original_manifest['files'][row['original_member']],
                        'union disagrees with original member manifest')
            if original:
                require(raw == original.read(row['original_member']), 'direct original bytes differ')
            if restored:
                path = restored/row['original_member']
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                require(identity(path.read_bytes()) == row['identity'], 'restored disk bytes differ')
        return {'schema': 'plif-attention-member-union-validation-v1', 'passed': True,
                'members_verified': len(members), 'provider_counts': dict(Counter(r['provider'] for r in members)),
                'direct_original_member_byte_comparison': original is not None,
                'restored_member_tree_on_disk_verified': restored is not None,
                'original_combined_zip_reuploaded': False, 'original_compressed_zip_bytes_reconstructed': False,
                'review_archive': identity(Path(review_archive).read_bytes()),
                'input_archive': identity(Path(input_archive).read_bytes()),
                'uncompressed_original_member_identity_sha256': hashlib.sha256(encode({r['original_member']: r['identity'] for r in members})).hexdigest(),
                'scope': 'Exact coverage of the original75 uncompressed archive members. Wider prepared-data dependencies are listed separately. No experiment rerun or new scientific credit.',
                'scientific_admission': 'HOLD'}


def build(args):
    original_id = identity(args.combined_archive.read_bytes())
    input_id = identity(args.input_archive.read_bytes())
    require(original_id == {'bytes': 729786, 'sha256': ORIGINAL_SHA}, 'wrong original package')
    require(input_id == {'bytes': 449039, 'sha256': INPUT_SHA}, 'wrong existing input package')
    require(not args.output.exists(), 'output exists; reconcile before retry')
    with ZipFile(args.combined_archive) as original, ZipFile(args.input_archive) as inputs:
        for archive in [original, inputs]:
            check_archive(archive)
        check_manifest(original, 'MANIFEST.json')
        check_manifest(inputs, 'ARCHIVE_MANIFEST.json')
        index = defaultdict(list)
        for name in inputs.namelist():
            item = identity(inputs.read(name))
            index[(item['bytes'], item['sha256'])].append(name)
        retained, rows = {}, []
        for name in original.namelist():
            raw = original.read(name)
            item = identity(raw)
            matches = index.get((item['bytes'], item['sha256']), [])
            # Keep each experiment's own empty stderr logs with its outputs.
            if matches and not is_independent_output(name):
                provider = 'existing_inputs'
                member = name if name in matches else sorted(matches)[0]
            else:
                provider = 'independent_review_outputs'
                member = 'original/'+name
                retained[member] = raw
            rows.append({'original_member': name, 'identity': item,
                         'provider': provider, 'provider_member': member})
        mapping = {'schema': 'plif-attention-original-member-union-v1',
                   'created_utc': datetime.now(timezone.utc).isoformat(),
                   'original_combined_archive': original_id, 'existing_input_archive': input_id,
                   'existing_input_archive_relative_path': '../p2/plif-analog-diagnostics.zip',
                   'review_output_archive_name': args.output.name,
                   'original_member_count': 75, 'existing_member_count': 41,
                   'provider_counts': dict(Counter(r['provider'] for r in rows)), 'members': rows,
                   'division_rule': 'Original attempts/source/shared metadata remain in the existing input archive; independent review/profiler outputs keep their own logs. Any original member absent there is retained in full.',
                   'original_missing_input_included_here': 'reviewed-data/A01-0.json',
                   'original_zip_bytes_reuploaded': False, 'scope': 'Original uncompressed member coverage, not all external runtime/data dependencies.',
                   'scientific_admission': 'HOLD'}
        profile = json.loads(original.read('attention-cpu-path-review-v4/RESULT.json'))
        dependencies = {'schema': 'attention-profile-prepared-data-dependencies-v1',
                        'data_manifest_sha256': profile['data_manifest_sha256'],
                        'episodes': profile['episodes'], 'embedded_episode_ids': ['A01-0'],
                        'external_episode_ids': [r['id'] for r in profile['episodes'] if r['id'] != 'A01-0'],
                        'scope': 'The original combined package embedded only A01-0. The other31 profile inputs require the complete study prepared dataset or its pinned official-data reconstruction chain; this repackaging does not expand that original coverage.'}
    retained['UNION-COVERAGE.json'] = encode(mapping)
    retained['DATA-DEPENDENCIES.json'] = encode(dependencies)
    retained['verify_union.py'] = Path(__file__).read_bytes()
    retained['README.md'] = (
        '# Independent PLIF and Attention review outputs\n\n'
        'This archive complements the existing `../p2/plif-analog-diagnostics.zip`. '
        'Its original attempts, source capsule and shared metadata cover40 original members. '
        'This archive retains35 more original members:33 independent PLIF/Attention review outputs '
        '(including each of the four profiler attempts and its own empty stderr), the original '
        'combined MANIFEST, and the missing full A01-0 input.\n\n'
        'UNION-COVERAGE.json maps every original member to exact bytes and SHA256. '
        'Together the two archives reproduce all75 original uncompressed members. '
        'The original729786-byte combined ZIP remains unchanged; it was not re-uploaded '
        'or claimed to be byte-for-byte reconstructed as a compressed ZIP. No experiment was rerun.\n\n'
        'The original package contained one of the32 Attention profiling input episodes. '
        'DATA-DEPENDENCIES.json preserves the remaining31 exact episode identities and '
        'the complete prepared-data manifest SHA. Those remain dependencies of the wider '
        'study data chain; two small archives are not a standalone copy of that dataset.\n\n'
        'Run `python verify_union.py verify --input-archive INPUT.zip --review-archive REVIEW.zip`. '
        'Optionally pass `--combined-archive ORIGINAL.zip` for direct member-byte equality, '
        'or `--restore-dir NEW_DIRECTORY` for a verified member-tree restoration. '
        'The verifier checks manifests, CRC, duplicate/unsafe paths and all75 identities.\n\n'
        'The evidence still supports only the stated diagnostic/replay and measured CPU '
        'operator-path observations. It grants no training adequacy, whole-training numerical '
        'qualification, GPU performance, energy saving or scientific benefit.\n'
    ).encode()
    manifest = {'schema': 'plif-attention-independent-review-output-files-v1',
                'files': {name: identity(raw) for name, raw in sorted(retained.items())},
                'scientific_admission': 'HOLD'}
    retained['MANIFEST.json'] = encode(manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.output, 'x', ZIP_DEFLATED, compresslevel=9) as archive:
        for name, raw in sorted(retained.items()):
            archive.writestr(name, raw)
    with TemporaryDirectory(prefix='hcsn-original-members-') as temporary:
        receipt = verify(args.input_archive, args.output, args.combined_archive, Path(temporary)/'restored')
    require(args.output.stat().st_size < 512*1024, 'semantic review archive exceeds requested size target')
    require(identity(args.combined_archive.read_bytes()) == original_id
            and identity(args.input_archive.read_bytes()) == input_id, 'an original archive changed')
    receipt.update(new_archive_members=len(retained), original_archives_unchanged=True,
                   mapping_sha256=identity(retained['UNION-COVERAGE.json'])['sha256'],
                   manifest_sha256=identity(retained['MANIFEST.json'])['sha256'],
                   packaging_source_sha256=identity(Path(__file__).read_bytes())['sha256'])
    for name, raw in [('plif-attention-union-v1.json', retained['UNION-COVERAGE.json']),
                      ('plif-attention-union-v1-RECEIPT.json', encode(receipt)),
                      ('verify_plif_attention_union_v1.py', Path(__file__).read_bytes())]:
        with (args.output.parent/name).open('xb') as stream:
            stream.write(raw)
    print(json.dumps(receipt, indent=2, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('build')
    create.add_argument('--combined-archive', type=Path, required=True)
    create.add_argument('--input-archive', type=Path, required=True)
    create.add_argument('--output', type=Path, required=True)
    check = commands.add_parser('verify')
    check.add_argument('--input-archive', type=Path, required=True)
    check.add_argument('--review-archive', type=Path, required=True)
    check.add_argument('--combined-archive', type=Path)
    check.add_argument('--restore-dir', type=Path)
    args = parser.parse_args()
    if args.command == 'build':
        build(args)
    else:
        print(json.dumps(verify(args.input_archive, args.review_archive, args.combined_archive, args.restore_dir), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
