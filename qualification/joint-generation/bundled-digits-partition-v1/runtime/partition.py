"""Inert stdlib G1 mechanics. No real source path, loader, CLI or access authority."""
from decimal import Decimal
import hashlib
import json
import os
import re
import zlib
from dataclasses import dataclass
from pathlib import Path

DOMAIN = b'digits-joint-domain-v1/split/'
MAX_COMPRESSED = 131072
MAX_DECODED = 2 * 1024 * 1024
MAX_FILE = 2 * 1024 * 1024
MAX_OUTPUT = 4 * 1024 * 1024
TOKEN = re.compile(rb'[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]{1,2})?\Z')
REAL_SHA = '09f66e6debdee2cd2b5ae59e0d6abbb73fc2b0e0185d2e1957e9ebb51e23aa22'

class Reject(ValueError):
    pass

@dataclass(frozen=True)
class Profile:
    identity: str
    rows: int
    min_train_per_class: int
    min_heldout: int

REAL = Profile('bundled-digits-real-v1', 1797, 10, 100)
SYNTHETIC = Profile('handmade-synthetic-qualification-v1', 300, 1, 10)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def encode_json(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')

def bucket(h):
    if type(h) is not int or not 0 <= h < 2**256:
        raise Reject('split_integer')
    return 'TRAIN' if 5*h < 3*2**256 else ('selection' if 5*h < 4*2**256 else 'final')

def assignment(pixels):
    if len(pixels) != 64:
        raise Reject('pixel_length')
    digest = hashlib.sha256(pixels).digest()
    return digest.hex(), bucket(int.from_bytes(hashlib.sha256(DOMAIN + digest).digest(), 'big'))

def parse(blob, profile):
    if profile is not REAL and profile is not SYNTHETIC:
        raise Reject('profile')
    if not isinstance(blob, bytes) or len(blob) > MAX_COMPRESSED:
        raise Reject('compressed_cap')
    if profile == REAL and (len(blob) != 57523 or sha(blob) != REAL_SHA):
        raise Reject('source_identity')
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        raw = decoder.decompress(blob, MAX_DECODED + 1)
    except zlib.error:
        raise Reject('gzip') from None
    if len(raw) > MAX_DECODED or decoder.unconsumed_tail:
        raise Reject('decoded_cap')
    if not decoder.eof or decoder.unused_data:
        raise Reject('gzip_boundary')
    if not raw.endswith(b'\n') or b'\r' in raw:
        raise Reject('newline')
    lines = raw[:-1].split(b'\n')
    if len(lines) != profile.rows:
        raise Reject('row_count')
    rows = []
    for line in lines:
        if len(line) > 2144:
            raise Reject('row_length')
        tokens = line.split(b',')
        if len(tokens) != 65 or any(len(t) > 32 or TOKEN.fullmatch(t) is None for t in tokens):
            raise Reject('integer_csv')
        decimals = [Decimal(t.decode('ascii')) for t in tokens]
        if any(v < 0 or v > 16 or v != v.to_integral_value() for v in decimals[:64]) or not (0 <= decimals[64] <= 9 and decimals[64] == decimals[64].to_integral_value()):
            raise Reject('range')
        values = [int(v) for v in decimals]
        rows.append((bytes(values[:64]), values[64]))
    return rows

def build(blob, profile):
    rows = parse(blob, profile)
    groups = {}
    for row_number, (pixels, label) in enumerate(rows):
        key, split = assignment(pixels)
        if key in groups:
            group = groups[key]
            if group['pixels'] != pixels or group['label'] != label:
                raise Reject('conflicting_group')
            group['rows'].append(row_number)
        else:
            groups[key] = dict(pixels=pixels, label=label, rows=[row_number], split=split)
    partitions = {name: [] for name in ('TRAIN', 'selection', 'final')}
    coverage = [0]*10
    for key in sorted(groups):
        g = groups[key]
        partitions[g['split']].append((key, g))
        if g['split'] == 'TRAIN':
            coverage[g['label']] += 1
    if min(coverage) < profile.min_train_per_class or any(len(partitions[n]) < profile.min_heldout for n in ('selection','final')):
        raise Reject('minimum_groups')
    files = {}
    manifest = {'profile':profile.identity, 'source_sha256':sha(blob), 'source_bytes':len(blob), 'groups':[]}
    for name, entries in partitions.items():
        path = 'TRAIN/records.jsonl' if name == 'TRAIN' else 'management/' + name + '.jsonl'
        files[path] = b''.join(encode_json({'id':key,'pixels':list(g['pixels']),'label':g['label'],'multiplicity':len(g['rows'])}) for key,g in entries)
        for key,g in entries:
            manifest['groups'].append({'id':key,'partition':name,'source_rows':g['rows']})
    manifest['artifacts'] = {p:{'bytes':len(b),'sha256':sha(b)} for p,b in files.items()}
    files['management/manifest.json'] = encode_json(manifest)
    public = {'profile':profile.identity,'train_groups':len(partitions['TRAIN']), 'train_class_groups':coverage,'partition_group_counts':{n:len(x) for n,x in partitions.items()},'complete':True,'sealing':'execution discipline only; no OS isolation'}
    files['PUBLIC_RECEIPT.json'] = encode_json(public)
    if any(len(b)>MAX_FILE for b in files.values()) or sum(map(len,files.values())) > MAX_OUTPUT:
        raise Reject('output_cap')
    return files

def publish(files, output):
    """Exclusive directory reservation. COMPLETE marker is last, not global atomicity.

    Partial outputs are preserved on failure, never retried or overwritten. The
    caller may not consume anything unless COMPLETE and bound artifacts verify.
    """
    if set(files) != {'TRAIN/records.jsonl','management/selection.jsonl','management/final.jsonl','management/manifest.json','PUBLIC_RECEIPT.json'}:
        raise Reject('artifact_set')
    marker = encode_json({p:{'bytes':len(b),'sha256':sha(b)} for p,b in sorted(files.items())})
    if any(len(b)>MAX_FILE for b in files.values()) or sum(map(len,files.values()))+len(marker)>MAX_OUTPUT:
        raise Reject('output_cap')
    root = Path(output)
    root.mkdir()  # exclusive: existing empty, partial and complete directories fail
    (root/'TRAIN').mkdir()
    (root/'management').mkdir()
    for path, raw in sorted(files.items()):
        with (root/path).open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    with (root/'COMPLETE.pending').open('xb') as stream:
        stream.write(marker)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(root/'COMPLETE.pending', root/'COMPLETE.json')
    (root/'COMPLETE.pending').unlink()
    # No cross-file crash-atomicity claim; no permission changes or cleanup retry.


def verify_complete(output):
    """Management-only bounded binding verification; never returns record data."""
    root = Path(output)
    expected = {'TRAIN/records.jsonl','management/selection.jsonl','management/final.jsonl','management/manifest.json','PUBLIC_RECEIPT.json'}
    if root.is_symlink() or not root.is_dir():
        raise Reject('output_directory')
    for name in ('TRAIN','management'):
        if (root/name).is_symlink() or not (root/name).is_dir():
            raise Reject('output_directory')
    def read(path, cap):
        if path.is_symlink() or not path.is_file():
            raise Reject('artifact_type')
        with path.open('rb') as f:
            raw = f.read(cap + 1)
        if len(raw) > cap:
            raise Reject('artifact_cap')
        return raw
    raw = read(root/'COMPLETE.json',8192)
    try:
        marker = json.loads(raw)
    except (ValueError, UnicodeError):
        raise Reject('completion_json') from None
    if not isinstance(marker,dict) or set(marker)!=expected or encode_json(marker)!=raw:
        raise Reject('completion_schema')
    total=len(raw)
    for name,binding in marker.items():
        if not isinstance(binding,dict) or set(binding)!={'bytes','sha256'} or type(binding['bytes']) is not int or not 0<=binding['bytes']<=MAX_FILE or not isinstance(binding['sha256'],str) or re.fullmatch('[0-9a-f]{64}',binding['sha256']) is None:
            raise Reject('binding_schema')
        data=read(root/name,MAX_FILE)
        total+=len(data)
        if len(data)!=binding['bytes'] or sha(data)!=binding['sha256']:
            raise Reject('binding_mismatch')
    if total>MAX_OUTPUT:
        raise Reject('output_cap')
    return True
