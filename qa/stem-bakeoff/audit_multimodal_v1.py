"""Read-only replay of the fixed COCO experiment; no experiment imports.

The arguments relocate retained inputs, not the fixed experimental design.
Only the requested output directory is written. No model is downloaded or trained.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import subprocess
import unicodedata

import numpy as np
from PIL import Image, ImageOps
import torch
import torch.nn.functional as F

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo', required=True, type=Path)
parser.add_argument('--cohorts', required=True, type=Path)
parser.add_argument('--bank', required=True, type=Path)
parser.add_argument('--results', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--threads', type=int, choices=range(1, 9), default=2)
args = parser.parse_args()
REPO, DATA, BANK, RESULT, OUT = (
    p.resolve() for p in (args.repo, args.cohorts, args.bank, args.results, args.output)
)
for source in (REPO, DATA, BANK, RESULT):
    if not source.is_dir():
        parser.error(f'input directory does not exist: {source}')
for source in (DATA, BANK, RESULT):
    if OUT == source or source in OUT.parents:
        parser.error('output must be outside the retained data, bank and result directories')
if (OUT / 'audit.json').exists():
    parser.error('refusing to overwrite an existing audit.json; choose a fresh output directory')
OUT.mkdir(parents=True, exist_ok=True)
torch.set_num_threads(args.threads)


def canonical(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(x):
    return hashlib.sha256(x).hexdigest()


def read_json(path):
    return json.loads(path.read_bytes())


def ensure(condition, message):
    if not condition:
        raise AssertionError(message)


def metric(a, temperature):
    y, pred, accepted, p = (a[k] for k in ('labels', 'prediction', 'accepted', 'probabilities'))
    z = a['logits'] / temperature
    log_norm = np.logaddexp(z[:, 0], z[:, 1])
    derived = np.exp(z - log_norm[:, None])
    ensure(np.allclose(derived, p, atol=2e-14, rtol=2e-14), 'probability/logit mismatch')
    ensure(np.array_equal(p.argmax(1), pred), 'prediction mismatch')
    ensure(np.array_equal(p.max(1) >= .7, accepted), 'acceptance mismatch')
    counts = [int(((y == truth) & (pred == guess)).sum()) for truth, guess in ((0, 0), (0, 1), (1, 0), (1, 1))]
    tn, fp, fn, tp = counts
    errors = int(((pred != y) & accepted).sum())
    conf = p.max(1)
    ece = sum(float(mask.mean()) * abs(float(conf[mask].mean()) - float((pred[mask] == y[mask]).mean()))
              for b in range(10) if (mask := np.minimum((conf * 10).astype(int), 9) == b).any())
    ap = 0.0
    for score in np.unique(p[:, 1])[::-1]:
        equal = p[:, 1] == score
        above = p[:, 1] >= score
        ap += float(y[equal].sum() / y.sum()) * float(y[above].sum() / above.sum())
    n = int(accepted.sum())
    return {'rows': len(y), 'confusion_tn_fp_fn_tp': counts, 'accuracy': float((pred == y).mean()),
            'balanced_accuracy': .5 * (tp / (tp + fn) + tn / (tn + fp)),
            'positive_recall': tp / (tp + fn), 'negative_recall': tn / (tn + fp),
            'average_precision': ap, 'nll': float((log_norm - z[np.arange(len(y)), y]).mean()),
            'brier_multiclass_sum': float(np.square(p - np.eye(2)[y]).sum(1).mean()),
            'ece10_equal_width': ece, 'coverage': n / len(y), 'accepted_count': n,
            'accepted_error_count': errors, 'selective_risk': errors / n if n else None}


def bootstrap(a):
    names = sorted(set(a['pair_block_ids']))
    summaries = []
    for name in names:
        mask = a['pair_block_ids'] == name
        y, pred, accepted = (a[k][mask] for k in ('labels', 'prediction', 'accepted'))
        summaries.append([len(y), int((y == 1).sum()), int((y == 0).sum()),
                          int((pred == y).sum()), int(((y == 1) & (pred == 1)).sum()),
                          int(((y == 0) & (pred == 0)).sum()), int(accepted.sum()),
                          int(((pred != y) & accepted).sum())])
    draws = np.random.default_rng(20261022).integers(len(names), size=(2000, len(names)))
    n, pos, neg, correct, tp, tn, accepted, wrong = np.asarray(summaries, dtype=float)[draws].sum(1).T
    ratio = lambda x, d, default: np.divide(x, d, out=np.full_like(x, default), where=d > 0)
    return {'accuracy': correct / n, 'balanced_accuracy': .5 * (ratio(tp, pos, 0) + ratio(tn, neg, 0)),
            'positive_recall': ratio(tp, pos, 0), 'coverage': accepted / n,
            'selective_risk': ratio(wrong, accepted, 1)}


ensure(digest((RESULT / 'report.json').read_bytes()) ==
       '26c74e604c9404f93677d64687603f50afbf0414e7773c07a4237f5f9cbe0211',
       'this audit requires the fixed first experiment and its original calibration')
report = read_json(RESULT / 'report.json')
plan = read_json(RESULT / 'plan.json')
data = read_json(DATA / 'manifest.json')
bank = read_json(BANK / 'manifest.json')
audit = {'schema': 'hepta.real-multimodal-independent-audit.v1',
         'audited_at': datetime.now(timezone.utc).isoformat(),
         'repository_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
         'inputs': {str(p): digest(p.read_bytes()) for p in (RESULT / 'report.json', RESULT / 'plan.json',
                                                         BANK / 'manifest.json', DATA / 'manifest.json')},
         'method': 'Independent NumPy metric and cluster calculations, direct Torch functional inference from retained NPZ weights, source annotation and JPEG/RGB/hash replay; no experiment implementation imported.'}
ensure(plan == report['plan'], 'embedded plan differs')
ensure(digest(canonical(plan)) == report['plan_sha256'], 'plan digest differs')
ensure(digest((DATA / 'manifest.json').read_bytes()) == report['data_manifest_sha256'], 'data pin differs')
ensure(digest((BANK / 'manifest.json').read_bytes()) == report['bank_manifest_sha256'], 'bank pin differs')
actual_files = {str(p.relative_to(RESULT)) for p in RESULT.rglob('*') if p.is_file()} - {'report.json'}
ensure(actual_files == set(report['artifact_sha256']), 'result inventory differs')
for name, expected in report['artifact_sha256'].items():
    ensure(digest((RESULT / name).read_bytes()) == expected, 'result artifact hash ' + name)
for name, expected in plan['code_file_sha256'].items():
    ensure(digest((REPO / 'qa/stem-bakeoff' / name).read_bytes()) == expected, 'source changed ' + name)
ensure(read_json(RESULT / 'cohort-manifest.json') == data, 'copied data manifest differs')
ensure(read_json(RESULT / 'bank-manifest.json') == bank, 'copied bank manifest differs')
audit['integrity'] = {'result_files_verified': len(actual_files), 'hashed_source_files_verified': len(plan['code_file_sha256']),
                      'copied_manifests_equal': True, 'file_hashes_valid': True}

captions_raw = (DATA / 'source_captions_val2017.json').read_bytes()
ensure(digest(captions_raw) == 'afe3b30e403dd7f228e2373023abbd60042a6e10ec6874d3652df034d289ebb9', 'original annotation hash')
annotations = json.loads(captions_raw)
annotation_by_id = {r['id']: r for r in annotations['annotations']}
photo_by_id = {r['id']: r for r in annotations['images']}
pin = data['source_sample']['images']
ensure(digest((REPO / 'qa/stem-bakeoff/coco_caption_sample_v1.json').read_bytes()) == data['source_sample_sha256'], 'sample pin')
pixels, dhashes, normalized, bytes_total = set(), [], set(), 0
for record in pin:
    actual = annotation_by_id[record['caption_id']]
    ensure(actual['caption'] == record['text'] and actual['image_id'] == record['image_id'], 'caption/source mismatch')
    ensure(digest(record['text'].encode()) == record['text_sha256'], 'caption hash')
    norm = ' '.join(unicodedata.normalize('NFKC', record['text']).casefold().split())
    ensure(norm not in normalized, 'normalized caption duplicate')
    normalized.add(norm)
    image = DATA / 'images' / record['file_name']
    payload = image.read_bytes(); bytes_total += len(payload)
    ensure(len(payload) == record['image_bytes'] and digest(payload) == record['image_sha256'], 'JPEG bytes differ')
    with Image.open(image) as img:
        ensure(img.format == 'JPEG' and img.size == (record['width'], record['height']), 'image format/dimensions')
        rgb = ImageOps.exif_transpose(img).convert('RGB')
        pixel_hash = digest(canonical([rgb.width, rgb.height, 'RGB']) + rgb.tobytes())
        grey = np.asarray(rgb.convert('L').resize((9, 8), Image.Resampling.LANCZOS))
        bits = (grey[:, :-1] > grey[:, 1:]).ravel()
        dh = sum(int(v) << (63 - i) for i, v in enumerate(bits))
    ensure(pixel_hash == record['decoded_rgb_sha256'] and pixel_hash not in pixels, 'decoded duplicate/drift')
    ensure(f'{dh:016x}' == record['dhash64'], 'dHash drift')
    pixels.add(pixel_hash); dhashes.append(dh)
minimum_distance = min((a ^ b).bit_count() for a, b in itertools.combinations(dhashes, 2))
ensure(minimum_distance > 4, 'near duplicate screen failed')
rows = {split: [json.loads(s) for s in (DATA / (split + '.jsonl')).read_text().splitlines()]
        for split in ('train', 'dev', 'calibration', 'test')}
split_summary, seen_images, seen_captions, seen_blocks = {}, set(), set(), set()
for split, records in rows.items():
    images, caption_ids, blocks = set(), set(), defaultdict(list)
    for row in records:
        ensure(row['row_id'] == digest(canonical({k: v for k, v in row.items() if k != 'row_id'})), 'row identity')
        ensure(row['label'] == int(row['image_id'] == row['source_caption_image_id']), 'source label')
        actual = annotation_by_id[row['caption_id']]
        ensure((actual['caption'], actual['image_id']) == (row['text'], row['source_caption_image_id']), 'row source')
        ensure(digest(row['text'].encode()) == row['text_sha256'], 'row caption hash')
        images.add(row['image_id']); caption_ids.add(row['caption_id']); blocks[row['pair_block_id']].append(row)
    ensure(not (images & seen_images or caption_ids & seen_captions or set(blocks) & seen_blocks), 'split leakage')
    ensure({r['source_caption_image_id'] for r in records} == images, 'caption endpoint outside split')
    for block in blocks.values():
        ids = {r['image_id'] for r in block}
        ensure(len(block) == 4 and len(ids) == 2, 'pair block cardinality')
        ensure({(r['image_id'], r['source_caption_image_id']) for r in block} == set(itertools.product(ids, repeat=2)), 'not complete pair block')
        ensure(Counter(r['label'] for r in block) == {0: 2, 1: 2}, 'pair block labels')
    for field in ('image_id', 'caption_id'):
        marginal = defaultdict(Counter)
        for row in records: marginal[row[field]][row['label']] += 1
        ensure(all(count == {0: 1, 1: 1} for count in marginal.values()), 'unimodal marginal leak')
    seen_images.update(images); seen_captions.update(caption_ids); seen_blocks.update(blocks)
    ensure(digest((DATA / (split + '.jsonl')).read_bytes()) == data['splits'][split]['jsonl_sha256'], 'split bytes')
    split_summary[split] = {'rows': len(records), 'images': len(images), 'captions': len(caption_ids), 'pair_blocks': len(blocks)}
audit['dataset'] = {'splits': split_summary, 'unique_images': len(seen_images), 'jpeg_bytes_verified': bytes_total,
                    'exact_rgb_unique': len(pixels), 'normalized_caption_unique': len(normalized),
                    'minimum_pairwise_dhash_hamming': minimum_distance,
                    'all_image_and_caption_endpoints_disjoint_across_splits': True,
                    'balanced_unimodal_marginals_exact': True,
                    'real_world_entity_disjointness_authenticated': False, 'foundation_pretraining_contamination_excluded': False}
captions_per_image = defaultdict(list)
for annotation in annotations['annotations']:
    captions_per_image[annotation['image_id']].append(annotation)
selection_seed = 'hepta-coco-pair-v1-20261022'
ordered_images = sorted((v for v in photo_by_id.values() if v['license'] in (4, 5) and v['id'] in captions_per_image),
                        key=lambda v: digest(f'{selection_seed}:image:{v["id"]}'.encode()))
ensure([x['image_id'] for x in pin] == [x['id'] for x in ordered_images[:384]], 'sample not fixed hash prefix')
ensure(all(min(captions_per_image[x['image_id']], key=lambda a: digest(f'{selection_seed}:caption:{a["id"]}'.encode()))['id']
           == x['caption_id'] for x in pin), 'caption hash selection differs')
audit['dataset']['first_384_eligible_images_and_caption_hash_selection_replayed'] = True

ensure(digest((BANK / 'features.npz').read_bytes()) == bank['features_sha256'], 'bank payload')
with np.load(BANK / 'features.npz', allow_pickle=False) as npz:
    features = {name: npz[name] for name in ('text', 'image')}
tensor_hash = hashlib.sha256()
for name, a in features.items():
    ensure(a.shape == (384, 768) and a.dtype == np.float32 and np.isfinite(a).all(), 'bank array')
    tensor_hash.update(canonical([name, str(a.dtype), list(a.shape)])); tensor_hash.update(a.tobytes())
ensure(tensor_hash.hexdigest() == bank['feature_tensor_sha256'], 'bank tensor digest')
by_image = {r['image_id']: r for split in rows.values() for r in split if r['label'] == 1}
for channel, summary in bank['receipts'].items():
    payload = (BANK / summary['file']).read_bytes()
    ensure(digest(payload) == summary['sha256'], 'forward receipt hash')
    receipts = json.loads(payload)
    ids = []
    for receipt in receipts:
        start = receipt['offset']; n = receipt['batch_size']; ids.extend(receipt['source_ids'])
        bundle = receipt['bundle_manifest']
        ensure(digest(features[channel][start:start+n].tobytes()) == bundle['views']['global_features']['bytes_sha256'], 'receipt/bank tensor binding')
        expected_sources = []
        for image_id in receipt['source_ids']:
            row = by_image[image_id]; text = row['text'] if channel == 'text' else 'Image.'
            metadata = {'image_id': image_id, 'caption_id': row['caption_id'], 'source_image_sha256': row['image_sha256'],
                        'source_caption_sha256': row['text_sha256'], 'channel': channel}
            media = [['text', digest(text.encode())]] + ([['image', row['image_sha256']]] if channel == 'image' else [])
            expected_sources.append(digest(canonical({'text_source': digest(canonical({'text': text, 'record': metadata})), 'media_sources': media})))
        ensure(expected_sources == bundle['source_record_digests'] == bank['provenance'][channel][start:start+n], 'source provenance binding')
    ensure(ids == bank['image_ids'] and len(receipts) == 192, 'receipt source inventory')
ensure(bank['encoder']['tensor_sha256_before'] == bank['encoder']['tensor_sha256_after'], 'frozen owner hash')
audit['feature_bank'] = {'shape_per_modality': [384, 768], 'physical_owners': 1,
                         'storage_bytes': sum(a.nbytes for a in features.values()),
                         'observed_calls': bank['observed_module_calls'], 'all_384_receipt_feature_slices_bound': True,
                         'all_original_caption_and_media_source_digests_recomputed': True,
                         'encoder_parameters': bank['encoder']['loaded_parameter_count'],
                         'encoder_resident_tensor_bytes': bank['encoder']['resident_tensor_storage_bytes'],
                         'encoder_trainable_parameters': bank['encoder']['trainable_parameter_count'],
                         'bank_build_wall_ms': bank['runtime']['wall_ms'],
                         'bank_process_peak_rss_bytes': bank['process_lifetime_peak_rss_bytes']}

lookup = {n: i for i, n in enumerate(bank['image_ids'])}
def fuse(records, arm, intervention='paired'):
    partners = {}
    if intervention.startswith('shuffled'):
        groups = defaultdict(set)
        for r in records: groups[r['pair_block_id']].add(r['image_id'])
        for a, b in (sorted(x) for x in groups.values()): partners.update({a: b, b: a})
    text = torch.from_numpy(features['text'][[lookup[r['source_caption_image_id']] for r in records]].copy())
    image = torch.from_numpy(features['image'][[lookup[partners.get(r['image_id'], r['image_id'])] for r in records]].copy())
    text_missing = arm == 'image_only' or intervention == 'missing_text'
    image_missing = arm == 'text_only' or intervention == 'missing_image'
    if text_missing: text.zero_()
    if image_missing: image.zero_()
    joint = not (text_missing or image_missing)
    return torch.cat([text, image, text * image if joint else torch.zeros_like(text),
                      (text - image).abs() if joint else torch.zeros_like(text),
                      F.cosine_similarity(text, image).unsqueeze(1) if joint else torch.zeros((len(records), 1))], dim=1)


def forward(x, weights):
    state = torch.zeros((len(x), 8))
    gate = torch.sigmoid(F.linear(torch.cat([x, state], 1), weights['gate.weight'], weights['gate.bias']))
    adapted = x + gate * F.linear(F.gelu(F.linear(x, weights['down.weight'])), weights['up.weight'])
    return F.linear(adapted, weights['task_head.weight'], weights['task_head.bias']).numpy().astype(float)


weights, heads = {}, {}
for key, record in report['head_artifacts'].items():
    path = RESULT / record['directory']; manifest = read_json(path / 'manifest.json')
    ensure(digest((path / 'manifest.json').read_bytes()) == record['manifest_sha256'], 'head manifest external pin')
    ensure(digest((path / 'weights.npz').read_bytes()) == manifest['weights_file_sha256'], 'head weights')
    with np.load(path / 'weights.npz', allow_pickle=False) as arrays:
        weights[key] = {k: torch.from_numpy(arrays[k].copy()) for k in arrays.files}
    heads[key] = manifest['report']
    h = hashlib.sha256()
    for name, value in sorted(weights[key].items()):
        a = value.numpy(); h.update(canonical([name, list(a.shape), str(a.dtype)])); h.update(a.tobytes())
    ensure(h.hexdigest() == heads[key]['trained_tensor_sha256'], 'head tensor hash')
    arm = key.rsplit('-', 1)[0]
    calibration_logits = forward(fuse(rows['calibration'], arm), weights[key])
    y = np.array([r['label'] for r in rows['calibration']])
    temp_scores = {}
    for temperature in plan['temperature_grid']:
        z = calibration_logits / temperature
        temp_scores[temperature] = float((np.logaddexp(z[:, 0], z[:, 1]) - z[np.arange(len(y)), y]).mean())
    expected_temp = min(temp_scores, key=lambda t: (temp_scores[t], abs(math.log(t)), t))
    ensure(expected_temp == heads[key]['temperature'], 'calibration temperature selection')
    selected = min(report['selection'][key]['candidates'], key=lambda c: (c['development_uncalibrated_nll'], c['steps']))
    ensure(selected['steps'] == heads[key]['config']['steps'] and selected['trained_tensor_sha256'] == heads[key]['trained_tensor_sha256'], 'development selection')

ledger_arrays, independent_metrics, samples, max_forward_error = {}, {}, {}, 0.0
test_by_id = {r['row_id']: r for r in rows['test']}
minority_expected = sorted([r['row_id'] for r in rows['test'] if r['label'] == 1],
                           key=lambda x: digest(f'20261022:{x}'.encode()))[:32]
minority_expected = set(minority_expected) | {r['row_id'] for r in rows['test'] if r['label'] == 0}
for key, record in report['ledgers'].items():
    root = RESULT / record['directory']; manifest = read_json(root / 'manifest.json'); meta = manifest['metadata']
    ensure(digest((root / 'manifest.json').read_bytes()) == record['manifest_sha256'], 'ledger external manifest pin')
    ensure(digest((root / 'predictions.npz').read_bytes()) == manifest['arrays_sha256'] == record['arrays_sha256'], 'ledger array hash')
    with np.load(root / 'predictions.npz', allow_pickle=False) as npz: a = {n: npz[n] for n in npz.files}
    records = [test_by_id[str(s)] for s in a['source_ids']]
    base_key = meta['arm']; arm = base_key.rsplit('-', 1)[0]
    expected = forward(fuse(records, arm, meta['intervention']), weights[base_key])
    error = float(np.abs(expected - a['logits']).max()); max_forward_error = max(max_forward_error, error)
    ensure(error < 3e-5, 'retained weights do not reproduce logits ' + key)
    expected_y = np.array([1-r['label'] if meta['intervention'] == 'shuffled_relabelled' else r['label'] for r in records])
    ensure(np.array_equal(a['labels'], expected_y), 'ledger labels differ')
    ensure(list(a['image_group_ids']) == [r['group_id'] for r in records], 'image group alignment')
    ensure(list(a['pair_block_ids']) == [r['pair_block_id'] for r in records], 'pair block alignment')
    ensure(meta['identity']['head_sha256'] == heads[base_key]['trained_tensor_sha256'], 'ledger head identity')
    ensure(all(meta['identity'][field] == heads[base_key]['feature_identity'][field]
               for field in ('encoder_sha256', 'preprocess_sha256')), 'ledger encoder/preprocess identity')
    ensure(meta['identity']['plan_sha256'] == report['plan_sha256'] and meta['identity']['data_sha256'] == report['data_manifest_sha256'], 'ledger data/plan identity')
    ensure(meta['temperature'] == heads[base_key]['temperature'], 'intervention changed calibration')
    if meta['split'] == 'minority_test': ensure(set(a['source_ids']) == minority_expected, 'minority subset selection')
    else: ensure(set(a['source_ids']) == set(test_by_id), 'test source inventory')
    metrics = metric(a, meta['temperature'])
    for field, actual in metrics.items():
        reported = record['metrics'][field]
        if isinstance(actual, float): ensure(math.isclose(actual, reported, abs_tol=3e-12, rel_tol=1e-10), 'metric ' + key + '/' + field)
        else: ensure(actual == reported, 'metric ' + key + '/' + field)
    ledger_arrays[key], independent_metrics[key], samples[key] = a, metrics, bootstrap(a)
    if key in report['arm_screens'] or 'cluster_intervals' in record:
        bounds = report['arm_screens'][key]['cluster_intervals']['bounds'] if key in report['arm_screens'] else record['cluster_intervals']['bounds']
        for field, draws in samples[key].items():
            ensure(abs(float(np.quantile(draws, .05)) - bounds[field]['lower_one_sided_95']) < 1e-12, 'bootstrap lower')
            ensure(abs(float(np.quantile(draws, .95)) - bounds[field]['upper_one_sided_95']) < 1e-12, 'bootstrap upper')
audit['predictions'] = {'ledgers_verified': len(ledger_arrays), 'independent_metric_recomputations': True,
                        'all_saved_weights_reproduce_logits': True, 'max_absolute_logit_difference': max_forward_error,
                        'calibration_and_development_selection_recomputed': True,
                        'all_fixed_minorities_recomputed': True, 'cluster_intervals_reproduced': True,
                        'metrics': independent_metrics}

gated, linear = ledger_arrays['text_image-gated'], ledger_arrays['text_image-linear']
diff = samples['text_image-gated']['balanced_accuracy'] - samples['text_image-linear']['balanced_accuracy']
delta = float((gated['prediction'] == gated['labels']).mean() - (linear['prediction'] == linear['labels']).mean())
cg, cl = gated['prediction'] == gated['labels'], linear['prediction'] == linear['labels']
ensure(np.array_equal(gated['source_ids'], linear['source_ids']), 'head comparison row order')
audit['gated_vs_linear'] = {'accuracy_gain': delta, 'gated_only_correct': int((cg & ~cl).sum()),
                           'linear_only_correct': int((cl & ~cg).sum()),
                           'paired_bootstrap_lower_one_sided_95': float(np.quantile(diff, .05)),
                           'paired_bootstrap_upper_one_sided_95': float(np.quantile(diff, .95)),
                           'paired_bootstrap_two_sided_95': np.quantile(diff, [.025, .975]).tolist(),
                           'significant_accuracy_gain_established': False,
                           'one_discordant_block_exact_sign_test_p_one_sided': .5,
                           'one_discordant_block_exact_sign_test_p_two_sided': 1.0}
for key in ('text_image-gated', 'text_image-linear'):
    a = ledger_arrays[key]; z = a['logits']
    audit['gated_vs_linear'][key + '_uncalibrated_nll'] = float((np.logaddexp(z[:, 0], z[:, 1])-z[np.arange(len(z)), a['labels']]).mean())

cosines = F.cosine_similarity(torch.from_numpy(features['text'][[lookup[r['source_caption_image_id']] for r in rows['test']]]),
                               torch.from_numpy(features['image'][[lookup[r['image_id']] for r in rows['test']]])).numpy()
labels = np.array([r['label'] for r in rows['test']]); pos, neg = cosines[labels == 1], cosines[labels == 0]
audit['posthoc_explanatory_cosine_diagnostic'] = {
    'used_for_training_selection_or_qualification': False,
    'positive_quantiles_0_25_50_75_100': np.quantile(pos, [0, .25, .5, .75, 1]).tolist(),
    'negative_quantiles_0_25_50_75_100': np.quantile(neg, [0, .25, .5, .75, 1]).tolist(),
    'rank_auroc': float((pos[:, None] > neg[None, :]).mean() + .5 * (pos[:, None] == neg[None, :]).mean())}
audit['error_examples'] = []
for i in np.flatnonzero(~cg):
    row = test_by_id[str(gated['source_ids'][i])]
    audit['error_examples'].append({k: row[k] for k in ('row_id', 'image_id', 'source_caption_image_id', 'text', 'label')}
                                 | {'prediction': int(gated['prediction'][i]), 'confidence': float(gated['probabilities'][i].max())})
audit['minority'] = {'is_fixed_correlated_primary_test_subset': True, 'rows': 160, 'positive_rows': 32, 'negative_rows': 128,
                    'positive_pair_blocks': len({r['pair_block_id'] for r in rows['test'] if r['label'] == 1 and r['row_id'] in minority_expected}),
                    'no_refit_recalibration_or_threshold_change': True,
                    'bootstrap_recall_lower_equal_one_is_degenerate_not_a_guarantee': True}
audit['resource_comparison'] = {k: {'resident_parameters': v['resident_parameter_count'],
                                   'trainable_parameters': v['trainable_parameter_count'],
                                   'temperature': v['temperature'], 'selected_steps': v['optimizer_steps']}
                                for k, v in heads.items()}
audit['qualification'] = {'reported_primary': plan['primary_mode'], 'reported_quality_qualified': report['quality_qualified'],
                         'screen_scope': 'fixed COCO source-pair research screen only',
                         'production_activation_allowed': report['production_activation_allowed'],
                         'authority': report['authority'], 'state_policy_learning_qualified': report['state_policy_learning_qualified']}
q = plan['research_qualification']
replayed_arm_checks = {}
for key in report['arm_screens']:
    a, m = ledger_arrays[key], independent_metrics[key]
    checks = {'rows': m['rows'] >= q['min_rows'],
              'image_groups': len(set(a['image_group_ids'])) >= q['min_image_groups'],
              'pair_blocks': len(set(a['pair_block_ids'])) >= q['min_pair_blocks'],
              'balanced_accuracy': m['balanced_accuracy'] >= q['min_balanced_accuracy'],
              'positive_recall': m['positive_recall'] >= q['min_positive_recall'],
              'coverage': m['coverage'] >= q['min_coverage'], 'accepted_count': m['accepted_count'] >= q['min_accepted'],
              'selective_risk': m['selective_risk'] is not None and m['selective_risk'] <= q['max_selective_risk'],
              'cluster_risk_upper': float(np.quantile(samples[key]['selective_risk'], .95)) <= q['max_selective_risk_upper']}
    ensure(checks == report['arm_screens'][key]['checks'], 'arm qualification mismatch')
    replayed_arm_checks[key] = checks
replayed_joint = {}
for mode in ('linear', 'gated'):
    key = 'text_image-' + mode; score = independent_metrics[key]['balanced_accuracy']
    baselines = ['text_only-' + mode, 'image_only-' + mode]
    lower = float(np.quantile(samples[key]['balanced_accuracy'] - np.maximum(*(samples[x]['balanced_accuracy'] for x in baselines)), .05))
    checks = {'joint_arm_screen': all(replayed_arm_checks[key].values()),
              'gain_vs_best_unimodal': score - max(independent_metrics[x]['balanced_accuracy'] for x in baselines) >= q['min_joint_gain'],
              'paired_gain_lower_positive': not q['require_positive_gain_lower_bound'] or lower > 0}
    for intervention in ('shuffled_image', 'missing_text', 'missing_image'):
        other = key + '-' + intervention
        checks[intervention + '_drop'] = score - independent_metrics[other]['balanced_accuracy'] >= q['min_intervention_drop']
        checks[intervention + '_lower_positive'] = (not q['require_positive_gain_lower_bound'] or
                float(np.quantile(samples[key]['balanced_accuracy'] - samples[other]['balanced_accuracy'], .05)) > 0)
    ensure(checks == report['multimodal_screens'][mode]['checks'], 'joint qualification mismatch')
    replayed_joint[mode] = all(checks.values())
qualified = replayed_joint['gated'] and independent_metrics['text_image-gated-minority']['positive_recall'] >= .6
ensure(qualified == report['quality_qualified'], 'final qualification mismatch')
for mode in ('linear', 'gated'):
    primary = ledger_arrays['text_image-' + mode]; minor = ledger_arrays['text_image-' + mode + '-minority']
    positions = {str(s): i for i, s in enumerate(primary['source_ids'])}
    ensure(np.array_equal(minor['logits'], primary['logits'][[positions[str(s)] for s in minor['source_ids']]]), 'minority predictions changed')
    shuffled = ledger_arrays['text_image-' + mode + '-shuffled_relabelled']
    keys = {(r['image_id'], r['source_caption_image_id']): i for i, r in enumerate(rows['test'])}
    groups = defaultdict(set)
    for r in rows['test']: groups[r['pair_block_id']].add(r['image_id'])
    partners = {}
    for a, b in (sorted(s) for s in groups.values()): partners.update({a: b, b: a})
    mapping = [keys[(partners[r['image_id']], r['source_caption_image_id'])] for r in rows['test']]
    ensure(np.allclose(shuffled['logits'], primary['logits'][mapping], atol=3e-5, rtol=0), 'shuffled multiset identity')
audit['qualification']['independently_replayed_quality_qualified'] = qualified
audit['qualification']['all_preregistered_checks_reproduced'] = True
audit['findings'] = [
    {'id': 'F1', 'category': 'qualification_limit', 'title': 'No significant gated accuracy advantage over linear',
     'detail': '251/256 versus 250/256, one discordant block; paired bootstrap lower bound is zero. One-sided exact sign probability 0.5. Do not claim gated is superior or the optimal Cell investment from this experiment.'},
    {'id': 'F2', 'category': 'operational_defect_for_missing_modality_use', 'title': 'Missing modalities cause confidently wrong fallback',
     'detail': 'With either modality zeroed, gated accepts all 256 rows and predicts every row negative: accuracy 50%, selective risk 50%, positive recall 0%. The missing-mask metadata is not consumed by predict_task. Sensitivity PASS does not establish missingness robustness or abstention.'},
    {'id': 'F3', 'category': 'qualification_limit', 'title': 'Source provenance matching is narrower than semantic truth',
     'detail': 'Random within-block negatives are captions originating from another image, not human-adjudicated contradictions. The frozen embedding cosine alone has posthoc AUROC 0.99646. High source-pair accuracy is plausible; it does not establish general visual reasoning, hard-negative discrimination or novel multimodal foundation learning.'},
    {'id': 'F4', 'category': 'calibration_limitation', 'title': 'Honest calibration selection overconfident on independent test',
     'detail': 'Gated calibration is 128/128 and selects temperature 0.25. Test NLL worsens from uncalibrated 0.05582 to 0.16712; calibrated linear NLL is 0.06053. All five gated errors are accepted at confidence >=0.9568. Do not retune temperature on this test.'},
    {'id': 'F5', 'category': 'statistical_limit', 'title': 'Minority subset is correlated and its perfect-recall bootstrap is degenerate',
     'detail': '160 fixed rows, 32 positives from 29 pair blocks plus all 128 negatives, reuse primary predictions. Recall 32/32 is descriptive and passes the stated point threshold; the empirical [1,1] recall interval does not guarantee perfect recall. This is not independent replication.'},
    {'id': 'F6', 'category': 'comparison_scope', 'title': 'Same budget does not mean equal compute or equal trained parameters',
     'detail': 'Within each mode, three modality arms share owner, 3073-wide fusion, rows and the same 4200-step selection grid; all select 3000 steps. Gated trains 33814 parameters versus linear 6148. Both retain the same 52258-parameter container, so reported linear memory is not an optimized standalone affine readout baseline. Text/image encoder work is not equal; no 4096-head physical allocation, energy or target-device qualification occurred.'},
    {'id': 'F7', 'category': 'intervention_limit', 'title': 'Swapped-image relabelling is an exact permutation diagnostic',
     'detail': 'A disjoint two-image block contains the full 2x2 Cartesian product. Swapping images permutes those same four inputs and reverses source-pair labels; original-label accuracy is the complement, and relabelled accuracy returns exactly. This is sensitivity/consistency evidence, not independent robustness or a new corrupted-input distribution.'},
    {'id': 'F8', 'category': 'leakage_boundary', 'title': 'Run-level source isolation verified; foundation exposure remains unknown',
     'detail': 'All image and caption identities, normalized captions, exact pixels and declared dHash screen are isolated across splits. No labels/IDs enter numerical features or model tokens. Public COCO exposure during foundation pretraining and real-world-entity identity overlap are not excluded. Hashes and local timing alone are not third-party preregistration custody.'}
]
audit['invalidating_research_screen_defects_found'] = []
audit['status'] = 'INTEGRITY_AND_RECOMPUTATION_PASS_WITH_MATERIAL_LIMITATIONS'
(OUT / 'audit.json').write_bytes(json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False).encode() + b'\n')
print(json.dumps({'status': audit['status'], 'verified_images': len(pin), 'verified_ledgers': len(ledger_arrays),
                  'max_logit_difference': max_forward_error, 'minimum_dhash_distance': minimum_distance,
                  'gate_vs_linear': audit['gated_vs_linear'], 'cosine': audit['posthoc_explanatory_cosine_diagnostic'],
                  'minority': audit['minority']}, ensure_ascii=False))
