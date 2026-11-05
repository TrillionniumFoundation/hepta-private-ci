"""Derive a non-executing foundation binding checklist from frozen inputs."""

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path('/workspace/scratch/07dd58cc9630')
HERE = Path(__file__).resolve().parent
OUT = HERE / 'foundation-readiness-v1'
OUT.mkdir(exist_ok=True)


def load(path):
    return json.loads(path.read_bytes())


def identity(path):
    data = path.read_bytes()
    return {'path': str(path.relative_to(ROOT)), 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest(),
            'blob': hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()}


def dump(name, data):
    path = OUT / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    return identity(path)


payload = load(HERE / 'payload-manifest.json')
epoch = load(HERE / 'epoch-foundation.json')
integrity = identity(HERE / 'runner-integrity.json')
assert integrity['sha256'] == 'dacf3296af381bee42fcf7bafb7796aac8cb558ea8a0df078d325e919344780a'
selection_path = ROOT / 'ci-audit/recovered-20261105/full-fb9-complete-archive/decoded-verified-v1/full-workspace-selection.json'
selection = load(selection_path)
selection_id = identity(selection_path)
assert selection_id['bytes'] == 5364870
assert selection_id['sha256'] == '48dcb2b104793c7dac9699803e4746d6d8145bcc66701de167de57cbf6bd3c6c'
assert selection['source'] == 'fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff'
assert selection['cargo_profile'] == 'dev-small' and selection['nextest_profile'] == 'local'
helpers = selection['helpers_after_catalog_before_just']
programs = selection['test_binaries_after_catalog_before_just']
unique = {row['path']: row for row in [*programs, *helpers]}
assert len(unique) == len(programs) + len(helpers) == 354
executable_bytes = sum(row['bytes'] for row in unique.values())
assert executable_bytes == 18122997968
roster = sorted(Path(row['path']).name for row in helpers)
assert len(roster) == 33

initial, current, modes = {}, {}, {}
transitions, stages, positive, negative = [], [], [], []


def apply(label):
    delta = payload['deltas'][label]
    for row in delta['files']:
        path = row['path']
        if path not in initial:
            initial[path] = row['before_blob']
            current[path] = row['before_blob']
            modes[path] = row['mode']
        assert current[path] == row['before_blob'], (label, path)
        assert modes[path] == row['mode']
        current[path] = row['after_blob']
    transitions.append(label)


for operation in epoch['operations']:
    if operation['kind'] == 'apply':
        apply(operation['delta'])
        continue
    for delta in operation.get('before', []):
        apply(delta)
    stage = {'display_label': 'B16/phase/' + operation['id'], 'kind': operation['kind'],
             'before': operation.get('before', []), 'restore': operation.get('restore'),
             'scopes': copy.deepcopy(operation['scopes'])}
    for scope in operation['scopes']:
        (negative if operation['kind'] == 'negative' else positive).extend(scope['exact_names'])
    if operation.get('restore'):
        apply(operation['restore'])
    stages.append(stage)
assert len(initial) == 16 and sum(v is not None for v in initial.values()) == 7
assert len(set(positive)) == 24 and len(positive) == 27 and len(negative) == 10
assert set(current) < set(payload['foundation_end_map'])
context_only = {p: b for p, b in payload['foundation_end_map'].items() if p not in current}
assert set(context_only) == {'codex-rs/Cargo.toml', 'codex-rs/hepta-memory/Cargo.toml',
                             'codex-rs/hepta-memory/src/cognitive_store_recovery_tests.rs'}
for path, blob in current.items():
    assert payload['foundation_end_map'][path] == blob

cabc_path = ROOT / 'hepta-audit-fourth/inputs/cabc-tree.json'
cabc = {row['path']: row for row in load(cabc_path)['tree']}
fb9_codex_api_path = ROOT / 'architecture-audit/fb9-proxy-connect-20261105/fb9-codex-tree-api.json'
fb9_codex = json.loads(load(fb9_codex_api_path)['structuredContent']['content'])
fb9_crates = {row['path']: row for row in fb9_codex['tree']}
subtrees = []
for crate in ['state', 'hepta-memory']:
    assert fb9_crates[crate]['sha'] == cabc['codex-rs/' + crate]['sha']
    subtrees.append({'path': 'codex-rs/' + crate, 'fb9_tree': fb9_crates[crate]['sha'],
                     'same_as_cabc_tree': True, 'final_A_tree_not_observed': True})
frontier = []
for path, blob in initial.items():
    assert (cabc[path]['sha'] if path in cabc else None) == blob
    frontier.append({'path': path, 'mode': modes[path], 'required_initial_blob': blob,
                     'required_initial_state': 'ABSENT' if blob is None else 'EXACT_EXISTING',
                     'observed_at_last_tested_fb9': True,
                     'final_A_match': None, 'foundation_final_blob': current[path]})

budget = {'additional_executable_families': 1, 'other_cargo_growth_bytes': 12000000000,
          'bazel_growth_bytes': 0, 'evidence_growth_bytes': 2000000000,
          'estimate_review_reference': None}
reserve = 8000000000
required = executable_bytes + budget['other_cargo_growth_bytes'] + budget['evidence_growth_bytes'] + reserve
root_reported_free = 47045021696
assert required == 40122997968
assert root_reported_free - required == 6922023728

binding = load(HERE / 'binding-template-UNBOUND.json')
binding['last_tested_A_tree'] = selection['source']
binding['last_tested_A_artifacts'] = {'path': None, 'bytes': selection_id['bytes'], 'sha256': selection_id['sha256']}
binding['A_helper_basename_roster'] = roster
binding['capacity_plan'] = budget
assert binding['execute'] is False and binding['final_A_tree'] is None
binding_id = dump('foundation-binding-UNBOUND.json', binding)

helper_id = dump('last-tested-fb9-helper-contract.json', {
    'schema': 'hepta-b16-last-tested-A-helper-roster-v1',
    'source_tree': selection['source'], 'full_original_artifact_receipt': selection_id,
    'catalogue_is_original_full_workspace': True,
    'program_count': len(programs), 'program_bytes': sum(r['bytes'] for r in programs),
    'helper_count': len(helpers), 'helper_bytes': sum(r['bytes'] for r in helpers),
    'unique_executable_count': len(unique), 'unique_executable_bytes': executable_bytes,
    'helper_basename_multiset': roster,
    'helper_identity_observations': [{'basename': Path(r['path']).name, 'bytes': r['bytes'], 'sha256': r['sha256']} for r in helpers],
    'limits': ['Observed executable file bytes are not total target allocation or a measured peak.',
               'The native paths remain in the original receipt; this projection does not change or relabel it.',
               'These old hashes are not B execution qualifications. Each B scope actually rebuilds and records current identities.',
               'Final A after hygiene remains a separately bound source identity.'],
})

readiness = {
    'schema': 'hepta-b16-foundation-binding-readiness-v1',
    'status': 'SOURCE_ONLY_PREPARATION_PENDING_FINAL_A_AND_EXPLICIT_AUTHORIZATION',
    'internal_stage_ids_are_not_original_blocker_ids': True,
    'display_namespace': 'B16/phase', 'authorized_epoch_proposal': 'foundation',
    'runner_v3_review': {'blob': '0386b554e5a396330e4ddee83a0cc903647b9f2b', 'map_blob': '240122fa2895525e8f95e6b3490a23e9bc5bd105'},
    'independent_v3_static_review_blob': '1dc4b57dc1b8ef6b9b66d9c9739358efbe2f797d',
    'frozen_runner_integrity': integrity, 'frozen_payload': identity(HERE / 'payload-manifest.json'),
    'frozen_foundation_epoch': identity(HERE / 'epoch-foundation.json'),
    'actual_last_tested_A_tree': selection['source'], 'final_A_tree': None,
    'last_tested_A_artifact': selection_id,
    'archive_index_blob': '87873969544e952a8fcff9ad771f834ffc856537',
    'archive_strict_decode_review_blob': '6296d695a50d3344387d2c2b48fc081871356448',
    'foundation_source_frontier': frontier, 'last_tested_subtree_proof': subtrees,
    'frozen_projection_context_not_changed_by_foundation': context_only,
    'source_frontier_limit': 'All 16 preimages match last-tested fb9 via complete matching crate subtrees, not yet final A. A changed existing blob or a new-path collision must stop for a reviewed delta; never overwrite with a cabc donor.',
    'foundation_counts': {'source_paths': 16, 'existing_exact_preimages': 7, 'new_paths_requiring_absence': 9,
                          'distinct_positive_cases': 24, 'positive_case_executions': 27, 'negative_case_executions': 10},
    'delta_order_including_finally': transitions, 'exact_stages': stages,
    'separation_guards': [
        'No SQLx vendor/native lifetime-token adoption in foundation; otherwise the old missing-custody negatives could be masked.',
        'No Cargo.toml, BUILD.bazel, Cargo.lock or MODULE.bazel.lock changes in foundation.',
        'No Bazel dependency generation/build/test operations in foundation; the unchanged runner still checks the pinned Bazel version.',
        'No changed original SQLite/physical assertion, timeout, retry, ignored-support accounting, or phase ordering.',
        'Only ordinary JUnit exit 101 plus the frozen exact physical endpoint can qualify a negative. Timeout/leak/error/early-return remains invalid.',
    ],
    'capacity_proposal': {
        'binding_capacity_plan': budget, 'min_free_bytes': reserve,
        'observed_last_tested_executable_bytes': executable_bytes,
        'proposed_required_free_bytes': required,
        'root_reported_current_free_bytes': root_reported_free,
        'root_reported_free_decimal_GB': root_reported_free / 1000000000,
        'arithmetic_headroom_bytes': root_reported_free - required,
        'root_free_provenance': 'Root message citing actual A hygiene-manifest observation; this author has not independently reread that host free-space receipt.',
        'same_V3_runner_supports_epoch_specific_budget_without_runtime_change': True,
        'driver_would_require_new_review': True,
        'driver_old_8GB_Bazel_allowance_required_if_other_values_unchanged': required + 8000000000,
        'limits': [
            'This is a conditional planning estimate, not a demonstrated compiler/linker peak or a hard upper bound.',
            'A fresh same-filesystem free-byte reading and explicit root budget review are still required at actual launch.',
            'The runner checks the original 8 GB reserve before and after commands; this does not prove an in-flight build never drops below it.',
            'No cache deletion, scope reduction, retry, profile change, or inherited executable qualification is authorized.',
            'Driver has a new dependency/workspace edge and real Bazel lock generation; it must use the actual foundation terminal state and a newly reviewed remaining-growth plan.',
        ],
    },
    'binding_checklist': [
        {'item': 'final_A_tree and initial_tree', 'state': 'PENDING', 'requirement': 'Actual independently reviewed full source after A fix/fmt. Both must be exactly equal for foundation.'},
        {'item': 'last_tested_A versus final_A relation', 'state': 'PENDING', 'requirement': 'Retain fb9 full artifacts under fb9. Review exact hygiene delta; do not relabel old program hashes or rerun A after hygiene solely for this field.'},
        {'item': '16 source preimages and absent paths', 'state': 'PENDING_FINAL_A', 'requirement': 'Check all frontier rows against the full final-A tree and working files. Known fb9 equality is only prior evidence.'},
        {'item': 'ordinary HEAD and ordinary index', 'state': 'PENDING', 'requirement': 'Pin the actual final A bytes and HEAD; do not reuse the earlier pre-Python index identity. Require no unreviewed untracked source.'},
        {'item': 'two active lock files', 'state': 'PENDING', 'requirement': 'Pin both actual final-A Cargo.lock and MODULE.bazel.lock. Foundation must leave them byte-identical.'},
        {'item': 'baseline full no-p metadata', 'state': 'PENDING', 'requirement': 'Bind actual metadata to final_A/initial_tree, with its complete graph and source relationship; no old source retagging.'},
        {'item': 'last tested complete helpers', 'state': 'OBSERVED_FB9', 'requirement': 'Bind the immutable full-selection receipt and all 33 basenames. Each B scope must build the six normal helpers and catalogue the full workspace, then record actual current 33 identities.'},
        {'item': 'target/cache ownership and disk', 'state': 'PENDING', 'requirement': 'Reuse the root-bound existing dev-small A target, no cache copy or deletion. Bind a future B-only Bazel-cache identity without creating it during foundation; driver creates it after separate approval. All measured locations share the actual filesystem.'},
        {'item': 'tools, recipes and environment', 'state': 'PENDING', 'requirement': 'Pin all six actual tools, original recipe hashes, Rust 1.95.0, dev-small/local, actual helper inputs and allowed environment. Do not inherit a missing prerequisite as zero tests.'},
        {'item': 'explicit launch authorization', 'state': 'PENDING', 'requirement': 'Root separately binds epoch foundation only, source/runner/payload identities and reviewed capacity. This artifact is not an execution guard.'},
    ],
    'prepared_binding': binding_id, 'helper_contract': helper_id,
    'no_native_commands_run': True, 'no_runner_or_source_payload_edits': True,
    'no_blocker_exit_or_status_changes': True,
}
readiness_id = dump('foundation-readiness.json', readiness)

md = f'''# B16 基础阶段：最终 A 绑定清单

本文件是 V3 runner 的独立准备收据，**没有启动 B，没有修改冻结 runner 或产品源码**。这里只准备 `B16/phase/B01–B10`，这些内部编号不代表原 blocker 账本的 B01–B10。

## 已固定与待固定

现成 fb9 完整 selection 原件为 5,364,870 字节，SHA-256 `48dcb2b104793c7dac9699803e4746d6d8145bcc66701de167de57cbf6bd3c6c`。321 个实际测试程序共 15,300,982,712 字节，33 个实际 helper 共 2,822,015,256 字节，354 个独立文件合计 **18,122,997,968 字节**。这是文件大小观察，不能当作整个 target 的占用或构建峰值。

`last_tested_A_tree` 可固定为 `fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff`。`final_A_tree` 必须等 A 最后的 fix/fmt 与完整源审查。原 ordinary index 曾受 Python/Git 步骤影响，因此索引、HEAD、两把锁和完整 metadata 都必须从最终状态重新绑定；不能把 fb9 旧产物改标签说成 final A 测过。

基础阶段有 16 个路径，7 个要求既有精确 blob，9 个要求原路径不存在。全部在 last-tested fb9 上已用真实 crate subtree 身份与冻结 payload 对齐，但最终 A 仍须再次核对。逐文件 pre/post 和 absent 要求已列入 JSON；任何不符必须停止并审新 delta。

## 这一个 epoch 的范围

保持原 24 个不同正向用例、27 次正向执行（codec 前 3 个在后续 7 例中重复）及 10 次精确反事实；保持真实 SQLite、物理锁、原时间预算、0 retry、完整 JUnit 与 finally 精确恢复。先完成 foundation，再引入 native lifetime token。基础阶段不改 Cargo/BUILD 或两把锁，不进行 Bazel 生成、build 或 test；既有 runner 的 Bazel 版本校验仍保留。

每个 scope 仍实际构建 6 个 normal helpers，并运行完整 workspace metadata/catalog，然后精确核对来自 fb9 的完整 33 个 basename 清单，重新记录当前程序与 helper 字节。共用 target 不构成借用旧产物资格。

## 单阶段容量提案

| 项目 | 字节 |
| --- | ---: |
| 额外一个实际已观测 executable family | 18,122,997,968 |
| 其他 Cargo 增长估计 | 12,000,000,000 |
| foundation 的 Bazel 增长 | 0 |
| evidence 增长估计 | 2,000,000,000 |
| 原保留余量 | 8,000,000,000 |
| **规划所需 free** | **40,122,997,968** |
| Root 给出的实际 free 观察 | 47,045,021,696 |
| 仅按以上数字的余量 | 6,922,023,728 |

Root 的 free 是十进制 47.045 GB；作者尚未独立重读其 host 收据。这个估算不是峰值实证，也不是启动许可。实际启动前必须重新读取同一文件系统 free，并由 Root 明确接受本 epoch 的估算。原 8 GB 检查不变、不删 cache、不减少 scope；命令前后检查也不能保证编译进行中绝不跌破余量。

driver 阶段会新增依赖和真实 Bazel 生成，必须依据 foundation 真实终态重新评估。如仍套用旧 8 GB Bazel 估计，总要求会回到 48,122,997,968 字节，超过这次报告的 free，不能将 foundation 的预算许可外推。

## 可交接入口

`foundation-binding-UNBOUND.json` 仅预填真实 fb9 selection 哈希、33 个 helper basename 和待审容量提案；`execute=false`，最终 A、索引、锁、metadata、路径及审批引用仍为空。它不能启动 runner。实际执行仍由唯一 native executor 在 Root 的独立 source guard 后进行：`python3 b16_runner.py --binding <reviewed-binding> --epoch foundation`。

完整逐项检查和 exact stage 名单见 `foundation-readiness.json`。V3 runner、原始 42 个对象及 V1/V2 历史保留，本次不改变 B16 或原 23 项 blocker 的退出条件。
'''
(OUT / 'FOUNDATION_BINDING_ZH.md').write_text(md)
print(json.dumps({'artifacts': [readiness_id, binding_id, helper_id, identity(OUT / 'FOUNDATION_BINDING_ZH.md')], 'required_bytes': required, 'headroom_bytes': root_reported_free - required}, indent=2))
