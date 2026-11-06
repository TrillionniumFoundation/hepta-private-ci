#!/usr/bin/env python3
"""Freeze root publication receipts and actual native failure evidence."""
from pathlib import Path
import base64
import hashlib
import json
import re
import shutil
import zipfile

ROOT = Path(__file__).resolve().parent
DST = ROOT / 'root-followup-delivery'
DST.mkdir(exist_ok=True)


def identity(data):
    return {'bytes': len(data), 'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
            'sha256': hashlib.sha256(data).hexdigest()}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    scope = json.loads((ROOT / 'b23-closure-root-replay/scope.stdout.original.json').read_text())
    executions = json.loads((ROOT / 'b23-closure-root-replay/replay-execution.json').read_text())
    assert scope['unchanged_original_exit_zh'] == '真实baseline丢信号窗口成立；修后3个单信号父测试与2个原drain用例通过；配置关闭/stdio及平台语义不变，最终原CI验收。'
    assert all(e['exit_code'] == 0 and e['matches_frozen_stdout'] for e in executions)
    custody = [
        ('main92.registry.actual.json', Path('/tmp/hepta-runtime-recovery-20261106/format-review-recovery/main92-six-artifacts-delivery-v2/registry.actual.json'), 'd59627c444e9c01eaa39fdcdd315060731cd5dd5'),
        ('diagnostic-terminal.registry.actual.json', ROOT / 'diagnostic-terminal-delivery/registry.actual.json', '411b8e481be63f1002a6b7b874f0a20f85ea79f5'),
    ]
    certificate = {'schema': 'hepta-b23-root-original-exit-acceptance-v1',
        'decision': 'CLOSED_SCOPED', 'blocker_id': 'B23',
        'unchanged_original_exit_zh': scope['unchanged_original_exit_zh'],
        'independent_review': identity((ROOT / 'b23-closure-root-replay/independent-review.original.json').read_bytes()),
        'root_actual_offline_executions': executions,
        'scope': 'Original GNU/Linux shutdown signal and drain product contract at product tree 3982ba56dc5a3f1da0c1de7ea57992f88125c359.',
        'prior_physical_baseline_and_causal_acceptance_retained_not_rerun': True,
        'fresh_native': {'run': 42155150876, 'job': 127687422035, 'source_head': 'e63ed76c5d8ded046f97caffbdbe2883140e6032', 'actual_checkout': 'b3bc3dcf5684568dd03f3667ecd2307b8577a0a6', 'passed': 307, 'failed': 0, 'ignored': 1, 'original_bazel_exit': 0, 'job_overall': 'failure'},
        'original_main_ci': {'run': 42123581385, 'job': 127679861926, 'actual_checkout': 'b7a57dbb61b00e51c05da9cf5c4bc95b365d85ae', 'job_overall': 'success', 'eight_target_shards_cached': True},
        'separate_result_chains': 'All eight log hashes and action digests differ; no claim the main job reused diagnostic outputs. Binary, args/env/platform and recursive input/tool graph match.',
        'collector_failure_and_eight_missing_XML_remain': True,
        'no_additional_exit_criterion_created': True,
        'custody_now_actual': [{'archive_registry': n, **identity(p.read_bytes())} for n, p, _ in custody],
        'historical_review_pending_custody_text_not_rewritten': True,
        'other_blockers_unchanged_by_this_acceptance': True,
        'does_not_qualify': ['whole library B15', 'all platforms', 'all project', 'new collector head'],
    }
    write(ROOT / 'b23-closure-root-replay/ROOT_ACCEPTANCE.json', certificate)
    names = ['new-fixes-ci-cut-originals.json', 'final-seven-heads-ci-cut-originals.json',
             'arg0-clippy/GNU-clippy-127717742578.original.log', 'arg0-clippy/publication-originals.json',
             'collector-v3-publication-originals.json',
             'cargo-deny-publication-originals.json',
             'collector-v3-root-static.stdout.json', 'collector-v3-root-static.stderr.txt',
             'pty-discard-publication-originals.json',
             'windows-setup-causes/repo-checks-127703396530.original.log']
    names += [str(p.relative_to(ROOT)) for folder in ['b23-closure-root-replay', 'windows-format']
              for p in sorted((ROOT / folder).iterdir()) if p.is_file()]
    names += [str(p.relative_to(ROOT)) for p in sorted((ROOT / 'cargo-deny-native').iterdir())
              if p.is_file() and p.name != 'cargo-deny.ansi-stripped.derived.txt']
    payload = [(n, ROOT / n) for n in names]
    for n, p, expected in custody:
        assert identity(p.read_bytes())['git_blob'] == expected
        payload.append(('custody/' + n, p))
    assert len({n for n, _ in payload}) == len(payload)
    rows = []
    for n, p in payload:
        data = p.read_bytes()
        assert not re.search(rb'https://[^\s"<>]*(?:blob\.core\.windows\.net|amazonaws\.com)[^\s"<>]*(?:[?&](?:sig|X-Amz-Signature)=)', data, re.I), n
        rows.append({'path': n, **identity(data)})
    write(DST / 'manifest.json', {'schema': 'root-followup-exact-members-v1', 'files': rows,
        'download_tool_responses_with_temporary_signed_URLs_excluded': True})
    with zipfile.ZipFile(DST / 'snapshot.zip', 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for n, p in payload:
            info = zipfile.ZipInfo(n, (2026, 11, 6, 5, 20, 0))
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_STORED if n.endswith('.zip') else zipfile.ZIP_DEFLATED
            z.writestr(info, p.read_bytes())
    raw = (DST / 'snapshot.zip').read_bytes()
    encoded = base64.b64encode(raw)
    parts = []
    for offset in range(0, len(encoded), 400000):
        n = f'snapshot.zip.b64.part{len(parts) + 1:03d}'
        data = encoded[offset:offset + 400000]
        (DST / n).write_bytes(data)
        parts.append({'path': n, **identity(data)})
    write(DST / 'archive.json', {'schema': 'base64-parted-exact-zip-v1', 'archive': identity(raw),
        'parts': parts, 'payload_manifest': identity((DST / 'manifest.json').read_bytes())})
    shutil.copyfile(__file__, DST / 'build_packet.py')
    print(json.dumps({'archive': identity(raw), 'parts': len(parts), 'payload_members': len(payload),
        'original_payload_bytes': sum(x['bytes'] for x in rows)}, indent=2))


if __name__ == '__main__':
    main()
