"""Read-only accounting of frozen V3 actions; no labels, new policy or intervals."""

import argparse
import hashlib
import json
import math
from pathlib import Path


FIELDS = ('direct_soft_total', 'direct_current', 'forgetting', 'effort',
          'terminal_current_nll', 'terminal_old_nll')
CONTRASTS = (
    ('loss2_h8_vs_myopic', 'loss2_h8_direct_soft', 'loss2_h1_direct_soft'),
    ('full_h8_vs_myopic', 'full_h8_direct_soft', 'loss2_h1_direct_soft'),
    ('full_h8_vs_loss2_h8', 'full_h8_direct_soft', 'loss2_h8_direct_soft'),
)


def mean(values):
    return math.fsum(values) / len(values)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                   indent=2, allow_nan=False) + '\n')


def read_inputs(root, manifest_path=None):
    manifest_file = Path(manifest_path) if manifest_path else root / 'source_manifest.json'
    manifest = json.loads(manifest_file.read_bytes())
    identity = {'repository': 'TrillionniumFoundation/hepta-private-ci',
                'commit': 'a062749d768ea09838921c7f3bfd8b644541b873',
                'prefix': 'qa/stem-bakeoff/evidence/20261024-cell-parameter-field-v3'}
    if any(manifest.get(key) != value for key, value in identity.items()):
        raise ValueError('input manifest is not the fixed V3 source identity')
    expected = {f'runs/anchor-{i:02d}.json' for i in range(18)} | {
        'protocol.json', 'external-analysis.json'}
    if {row['path'] for row in manifest['files']} != expected or len(manifest['files']) != 20:
        raise ValueError('exact published score/protocol input census required')
    payloads, identities = {}, []
    for row in manifest['files']:
        name = row['path']
        raw = (root / name).read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        if blob != row['git_blob_sha1']:
            raise ValueError('input Git identity differs: ' + name)
        identities.append({**row, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
        payloads[name] = json.loads(raw)
    return manifest, payloads, identities


def summarize(rows, label, **identity):
    means = {key: mean([r['difference'][key] for r in rows]) for key in FIELDS}
    thresholds = [r['fixed_action_rho']['rho_star'] for r in rows
                  if r['fixed_action_rho']['rho_star'] is not None]
    d_effort, d_risk = means['effort'], means['direct_current'] + means['forgetting']
    return {'contrast': label, **identity, 'anchor_count': len(rows),
        'mean_difference': means,
        'negative_difference_counts': {key: sum(r['difference'][key] < 0 for r in rows) for key in FIELDS},
        'positive_difference_counts': {key: sum(r['difference'][key] > 0 for r in rows) for key in FIELDS},
        'mean_action_norm_ratio': mean([r['action_norm_ratio'] for r in rows]),
        'action_norm_ratio_range': [min(r['action_norm_ratio'] for r in rows),
                                    max(r['action_norm_ratio'] for r in rows)],
        'rho_star_mean': mean(thresholds) if thresholds else None,
        'rho_star_range': [min(thresholds), max(thresholds)] if thresholds else None,
        'rho_star_of_equal_anchor_mean_cost': -rows[0]['fixed_action_rho']['rho0'] * d_risk / d_effort
                                             if d_effort < 0 else None,
        'scope': 'fixed-anchor descriptive arithmetic; no independent-anchor sampling inference'}


def analyze(root, manifest_path=None):
    manifest, data, identities = read_inputs(root, manifest_path)
    protocol, external = data['protocol.json'], data['external-analysis.json']
    h, rho0, gamma = protocol['h'], protocol['effort_price'], protocol['direct_coefficient']
    if (h, rho0, gamma) != (0.02, 0.1, 0.03):
        raise ValueError('frozen V3 objective identity differs')
    errors = {'actual_direct_sum': 0.0, 'actual_tracking_sum': 0.0,
              'predicted_direct_sum': 0.0, 'predicted_tracking_sum': 0.0,
              'effort_from_physical_norm_squared': 0.0, 'contrast_sum': 0.0}
    rows, conditions, h1_equal = [], 0, 0
    for index in range(18):
        item = data[f'runs/anchor-{index:02d}.json']
        initial, records = item['initial'], item['records']
        if (initial['initial_index'] != index or len(records) != 19
                or len({r['method_id'] for r in records}) != 19
                or any(r['status'] != 'completed' for r in records)):
            raise ValueError('frozen completed condition census differs')
        by_method = {r['method_id']: r for r in records}
        for record in records:
            if record['initial_state_sha256'] != initial['state_sha256']:
                raise ValueError('candidate common complete state differs')
            energy = record['physical_intervention_squared_norm']
            expected_effort = rho0 * energy / (2 * h)
            scored = [('actual', record['actual_scores'])]
            scored += [('predicted', v) for v in record['predicted_scores'].values()]
            for kind, score in scored:
                for name in ('direct', 'tracking'):
                    residual = abs(score[name + '_soft_total'] - math.fsum(
                        (score[name + '_current'], score['forgetting'], score['effort'])))
                    key = kind + '_' + name + '_sum'
                    errors[key] = max(errors[key], residual)
                errors['effort_from_physical_norm_squared'] = max(
                    errors['effort_from_physical_norm_squared'], abs(score['effort'] - expected_effort))
            conditions += 1
        a, b = by_method['loss2_h1_direct_soft'], by_method['full_h1_direct_soft']
        if a['final_state_sha256'] != b['final_state_sha256'] or a['actual_scores'] != b['actual_scores']:
            raise ValueError('direct H1 reference controllers differ')
        h1_equal += 1
        for label, left, right in CONTRASTS:
            lhs, rhs = by_method[left], by_method[right]
            delta = {key: lhs['actual_scores'][key] - rhs['actual_scores'][key] for key in FIELDS}
            risk, effort = delta['direct_current'] + delta['forgetting'], delta['effort']
            errors['contrast_sum'] = max(errors['contrast_sum'], abs(delta['direct_soft_total'] - risk - effort))
            rho_star = -rho0 * risk / effort if effort < 0 else None
            rows.append({'contrast': label, 'left': left, 'right': right,
                'head': initial['head'], 'seed': initial['seed'], 'anchor_offset': initial['anchor_offset'],
                'initial_id': initial['initial_id'], 'initial_state_sha256': initial['state_sha256'],
                'left_scores': {k: lhs['actual_scores'][k] for k in FIELDS},
                'right_scores': {k: rhs['actual_scores'][k] for k in FIELDS}, 'difference': delta,
                'weighted_current_nll_difference': delta['direct_current'] / gamma,
                'left_action_norm': math.sqrt(lhs['physical_intervention_squared_norm']),
                'right_action_norm': math.sqrt(rhs['physical_intervention_squared_norm']),
                'action_norm_ratio': math.sqrt(lhs['physical_intervention_squared_norm'] /
                                               rhs['physical_intervention_squared_norm']),
                'fixed_action_rho': {'rho0': rho0, 'rho_star': rho_star,
                    'nonnegative_crossover': rho_star is not None and rho_star >= 0,
                    'formula': 'delta_J(rho_prime) = delta_risk + (rho_prime/rho0)*delta_effort_at_rho0',
                    'qualification': 'Frozen actions only; no reoptimization, policy selection or change to the V3 primary objective.'}})
    if max(errors.values()) > 1e-17:
        raise ValueError('score accounting or physical-action identity failed')
    summaries = []
    for label, _, _ in CONTRASTS:
        selected = [r for r in rows if r['contrast'] == label]
        summaries.append(summarize(selected, label))
        for head in protocol['head_modes']:
            summaries.append(summarize([r for r in selected if r['head'] == head], label, head=head))
            for anchor in protocol['anchor_offsets']:
                summaries.append(summarize([r for r in selected if r['head'] == head and r['anchor_offset'] == anchor],
                                           label, head=head, anchor_offset=anchor))
    external_rows = []
    for head in protocol['head_modes']:
        profiles = {r['method_id']: r for r in external['anchor16_method_profiles'] if r['head'] == head}
        for label, left, right in CONTRASTS:
            lhs, rhs = profiles[left], profiles[right]
            external_rows.append({'head': head, 'anchor_offset': 16, 'contrast': label,
                'future_equal_month_nll_difference': lhs['future_equal_month']['nll'] - rhs['future_equal_month']['nll'],
                'role_nll_differences': {role: lhs['by_role'][role]['nll'] - rhs['by_role'][role]['nll']
                                         for role in lhs['by_role']},
                'scope': 'Existing frozen evaluation point estimates only; no new interval or confirmation.'})
    primary = [r for r in external['primary']['rows'] if r['id'] == 'remaining_vs_myopic_future']
    return {'schema': 'hepta.cell-v3-objective-decomposition.v1',
        'source_repository': manifest['repository'], 'source_commit': manifest['commit'], 'source_prefix': manifest['prefix'],
        'input_files': identities, 'objective': {'h': h, 'rho0': rho0, 'direct_coefficient': gamma},
        'checks': {'anchors': 18, 'registered_conditions_checked': conditions, 'direct_h1_full_loss2_equal': h1_equal,
                   'actual_score_sets': conditions, 'predicted_score_sets': 2 * conditions, 'maximum_absolute_errors': errors},
        'comparisons': rows, 'summaries': summaries, 'anchor16_external_point_differences': external_rows,
        'unchanged_registered_future_intervals': primary,
        'interpretation': [
            'Loss2 H8 reduces the scalarized actual objective by reducing its quadratic action penalty, while current risk rises.',
            'Effort is the prescribed quadratic action penalty, not measured wall time, CPU, memory or energy use.',
            'All stated rho thresholds rescore already frozen actions; they are not optimized policies at another price.',
            'Eighteen anchors are dependent states of six fixed seed/Head paths; all aggregates are descriptive.',
            'Future H8-minus-H1 point estimates are positive but original adjusted intervals cross zero; significant external deterioration is not established.',
            'The accounting explains the apparent internal-cost/current-risk reversal, but does not identify all causes of external generalization.'],
        'new_training_runs': 0, 'new_candidate_actions': 0, 'new_confidence_intervals': 0,
        'label_payloads_opened': False, 'policy_selected': False, 'frozen_v3_modified': False}


def markdown(report):
    global_rows = [r for r in report['summaries'] if 'head' not in r]
    lines = ['# V3 只读机制补充：共同 J 的改善来自哪里', '',
        '本分析仅复算固定 V3 的已发布分数，不读取标签 payload，不运行新动作，不重新优化或选择策略。', '',
        '## 共同目标的精确分解', '',
        '下表四个成本项单位为 10⁻⁶；末列 terminal 当前 NLL 差的单位为 nat。均为左减右、18 个相关 anchor 的描述性均值。', '',
        '| 比较 | Δ 当前风险成本 | Δ 旧任务惩罚 | Δ 动作惩罚 | Δ J | terminal 当前 NLL 差 |',
        '|---|---:|---:|---:|---:|---:|']
    for row in global_rows:
        d = row['mean_difference']
        lines.append(f"| {row['contrast']} | {d['direct_current']*1e6:.6f} | {d['forgetting']*1e6:.6f} | "
                     f"{d['effort']*1e6:.6f} | {d['direct_soft_total']*1e6:.6f} | {d['terminal_current_nll']:.9g} |")
    first = global_rows[0]
    lines += ['', '**Loss2 H8−H1 在 18/18 个状态上同时表现为：J 降低、当前风险成本升高、动作惩罚降低、terminal current-probe NLL 升高。**', '',
        '动作惩罚为 h·ρ·||u||²/2；它不是实测计算开销。Direct 替换了 tracking 的当前项，但共同目标仍保留此惩罚。', '',
        '## 仅对冻结动作重评分的临界 ρ', '',
        '保持这两个已经冻结的动作不变，ΔJ(ρ′)=Δrisk+(ρ′/ρ₀)Δeffort；当 Δeffort<0 时，ρ*=−ρ₀Δrisk/Δeffort。', '',
        f"Loss2 H8/H1 的 18 个临界值范围为 [{first['rho_star_range'][0]:.9f}, {first['rho_star_range'][1]:.9f}]，"
        f"算术均值 {first['rho_star_mean']:.9f}。按等权 anchor 平均成本计算的单一交点为 {first['rho_star_of_equal_anchor_mean_cost']:.9f}；"
        '后者是比值的另一种聚合，不等于逐状态交点的均值。原协议 ρ₀=0.1。', '',
        '**这些交点只说明原有两动作的目标计价；不能当作选择新 ρ 的验证结果，也不能当作另一 ρ 下重优化策略的性能。**', '',
        '## 已有外部评价的方向', '',
        '| Head | H8−H1 terminal current-probe NLL | current-validation NLL | future 等月 NLL |',
        '|---|---:|---:|---:|']
    for head in ('linear', 'gated'):
        current = next(r for r in report['summaries'] if r['contrast'] == 'loss2_h8_vs_myopic' and r.get('head') == head and r.get('anchor_offset') == 16)
        ext = next(r for r in report['anchor16_external_point_differences'] if r['contrast'] == 'loss2_h8_vs_myopic' and r['head'] == head)
        lines.append(f"| {head} | {current['mean_difference']['terminal_current_nll']:.9g} | "
                     f"{ext['role_nll_differences']['current_validation']:.9g} | {ext['future_equal_month_nll_difference']:.9g} |")
    lines += ['', 'Future 差异仅是原有点估计，原先校正区间仍跨零，没有新的外部劣化确认。有限状态的会计分解也不能覆盖所有分布迁移机制。', '',
        'Full H8 相对 H1 在全部 18 状态同时降低实际当前风险成本与动作惩罚；当前 Loss2 闭合近似和目标内的风险／动作权衡仍是应分别检查的问题。', '',
        f"来源固定：{report['source_repository']} @ `{report['source_commit']}`。全部 {len(report['input_files'])} 个输入包含 Git blob SHA1 与 SHA256；详见 JSON。", '']
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-directory', required=True)
    parser.add_argument('--manifest', help='External source manifest; inputs remain read-only.')
    parser.add_argument('--output', required=True)
    parser.add_argument('--markdown', required=True)
    args = parser.parse_args()
    result = analyze(Path(args.input_directory), args.manifest)
    write_json(args.output, result)
    Path(args.markdown).write_text(markdown(result))
    print(json.dumps({'checks': result['checks'], 'loss2': result['summaries'][0]}, indent=2))
