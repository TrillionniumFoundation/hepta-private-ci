import base64
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import struct


ROOT = Path('/workspace/scratch/07dd58cc9630')
WORK = ROOT / 'hepta-audit-fourth'
ARCHIVE = ROOT / 'ci-audit/recovered-20261105/windows-index-complete-archive'
DECODED = ARCHIVE / 'decoded-verified-v1'


def ident(b):
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(),
            'blob': hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()}


def check(b, expected):
    got = ident(b)
    assert got['bytes'] == expected['bytes'] and got['sha256'] == expected['sha256']
    return got


def load(name):
    return json.loads((DECODED / name).read_bytes())


native = json.loads((ARCHIVE / 'native-export-manifest-v1.json').read_bytes())
transport = json.loads((ARCHIVE / 'transport-manifest-v1.json').read_bytes())
assert native == transport['native_export']
lookup = {a['name']: a for a in native['assets']}
exact_dir = WORK / 'inputs/windows-index-exact-git-chunks'
exact_dir.mkdir(exist_ok=True)
originals, chunks = [], []
for asset in transport['assets']:
    offset, parts = 0, []
    for part in asset['chunks']:
        assert part['offset'] == offset
        saved = (ARCHIVE / part['path']).read_bytes()
        trailing_lf = len(saved) == part['bytes'] + 1 and saved.endswith(b'\n')
        b = saved[:-1] if trailing_lf else saved
        entry = check(b, part)
        (exact_dir / (entry['blob'] + '.b64.txt')).write_bytes(b)
        chunks.append({'asset': asset['name'], 'offset': offset,
                       'local_transport_terminal_lf_separately_excluded': trailing_lf, **entry})
        parts.append(b)
        offset += len(b)
    encoded = b''.join(parts)
    wanted = lookup[asset['name']]
    assert len(encoded) == wanted['base64_bytes'] and hashlib.sha256(encoded).hexdigest() == wanted['base64_sha256']
    for part in wanted['parts']:
        check(encoded[part['offset']:part['offset'] + part['bytes']], part)
    zipped = base64.b64decode(encoded, validate=True)
    check(zipped, asset['gzip'])
    assert int.from_bytes(zipped[4:8], 'little') == 0
    b = gzip.decompress(zipped)
    got = check(b, asset['original'])
    assert (DECODED / asset['name']).read_bytes() == b
    originals.append({'name': asset['name'], **got})
assert len(originals) == 23 and sum(x['bytes'] for x in originals) == 12702865


def parse_index(b):
    assert b[:4] == b'DIRC' and hashlib.sha1(b[:-20]).digest() == b[-20:]
    version, count = struct.unpack('>II', b[4:12])
    assert version == 2
    entries, cursor = [], 12
    for _ in range(count):
        start = cursor
        values = struct.unpack('>10I20sH', b[start:start + 62])
        flags = values[-1]
        assert flags & 0x4000 == 0
        end = b.index(b'\0', start + 62)
        name = b[start + 62:end]
        assert flags & 0xfff == min(len(name), 0xfff)
        cursor = start + ((end - start + 1 + 7) // 8) * 8
        assert not any(b[end:cursor])
        entries.append({'path': name.decode(), 'oid': values[10].hex(),
                        'mode': format(values[6], 'o'), 'stage': (flags >> 12) & 3,
                        'assume_valid': bool(flags & 0x8000), 'extended': 0,
                        'skip_worktree': False, 'intent_to_add': False, 'flags': flags,
                        'stat': dict(zip(('ctime_s', 'ctime_ns', 'mtime_s', 'mtime_ns', 'dev', 'ino', 'uid', 'gid', 'size'),
                                         [*values[:6], *values[7:10]]))})
    extensions = []
    while cursor < len(b) - 20:
        signature = b[cursor:cursor + 4].decode()
        length = struct.unpack('>I', b[cursor + 4:cursor + 8])[0]
        payload = b[cursor + 8:cursor + 8 + length]
        assert len(payload) == length
        extensions.append({'signature': signature, 'bytes': length,
                           'sha256': hashlib.sha256(payload).hexdigest(), 'offset': cursor})
        cursor += length + 8
    assert cursor == len(b) - 20
    return {'version': version, 'entry_count': count, 'entries': entries,
            'extensions': extensions, 'checksum_sha1': b[-20:].hex()}


def ls_stage(name):
    answer = []
    for row in (DECODED / name).read_bytes().split(b'\0'):
        if row:
            header, path = row.split(b'\t', 1)
            mode, oid, stage = header.decode().split()
            answer.append((path.decode(), mode, oid, int(stage)))
    return Counter(answer)


def ls_tree(name):
    answer = []
    for row in (DECODED / name).read_bytes().split(b'\0'):
        if row:
            header, path = row.split(b'\t', 1)
            mode, kind, oid = header.decode().split()
            assert kind == 'blob'
            answer.append((path.decode(), mode, oid, 0))
    return Counter(answer)


def semantic(parsed):
    return Counter((x['path'], x['mode'], x['oid'], x['stage']) for x in parsed['entries'])


ordinary_bytes = (DECODED / '001-ordinary-index.snapshot').read_bytes()
ordinary = parse_index(ordinary_bytes)
assert ordinary == load('002-ordinary-index-parsed.json')
assert ordinary['entry_count'] == 9575
assert all(not x[k] for x in ordinary['entries'] for k in ('stage', 'assume_valid', 'extended', 'skip_worktree', 'intent_to_add'))
assert semantic(ordinary) == ls_stage('005-ordinary-ls-files-stage.stdout') == ls_tree('007-ordinary-head-ls-tree.stdout')
flags = (DECODED / '010-ordinary-ls-files-flags.stdout').read_bytes().split(b'\0')
assert Counter(row[:1].decode() for row in flags if row) == {'H': 9575}
assert {row[2:].decode() for row in flags if row} == {x['path'] for x in ordinary['entries']}
private_bytes = (DECODED / '022-17-wrapper-python-original-suite-after.index').read_bytes()
private = parse_index(private_bytes)
assert semantic(private) == ls_stage('012-private-candidate-ls-files-stage.stdout') == ls_tree('014-candidate-ls-tree.stdout')
assert not (DECODED / '016-candidate-diff-files.stdout').read_bytes()
assert not (DECODED / '018-candidate-untracked.stdout').read_bytes()
assert (DECODED / '003-head.stdout').read_text().strip() == 'cabcb40d36e116beaa65750e1f674c52035da785'
for p in DECODED.glob('*.stderr'):
    assert p.stat().st_size == 0
commands = load('020-commands.json')
assert len(commands) == 8 and all(c['exit_code'] == 0 for c in commands)
assert all(c['env_override'].get('GIT_OPTIONAL_LOCKS') == '0' for c in commands)
summary = load('021-summary.json')
check(ordinary_bytes, summary['actual_ordinary_index'])
check(private_bytes, summary['private_source_index_before'])
check(private_bytes, summary['private_source_index_after'])


def tree_oid(files):
    root = {}
    for path, mode, oid, stage in files:
        assert stage == 0
        node = root
        components = path.split('/')
        for component in components[:-1]:
            node = node.setdefault(component, {})
        assert components[-1] not in node
        node[components[-1]] = (mode, oid)
    def encode(node):
        entries = []
        for name, value in node.items():
            directory = isinstance(value, dict)
            mode, oid = ('40000', encode(value)) if directory else value
            entries.append((name.encode() + (b'/' if directory else b''),
                            mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(oid)))
        content = b''.join(row for _, row in sorted(entries))
        return hashlib.sha1(b'tree ' + str(len(content)).encode() + b'\0' + content).hexdigest()
    return encode(root)


ordinary_tree = tree_oid(semantic(ordinary))
private_tree = tree_oid(semantic(private))
assert ordinary_tree == 'b2d7f038d6d88156bc6a4cb29c8703f69b808f29'
assert private_tree == 'fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff'
api = json.loads((WORK / 'inputs/cabc-tree.json').read_bytes())
assert not api['truncated']
assert Counter((x['path'], x['mode'], x['sha'], 0) for x in api['tree'] if x['type'] == 'blob') == semantic(ordinary)
assert summary['ordinary_index_bytes_stable_during_read'] is True

report = {
    'schema': 'hepta-windows-python-index-complete-independent-root-review-v1',
    'observed_at_utc': datetime.now(timezone.utc).isoformat(),
    'original_inspector_job': native['original_inspector_job'],
    'source_tree': private_tree,
    'archive_blob': '288c45f95aa442e7c00048c87fcc76cfbfccef36',
    'archive_path': 'native-evidence/windows-index-complete-archive/archive.json',
    'native_manifest': ident((ARCHIVE / 'native-export-manifest-v1.json').read_bytes()),
    'all23_originals_strict_base64_gzip_crc_decode_and_reopen_equal': True,
    'original_count': 23, 'original_bytes': 12702865,
    'originals': originals, 'transport_chunks': chunks,
    'root_independent_binary_index_parser': {
        'ordinary': ident(ordinary_bytes), 'private': ident(private_bytes),
        'ordinary_version': ordinary['version'], 'ordinary_entries': ordinary['entry_count'],
        'private_entries': private['entry_count'],
        'sha1_trailing_checksums_valid': True,
        'all_ordinary_stat_fields_modes_oids_paths_flags_equal_native_full_parse': True,
        'ordinary_special_flags_or_nonzero_stages': 0,
        'ordinary_extensions': ordinary['extensions'],
        'ordinary_entry_counter_equal_git_stage_list_and_full_head_tree': True,
        'private_entry_counter_equal_git_stage_list_and_full_fb9_tree': True,
        'ordinary_tree_recomputed_from_entries': ordinary_tree,
        'private_tree_recomputed_from_entries': private_tree,
        'full_cabc_API_blob_path_counter_equal_ordinary_index': True,
    },
    'candidate_worktree_diff_and_untracked_empty': True,
    'all8_readonly_git_commands_exit0_optional_locks0': True,
    'root_did_not_read_or_modify_live_index_source_target_or_refs': True,
    'limitations': summary['limitations'] + [
        'The previous8ccf ordinary index binary remains unavailable. Current semantic equality and stable read receipts do not identify which old stat/extension bytes changed or prove the exact triggering process.',
        'No reset, staging of the ordinary index, repeated Python suite or repeated full test was performed for this review.',
    ],
    'original_python_suite_controller1_preserved': True,
    'all_blockers_closed': False,
}
p = WORK / 'deliverables/fourth-windows-index-complete-root-review.json'
p.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'review': ident(p.read_bytes()), 'originals': 23, 'original_bytes': 12702865,
                  'ordinary_entries': ordinary['entry_count'], 'private_entries': private['entry_count'],
                  'ordinary_tree': ordinary_tree, 'private_tree': private_tree}, ensure_ascii=False))
