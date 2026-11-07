#!/usr/bin/env python3
"""Seal the completed local R31 readback without rerunning any gate or reader."""
import ast
import gzip
import hashlib
import json
import os
from pathlib import Path

D = Path(__file__).resolve().parent


def pin(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def save(name, data):
    if not isinstance(data, bytes):
        data = (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode()
    with (D / name).open('xb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    return {'path': name, **pin(data)}


def main():
    report_path = D / 'closed-readback-v1/INDEPENDENT-READBACK.json'
    raw = report_path.read_bytes()
    assert pin(raw)['sha256'] == 'f541010b965bf92bcf0472f83d88d28b4e545ed1d6835357c0bf989d32a0573c'
    report = json.loads(raw)
    assert report['classification'] == 'CLOSED_DEFAULT_WORKSPACE_PASS' and not report['integrity_errors']
    execution = json.loads((D / 'LOCAL-EXECUTION.json').read_bytes())
    assert execution['exit_code'] == 0
    checker_pin = pin((D / 'review_closed_archive.py').read_bytes())
    assert checker_pin['sha256'] == '9e2b06dd59c726757eb5af0f2262d548c6267a7570ea91926730142ecb1627f1'
    ast.parse((D / 'review_closed_archive.py').read_bytes())
    rows_file = D / 'closed-readback-v1' / report['independent_rows']['path']
    rows_raw = gzip.decompress(rows_file.read_bytes())
    assert pin(rows_raw) == report['independent_rows']['uncompressed']
    summary = {
        'schema': 'hepta.source53-r31-independent-closure-summary.v1',
        'classification': report['classification'],
        'independent_report': {'path': 'closed-readback-v1/INDEPENDENT-READBACK.json', **pin(raw)},
        'source_commit': report['source_commit'], 'source_tree': report['source_tree'], 'native_HEAD': report['native_HEAD'],
        'archive': report['archive'], 'source': report['source'], 'fresh_metadata': report['fresh_metadata'],
        'raw_exit': report['phase']['raw_exit'], 'effective_exit': report['phase']['effective_exit'],
        'outer_exit': report['outer']['exit_code'], 'natural_terminal': True,
        'wall_seconds_including_build': report['phase']['wall_seconds_including_build'],
        'nextest_execution_seconds': report['execution']['summary']['seconds'],
        'unique_test_count': report['execution']['terminal_unique_test_count'],
        'counts': report['execution']['terminal_counts'], 'reported_skipped': report['execution']['reported_skipped'],
        'skip_identities_inferred': False,
        'announced_binary_count': report['execution']['announced']['binary_count'],
        'binary_groups_with_executed_rows': report['execution']['binary_groups_with_execution_rows'],
        'announced_binaries_not_conflated_with_executed_groups': True,
        'missing_test_ids': report['execution']['baseline_missing'],
        'additional_test_ids': report['execution']['additional_test_ids'],
        'duplicate_execution_ids': report['execution']['duplicate_execution_ids'],
        'footer_rows_excluded_count': len(report['execution']['footer_rows_excluded']),
        'failure_block_count': len(report['execution']['failure_spans']),
        'controller_stdout': report['controller']['stdout'], 'controller_stderr': report['controller']['stderr'],
        'original_R29_history_preserved': report['original_R29_failed_population'],
        'original_source52_R28_project_gate_remains_historical': True,
        'source53_R30_project_gate_and_R31_workspace_gate_not_added_together': True,
        'diagnostic_only': True, 'behavior_repair_claimed': False,
        'all_platforms_features_external_services_qualified': False,
        'science_qualification': False, 'finalizer_authorization_or_execution_claimed': False,
        'supersedes_only_the_pending_full_log_scope_of': 'CLOSED-SMALL-READBACK.json',
        'historical_small_readback_bytes_unchanged': True,
        'shared_free_space_samples_not_interpreted_as_exclusive_cost': True,
        'reader': {'path': 'review_closed_archive.py', **checker_pin},
        'runner_imported_or_executed': False,
        'native_Rust_metadata_fix_fmt_or_git_commands_executed': False}
    summary_pin = save('CLOSURE-SUMMARY.json', summary)
    save('README.md', ('''# R31：独立完整闭合读回

本组独立读取实际闭合归档中的完整日志、rows、回执、资源记录、controller 和源码字节。reader 首次纯本地执行退出 0，没有导入或运行 native runner、exporter、Rust、metadata、fix 或 fmt。

## 实测结果

- 原 `just test --locked --retries 0`，默认 193 个 workspace members。
- 完整原日志重建 **20,228 个唯一 `(binary, name)` 身份，全部 PASS；0 FAIL、0 TIMEOUT，130 reported skip**。skip 身份没有从总数反推。
- 与原 R29 的 20,228 个执行身份完全相同，没有 missing、additional 或重复执行身份；当前 footer 重述为 0，真实失败块为 0。
- Starting 宣告 **366 binaries**；有实际执行行的 binary 身份组为 **323**，两者分别保留。
- nextest 执行 **1643.187 秒**；含构建等的原 tests wall 为 **1854.4279615879059 秒**。raw、effective、outer 均为 0。
- 全归档 **353 regular members / 352 INDEX entries** 完整 raw SHA256、Git blob 和 mode 读回；其中 **197 个源码文件**独立核对，原 source52 的 195 行加两份 source53 诊断文件。没有把 tar 权限位当成 Git 文件类型，也没有宣称另做完整离线 Git tree 重建。
- 原 fresh metadata 调用退出 0；193 members/default members 及 scope 的原始顺序逐项匹配。metadata 与历史相同 bytes 不改变本次调用的原回执身份。
- controller stdout **4875 B**、stderr **0 B** 由原 range/hex/text 完整拼接；开始、raw return、receipt 三条事件与原文件相等。

## 证据边界

source53 保持 `diagnostic_only=true`、`behavior_repair_claimed=false`。R29/source52 原 Bedrock 失败仍是失败；本次同 ID 实测 PASS 0.354 秒，不能仅据诊断日志新增和重跑通过声称已证明行为修复。历史 R28、同源 R30 和本次 R31 不合并计数。

本组核验工程执行证据，不授予科学结论、全平台/全部 feature/外部服务资格或 finalizer 执行权限。原测试之后未由 reader 运行任何 fix/fmt 或测试。共享文件系统空间采样不能当作该门独占资源成本。

`CLOSED-SMALL-READBACK.json` 保留最初大日志尚未传回的历史 pending 字段；本组完整报告补齐它的范围，没有重写旧原件。`EXPORTER-BINDING-READBACK.json` 仅证明当时 literal 绑定和单行 activation 字节关系，不是 exporter 执行回执。

## 复核入口

- `CLOSURE-SUMMARY.json`：简明结果及完整原证据 pins。
- `closed-readback-v1/INDEPENDENT-READBACK.json`：独立全量结果。
- `closed-readback-v1/EXECUTED-ROWS.json.gz`：完整逐 ID/耗时/原行号/字节偏移；mtime=0，无损内容与 native rows 原 bytes 一致。
- `closed-readback-v1/ARCHIVE-MEMBERS.json`、`SOURCE-FILES.json`、`ORIGINAL-PINS.json`：逐项原件映射。
- `LOCAL-EXECUTION.json`：本地 reader 实际首次执行结果。
- `review_closed_archive.py`：不依赖 producer parser 的可重现本地 reader；需要原归档和 root 只读授权原件路径。
''').encode())
    binary = {'schema': 'hepta.source53-r31-independent-binary-plan.v1',
        'files': [{'path': 'closed-readback-v1/EXECUTED-ROWS.json.gz', **pin(rows_file.read_bytes()),
                   'uncompressed': pin(rows_raw), 'gzip_mtime': 0,
                   'purpose': 'Independent full raw-log rows; exact bytes equal the original native derived rows.',
                   'git_object_created_by_this_agent': False}],
        'archive_not_duplicated_in_this_group': report['archive']}
    save('BINARY-PLAN.json', binary)
    files = []
    for path in sorted(D.rglob('*')):
        if path.is_file():
            assert not path.is_symlink()
            files.append({'path': str(path.relative_to(D)), **pin(path.read_bytes())})
    handoff = {'schema': 'hepta.source53-r31-independent-closure-handoff.v1',
               'classification': 'CLOSED_DEFAULT_WORKSPACE_PASS', 'file_count': len(files),
               'listed_bytes': sum(row['bytes'] for row in files), 'files': files,
               'closure_summary': summary_pin,
               'raw_originals_reproducible_from_archive': report['archive'],
               'no_canonical_report_or_ledger_mutation': True, 'no_native_execution': True}
    handoff_pin = save('HANDOFF-MANIFEST.json', handoff)
    for row in files:
        assert pin((D / row['path']).read_bytes()) == {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}
    print(json.dumps({'handoff': handoff_pin, 'closure': summary_pin,
                      'files_including_handoff': len(files) + 1,
                      'bytes_including_handoff': handoff['listed_bytes'] + handoff_pin['bytes']}))


if __name__ == '__main__':
    main()
