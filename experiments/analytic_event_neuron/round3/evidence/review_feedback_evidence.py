"""Report-only independent evidence primitives. Never invokes scientific code/native."""

from collections import Counter
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import struct
import tarfile

import numpy as np
from PIL import Image

Q, STEP, ZERO = 1 << 24, 1 / 4096, '0' * 64
SCHEMA = 'hepta.feedback-count-owner.v3'
PROJECT = Path(__file__).resolve().parent.parent
REPO = PROJECT.parents[2]
ARMS = ('gaussian', 'probit', 'event', 'quantized', 'numeric', 'analytic', 'history', 'zero', 'reset')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_new(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(document, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')


def arrays(path):
    with np.load(path, allow_pickle=False) as data:
        return {k: data[k].item() if data[k].ndim == 0 else data[k].copy() for k in data.files}


class Review:
    def __init__(self):
        self.counts, self.maximum = Counter(), {}

    def require(self, condition, kind, message):
        self.counts[kind] += 1
        if not condition:
            raise AssertionError(kind + ': ' + message)

    def close(self, actual, expected, kind, message, tolerance=2e-11):
        a, b = np.asarray(actual), np.asarray(expected)
        self.require(a.shape == b.shape, kind, message + ' shape')
        if a.dtype.kind in 'USO' or b.dtype.kind in 'USO':
            self.require(np.array_equal(a, b), kind, message)
            return
        gap = float(np.max(np.abs(a.astype(float) - b.astype(float)))) if a.size else 0.0
        self.maximum[kind] = max(self.maximum.get(kind, 0.0), gap)
        self.require(np.isfinite(a).all() and np.isfinite(b).all() and gap <= tolerance, kind, message)


def verify_freeze(root, review):
    root = Path(root).resolve()
    frozen = read_json(root / 'FREEZE.json')
    review.require(len(frozen['source_commit']) == 40 and all(c in '0123456789abcdef' for c in frozen['source_commit']), 'freeze', 'published commit syntax')
    current = {str(p.relative_to(REPO)) for d in (PROJECT.parent, PROJECT.parent / 'round2', PROJECT)
               for p in d.iterdir() if p.is_file() and p.suffix in {'.py', '.rs', '.json', '.md', '.txt'} and p.name != 'README.md'}
    review.require(current == set(frozen['sources_sha256']), 'freeze', 'exact scientific source inventory')
    for key, base in (('sources_sha256', REPO), ('artifacts_sha256', root)):
        review.require(bool(frozen[key]), 'freeze', 'nonempty binding')
        for name, expected in frozen[key].items():
            path = (base / name).resolve()
            review.require(path.is_relative_to(base) and file_hash(path) == expected, 'freeze', name)
    review.require(file_hash(PROJECT / 'PROTOCOL.json') == frozen['protocol_sha256'], 'freeze', 'protocol digest')
    return frozen


def png_value(content, review):
    with Image.open(io.BytesIO(content)) as image:
        review.require(image.format == 'PNG' and image.mode == 'L' and image.size == (256, 32), 'png', 'format')
        pixels = np.asarray(image)
    bits = pixels[0, ::4]
    block = np.repeat(bits, 4)[None, :]
    review.require(np.all((bits == 0) | (bits == 255)) and np.all(pixels[:16] == block)
                   and np.all(pixels[16:] == 255 - block), 'png', 'all payload and complement pixels')
    packed = sum(int(v == 255) << (63 - j) for j, v in enumerate(bits)).to_bytes(8, 'big')
    value = struct.unpack('>d', packed)[0]
    review.require(math.isfinite(value), 'png', 'finite IEEE payload')
    return value


def archive_index(path, metadata, review, kind, transport=False):
    """One streaming pass; retains hashes, scalar readbacks and JSON, never PNG/binaries."""
    expected_hash = metadata['archive_sha256'] if transport else metadata['sha256']
    expected_size = metadata['archive_bytes'] if transport else metadata['bytes']
    review.require(file_hash(path) == expected_hash and Path(path).stat().st_size == expected_size, 'archive', kind + ' container')
    hashes, values, documents, manifest = {}, {}, {}, None
    prefix = 'readbacks/' if transport else Path(path).name.removesuffix('.tar.gz') + '/'
    manifest_name = metadata['manifest_member'] if transport else prefix + 'MANIFEST.json'
    receipt_name = metadata.get('receipt_member')
    receipt_rows = []
    with tarfile.open(path, 'r|gz') as tar:
        for member in tar:
            parsed = PurePosixPath(member.name)
            review.require(not parsed.is_absolute() and '..' not in parsed.parts and '\\' not in member.name, 'archive', 'safe member')
            if member.isdir():
                continue
            review.require(member.isfile() and member.name not in hashes and member.name.startswith(prefix), 'archive', 'unique regular member')
            content = tar.extractfile(member).read()
            hashes[member.name] = {'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}
            review.require(len(content) == member.size, 'archive', 'complete member')
            if member.name == manifest_name:
                manifest = json.loads(content)['files']
            elif member.name == receipt_name:
                receipt_rows = [json.loads(line) for line in content.splitlines()]
            elif transport:
                if member.name.endswith('/prediction.png'):
                    values[member.name] = png_value(content, review)
                elif member.name.endswith('/prediction.txt'):
                    values[member.name] = float(content)
                elif member.name.endswith('/observation.json'):
                    doc = json.loads(content)
                    review.require(set(doc) == {'schema', 'value'} and doc['schema'] == 'hepta.analytic-event.public-observation.v1'
                                   and type(doc['value']) in (float, int) and math.isfinite(doc['value']), 'transport', 'public scalar schema')
                    values[member.name] = float(doc['value'])
                else:
                    review.require(False, 'archive', 'unexpected transport file')
            elif member.name.endswith('.json'):
                documents[member.name] = json.loads(content)
    review.require(manifest is not None and set(hashes) == {prefix + n for n in manifest} | {manifest_name}, 'archive', kind + ' full inventory')
    for name, expected in manifest.items():
        review.require(hashes[prefix + name] == expected, 'archive', kind + ' member SHA/length')
    count_key = 'verified_archive_files' if transport else 'verified_files'
    review.require(len(hashes) == metadata[count_key], 'archive', kind + ' member count')
    if not transport:
        return {'hashes': hashes, 'documents': documents, 'prefix': prefix}
    review.require(hashes[manifest_name]['sha256'] == metadata['manifest_sha256'] and hashes[receipt_name]['sha256'] == metadata['receipt_sha256'], 'transport', 'index and receipt digests')
    receipts, used, counts = {}, set(), Counter()
    for row in receipt_rows:
        key = tuple(row[k] for k in ('case', 'arm', 'kind', 'stage'))
        review.require(key not in receipts and row['scope'] == 'feedback3_confirmation' and row['private_target_supplied'] is False, 'transport', 'unique target-free operation')
        review.require(0 < row['began_ns'] <= row['written_ns'] <= row['readback_ns'], 'chronology', 'write/reopen order')
        fields = ('text_path', 'image_path') if row['kind'] == 'delivery' else ('path',)
        operation = 'deliver' if row['kind'] == 'delivery' else 'observe'
        directory = hashlib.sha256(json.dumps([row['scope'], row['case'], row['arm'], row['stage'], operation], separators=(',', ':')).encode()).hexdigest()[:24]
        for field in fields:
            name = prefix + row[field]
            hash_key = {'path': 'sha256', 'text_path': 'text_sha256', 'image_path': 'image_sha256'}[field]
            review.require(name in values and PurePosixPath(row[field]).parent.as_posix() == directory
                           and hashes[name]['sha256'] == row[hash_key] and name not in used, 'transport', 'path/content/operation binding')
            used.add(name)
        value = values[prefix + row[fields[0]]]
        if row['kind'] == 'delivery':
            review.require(struct.pack('>d', value) == struct.pack('>d', values[prefix + row['image_path']])
                           == struct.pack('>d', row['prediction']), 'transport', 'bit-identical text/PNG/receipt')
        receipts[key] = (row, value)
        counts[row['kind']] += 1
    review.require(used == set(values) and counts['delivery'] == metadata['deliveries'] and counts['observation'] == metadata['observations']
                   and len(used) == metadata['files'], 'transport', 'exhaustive receipt coverage')
    return {'receipts': receipts, 'hashes': hashes, 'counts': dict(counts)}


def posterior(calibration, public):
    """Independent dense joint-Gaussian conditional moments."""
    prior = calibration['error_variance']
    noise = calibration['noise_scale'] * np.asarray(public['variances'])
    covariance = np.diag(noise) + np.full((len(noise), len(noise)), prior)
    weights = np.linalg.solve(covariance, np.full(len(noise), prior))
    return float(weights @ np.asarray(public['residuals'])), float(prior - weights.sum() * prior)


def probability(mean, variance, lower, upper):
    a, b = (lower - mean) / math.sqrt(variance), (upper - mean) / math.sqrt(variance)
    tail = lambda x: .5 * math.erfc(x / math.sqrt(2))
    put, call = tail(-a), tail(b)
    middle = tail(a) - tail(b) if a >= 0 else tail(-b) - tail(-a) if b <= 0 else 1 - put - call
    return np.array([put, middle, call])


def wait_value(mean, variance, cost, noise, wait_cost):
    spread = math.sqrt(variance * variance / (variance + noise))
    cut = math.sqrt(cost)
    a, b = (mean - cut) / spread, (-mean - cut) / spread
    cdf = lambda z: .5 * math.erfc(-z / math.sqrt(2))
    pdf = lambda z: math.exp(-z * z / 2) / math.sqrt(2 * math.pi)
    value = (mean * mean + spread * spread - cost) * (cdf(a) + cdf(b))
    value += spread * ((mean + cut) * pdf(a) + (cut - mean) * pdf(b))
    return max(0.0, value) - wait_cost


def runtime_receipt(row, identity, model, previous, review, mode='error_feedback'):
    public, native, packet = row['public'], row['native'], row['packet']
    config = {'mean_step': STEP, 'logvar_step': STEP, 'mode': mode, 'maximum_count': 2147483647}
    model_sha = digest(model)
    subject = digest([SCHEMA, identity, model_sha, config])
    seq = 1 if previous is None else previous['sequence'] + 1
    old_levels = [0, 0] if previous is None else previous['decoder']['levels']
    timestamp = float(len(public['residuals']))
    previous_time = None if previous is None else previous['time']
    mean, variance = posterior(model['calibration'], public)
    review.close(row['source_forecast'], [mean, variance], 'posterior', 'dense conditional moments')
    source_mean, source_variance = row['source_forecast']
    levels = [math.floor(source_mean / STEP + .5), math.floor(math.log(source_variance) / STEP + .5)]
    expected_packet = {'schema': 'hepta.signed-event.packet.v1', 'config_sha256': digest(config), 'sequence': seq,
                       'time': timestamp, 'observation_kind': 'propagation' if previous_time == timestamp else 'observed',
                       'counts': [levels[j] - old_levels[j] for j in range(2)]}
    decoder = {'schema': 'hepta.signed-event.decoder.v1', 'config': config, 'levels': levels, 'sequence': seq, 'time': timestamp}
    review.require(packet == expected_packet and row['decoder'] == decoder, 'packet', 'independent count reconstruction')
    review.require(all(type(x) is int and abs(x) <= config['maximum_count'] for x in packet['counts']), 'packet', 'count domain')
    request = {'schema': SCHEMA, 'subject': subject, 'model_sha256': model_sha, 'public_sha256': digest(public),
               'source_sha256': digest(row['source_forecast']), 'sequence': seq, 'time': timestamp}
    review.require(all(row[k] == v for k, v in request.items()) and row['request_sha256'] == digest(request), 'runtime', 'identity/request binding')
    decoded = [levels[0] * STEP, math.exp(levels[1] * STEP), -math.sqrt(public['repair_cost']), math.sqrt(public['repair_cost'])]
    # Rust's JSON decimal parser can return an adjacent FP64 value. Q24 must
    # nevertheless agree exactly with independently decoded count state.
    review.close(native['input_parameters_fp64'], decoded, 'native_json', 'count-only native input',
                 2 * max(math.ulp(x) for x in decoded))
    review.require(all(abs(a - b) <= 2 * math.ulp(b) for a, b in zip(native['input_parameters_fp64'], decoded)),
                   'native_json', 'each IPC parameter within two FP64 ulps')
    quantized = [round(x * Q) / Q for x in decoded]
    review.close(native['head']['parameters_q24_decoded'], quantized, 'runtime', 'ties-even parameter Q24', 0)
    reference = probability(*quantized)
    p = native['head']['probabilities']
    review.close(p, reference, 'cdf', 'independent erfc Gaussian tails', 3e-15)
    raw = np.asarray(p) * Q
    counts = np.floor(raw).astype(int)
    remainder = Q - int(counts.sum())
    review.require(0 <= remainder <= 3, 'cdf', 'simplex rounding residual')
    order = sorted(range(3), key=lambda j: (-(raw[j] - counts[j]), j))
    for j in order[:remainder]:
        counts[j] += 1
    review.require(counts.tolist() == native['head']['probabilities_q24'] and int(counts.sum()) == Q and np.all(counts >= 0), 'cdf', 'exact largest-remainder mass')
    review.close(counts / Q, reference, 'q24_cdf', 'actual delivered probabilities', 1 / Q + 3e-15)
    law = {'mean': quantized[0], 'variance': quantized[1], 'probabilities': (counts / Q).tolist(), 'native_quantized': True}
    before = ZERO if previous is None else previous['checkpoint_after']
    native_before = ZERO if previous is None else previous['native']['checkpoint_after']
    after = digest([before, digest(request), decoder, native['checkpoint_after'], law])
    review.require(row['law'] == law and row['checkpoint_before'] == before and row['checkpoint_after'] == after,
                   'runtime', 'adapter chain and policy law')
    review.require(native['checkpoint_before'] == native_before and native['sequence'] == seq and native['recovered'] == (seq > 1)
                   and native['case'] == subject and native['native_binary_sha256'] == model['native_binary_sha256'], 'runtime', 'native ancestry/binary')
    review.require(row['logical_unit_events'] == sum(abs(x) for x in packet['counts']) and row['packet_bytes'] == len(json.dumps(packet, sort_keys=True, separators=(',', ':')).encode()), 'runtime', 'packet cost')
    review.require(row['receiver_reopened_before_native'] and not row['encoder_residual_used_by_policy'] and not row['cross_owner_atomicity']
                   and row['authority'] == 'DENY_ALL' and native['authority'] == 'DENY_ALL' and native['abstain']
                   and native['legacy_runtime_confidence_ppm'] == 0 and not native['calibrated_success_probability']
                   and native['original_neuron_runtime'] and native['original_sparse_journal'] and native['typed_model_port']
                   and native['independent_anchor_witness'] and not native['native_owner_integration'], 'qualification', 'unqualified bounded experimental authority')
    review.require(native['checkpoint_bytes'] == 648 and native['journal_bytes'] == 136 + 464 * seq
                   and native['journal_bytes_written'] == 464 and native['witness_bytes'] == 112 * (seq + 1)
                   and native['head']['allocated_output_vector_bytes'] == 160, 'accounting', 'journal/witness/output allocations')
    review.require(0 <= row['native_cdf_error'] < 2e-15 and native['subprocess_roundtrip_ns'] > 0
                   and native['typed_tick_wall_ns'] > 0 and row['compute_ns_before_commit'] > 0, 'accounting', 'measured cost/reference')
    return law


def owner_state(index, receipts, review):
    subject = receipts[0]['subject']
    stem = index['prefix'] + subject + '/'
    state_env = index['documents'][stem + 'state.json']
    witness_env = index['documents'][stem + 'delivery.witness.json']
    state, witness = state_env['document'], witness_env['document']
    review.require(set(state_env) == {'document', 'sha256'} and digest(state) == state_env['sha256']
                   and set(witness_env) == {'document', 'sha256'} and digest(witness) == witness_env['sha256'], 'owner', 'durable envelope digests')
    review.require(state['receipts'] == receipts and witness['subject'] == subject and len(witness['records']) == len(receipts), 'owner', 'complete delivery chain')
    for i, receipt in enumerate(receipts):
        target = [receipt['source_forecast'][0], math.log(receipt['source_forecast'][1])]
        encoder = {'schema': 'hepta.signed-event.neuron.v1', 'decoder': receipt['decoder'], 'last_target': target,
                   'residual': [target[j] - receipt['decoder']['levels'][j] * STEP for j in range(2)]}
        prefix_state = {'schema': SCHEMA, 'subject': subject, 'sequence': i + 1,
                        'checkpoint': receipt['checkpoint_after'], 'native_checkpoint': receipt['native']['checkpoint_after'],
                        'encoder': encoder, 'decoder': receipt['decoder'], 'receipts': receipts[:i + 1]}
        record = {'sequence': i + 1, 'predecessor': receipt['checkpoint_before'], 'checkpoint': receipt['checkpoint_after'],
                  'state_sha256': digest(prefix_state), 'law_sha256': digest(receipt['law'])}
        review.require(witness['records'][i] == record, 'owner', 'independent prefix-state and witness reconstruction')
    review.require(state == prefix_state, 'owner', 'final encoder decoder receiver state')
    review.require(index['hashes'][stem + 'native/state.journal']['bytes'] == receipts[-1]['native']['journal_bytes']
                   and index['hashes'][stem + 'native/anchor.witness']['bytes'] == receipts[-1]['native']['witness_bytes'], 'owner', 'native durable byte costs')
    return subject
