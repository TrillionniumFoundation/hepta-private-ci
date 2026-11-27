"""Original DINO + Granite three-class query-binding falsification, research only.

Train process reads only authentic pretrained source/feature ZIPs and TRAIN labels.
Independent late-label review is a separate command/process. No publisher signature,
pretrained forward, general VLM, production authority, or new future task is claimed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time
from zipfile import ZipFile

import numpy as np

SOURCE_ZIP_SHA = '49ee4b855879e8ad463fb3f0ffb21e30b332fb24d1626360aa8f382d16ef82ad'
FEATURE_ZIP_SHA = '92536c949e16ee0722357ccb1d881f371707df3c26424cd93dd2bfc96e49511e'
TARGET_ZIP_SHA = '946101fe7e57a151ce5ae9ec314fc6e01b7244aeac48f49034ee0a581e09c67d'
SOURCE_MANIFEST_SHA = '0233221fae3986612ed34c86b3da2e708b2423a77d19a74f1d0a73ed46e81490'
DINO_REV = '150c8e7bb7cef2d30ec31b13a517af14840ee3f7'
DINO_WEIGHTS = 'ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1'
DINO_PREPROCESS_SHA = '14e780d86fa1861f8751f868d7f45425b5feb55c38ca26f152ca5097ab30f828'
DINO_FEATURE_ENCODER_SHA = '66301a1057dffff05adbb24d8e635b74d1b01e4d3ebb477bee1f25fdd5e3d8a8'
GRANITE_FEATURE_ENCODER_SHA = '651431e0ce6e37a34a7f576d1164b277a87d39466c77418b9d0bf4d5a15c0257'
GRANITE_REV = '835ad14087e140460703cf0fae09f97d469d65c2'
GRANITE_ENCODED_SHA = '4e60d544823a9f4441d3a040c2415080092923114d8082c0530e7c93f3a186e0'
DATA_REV = '27aa014ce09b193e1a6f58112d4a66e0eddb69c5'
MODEL_SCOPE = 'hepta-e2-natural-beans-retrospective-research'
CLASSES = ('angular_leaf_spot', 'bean_rust', 'healthy')
WIDTH = 384
RANK = 8
STEPS = 160
SEED = 1197
LR = 0.3
L2 = 0.0001
SCALE = 24.0
SCHEMA = 'hepta.hdcf.original-vision-text-binding.v12'
PRED_SCHEMA = 'hepta.hdcf.original-vision-text-predictions.v12'


class Denied(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise Denied(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(obj):
    try:
        return json.dumps(obj, ensure_ascii=True, sort_keys=True, allow_nan=False,
                          separators=(',', ':')).encode('ascii')
    except (ValueError, TypeError, UnicodeError) as error:
        raise Denied('noncanonical JSON') from error


def read_json(raw):
    need(len(raw) < 3_000_000, 'oversized JSON')
    def unique(seq):
        out = {}
        for k, v in seq:
            need(k not in out, 'duplicate JSON key')
            out[k] = v
        return out
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(Denied('nonfinite JSON')))
    except (ValueError, UnicodeError, TypeError) as error:
        raise Denied('invalid JSON') from error


def read_jsonl(raw):
    need(raw.endswith(b'\n') and len(raw) < 5_000_000, 'invalid JSONL')
    return [read_json(line) for line in raw.splitlines()]


class PinnedArchive:
    def __init__(self, path, expected, cap=16_000_000):
        p = Path(path)
        need(p.is_file() and not p.is_symlink() and 0 < p.stat().st_size <= cap,
             'archive not regular/bounded')
        with p.open('rb') as fd:
            need(hashlib.file_digest(fd, 'sha256').hexdigest() == expected,
                 'original artifact outer SHA mismatch')
        self.z = ZipFile(p)
        entries = self.z.infolist()
        need(1 <= len(entries) <= 100 and
             sum(i.file_size for i in entries) <= 30_000_000, 'unsafe ZIP size')
        names = [i.filename for i in entries]
        need(len(names) == len(set(names)), 'duplicate archive entry')
        for i in entries:
            need(not i.is_dir() and i.file_size <= 8_000_000 and
                 not i.filename.startswith('/') and '\\' not in i.filename and
                 all(p not in ('', '.', '..') for p in i.filename.split('/')) and
                 ((i.external_attr >> 16) & 0o170000) != 0o120000,
                 'unsafe archive entry')
        self.names = set(names)

    def read(self, name):
        need(name in self.names, 'missing source member: ' + name)
        return self.z.read(name)

    def close(self):
        self.z.close()


def load_training_only(source_zip, feature_zip):
    """Never reads any original heldout target archive or heldout class field."""
    source = PinnedArchive(source_zip, SOURCE_ZIP_SHA)
    feat = PinnedArchive(feature_zip, FEATURE_ZIP_SHA)
    try:
        manifest_raw = source.read('source-manifest.json')
        manifest = read_json(manifest_raw)
        need(sha(manifest_raw) == SOURCE_MANIFEST_SHA and
             manifest['schema'] == 'hepta.e2.beans-natural-retrospective.v1.source-plan' and
             manifest['dataset_revision'] == DATA_REV and
             manifest['scope'] == MODEL_SCOPE and
             manifest['train_cases'] == 36 and manifest['test_cases'] == 24 and
             manifest['phase_time_is_not_original_timestamp'] is True and
             manifest['production_accepted'] is False, 'original source manifest drift')
        for name, expected in manifest['file_sha256s'].items():
            need(sha(source.read('source/' + name)) == expected, 'source input manifest drift')
        train = read_jsonl(source.read('source/train_images.jsonl'))
        held = read_jsonl(source.read('source/future_images.jsonl'))
        classes_rows = read_jsonl(source.read('source/train_class.jsonl'))
        class_by_id = {r['case_id']: r['class_label'] for r in classes_rows}
        need(len(train) == 36 and len(held) == 24 and len(class_by_id) == 36 and
             all(list(class_by_id.values()).count(c) == 12 for c in CLASSES), 'training class census')
        seen_cases, seen_groups, seen_images = set(), set(), set()
        for phase, rows in [('train', train), ('future', held)]:
            for row in rows:
                need(set(row) == {'case_id','condition','group_id','image_path',
                                 'image_sha256','observed_at','question','scope',
                                 'source_sha256','split'} and
                     row['scope'] == MODEL_SCOPE and row['split'] == phase and
                     row['condition'] == 'vision_required' and
                     row['case_id'] not in seen_cases and
                     row['group_id'] not in seen_groups and
                     row['image_sha256'] not in seen_images and
                     row['image_path'] == row['case_id'] + '.jpg', 'source identity leak')
                original_image = source.read('source/images/' + row['image_path'])
                need(sha(original_image) == row['image_sha256'] and
                     original_image[:2] == b'\xff\xd8', 'actual original image bytes mismatch')
                seen_cases.add(row['case_id'])
                seen_groups.add(row['group_id'])
                seen_images.add(row['image_sha256'])
        vectors = {}
        for phase, originals in [('train', train), ('future', held)]:
            directory = 'vision_train' if phase == 'train' else 'vision_future'
            raw = feat.read(directory + '/features.jsonl')
            receipt = read_json(feat.read(directory + '/receipt.json'))
            need(receipt['phase'] == phase and receipt['feature_width'] == WIDTH and
                 receipt['actual_model_forwards'] == len(originals) and
                 receipt['encoder_revision'] == DINO_REV and
                 receipt['snapshot_file_sha256s']['model.safetensors'] == DINO_WEIGHTS and
                 receipt['snapshot_file_sha256s']['preprocessor_config.json'] == DINO_PREPROCESS_SHA and
                 receipt['source_sha256'] == sha(b''.join(canonical(row)+b'\n' for row in originals)) and
                 receipt['checkpoint_locally_byte_verified'] is True and
                 receipt['publisher_authenticated'] is False and
                 receipt['labels_seen'] is False and
                 receipt['output_sha256'] == sha(raw), 'original DINO provenance mismatch')
            observed = read_jsonl(raw)
            need(len(observed) == len(originals), 'model output census mismatch')
            arr = []
            for row, observed_row in zip(originals, observed, strict=True):
                need(observed_row['case_id'] == row['case_id'] and
                     observed_row['group_id'] == row['group_id'] and
                     observed_row['image_sha256'] == row['image_sha256'] and
                     observed_row['source_sha256'] == row['source_sha256'] and
                     observed_row['source']['modality'] == 'image' and
                     observed_row['source']['encoder_sha256'] == DINO_FEATURE_ENCODER_SHA and
                     observed_row['source']['input_sha256'] == row['image_sha256'] and
                     'target' not in observed_row and 'label' not in observed_row,
                     'pretrained feature source/label mismatch')
                vec = np.asarray(observed_row['source']['values'], dtype=np.float64)
                need(vec.shape == (WIDTH,) and np.all(np.isfinite(vec)) and
                     np.max(np.abs(vec)) <= 8, 'nonfinite feature')
                arr.append(vec)
            vectors[phase] = np.stack(arr)
        encoded_raw = feat.read('granite_train/encoded.jsonl')
        rec = read_json(feat.read('granite_train/receipt.json'))
        need(rec['candidate'] == 'granite-97m-r2' and rec['model_revision'] == GRANITE_REV and
             rec['encoded_sha256'] == GRANITE_ENCODED_SHA == sha(encoded_raw) and
             rec['feature_encoder_identity'] == GRANITE_FEATURE_ENCODER_SHA and
             rec['examples'] == 36 and rec['output_width'] == WIDTH and
             rec['model_checkpoint_locally_verified'] is True and
             rec['model_publisher_authenticated'] is False and
             rec['production_accepted'] is False, 'Granite pretrained provenance drift')
        rows = read_jsonl(encoded_raw)
        need(len(rows) == len(train), 'original train-only Granite example census')
        proto = {}
        text_source_hashes = {}
        for original, row in zip(train, rows, strict=True):
            label = class_by_id[original['case_id']]
            need(row['case_id'] == original['case_id'] and
                 row['group_id'] == original['group_id'] and
                 row['target']['modality'] == 'text' and
                 row['target']['encoder_sha256'] == GRANITE_FEATURE_ENCODER_SHA and
                 row['source']['modality'] == 'image' and
                 row['source']['encoder_sha256'] == DINO_FEATURE_ENCODER_SHA and
                 row['source']['input_sha256'] == original['image_sha256'],
                 'Granite source/case drift')
            value = np.asarray(row['target']['values'], dtype=np.float64)
            need(value.shape == (WIDTH,) and np.all(np.isfinite(value)) and
                 np.max(np.abs(value)) <= 8, 'invalid actual Granite target')
            text_hash = row['target']['input_sha256']
            if label in proto:
                need(text_hash == text_source_hashes[label] and
                     np.array_equal(value, proto[label]), 'not three exact class prototypes')
            else:
                proto[label] = value
                text_source_hashes[label] = text_hash
        need(set(proto) == set(CLASSES) and len(set(text_source_hashes.values())) == 3,
             'incomplete text cue bindings')
        sealed = read_json(feat.read('sealed_class_predictions.json'))
        need(sealed['future_labels_seen'] is False and
             sealed['production_accepted'] is False and
             'vision_prototype' in sealed['arms'] and
             len(sealed['rows']) == len(held), 'original strong visual baseline absent')
        baseline = {}
        for original, pred in zip(held, sealed['rows'], strict=True):
            need(pred['case_id'] == original['case_id'] and
                 pred['group_id'] == original['group_id'] and
                 pred['source_input_sha256'] == original['image_sha256'],
                 'strong DINO original case changed')
            label = pred['predicted_labels']['vision_prototype']
            need(label in CLASSES, 'invalid strong DINO baseline')
            baseline[original['case_id']] = CLASSES.index(label)
        return {'train': train, 'held': held,
                'train_labels': np.asarray([CLASSES.index(class_by_id[r['case_id']]) for r in train], dtype=np.int64),
                'train_X': vectors['train'], 'held_X': vectors['future'],
                'T': np.stack([proto[c] for c in CLASSES]),
                'strong': baseline, 'text_hashes': text_source_hashes}
    finally:
        source.close()
        feat.close()


def permutation(width=WIDTH):
    """Deterministic seeded signed permutation: Q Q.T = I exactly."""
    rng = np.random.default_rng(312)
    p = rng.permutation(width)
    s = rng.choice(np.asarray([-1., 1.]), size=width)
    return p, s


def sigmoid_scores(score):
    # Stable softmax across the three original text cue choices.
    z = score - np.max(score, axis=1, keepdims=True)
    p = np.exp(z)
    return p / np.sum(p, axis=1, keepdims=True)


def fit_rank8(x, text, y, *, transformed=False):
    """Real float64 6144-parameter Organ, 160 TRAIN-only SGD steps."""
    need(x.shape == (36, WIDTH) and text.shape == (3, WIDTH) and
         y.shape == (36,) and np.all((y >= 0) & (y <= 2)), 'fit input shape')
    seed = np.random.default_rng(SEED)
    a = seed.normal(0, 0.05, size=(WIDTH, RANK))
    b = seed.normal(0, 0.05, size=(WIDTH, RANK))
    if transformed:
        perm, signs = permutation()
        text = text[:, perm] * signs[None, :]
        b = b[perm, :] * signs[:, None]
    cpu_start = time.process_time_ns()
    wall_start = time.perf_counter_ns()
    loss_start = None
    for k in range(STEPS):
        u, q = x @ a, text @ b
        scores = SCALE * (u @ q.T)
        p = sigmoid_scores(scores)
        loss = float(-np.mean(np.log(np.maximum(p[np.arange(len(y)), y], 1e-300))))
        if loss_start is None:
            loss_start = loss
        error = p.copy()
        error[np.arange(len(y)), y] -= 1.0
        error /= len(y)
        da = SCALE * x.T @ (error @ q) + L2 * a
        db = SCALE * text.T @ (error.T @ u) + L2 * b
        a -= LR * da
        b -= LR * db
        need(np.all(np.isfinite(a)) and np.all(np.isfinite(b)), 'numerical divergence')
    cpu_ns = time.process_time_ns() - cpu_start
    wall_ns = time.perf_counter_ns() - wall_start
    loss_final = float(-np.mean(np.log(np.maximum(sigmoid_scores(SCALE * ((x @ a) @ (text @ b).T))[np.arange(len(y)), y], 1e-300))))
    return a, b, {'steps': STEPS, 'parameters': int(a.size + b.size),
                  'paid_scalar_updates': int(STEPS * (a.size + b.size)),
                  'start_ce': loss_start, 'final_ce': loss_final,
                  'cpu_ns_unattested': cpu_ns, 'wall_ns_unattested': wall_ns}


def ridge(x, y, held, alpha=0.1):
    """Strong independent TRAIN-only visual multiclass ridge control."""
    onehot = np.eye(3, dtype=np.float64)[y]
    k = x @ x.T
    weights = np.linalg.solve(k + alpha * np.eye(len(x)), onehot)
    return (held @ x.T) @ weights


def fit_and_seal(source_zip, feature_zip):
    r = load_training_only(source_zip, feature_zip)
    x, h, text, y = r['train_X'], r['held_X'], r['T'], r['train_labels']
    a, b, cost = fit_rank8(x, text, y)
    a2, b2, cost_null = fit_rank8(x, text, y, transformed=True)
    p, s = permutation()
    text_null = text[:, p] * s[None, :]
    origin_scores = SCALE * ((h @ a) @ (text @ b).T)
    null_scores = SCALE * ((h @ a2) @ (text_null @ b2).T)
    # Gram-isometric text control MUST be prediction-equivalent, and therefore
    # destroys any claim that class-name semantics were separately learned.
    tolerance = float(np.max(np.abs(origin_scores - null_scores)))
    need(tolerance <= 1e-8, 'orthogonal null is not representation-equivalent')
    direct = h @ text.T
    ridge_score = ridge(x, y, h)
    rows = []
    for i, source in enumerate(r['held']):
        case = source['case_id']
        rows.append({'id': case, 'source_sha256': source['source_sha256'],
                     'group_id': source['group_id'], 'image_sha256': source['image_sha256'],
                     'scores': {'organ': origin_scores[i].tolist(),
                                'orthogonal_null': null_scores[i].tolist(),
                                'direct': direct[i].tolist(),
                                'visual_ridge': ridge_score[i].tolist(),
                                'wrong_text_cue': origin_scores[i, [1,2,0]].tolist()},
                     'original_visual_prototype_class': CLASSES[r['strong'][case]]})
    payload = {
        'schema': PRED_SCHEMA, 'model_scope': MODEL_SCOPE,
        'original_source_zip_sha256': SOURCE_ZIP_SHA,
        'original_feature_zip_sha256': FEATURE_ZIP_SHA,
        'producer_actual_new_pretrained_forwards': 0,
        'cell_split_authorized': False, 'production_authorized': False,
        'original_public_historical_not_true_future': True,
        'train_images': len(r['train']), 'held_images': len(r['held']),
        'train_membership_pairs': len(r['train']) * 3,
        'held_membership_pairs': len(r['held']) * 3,
        'source_label_hash': sha(canonical([{'id':row['case_id'],'class':CLASSES[int(y[j])]} for j,row in enumerate(r['train'])])),
        'text_class_order': list(CLASSES), 'text_source_sha256s': r['text_hashes'],
        'rank': RANK, 'fit_cost': {'real_text_organ': cost, 'signed_permutation_control': cost_null},
        'original_gram_invariant_max_score_abs_error': tolerance,
        'rows': rows,
    }
    payload['prediction_seal_sha256'] = sha(canonical(payload))
    return payload


def write_new(path, obj):
    data = canonical(obj) + b'\n'
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description='HDCF V12 original Organ query-binding research')
    parser.add_argument('command', choices=('train',))
    parser.add_argument('--source-zip', required=True)
    parser.add_argument('--features-zip', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    try:
        doc = fit_and_seal(args.source_zip, args.features_zip)
        write_new(args.out, doc)
    except (Denied, OSError, ValueError, KeyError, np.linalg.LinAlgError) as e:
        parser.exit(2, 'DENY_ALL: ' + str(e) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
