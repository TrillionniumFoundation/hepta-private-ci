#!/usr/bin/env python3
"""Create only the R31 formal attachment draft from frozen local originals."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile

PREP = Path(__file__).resolve().parent
B = PREP.parent
TARGET_REL = 'hepta-cell/qualification/cell-unification-20261106/native-evidence/r31-workspace-checkpoint'
TARGET = B / TARGET_REL
ARCHIVE_REL = 'native-validation-results/r31-archive-closed/checkpoint-r31-closed.tar.gz'
ARCHIVE_PIN = {'bytes': 4484123, 'sha256': '87afd6c49a3c753b90c8e53b3b70988f2964352fcf2daf0ed85c536ac6f77563',
               'git_blob': '693da6d9414f88c1620516a28958c518ac924978'}
DIRS = [
    ('source53-r31-preparation', 'preparation/runner'),
    ('source53-r31-binding', 'preparation/runner-binding'),
    ('source53-r31-root-review', 'reviews/root-runner'),
    ('source53-r31-native-static-review', 'reviews/native-runner'),
    ('source53-r31-independent-static-review', 'reviews/peer-runner'),
    ('source53-r31-binding-independent-review', 'reviews/peer-runner-binding'),
    ('native-validation-results/r31-start-closed', 'native-readback/start'),
    ('native-validation-results/r31-closed-input', 'native-readback/closed'),
    ('source53-r31-export-preparation', 'preparation/exporter'),
    ('source53-r31-export-binding', 'preparation/exporter-binding'),
    ('source53-r31-export-root-review', 'reviews/root-exporter'),
    ('r31-export-native-independent-review', 'reviews/native-exporter'),
    ('native-validation-results/r31-export-closed', 'export-closure'),
    ('source53-r31-independent-closure', 'reviews/independent-full-readback'),
]
FILES = [
    ('native-validation-results/r31-archive-closed/FILE-INFO-ORIGINAL.json', 'transport/FILE-INFO-ORIGINAL.json'),
    ('native-validation-results/r31-archive-closed/ARCHIVE-EXPECTED-PIN.json', 'transport/ARCHIVE-EXPECTED-PIN.json'),
    ('native-validation-results/r31-archive-closed/TRANSFER-READBACK.json', 'transport/TRANSFER-READBACK.json'),
    ('native-validation-results/r31-archive-closed/ROOT-ARCHIVE-READBACK.json', 'reviews/ROOT-ARCHIVE-READBACK.json'),
    ('native-validation-results/r31-archive-closed/ACTUAL-GIT-BLOB-RESPONSE.json', 'publication/ACTUAL-GIT-BLOB-RESPONSE.json'),
    ('r31-archive-root-review/LEDGER-BEFORE-ARCHIVE-REGISTRATION.json', 'publication/LEDGER-BEFORE-ARCHIVE-REGISTRATION.json'),
    ('r31-archive-root-review/LEDGER-AFTER-ARCHIVE-REGISTRATION.json', 'publication/LEDGER-AFTER-ARCHIVE-REGISTRATION.json'),
    ('r31-archive-root-review/verify_archive.py', 'reproduction/root_verify_archive.py'),
]


def require(ok, message):
    if not ok:
        raise AssertionError(message)


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def safe(name):
    p = PurePosixPath(name)
    require(name and not p.is_absolute() and '..' not in p.parts and '.' not in p.parts, 'unsafe relative attachment path')


def stable_file(path):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and not path.is_symlink(), 'not an original regular file: ' + str(path))
    data = path.read_bytes(); after = path.lstat()
    require((before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino)
            == (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino)
            and len(data) == after.st_size, 'source changed during read: ' + str(path))
    return data, stat.S_IMODE(after.st_mode)


def write_new(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    require(path.read_bytes() == raw, 'local write readback differs')


def main():
    require(not TARGET.exists(), 'new formal directory already exists')
    archive_raw, _ = stable_file(B / ARCHIVE_REL)
    require(pin(archive_raw) == ARCHIVE_PIN, 'wrong whole R31 archive')
    archive_members, archive_modes = {}, {}
    with tarfile.open(fileobj=io.BytesIO(archive_raw), mode='r:gz') as tf:
        for member in tf.getmembers():
            safe(member.name)
            require(member.isfile() and not member.issym() and not member.islnk() and member.name not in archive_members,
                    'unsafe or duplicate archive member')
            data = tf.extractfile(member).read()
            require(len(data) == member.size, 'short archive member')
            archive_members[member.name], archive_modes[member.name] = data, member.mode
    index = json.loads(archive_members['INDEX.json'])
    indexed = {row['path']: row for row in index['files']}
    require(len(archive_members) == 353 and len(indexed) == len(index['files']) == 352
            and set(indexed) == set(archive_members) - {'INDEX.json'}, 'archive population differs')
    for name, row in indexed.items():
        require(pin(archive_members[name]) == {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}, 'archive original raw pin differs')
        declared_mode = int(row['mode'], 8) if isinstance(row['mode'], str) else row['mode']
        require(declared_mode & 0o7777 == archive_modes[name] & 0o7777, 'archive mode differs')
    require(sum(name.startswith('source/') for name in archive_members) == 197, 'wrong source count')
    independent_raw = (B / 'source53-r31-independent-closure/closed-readback-v1/INDEPENDENT-READBACK.json').read_bytes()
    require(pin(independent_raw)['sha256'] == 'f541010b965bf92bcf0472f83d88d28b4e545ed1d6835357c0bf989d32a0573c', 'independent report changed')
    independent = json.loads(independent_raw)
    root_raw = (B / 'native-validation-results/r31-archive-closed/ROOT-ARCHIVE-READBACK.json').read_bytes()
    root = json.loads(root_raw)
    require(root['result'] == 'ORIGINAL_SOURCE53_R31_PASS' and root['archive'] == ARCHIVE_PIN, 'root archive result differs')
    require(root['counts'] == independent['execution']['terminal_counts'] == {'PASS': 20228, 'FAIL': 0, 'TIMEOUT': 0}
            and root['reported_skipped'] == independent['execution']['reported_skipped'] == 130,
            'independent/root current gate disagree')
    publication = json.loads((B / 'native-validation-results/r31-archive-closed/ACTUAL-GIT-BLOB-RESPONSE.json').read_bytes())
    require(publication['isError'] is False and publication['structuredContent']['sha'] == ARCHIVE_PIN['git_blob'], 'actual archive Git publication differs')

    payloads, canonical, mappings, source_snapshots = {}, {}, [], {}
    def generated(name, raw):
        safe(name)
        require(name not in payloads, 'generated payload collision: ' + name)
        payloads[name] = raw
    def attach(origin, desired, raw, origin_mode=None, force=False):
        safe(desired)
        raw_pin = pin(raw)
        transformed = desired.endswith(('.json', '.log', '.txt')) and len(raw) >= 65536
        if transformed:
            raw.decode('utf-8')
            stored = gzip.compress(raw, mtime=0)
            require(gzip.decompress(stored) == raw, 'gzip roundtrip differs')
            desired += '.gz'
        else:
            stored = raw
        stored_pin = pin(stored)
        can_deduplicate = not force and (len(raw) >= 65536 or desired.endswith('.gz'))
        key = (stored_pin['bytes'], stored_pin['sha256'], stored_pin['git_blob'])
        destination = canonical.get(key) if can_deduplicate else None
        if destination is None:
            destination = desired
            if destination in payloads:
                require(payloads[destination] == stored, 'attachment destination collision')
            else:
                payloads[destination] = stored
            canonical.setdefault(key, destination)
        require(payloads[destination] == stored, 'deduplicated bytes differ')
        mappings.append({'origin': origin, 'raw': raw_pin, 'original_mode': origin_mode,
                         'requested_destination': desired, 'destination': destination,
                         'storage': 'deterministic_gzip' if transformed else 'exact_bytes',
                         'gzip_mtime': 0 if transformed else None, 'stored': stored_pin,
                         'deduplicated': destination != desired})
    def attach_file(source, destination, force=False):
        path = B / source
        raw, mode = stable_file(path)
        require(source not in source_snapshots or source_snapshots[source] == pin(raw), 'source snapshot changed')
        source_snapshots[source] = pin(raw)
        attach({'kind': 'local_original', 'path': source}, destination, raw, mode, force)

    attach_file(ARCHIVE_REL, 'archive/checkpoint-r31-closed.tar.gz', True)
    for name, raw in sorted(archive_members.items()):
        origin = {'kind': 'archive_member', 'archive': ARCHIVE_REL, 'member': name}
        if name.startswith('source/'):
            mappings.append({'origin': origin, 'raw': pin(raw), 'original_mode': archive_modes[name],
                             'storage': 'original_archive_member_only',
                             'destination': 'archive/checkpoint-r31-closed.tar.gz', 'archive_member': name,
                             'stored_archive': ARCHIVE_PIN, 'source_not_duplicated': True})
        else:
            attach(origin, 'original/' + name, raw, archive_modes[name])
    verified_handoffs = []
    for source_dir, destination_dir in DIRS:
        directory = B / source_dir
        require(directory.is_dir() and not directory.is_symlink(), 'required frozen directory absent: ' + source_dir)
        handoff = directory / 'HANDOFF-MANIFEST.json'
        if handoff.is_file():
            manifest = json.loads(handoff.read_bytes())
            for row in manifest['files']:
                raw = (directory / row['path']).read_bytes()
                for key in ('bytes', 'sha256', 'git_blob'):
                    if key in row:
                        require(pin(raw)[key] == row[key], 'frozen HANDOFF pin differs: ' + source_dir + '/' + row['path'])
            verified_handoffs.append({'path': str(handoff.relative_to(B)), **pin(handoff.read_bytes()),
                                      'listed_files': len(manifest['files']), 'all_listed_raw_pins_verified': True})
        for path in sorted(directory.rglob('*')):
            require(not path.is_symlink(), 'support directory symlink')
            if path.is_file():
                require('__pycache__' not in path.parts and '.git' not in path.parts, 'unexpected generated/checkout file')
                attach_file(str(path.relative_to(B)), destination_dir + '/' + str(path.relative_to(directory)))
    for source, destination in FILES:
        attach_file(source, destination)
    for filename in ('assemble_formal.py', 'verify_attachment.py', 'seal_formal.py'):
        attach_file('r31-formal-preparation/' + filename, 'reproduction/' + filename)
    # Stable top-level independent entry point; this is the exact report,
    # not a new conclusion manufactured from the manifest.
    attach_file('source53-r31-independent-closure/closed-readback-v1/INDEPENDENT-READBACK.json',
                'INDEPENDENT-READBACK.json', True)

    mapping_document = {'schema': 'hepta.r31-formal-source-destination-map.v1',
        'formal_root': TARGET_REL, 'archive': ARCHIVE_PIN,
        'rows': mappings, 'historical_fields_rewritten': False,
        'large_duplicates_resolve_through_this_map': True,
        'source_members_stored_only_inside_the_unchanged_archive': 197,
        'non_source_archive_members_individually_preserved': 156}
    generated('SOURCE-DESTINATION-MAPPING.json', encoded(mapping_document))
    generated('ORIGINAL-MEMBER-MAPPING.json', encoded({'schema': 'hepta.r31-original-archive-member-map.v1',
        'archive': {'path': 'archive/checkpoint-r31-closed.tar.gz', **ARCHIVE_PIN},
        'regular_members': 353, 'INDEX_rows': 352,
        'members': [row for row in mappings if row['origin']['kind'] == 'archive_member']}))
    generated('CLOSURE-MAPPING.json', encoded({'schema': 'hepta.r31-formal-reference-closure.v1',
        'rule': 'Resolve every original workspace path or archive member through SOURCE-DESTINATION-MAPPING.json; decompress only when its storage field says deterministic_gzip.',
        'source53_commit': independent['source_commit'], 'source53_tree': independent['source_tree'],
        'frozen_source_groups': [{'original_directory': source, 'formal_requested_prefix': destination} for source, destination in DIRS],
        'verified_frozen_handoffs': verified_handoffs,
        'original_relative_references_preserved_without_rewriting': True,
        'source_archive_is_complete': True,
        'unmaterialized_source_members_are_present_in_the_original_archive_not_missing': True,
        'not_a_self_attestation_of_native_execution': True,
        'execution_claims_come_from_original_gate_receipts_full_logs_and_independent_readbacks': True}))
    root_result_path = 'reviews/ROOT-ARCHIVE-READBACK.json'
    closure = {'schema': 'hepta.source53-r31-formal-workspace-checkpoint.v1',
        'status': 'CLOSED_ORIGINAL_DEFAULT_WORKSPACE_PASS', 'engineering_gate': 'PASS',
        'source_commit': independent['source_commit'], 'source_tree': independent['source_tree'],
        'actual_native_HEAD': independent['native_HEAD'], 'changed_source_count': 197,
        'diagnostic_only': True, 'behavior_repair_claimed': False,
        'archive': {'path': 'archive/checkpoint-r31-closed.tar.gz', **ARCHIVE_PIN, 'regular_members': 353, 'INDEX_rows': 352},
        'original_producer_files': 18, 'outer_terminal_kept_separately': True,
        'original_command': independent['phase']['command'], 'raw_exit': independent['phase']['raw_exit'],
        'effective_exit': independent['phase']['effective_exit'], 'outer_exit': independent['outer']['exit_code'],
        'unique_binary_name_test_ids': independent['execution']['terminal_unique_test_count'],
        'counts': independent['execution']['terminal_counts'], 'reported_skipped': independent['execution']['reported_skipped'],
        'skip_identities_inferred': False, 'baseline_missing': [], 'additional_ids': [], 'duplicate_execution_ids': [],
        'footer_rows_excluded_count': 0, 'actual_failure_blocks': 0,
        'announced_binaries': independent['execution']['announced']['binary_count'],
        'binary_groups_with_executed_rows': independent['execution']['binary_groups_with_execution_rows'],
        'tests_wall_seconds_including_build': independent['phase']['wall_seconds_including_build'],
        'nextest_execution_seconds': independent['execution']['summary']['seconds'],
        'fresh_metadata': independent['fresh_metadata'],
        'source_byte_readback': independent['source'],
        'controller': {'stdout': independent['controller']['stdout'], 'stderr': independent['controller']['stderr'],
                       'complete_ranges_reconstructed': True, 'events_match_raw_and_receipt': True},
        'root_readback': {'path': root_result_path, **pin(root_raw)},
        'independent_readback': {'path': 'INDEPENDENT-READBACK.json', **pin(independent_raw)},
        'original_source52_R29_failure': independent['original_R29_failed_population'],
        'historical_source52_R28_and_source53_R30_not_added_to_current_counts': True,
        'artifact_export': {'separate_from_original_gate': True, 'original_gate_exit_not_replaced_by_export_exit': True,
                            'export_exit': 0, 'producer_result': 'original/evidence/native-workspace-r31-closed-result-review.json'},
        'archive_actual_Git_blob_created': True,
        'archive_publication_response': 'publication/ACTUAL-GIT-BLOB-RESPONSE.json',
        'archive_registration_snapshot': 'publication/LEDGER-AFTER-ARCHIVE-REGISTRATION.json',
        'archive_registration_snapshot_counts': {'source': 53, 'binary': 236, 'artifact': 6},
        'registration_snapshot_is_not_a_future_live_total': True,
        'all_platforms_features_external_services_qualified': False,
        'science': 'HOLD', 'authority': 'DENY_ALL',
        'formatter_or_fix_results_included': False, 'finalizer_authorized_by_this_attachment': False,
        'post_fix_fmt_qualification_claimed': False,
        'shared_filesystem_samples_not_attributed_as_exclusive_resource_cost': True,
        'canonical_docs_INDEX_ledger_source_or_native_modified': False,
        'attachment_manifest': 'ATTACHMENT-MANIFEST.json',
        'source_mapping': 'SOURCE-DESTINATION-MAPPING.json',
        'old_failed_and_pending_snapshot_bytes_preserved': True}
    generated('CLOSURE.json', encoded(closure))
    generated('README.md', '''# R31 原始工作区门：完整闭合证据

原 source53 默认工作区门已自然通过：**20,228 个唯一测试身份全部 PASS，0 FAIL、0 TIMEOUT，130 reported skip**。原命令为 `just test --locked --retries 0`，由本次实际 metadata 确认默认 193 个成员；没有新增 package selector、filter、feature、ignore 或 retry。

原 tests raw、effective、outer 返回均为 0。nextest 执行 1643.187 秒，含构建等的 wall 为 1854.4279615879059 秒。Starting 的 366 binaries 与实际出现执行行的 323 个 binary 身份组分别记录。完整日志、原 rows、原 R29 的 20,228 个身份集合逐项相符；当前无重复身份、无 footer 失败重述、无失败块。

## 来源与复核

- [CLOSURE.json](CLOSURE.json)：门禁结果、来源、精确 pins 与资格边界。
- [INDEPENDENT-READBACK.json](INDEPENDENT-READBACK.json)：独立 reader 首次纯本地执行的完整结果。
- [ROOT-ARCHIVE-READBACK.json](reviews/ROOT-ARCHIVE-READBACK.json)：root 另一实现的独立核验。
- [原归档](archive/checkpoint-r31-closed.tar.gz)：4,484,123 字节，SHA256 `87afd6c49a3c753b90c8e53b3b70988f2964352fcf2daf0ed85c536ac6f77563`，353 regular members / 352 INDEX rows。
- [SOURCE-DESTINATION-MAPPING.json](SOURCE-DESTINATION-MAPPING.json)：每份原字节及压缩、去重后的实际位置。
- [ORIGINAL-MEMBER-MAPPING.json](ORIGINAL-MEMBER-MAPPING.json)：353 个原归档成员的完整保全映射。
- [CLOSURE-MAPPING.json](CLOSURE-MAPPING.json)：原审计内部相对路径的定位规则。
- [ATTACHMENT-MANIFEST.json](ATTACHMENT-MANIFEST.json)：最终附件逐文件 bytes/SHA256/Git blob。

全部 197 个源码的 SHA256、Git blob 和模式均从归档重新核验，原 source52 的 195 行和新增的两个 source53 诊断文件关系保持。源码仅在完整原归档中存放；156 个非源码成员另行保全。大 JSON、日志和文本只作 mtime=0 gzip，无损解压逐项相等；大件重复字节可共用一个实际附件，通过映射定位。原报告的历史 null/false/pending 字段和初稿修正记录均未改写。

本组包含惰性 runner、实际 binding/授权、原启动记录、完整闭合原件/controller、exporter 初稿和修正/静态审阅/实际授权及独立导出回执。69 个传输分块的 base64 内容未重复复制；原 whole-file 信息、传输读回、完整 SHA/Git blob 和原归档仍在。原归档 Git blob `693da6d9414f88c1620516a28958c518ac924978` 的实际创建响应及固定登记快照保留。

## 结果边界

source53 保持 **diagnostic_only=true、behavior_repair_claimed=false**。R29/source52 原 Bedrock FAIL 10.643 秒仍然保留；R31 同一 ID PASS 0.354 秒是本次观察，不能仅据添加诊断日志和后续通过宣称证明了行为修复。R28 历史项目门、R30 同源项目门与 R31 默认工作区门分别保存，不累加计数。

exporter 的自然 0 只表示归档成功，不替代原工作区退出码。本组不含也不授权 fix/fmt；不宣称格式化后资格、全部 feature、全部平台或外部服务通过。科学结论继续 **HOLD**，权限边界保持 **DENY_ALL**。共享文件系统空间采样不当作本门独占资源成本。
'''.encode())
    binary = []
    for path, raw in sorted(payloads.items()):
        if path.endswith('.gz'):
            binary.append({'path': path, **pin(raw),
                           'actual_git_object_already_created': True if path == 'archive/checkpoint-r31-closed.tar.gz' else None,
                           'must_not_reupload_archive': path == 'archive/checkpoint-r31-closed.tar.gz',
                           'root_owns_upload_and_registration': True})
    generated('BINARY-PLAN.json', encoded({'schema': 'hepta.r31-formal-binary-plan.v1',
        'formal_root': TARGET_REL, 'files': binary, 'no_git_upload_performed_by_assembler': True,
        'exact_duplicate_binary_payloads_share_actual_destination': True}))
    generated('PROVENANCE-SNAPSHOT.json', encoded({'schema': 'hepta.r31-formal-frozen-local-input-snapshot.v1',
        'source_files': [{'path': path, **value} for path, value in sorted(source_snapshots.items())],
        'verified_handoffs': verified_handoffs, 'archive_members': 353,
        'only_this_snapshot_included_not_future_added_files': True}))
    # A second read pins every selected source before producing the new group.
    for path, expected in source_snapshots.items():
        require(pin(stable_file(B / path)[0]) == expected, 'input changed before attachment write')
    TARGET.mkdir(parents=True, exist_ok=False)
    for name, raw in sorted(payloads.items()):
        write_new(TARGET / name, raw)
    copy_plan = {'schema': 'hepta.r31-formal-preseal-copy-plan.v1', 'target': TARGET_REL,
        'files': [{'path': name, **pin(raw)} for name, raw in sorted(payloads.items())],
        'file_count': len(payloads), 'bytes': sum(len(raw) for raw in payloads.values()),
        'source_mapping_rows': len(mappings), 'original_archive_member_rows': 353,
        'source_archive_only_rows': 197, 'non_source_member_rows': 156,
        'source_group_count': len(DIRS), 'binary_files': len(binary),
        'not_yet_sealed': True, 'native_Rust_formatter_or_Git_execution': False}
    write_new(PREP / 'COPY-PLAN.json', encoded(copy_plan))
    print(json.dumps({'target': TARGET_REL, 'payload_files': len(payloads), 'payload_bytes': copy_plan['bytes'],
                      'mapping_rows': len(mappings), 'binary_files': len(binary),
                      'copy_plan': pin((PREP / 'COPY-PLAN.json').read_bytes()), 'status': 'READY_FOR_INDEPENDENT_ATTACHMENT_BYTE_READBACK'}))


if __name__ == '__main__':
    main()
