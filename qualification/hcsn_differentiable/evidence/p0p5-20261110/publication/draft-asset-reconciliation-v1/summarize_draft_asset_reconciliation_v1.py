"""Independently check retained asset receipts and keep partial uploads explicit."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identity(path):
    data = path.read_bytes()
    return {'bytes': len(data), 'sha256': digest(data)}


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--inputs', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
inputs = args.inputs.resolve()
output = args.output.resolve()
capsules = {}
capsule_specs = {
    'main': ('main-receipts.zip', 45741, '447f2d53719005ba1ff82009a0ec7d2197ceec351da5d44ce7cab3e1ef442b02'),
    'desktop': ('desktop-receipts.zip', 113558, 'c15c0a753e289197cb517ef1d5a116a98a5ff5b69a8b25cef93c167998975152'),
}
input_hashes = {}
for key, (name, size, sha) in capsule_specs.items():
    path = inputs / name
    need = {'bytes': size, 'sha256': sha}
    require(identity(path) == need, 'Capsule identity differs: ' + name)
    input_hashes[name] = need
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), 'Duplicate archive name')
        require(all(not n.startswith('/') and '..' not in PurePosixPath(n).parts for n in names),
                'Unsafe archive path')
        require(archive.testzip() is None, 'Archive CRC failed')
        data = {name: archive.read(name) for name in names}
        manifest = json.loads(data['CAPSULE_MANIFEST.json'])
        for member, expected in manifest['files'].items():
            raw = data[member]
            require({'bytes': len(raw), 'sha256': digest(raw)} == expected, 'Member differs: ' + member)
        require(set(data) == set(manifest['files']) | {'CAPSULE_MANIFEST.json'}, 'Unlisted member')
        capsules[key] = data


def read(host, member):
    return json.loads(capsules[host][member])


def reference(host, member):
    raw = capsules[host][member]
    return {'archive': capsule_specs[host][0], 'member': member,
            'bytes': len(raw), 'sha256': digest(raw)}


phases = {
    'desktop_reconciliation_v1': ('desktop', 'runs/draft-three-assets-reconcile-v1/receipt.json'),
    'desktop_official_download_v2': ('desktop', 'runs/official-data-draft-v2/receipt.json'),
    'main_source_upload_v3': ('main', 'runs/official-data-draft-v3-main/receipt.json'),
    'main_official_upload_v5': ('main', 'runs/official-data-draft-v5-main/receipt.json'),
    'desktop_official_readback_v4': ('desktop', 'runs/official-data-draft-v4-desktop/receipt.json'),
}
reports = {name: read(*pair) for name, pair in phases.items()}
for name, report in reports.items():
    require(report['script_unchanged'] is True, 'Executed script changed: ' + name)
    require(report['publish_requested'] is False and report['overwrite_requested'] is False,
            'Unexpected publication/overwrite request')
new_upload_commands = [(name, command) for name, report in reports.items()
                       for command in report['commands']
                       if command['argv'][1:3] == ['release', 'upload']]
require(len(new_upload_commands) == 1 and new_upload_commands[0][0] == 'main_official_upload_v5',
        'Unexpected upload attempt roster')
require(new_upload_commands[0][1]['returncode'] == 1, 'Unexpected official upload status')
v1 = reports['desktop_reconciliation_v1']
verified = []
for expected_id, expected_sha in [
    (731802015, 'f54585285973bd29c80cbb6fc258bb48513f79e7629296bac3ca2c384a4e76a2'),
    (731824485, 'b7beeba44a945baf32c4d27efaa214fe35fc1a704a94927b77f583e9e02b5be0'),
]:
    matches = [row for row in v1['assets'] if row.get('asset_id') == expected_id]
    require(len(matches) == 1, 'Missing verified asset')
    row = matches[0]
    require(row['status'] == 'full_bytes_crc_and_anonymous_isolation_verified'
            and not row['upload_attempted'], 'Existing asset was reuploaded or not verified')
    require(row['authenticated_readback']['sha256'] == expected_sha
            and row['authenticated_readback']['zip_crc_passed'], 'Readback identity differs')
    require(all(probe['http_status'] == '404' and not probe['authorization_header_sent']
                for probe in row['anonymous_probes']), 'Anonymous isolation missing')
    verified.append({'name': row['expected']['name'], 'asset_id': expected_id,
                     'bytes': row['authenticated_readback']['bytes'], 'sha256': expected_sha,
                     'zip_members': row['authenticated_readback']['zip_members'],
                     'status': 'authenticated_full_bytes_crc_and_anonymous_isolation_verified',
                     'uploaded_in_this_work': False, 'evidence': reference(*phases['desktop_reconciliation_v1'])})

reader_root = 'runs/official-data-draft-v4-desktop/'
listing = read('desktop', reader_root + 'asset-0-fresh-assets.stdout')
official = [row for row in listing if row['name'] == 'official-localization-cloud.zip']
require(len(official) == 1, 'Official starter identity differs')
official = official[0]
require(official['id'] == 732265694 and official['state'] == 'starter'
        and official['digest'] is None and official['size'] == 6290730,
        'Unexpected official asset state')
failure_text = capsules['desktop'][reader_root + 'asset-0-authenticated-readback.stderr.redacted'].decode()
require('HTTP 404' in failure_text, 'Readback failure was not the retained HTTP404')
upload_text = capsules['main']['runs/official-data-draft-v5-main/upload-once.stderr.redacted'].decode()
require('HTTP 408' in upload_text and 'Upload body timed out' in upload_text,
        'Official upload failure differs')
embedded = read('desktop', reader_root + 'asset-0-fresh-release.stdout')
require(not any(row['name'] == official['name'] for row in embedded['assets']),
        'Embedded-list scope differs from observation')
require(read('desktop', reader_root + 'release-final.stdout')['draft'] is True,
        'Final independent draft check failed')
source_receipt_member = 'runs/cloud-p2-draft-upload-v1/official-data-download.json'
source_receipt = read('main', source_receipt_member)
expected_source_sha = '6660124b4d1fd98963c56a6804bbb0ca0c5ee12edc9b772c8a867148af20d0da'
require(source_receipt['http_status'] == 200 and source_receipt['bytes'] == 6290730
        and source_receipt['sha256'] == expected_source_sha, 'Original official download differs')
require(reports['main_official_upload_v5']['source']['sha256'] == expected_source_sha,
        'Attempted upload source differs from original official download')

cost_rows = []
for name, report in reports.items():
    cost_rows.append({'id': name, 'status': report['status'],
                     'driver_wall_seconds_after_imports': report['driver_wall_seconds_after_imports'],
                     'driver_absolute_process_cpu_sample_seconds': report['driver_process_cpu_seconds_since_process_start'],
                     'waited_children_cpu_seconds': report['waited_children_cpu_seconds'],
                     'whole_exit_process_cpu_seconds': None,
                     'scope': 'Driver elapsed excludes imports; absolute self CPU sample includes imports but precedes final receipt/manifest serialization and exit. Child CPU covers waited subprocesses. Command walls are nested inside driver wall.',
                     'evidence': reference(*phases[name])})
old_main = read('main', 'runs/cloud-p2-draft-upload-v1/receipt.json')
old_width = read('desktop', 'runs/draft-three-assets-reconcile-v1/prior-width16-receipt.json')
require(old_main['wall_seconds'] == 1258.5981671250001, 'Original uploader timer differs')
historical = [
    {'id': 'original_main_cloud_uploader', 'reported_wall_seconds': old_main['wall_seconds'],
     'scope': 'Historical uploader body timer after imports; includes the official download and failed 600s readback. No additional whole-exit CPU was recovered.',
     'evidence': reference('main', 'runs/cloud-p2-draft-upload-v1/receipt.json')},
    {'id': 'original_width16_uploader', 'reported_wall_seconds': old_width['wall_seconds'],
     'scope': 'Original receipt timer; do not claim an independently captured complete process or exit CPU.',
     'evidence': reference('desktop', 'runs/draft-three-assets-reconcile-v1/prior-width16-receipt.json')},
]
control_path = inputs / 'control-ledger.json'
control_bytes = control_path.read_bytes()
input_hashes[control_path.name] = {'bytes': len(control_bytes), 'sha256': digest(control_bytes)}
control = json.loads(control_bytes)
archive_costs = []
for host, row in control['archives'].items():
    result = row['terminal']
    body = json.loads(next(item['text'] for item in result['content'] if item['type'] == 'text'))
    require(body['output_complete'] and body['status']['exit_code'] == 0, 'Archive process not complete')
    observed = json.loads(body['text'])
    require(observed['sha256'] == capsule_specs[host][2], 'Archive observer hash differs')
    archive_costs.append({'host': host, 'wall_seconds_after_imports': observed['wall_seconds_after_imports'],
                          'absolute_cpu_sample_seconds': observed['process_cpu_seconds_since_process_start'],
                          'evidence': 'control-ledger.json: archives.' + host + '.terminal',
                          'scope': 'Archive builder timer and absolute CPU sample; separate from upload/readback jobs, no exit rusage claimed.',
                          'original_pretty_receipt_readback_succeeded': not row['exact_pretty_receipt_read'].get('isError', False)})
transfer = control['source_file_transfer']
require(transfer['offset'] == 196608 and transfer['status'] == 'paused_uncommitted_stage_outcome_unknown',
        'Unexpected uncommitted transfer state')

summary = {
    'schema': 'hcsn-draft-three-assets-final-reconciliation-v1',
    'created_utc': datetime.now(timezone.utc).isoformat(),
    'repository': 'TrillionniumFoundation/hepta-private-ci', 'release_id': 440410488,
    'tag': 'hcsn-research-20261110-c385', 'status': 'two_verified_one_failed_starter',
    'scientific_credit': False, 'release_published': False,
    'verified_existing_assets': verified,
    'official_data_asset': {
        'asset_id': official['id'], 'name': official['name'], 'observed_state': 'starter',
        'declared_server_size': official['size'], 'server_digest': None,
        'authenticated_full_readback_verified': False, 'authenticated_readback_http_status': 404,
        'anonymous_asset_check_performed': False,
        'upload_invocations_in_this_work': 1, 'upload_returncode': 1, 'upload_http_status': 408,
        'expected_payload_sha256': expected_source_sha,
        'declared_size_is_not_verified_uploaded_bytes': True,
        'full_asset_list_evidence': reference('desktop', reader_root + 'asset-0-fresh-assets.stdout'),
        'readback_error_evidence': reference('desktop', reader_root + 'asset-0-authenticated-readback.stderr.redacted'),
        'upload_error_evidence': reference('main', 'runs/official-data-draft-v5-main/upload-once.stderr.redacted'),
        'observation_completed_utc': reports['desktop_official_readback_v4']['completed_utc'],
        'no_delete_replace_or_further_upload_performed': True,
    },
    'list_semantics_observed': {
        'embedded_release_asset_count': len(embedded['assets']), 'complete_asset_list_count': len(listing),
        'starter_visible_in_embedded_release': False, 'starter_visible_in_complete_assets_endpoint': True,
        'interpretation': 'The main v5 still-absent error means absent from the embedded release list, not absent from all asset records. Its embedded-list uploader must not be reused as a general absence test.',
    },
    'original_official_file': {'bytes': 6290730, 'sha256': expected_source_sha,
        'source_url': source_receipt['url'], 'original_http_status': 200,
        'original_source_evidence': reference('main', source_receipt_member),
        'cloud_path': '/workspace/scratch/c385a7439f8e/official-localization-cloud.zip',
        'main_path': '/Users/qianqi/hepta-hcsn-p0p5-20261110-c385/recovery/official-localization-cloud.zip'},
    'new_phase_costs': cost_rows, 'historical_costs_retained': historical,
    'nested_costs_not_additive': [
        {'id': 'original_official_download', 'wall_seconds': source_receipt['wall_seconds'],
         'included_in': 'original_main_cloud_uploader'},
        {'id': 'failed_official_upload_command',
         'wall_seconds': new_upload_commands[0][1]['whole_subprocess_wall_seconds'],
         'included_in': 'main_official_upload_v5'},
    ],
    'new_phase_driver_wall_sum': sum(row['driver_wall_seconds_after_imports'] for row in cost_rows),
    'wall_sum_scope': 'Only a sum of five separately recorded after-import driver intervals; not end-to-end calendar time, not all historical work, and not a full-process total.',
    'archive_builder_costs': archive_costs,
    'uncommitted_file_transport': {
        'upload_id': transfer['upload_id'], 'host': transfer['host'], 'path': transfer['path'],
        'last_acknowledged_offset': transfer['offset'],
        'next_524288_byte_chunk_and_exact_replay': 'Both MCP timed out; staged progress beyond the ACK is unknown.',
        'commit_called': False, 'destination_published': False,
        'tool_call_elapsed_seconds': [row['tool_elapsed_seconds'] for row in transfer['chunks']],
        'scope': 'Client await durations for transfer RPC calls; not native process CPU or successful-byte accounting. No more chunks or commit sent.',
        'evidence': 'control-ledger.json: source_file_transfer'},
    'accounting_complete': False, 'energy_joules': None, 'currency_cost': None,
    'total_calendar_wall_seconds': None, 'total_whole_exit_cpu_seconds': None,
    'input_archives_and_control': input_hashes,
    'capsule_payload_scope': '140 archive members total, including both capsule manifests. Raw successful/partial/empty payloads remain at native paths under SHA references; source, metadata, small original receipts and logs are embedded.',
}
output.mkdir(exist_ok=False)
(output / 'SUMMARY.json').write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + '\n')
lines = ['# 草稿资产对账结果', '',
         '两个既有研究资产已完成认证全字节回读、ZIP CRC 与匿名 API/下载地址 404 检查。官方数据资产的唯一新上传尝试失败；随后完整资产列表显示 starter 记录，不能记为成功归档。', '',
         '| 资产 | 状态 | 标识与字节 |', '| --- | --- | --- |',
         '| cloud-p2-diagnostics-20261110-v1.zip | 完整验真；没有重传 | 731802015；17,670,639 B；157 ZIP 成员 |',
         '| hcsn-width16-v6-audit-20261110.zip | 完整验真；没有重传 | 731824485；4,460,517 B；109 ZIP 成员 |',
         '| official-localization-cloud.zip | starter；digest=null；认证下载 HTTP 404 | 732265694；服务端声明 6,290,730 B，不等于成功上传的字节 |', '',
         '官方上传命令返回 HTTP 408（上传体因不活动超时），耗时 537.948344583 秒。release GET 的内嵌数组只有 17 项，没有显示该 starter；独立 assets 列表有 18 项，明确显示 starter。因此原 main v5 的 still-absent 错误必须按该观测范围理解，不能推导远端完全没有记录，也不能将该脚本复用为通用缺失判断。没有删除、覆盖或再次上传这个资产；草稿状态保持。', '',
         '原始官方文件仍完整保存在 cloud 和 main：6,290,730 B，SHA-256 为 6660124b4d1fd98963c56a6804bbb0ca0c5ee12edc9b772c8a867148af20d0da。原官方 UCI 下载回执为 HTTP 200，完整来源在 main capsule 中。此后的两个 desktop UCI 下载失败均保留为失败，不改变原始文件来源。', '',
         '## 新增费用口径', '', '| 阶段 | driver wall（导入后，秒） | driver CPU 采样（秒） | waited child CPU（秒） |', '| --- | ---: | ---: | ---: |']
for row in cost_rows:
    lines.append(f"| {row['id']} | {row['driver_wall_seconds_after_imports']:.9f} | {row['driver_absolute_process_cpu_sample_seconds']:.9f} | {row['waited_children_cpu_seconds']:.9f} |")
lines += ['', 'CPU 采样来自进程启动后的累计时钟，但发生在最终 receipt/manifest 序列化和进程退出之前，不是完整 exit rusage。子命令 wall 嵌套在 driver wall 内，不再相加。五段 driver wall 合计仅用于列清这五个区段，不能冒充端到端时间或全部费用。', '',
          '原 main uploader 的 1258.598167125 秒包含官方原包下载 639.887319916 秒及其失败回读；该下载不能再次加总。原 width16 成功 uploader 的 92.554298136 秒另行保留。两个 capsule 构建的 wall/CPU 以及不成功的文件传输 RPC 时长单列于 SUMMARY.json。能源、货币费用和完整总账仍未知。', '',
          'cloud→desktop 的另一路文件传输只确认到 offset 196608；后续 524288 字节块及同 ID/同偏移的精确重放均超时。没有发送 commit，目标没有发布，之后停止传输。不能把超时视为成功字节，也不与本次 GitHub 上传混为一项。', '',
          '## 复核与复制', '',
          '两个 ZIP 共 140 个成员，逐成员尺寸/SHA-256、ZIP CRC 和路径安全已在 cloud 再核。原始大读回文件及失败 partial/empty payload 没有重新嵌入小包；PAYLOAD_REFERENCES.json 保留原生路径和完整哈希。原小型 receipt、API 元数据、日志及源代码字节均保留在包内。', '',
          '复制清单见 COPY_LIST.json；SUMMARY.json 为机器可读结论、每条原始来源和费用作用域。此工作没有新增训练、数值资格或科学收益信用。', '']
(output / 'README.md').write_text('\n'.join(lines))
copy_list = [{'source': str(inputs / name), 'suggested_filename': name, **ident}
             for name, ident in input_hashes.items()]
copy_list.append({'source': str(Path(__file__).resolve()),
                  'suggested_filename': Path(__file__).name, **identity(Path(__file__))})
for name in ('SUMMARY.json', 'README.md'):
    copy_list.append({'source': str(output / name), 'suggested_filename': name, **identity(output / name)})
(output / 'COPY_LIST.json').write_text(json.dumps(copy_list, indent=2) + '\n')
for name, expected in input_hashes.items():
    require(identity(inputs / name) == expected, 'Input changed while summarizing')
result = {p.name: identity(p) for p in output.iterdir() if p.is_file()}
(output / 'MANIFEST.json').write_text(json.dumps({'files': result, 'scope': 'Summary outputs excluding this manifest.'}, indent=2) + '\n')
print(json.dumps({'output': str(output), 'status': summary['status'], 'files': result}, indent=2))
