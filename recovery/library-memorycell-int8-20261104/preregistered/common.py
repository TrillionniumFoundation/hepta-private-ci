"""Pure standard-library validation, agreement and prospective decision rules."""
import hashlib
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parent

def process_peak(snapshot):
    # Linux ru_maxrss may retain a pre-exec ancestor high-water mark.
    value = snapshot['status_VmHWM']
    assert isinstance(value, int) and value > 0
    return value


def read_json(path):
    return json.loads(Path(path).read_text())

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def validate_fixtures(data):
    assert set(data) == {'schema', 'purpose', 'queries'}
    assert data['schema'] == 1 and len(data['queries']) == 12
    counts = {'short': 48, 'medium': 112, 'long': 224}
    strata = []
    for i, row in enumerate(data['queries'], 1):
        assert set(row) == {'id', 'stratum', 'query', 'passages'}
        assert row['id'] == f'q{i:02d}'
        assert 1 <= len(row['query'].split()) <= 24
        assert len(row['passages']) == 4
        strata.append(row['stratum'])
        for j, p in enumerate(row['passages'], 1):
            assert set(p) == {'id', 'text'}
            assert p['id'] == f'q{i:02d}p{j}'
            assert len(p['text'].split()) == counts[row['stratum']]
    assert strata == ['short'] * 4 + ['medium'] * 4 + ['long'] * 4
    for index in (3, 7):
        assert data['queries'][index]['passages'][0]['text'] == data['queries'][index]['passages'][1]['text']
    return data['queries']

def nearest_rank(values, probability):
    assert values and 0 < probability <= 1
    return sorted(values)[math.ceil(probability * len(values)) - 1]

def top_set(scores, epsilon):
    assert len(scores) == 4 and all(math.isfinite(v) for v in scores)
    best = max(scores)
    return {i for i, value in enumerate(scores) if best - value <= epsilon}

def agreement(reference, candidate, epsilon, margin=0.1, query_offset=0):
    assert len(reference) == len(candidate) and len(reference) > 0
    differences = []
    overlapping = exact_top_sets = 0
    ties_ref = ties_cand = strict_pairs = discordant = tie_mismatches = 0
    margin_total = margin_correct = 0
    rank_changes = []
    for qi, (r, c) in enumerate(zip(reference, candidate), 1 + query_offset):
        rset, cset = top_set(r, epsilon), top_set(c, epsilon)
        differences += [abs(x - y) for x, y in zip(r, c)]
        overlapping += bool(rset & cset)
        exact_top_sets += rset == cset
        ties_ref += len(rset) > 1
        ties_cand += len(cset) > 1
        for i in range(4):
            for j in range(i + 1, 4):
                def sign(value):
                    return 0 if abs(value) <= epsilon else (1 if value > 0 else -1)
                rs, cs = sign(r[i] - r[j]), sign(c[i] - c[j])
                if abs(r[i] - r[j]) >= margin:
                    margin_total += 1
                    margin_correct += rs == cs
                if rs != cs:
                    rank_changes.append({'query': f'q{qi:02d}', 'passages': [i + 1, j + 1], 'reference_sign': rs, 'candidate_sign': cs, 'reference_gap': abs(r[i] - r[j])})
                if rs and cs:
                    strict_pairs += 1
                    discordant += rs != cs
                elif rs != cs:
                    tie_mismatches += 1
    return {'max_abs_raw_logit_difference': max(differences),
            'mean_abs_raw_logit_difference': statistics.mean(differences),
            'top_set_overlap_queries': overlapping, 'identical_top_set_queries': exact_top_sets,
            'reference_top_tie_queries': ties_ref, 'candidate_top_tie_queries': ties_cand,
            'strict_comparable_passage_pairs': strict_pairs,
            'discordant_strict_passage_pairs': discordant, 'passage_pair_tie_mismatches': tie_mismatches,
            'margin_comparable_pairs': margin_total, 'margin_concordant_pairs': margin_correct,
            'margin_concordance': margin_correct / margin_total if margin_total else 0.0,
            'all_pairwise_rank_changes': rank_changes}

def repeat_difference(left, right):
    assert len(left) == len(right) == 12
    return max(abs(a - b) for l, r in zip(left, right) for a, b in zip(l, r))

def summarize(sessions, protocol):
    assert [s['arm'] for s in sessions] == protocol['order']
    epsilon = protocol['tie_epsilon']
    paired = []
    for index in range(0, len(sessions), 2):
        by_arm = {s['arm']: s for s in sessions[index:index + 2]}
        paired.append((by_arm['fp32'], by_arm['int8']))
    agreements = [agreement(b['scores'], c['scores'], epsilon, protocol['ranking_reference_margin']) for b, c in paired]
    repeats = {arm: max(repeat_difference([s for s in sessions if s['arm'] == arm][0]['scores'], s['scores'])
                       for s in sessions if s['arm'] == arm) for arm in ('fp32', 'int8')}
    pairs = []
    for base, candidate in paired:
        b, c = base['timing'], candidate['timing']
        warm_b, warm_c = b['mean_query_ms'], c['mean_query_ms']
        ready_b, ready_c = base['ready_from_launch_ms'], candidate['ready_from_launch_ms']
        saving = warm_b - warm_c
        pairs.append({
            'warm_throughput_ratio': c['pairs_per_second'] / b['pairs_per_second'],
            'p95_latency_ratio': c['p95_query_ms'] / b['p95_query_ms'],
            'state_serialized_bytes_ratio': candidate['state_serialized_bytes'] / base['state_serialized_bytes'],
            'first_query_from_launch_ratio': candidate['first_query_from_launch_ms'] / base['first_query_from_launch_ms'],
            'ready_from_launch_ratio': ready_c / ready_b,
            'full_session_from_launch_ratio': candidate['full_session_from_launch_ms'] / base['full_session_from_launch_ms'],
            'projected_500_query_cost_ratio': (ready_c + protocol['projection_queries'] * warm_c) /
                                              (ready_b + protocol['projection_queries'] * warm_b),
            'break_even_queries': max(0, math.ceil((ready_c - ready_b) / saving)) if saving > 0 else None,
            'break_even_note': 'No sustained warm speed saving' if saving <= 0 else 'Linear projection; not observed service traffic',
            'startup_inference_peak_rss_bytes_ratio': candidate['startup_inference_peak_rss_bytes'] / base['startup_inference_peak_rss_bytes'],
            'experiment_peak_rss_including_serialization_ratio': candidate['worker_peak_rss_bytes'] / base['worker_peak_rss_bytes']})
    g = protocol['gates']
    checks = {
        'raw_logit_max_difference': all(a['max_abs_raw_logit_difference'] <= g['max_abs_raw_logit_difference'] for a in agreements),
        'raw_logit_mean_difference': all(a['mean_abs_raw_logit_difference'] <= g['mean_abs_raw_logit_difference'] for a in agreements),
        'top_set_overlap': all(a['top_set_overlap_queries'] >= g['minimum_top_set_overlap_queries'] for a in agreements),
        'identical_top_sets': all(a['identical_top_set_queries'] >= g['minimum_identical_top_set_queries'] for a in agreements),
        'margin_ranking': all(a['margin_comparable_pairs'] >= g['minimum_margin_comparable_pairs'] and a['margin_concordance'] >= g['minimum_margin_concordance'] for a in agreements),
        'repeat_consistency': all(v <= g['repeat_max_abs_logit_difference'] for v in repeats.values()),
        'state_bytes': all(p['state_serialized_bytes_ratio'] <= g['max_state_serialized_bytes_ratio'] for p in pairs),
        'warm_throughput': all(p['warm_throughput_ratio'] >= g['minimum_each_pair_warm_throughput_ratio'] for p in pairs),
        'p95': all(p['p95_latency_ratio'] <= g['maximum_each_pair_p95_latency_ratio'] for p in pairs),
        '500_query_projected_cost': all(p['projected_500_query_cost_ratio'] <= g['maximum_each_pair_projected_500_query_cost_ratio'] for p in pairs)}
    return {'scope': 'Engineering-only agreement and cost on 48 fictional pairs, one host; no utility inference',
            'timing_units': 'Six counterbalanced session pairs; requests are not independent statistical replicates',
            'pair_agreement': agreements,
            'pair_agreement_by_stratum': [{name: agreement(b['scores'][offset:offset + 4], c['scores'][offset:offset + 4], epsilon, protocol['ranking_reference_margin'], offset) for name, offset in (('short', 0), ('medium', 4), ('long', 8))} for b, c in paired],
            'repeat_max_abs_logit_difference': repeats,
            'paired_costs': pairs, 'gates': checks,
            'decision': 'PASSES_ENGINEERING_SCREEN_ON_THIS_FIXTURE_AND_HOST_ONLY' if all(checks.values()) else 'DOES_NOT_QUALIFY',
            'negative_costs_retained': True, 'confidence_intervals': None}

def verify_seal():
    seal = read_json(ROOT / 'seal.json')
    for name, expected in seal['sha256'].items():
        assert Path(name).name == name
        assert sha256(ROOT / name) == expected, f'Frozen artifact mismatch: {name}'
    return sha256(ROOT / 'seal.json')

def verify_assets(asset_dir, admission, protocol):
    root = Path(asset_dir).resolve()
    allowed = {'config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json', 'vocab.txt', 'model.safetensors'}
    files = admission['asset_sha256']
    assert set(files) <= allowed
    assert {'config.json', 'tokenizer_config.json', 'vocab.txt', 'model.safetensors'} <= set(files)
    assert set(p.name for p in root.iterdir()) == set(files), 'Unlisted assets or code present'
    assert admission['model_revision'] == protocol['model_revision']
    assert files['model.safetensors'] == protocol['model_safetensors_sha256']
    for name, expected in files.items():
        path = root / name
        assert path.is_file() and not path.is_symlink()
        assert path.stat().st_size < (200_000_000 if name == 'model.safetensors' else 10_000_000)
        assert sha256(path) == expected, f'Asset hash mismatch: {name}'
    for name in ('config.json', 'tokenizer_config.json'):
        assert 'auto_map' not in read_json(root / name), 'Custom code mapping forbidden'
    config = read_json(root / 'config.json')
    assert config.get('model_type') == 'bert'
    assert config.get('hidden_size') == 384 and config.get('num_hidden_layers') == 6
    assert admission['runtime_versions'] == protocol['runtime_versions']
    return files
