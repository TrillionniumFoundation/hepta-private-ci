"""Freeze a source-only diagnosis; this script does not run the product or tests."""

import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


ROOT = Path('/workspace/scratch/07dd58cc9630')
OUT = ROOT / 'architecture-audit/fb9-proxy-connect-20261105'
REPO = 'TrillionniumFoundation/hepta-private-ci'
CASE = 'process_sandbox::tests::native_request_handles_remote_proxy_config_for_platform'
SOURCE = 'fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff'


def identity(path):
    data = path.read_bytes()
    return {
        'path': str(path.relative_to(ROOT)),
        'bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        'git_blob': hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest(),
    }


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def api_tree(path):
    result = json.loads(path.read_text())
    return json.loads(result['structuredContent']['content'])


original_tree_path = ROOT / 'hepta-audit-fourth/inputs/cabc-tree.json'
original_tree = json.loads(original_tree_path.read_text())
original_paths = {e['path']: e for e in original_tree['tree']}
top = api_tree(OUT / 'fb9-root-tree-api.json')
codex = api_tree(OUT / 'fb9-codex-tree-api.json')
assert top['sha'] == SOURCE and not top['truncated'] and not codex['truncated']
assert next(e['sha'] for e in top['tree'] if e['path'] == 'codex-rs') == codex['sha']
proxy_tree = next(e['sha'] for e in codex['tree'] if e['path'] == 'network-proxy')
assert proxy_tree == original_paths['codex-rs/network-proxy']['sha']

for name in ['process_sandbox.rs', 'process_sandbox_tests.rs']:
    source = ROOT / 'research-audit/fb9-new-failures-20261105/source/codex-rs/exec-server/src' / name
    dest = OUT / 'source/codex-rs/exec-server/src' / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)

sources = []
for path in sorted((OUT / 'source').rglob('*.rs')):
    row = identity(path)
    repo_path = str(path.relative_to(OUT / 'source'))
    assert row['git_blob'] == original_paths[repo_path]['sha'], repo_path
    row['repository_path'] = repo_path
    row['immutable_blob_url'] = f'https://api.github.com/repos/{REPO}/git/blobs/{row["git_blob"]}'
    row['source_binding'] = (
        'Exact fb9 network-proxy subtree equals the fixed cabc subtree; this file matches that tree entry.'
        if '/network-proxy/' in repo_path else
        'Actual fb9 native typed source read, independently byte-hashed by research; exact file also equals cabc.'
    )
    sources.append(row)
assert len(sources) == 14
source_by_path = {x['repository_path']: x for x in sources}

reports = []
for label, xml_path, review_path in [
    ('earlier_f825', 'ci-audit/recovered-20261105/full-owning-compressed-archive/full-junit.original',
     'ci-audit/recovered-20261105/full-owning-compressed-archive/full-review.original'),
    ('current_fb9', 'ci-audit/recovered-20261105/full-fb9-complete-archive/priority-decoded-v1/full-workspace.junit.xml',
     'ci-audit/recovered-20261105/full-fb9-complete-archive/priority-decoded-v1/full-workspace-review.json'),
]:
    xml_file, review_file = ROOT / xml_path, ROOT / review_path
    review = json.loads(review_file.read_text())
    cases = [c for c in ET.fromstring(xml_file.read_bytes()).iter('testcase') if c.get('name') == CASE]
    assert len(cases) == 1
    case = cases[0]
    fragment_path = OUT / f'{label}-case.xml'
    fragment_path.write_text(ET.tostring(case, encoding='unicode') + '\n')
    reports.append({
        'label': label, 'source_tree': review['source'], 'whole_junit': identity(xml_file),
        'whole_review': identity(review_file), 'exact_case_fragment': identity(fragment_path),
        'fragment_is_xml_serialization_not_claimed_raw_byte_range': True,
        'case_name': CASE, 'classname': case.get('classname'), 'seconds': case.get('time'),
        'status': 'FAIL' if case.find('failure') is not None else 'PASS',
        'terminal_nodes': [{'tag': c.tag, 'attributes': c.attrib, 'text': c.text}
                           for c in case if c.tag in ['failure', 'error', 'skipped']],
        'stdout': case.findtext('system-out'), 'stderr': case.findtext('system-err'),
        'retries': review['retries'], 'source_unchanged': review['source_unchanged'],
        'whole_run_exit_code': review['exit_code'], 'whole_run_counts': review['counts'],
    })
assert reports[0]['source_tree'] == 'f8251e1d14fa8524ab469281296cd4cf708f173c'
assert reports[0]['status'] == 'PASS' and reports[0]['seconds'] == '0.501'
assert reports[1]['source_tree'] == SOURCE and reports[1]['status'] == 'FAIL'
assert reports[1]['terminal_nodes'][0]['attributes']['type'] == 'test failure with exit code 101'
assert 'process_sandbox_tests.rs:338:10' in reports[1]['stderr']


def ref(name, lines, proposition):
    path = f'codex-rs/network-proxy/src/{name}'
    row = source_by_path[path]
    return {'path': path, 'blob': row['git_blob'], 'lines': lines, 'proposition': proposition}


findings = [
    {'id': 'P1', 'status': 'CONFIRMED_SOURCE_AND_ORIGINAL_FAILURE',
     'finding': 'The original Linux test prepared a native request with no sandbox, no policy decider, no audit observer, and an allowlist containing only allowed.example. It connected and wrote CONNECT blocked.example before failing at the unchanged 2-second response read timeout.',
     'sources': [{'path': 'codex-rs/exec-server/src/process_sandbox_tests.rs', 'blob': 'a66387ee0d892b82ba3fcf45662a13ef6b13c4c3', 'lines': [267, 349]},
                 {'path': 'codex-rs/exec-server/src/process_sandbox.rs', 'blob': '0bf5853a1d82df037d406fdffbe31d6bada1b2b4', 'lines': [78, 122]}],
     'limit': 'A completed TCP connect/write does not establish that the server parsed CONNECT or entered policy evaluation. No child or sandboxed process is executed by this test.'},
    {'id': 'P2', 'status': 'CONFIRMED_SOURCE_RISK_NOT_EXECUTED_CAUSAL_PROOF',
     'finding': 'Implicit allowlist rejection of this hostname reaches the local/private DNS check first. DNS lookup has a 2-second deadline, equal to the original client response deadline. If lookup remains pending until its deadline, the request cannot reliably finish policy, record the rejection, and deliver a response inside the same client deadline.',
     'sources': [ref('runtime.rs', [49, 49], 'DNS_LOOKUP_TIMEOUT is 2 seconds'),
                 ref('runtime.rs', [528, 602], 'Explicit deny, then local/private check, then allowlist'),
                 ref('runtime.rs', [934, 973], 'DNS error and timeout fail closed as non-public')],
     'limit': 'The original failure has no phase timestamps or DNS start/outcome evidence. The 10.514-second total duration is not evidence of load, DNS duration, blocking-pool shutdown, or a specific HTTP ingress stall.'},
    {'id': 'P3', 'status': 'CONFIRMED_CONTRACT_CONSTRAINT',
     'finding': 'Only NotAllowed is eligible for a policy-decider override. NotAllowedLocal and explicit Denied bypass the decider. Moving allowlist rejection in front of the DNS/private check globally would change which requests can be overridden. Restricting such a shortcut to no decider preserves the deny decision but changes denial reason priority for unresolved/private hostnames.',
     'sources': [ref('network_policy.rs', [340, 414], 'Decider is consulted only for NotAllowed'),
                 ref('runtime.rs', [549, 602], 'Documented priority and exact returns'),
                 ref('responses.rs', [52, 102], 'Both reasons share x-proxy-error but use different response bodies'),
                 ref('runtime.rs', [605, 641], 'BlockedRequest telemetry preserves exact reason')],
     'limit': 'No semantics-preserving DNS bypass under the existing reason/approval contract has been demonstrated. This review does not authorize a rejection-priority change.'},
    {'id': 'P4', 'status': 'CONFIRMED_SOURCE_IDENTITY_AND_NARROWING',
     'finding': 'The entire actual fb9 network-proxy subtree equals the cabc subtree. This ingress already uses HttpServer::http1(), not automatic HTTP version sniffing. The attribution preface peeks one byte; an ordinary CONNECT begins with C, so the 3-second attribution-frame branch is not taken once that byte is received. The test uses a static reloader and no policy observer.',
     'sources': [ref('http_proxy.rs', [144, 176], 'HTTP/1 service with attribution wrapper'),
                 ref('attribution.rs', [44, 112], 'Only a leading NUL enters the framed attribution timeout'),
                 ref('runtime.rs', [194, 208], 'Static reloader immediately returns None'),
                 ref('runtime.rs', [283, 309], 'Remote launch uses static reloader'),
                 ref('network_policy.rs', [262, 309], 'Optional synchronous policy audit observer')],
     'limit': 'Unchanged source does not prove identical feature graphs, scheduling, resolver state, or a clean current run. An existing earlier exact PASS is retained separately from the new FAIL.'},
    {'id': 'P5', 'status': 'CONFIRMED_SOURCE_LIFECYCLE_LIMIT',
     'finding': 'The managed builder reserves and retains a real loopback listener. run() spawns the HTTP service and returns its handle without a request-processed readiness acknowledgement. Successful TCP connect therefore cannot by itself exclude ingress or task-start latency.',
     'sources': [ref('proxy.rs', [200, 249], 'Managed loopback listener reservation'),
                 ref('proxy.rs', [1353, 1463], 'Task spawn and handle return'),
                 ref('http_proxy.rs', [113, 140], 'Listener conversion and serve entry')],
     'limit': 'This is a diagnosis boundary, not evidence that readiness caused the observed failure.'},
]

diagnostic_plan = {
    'status': 'PLAN_ONLY_NOT_AUTHORIZED_OR_APPLIED_AS_SOURCE',
    'target': {'package': 'codex-exec-server', 'test_kind': 'lib', 'exact_case': CASE},
    'constraints': ['Original blocked.example CONNECT and implicit deny configuration',
                    'Original 2-second response timeout and all assertions',
                    'No resolver override, explicit deny, IP replacement, skip, retry, or extra response',
                    'No host changes or new cross-platform qualification',
                    'Exact temporary-source guard with finally restoration if later approved'],
    'observations': [
        {'point': 'Original test', 'fields': 'Monotonic elapsed at prepare completion, TCP connect completion, write completion, and the actual read Result before the original expect.', 'reason': 'Separate setup and request deadline from total libtest/runtime teardown.'},
        {'point': 'HTTP CONNECT accept entry and original policy result', 'fields': 'Fixed diagnostic tag, monotonic elapsed, original decision/reason; no environment or credentials.', 'reason': 'Establish actual request parsing and whether response policy completed.'},
        {'point': 'host_blocked before the existing DNS await and after its original outcome', 'fields': 'Fixed target host, allowlisted/local-binding/explicit-deny booleans, DNS start and success/error/timeout/cancellation-relevant absence with elapsed.', 'reason': 'Demonstrate whether DNS was still pending at the client deadline; do not replace the resolver.'},
        {'point': 'Original denied-response construction after record_blocked', 'fields': 'Fixed tag plus monotonic elapsed and original reason.', 'reason': 'Distinguish completed DNS/policy from later response delivery delay.'},
    ],
    'decision_rules': [
        'No CONNECT accept marker before client timeout leaves ingress/readiness/scheduling open.',
        'CONNECT and DNS-start markers with DNS still pending at the original client timeout establish the deadline collision for that instrumented attempt, not a retrospective proof for the historical run.',
        'DNS/policy completing before the deadline requires following the existing record/response path; do not label it a DNS timeout.',
        'A diagnostic PASS does not close the earlier full-run failure or establish all-platform qualification.',
    ],
}

receipt = {
    'schema': 'hepta-fb9-proxy-connect-source-diagnosis-v1',
    'repository': REPO, 'actual_source_tree': SOURCE,
    'verdict': 'OPEN_ACTUAL_CAUSE_UNOBSERVED; STATIC_DNS_DEADLINE_COLLISION_CONFIRMED',
    'no_native_execution_no_product_patch_no_ref_mutation': True,
    'source_binding': {
        'actual_fb9_root': SOURCE, 'codex_rs_tree': codex['sha'], 'network_proxy_tree': proxy_tree,
        'whole_network_proxy_subtree_equals_cabc': True,
        'cabc_reference_commit': 'cabcb40d36e116beaa65750e1f674c52035da785',
        'cabc_recursive_tree_evidence': identity(original_tree_path),
        'actual_tree_api_receipts': [identity(OUT / 'fb9-root-tree-api.json'), identity(OUT / 'fb9-codex-tree-api.json')],
        'actual_exec_server_source_receipt': identity(ROOT / 'research-audit/fb9-new-failures-20261105/source-read-1-verification.json'),
    },
    'source_files': sources, 'exact_native_history': reports,
    'original_failure_projection': identity(ROOT / 'ci-audit/recovered-20261105/full-fb9-nonpass-projection-v1.json'),
    'findings': findings, 'minimal_future_diagnostic_plan': diagnostic_plan,
    'corrections': [
        'The original test has an implicit allowlist denial, not an explicit deny rule.',
        'The existing response read timeout is 2 seconds; 10.514 seconds is the total exact-case duration.',
        'NotAllowed and NotAllowedLocal share the x-proxy-error header value blocked-by-allowlist. Their response bodies and telemetry/audit reasons differ. Earlier informal wording suggesting a changed header is corrected.',
        'The HTTP ingress already uses HTTP/1. The old automatic version-sniffing issue is not established as present in this source.',
    ],
    'preserved_open_boundaries': [
        'The original full-run proxy failure remains open; no stage-specific causal observation is available.',
        'No product permission or rejection-priority change is proposed by this receipt.',
        'Earlier exact-case PASS does not override the later actual FAIL.',
        'Native Linux evidence is not Windows, macOS Intel, ARM, or full-matrix qualification.',
        'B16 runner qualification and the original blocker ledger are unaffected.',
    ],
}
write_json(OUT / 'static-diagnosis.json', receipt)

md = '''# fb9 ExecServer CONNECT 超时：固定源码复核

**结论：原失败保持开放。已经证实源码中存在 2 秒 DNS 截止时间与 2 秒客户端读响应截止时间的竞争，但原日志没有证明该次实际停在 DNS。此次只读复核没有修改产品、测试、权限或原生工作树。**

## 原始执行事实

精确用例为 `codex-exec-server::process_sandbox::tests::native_request_handles_remote_proxy_config_for_platform`。实际 fb9 树是 `fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff`。完整 JUnit 中该例为普通 exit 101，10.514 秒，在 `process_sandbox_tests.rs:338` 的原 2 秒响应读取发生 `Elapsed(())`。准备请求、TCP 连接和写入 CONNECT 已返回；该例没有启动子进程或执行 sandbox 命令。

原配置只允许 `allowed.example`，没有配置 explicit deny。请求 `blocked.example` 是隐式 allowlist 拒绝，decider 和审计 observer 都为 None。更早 f825 的完整 JUnit 有同名 PASS 0.501 秒；这条历史成功单独保留，不覆盖后来的真实失败。

## 源码路径与边界

| 环节 | 固定源码结论 | 对诊断的影响 |
| --- | --- | --- |
| managed proxy 启动 | builder 保留真实 loopback listener；run() spawn 后返回 handle | TCP connect 成功不等于 CONNECT 已解析 |
| ingress | 已使用 `HttpServer::http1()` | 不能复用旧 auto-sniffing 原因作为本次结论 |
| attribution | 首字节为 NUL 才进入 3 秒 frame 读取；普通 CONNECT 首字节为 C | 未收到首字节前仍可等待，收到 C 后不走 frame timeout |
| policy | explicit deny → local/private DNS → allowlist | 此 implicit deny 主机名在拒绝前仍会查询 DNS |
| DNS | 原 deadline 2 秒；失败、超时或私网解析均 fail closed | DNS 若持续 pending 到 deadline，403 无法可靠地赶上同样 2 秒的客户端截止时间 |
| override | 仅 NotAllowed 能交给 decider；NotAllowedLocal 不能被覆盖 | 不能把 allowlist 检查全局提前并声称权限合同不变 |

实际 fb9 整个 `codex-rs/network-proxy` subtree 为 `553134f61e34565be51840475a93f022b3b4dd0c`，与 cabc 完全相同。14 份相关源码的全字节、Git blob 和 SHA-256 身份在 JSON 中逐项保存；ExecServer 两份源码另与实际 fb9 typed read 对齐。

## 为什么暂不提交提前拒绝的生产修改

在没有 decider 的特例中，提前返回 NotAllowed 仍会拒绝请求。但对于解析失败或解析到私网的主机名，原结果是 NotAllowedLocal，提前返回会改变原拒绝优先级、响应正文与 audit/blocked telemetry reason。有 decider 时直接前移还可能让原不可覆盖的私网拒绝进入可覆盖分支。当前没有证明一种绕开 DNS 又保留这些原合同的修改。

修正此前一处口头描述：两个 reason 的 `x-proxy-error` 都是 `blocked-by-allowlist`，这个 header 不变；不同的是正文与具体 reason。也不能用 10.514 秒总耗时推断 DNS 时长、宿主负载、runtime shutdown 或特定 ingress 停顿。

## 最小后续观察

如后续批准一次受保护的临时诊断，仅保留同一个原用例、原 host、原 2 秒与全部断言：记录 prepare/connect/write/read 的真实单调时间；CONNECT accept 与原策略结果；原 DNS await 前后的固定阶段和结果；record_blocked 后构造原 403 的时点。不要替换 DNS、追加 deny、改成 IP、增加重试或放宽超时。临时源必须精确恢复。

这些观察可区分尚未进入 CONNECT、已进入 DNS 但客户端先到截止时间、以及策略完成后响应交付迟滞。即使一次诊断成功，也不能追认原失败已解释或全平台已通过。本报告中的诊断仅为方案，未应用、未运行。

完整原 JUnit 身份、两次精确 case XML、14 个源码 blob、实际树链及所有限域见 `static-diagnosis.json`。本项不会阻止 A 以明确 WIP 状态发布原 CI，也不改变 B16 或原 blocker 的验收条件。
'''
(OUT / 'STATIC_DIAGNOSIS_ZH.md').write_text(md)
print(json.dumps({'artifacts': [identity(OUT / 'static-diagnosis.json'), identity(OUT / 'STATIC_DIAGNOSIS_ZH.md')], 'sources': len(sources), 'network_proxy_tree': proxy_tree}, indent=2))
