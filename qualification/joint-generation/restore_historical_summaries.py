"""Verify and restore four losslessly compressed summaries; never runs experiments."""
import argparse, hashlib, json, os, pathlib, re, zlib
H = lambda b: hashlib.sha256(b).hexdigest()
NAMES = {'independent-fit-calibration-view', 'source-instruction-mask-ablation', 'source-scene-decomposition', 'source-scene-replication'}
def verified(root):
    root = pathlib.Path(root)
    mf = root / 'compressed-historical-summaries-manifest.json'
    if mf.is_symlink() or mf.stat().st_size > 16384: raise ValueError('manifest bound')
    data = json.loads(mf.read_bytes())
    if set(data) != {'schema', 'entries'} or data['schema'] != 'joint-summary-gzip-v1' or type(data['entries']) is not list or len(data['entries']) != 4: raise ValueError('manifest schema')
    result = {}; seen = set()
    for e in data['entries']:
        if type(e) is not dict or set(e) != {'package','compressed_bytes','compressed_sha256','original_bytes','original_sha256'}: raise ValueError('entry schema')
        name = e['package']
        if type(name) is not str or name not in NAMES or name in seen: raise ValueError('package')
        seen.add(name)
        for k in ('compressed_bytes','original_bytes'):
            if type(e[k]) is not int or not 0 < e[k] <= (511999 if k=='compressed_bytes' else 2000000): raise ValueError('byte bound')
        for k in ('compressed_sha256','original_sha256'):
            if type(e[k]) is not str or re.fullmatch('[0-9a-f]{64}', e[k]) is None: raise ValueError('digest')
        folder=root/name; p=folder/'SUMMARY.json.gz'
        if folder.is_symlink() or p.is_symlink() or p.stat().st_size != e['compressed_bytes']: raise ValueError('compressed size/path')
        b=p.read_bytes()
        if len(b)!=e['compressed_bytes'] or H(b)!=e['compressed_sha256']: raise ValueError('compressed digest')
        d=zlib.decompressobj(31); raw=d.decompress(b,e['original_bytes']+1)
        if not d.eof or d.unused_data or d.unconsumed_tail or len(raw)!=e['original_bytes'] or H(raw)!=e['original_sha256']: raise ValueError('gzip/raw integrity')
        json.loads(raw)
        result[name]=raw
    return result

def restore(root, output):
    values=verified(root)
    output=pathlib.Path(output)
    # Explicit new output only. Trusted local parent directory, not an adversarial FS sandbox.
    output.mkdir(exist_ok=False)
    for name, raw in values.items():
        folder=output/name; folder.mkdir()
        with (folder/'SUMMARY.json').open('xb') as f: f.write(raw)
    return {name:len(raw) for name,raw in values.items()}
if __name__ == '__main__':
    a=argparse.ArgumentParser(description=__doc__); a.add_argument('--root', type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent); a.add_argument('--output',type=pathlib.Path); args=a.parse_args()
    print(json.dumps(restore(args.root,args.output) if args.output else {k:len(v) for k,v in verified(args.root).items()},sort_keys=True))
