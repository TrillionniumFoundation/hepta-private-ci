"""Reconstruct every finite nonlinear MOSI candidate, including candidates censored on a different CPU."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

BASE = Path(__file__).resolve().parent
ORIG = BASE / 'source'
OUT = BASE / 'finite_replay'
FROZEN_TRAIN = '4eb6bfbe5ef009d314f09bedcba3688224eb48beb128b2da68e1bc3e398e8bea'
FROZEN_SEAL = '75ec41f336ab20aded67a94ac8c435861fe7fc1e2fc4276e8a5ceb5d4b31d256'


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, doc):
    p = path.with_suffix('.tmp')
    p.write_text(json.dumps(doc, sort_keys=True, indent=1, allow_nan=False) + '\n')
    p.replace(path)


def filename_keys(seal, key):
    return {k: h for k, h in seal['weights'].items() if k.startswith(key + '-r')}


def child(width, arm, seed):
    import torch

    key = f'{width}-{arm}-{seed}'
    seal = read(ORIG / 'SEAL.json')
    original = filename_keys(seal, key)
    assert original and arm in ('fp_h', 'fp_h_shuffle', 'fp_h_text', 'fp_r', 'random_h')
    assert sha(ORIG / 'SEAL.json') == FROZEN_SEAL and sha(ORIG / 'train.py') == FROZEN_TRAIN
    prior = BASE / 'candidate_replay/fits'
    records = []
    begin = time.monotonic()
    with tempfile.TemporaryDirectory(dir=OUT) as temp_path:
        temp = Path(temp_path)
        train = (ORIG / 'train.py').read_text()
        before = '        cand=(mae,mse)'
        after = '        if elapsed()>=max(RUNGS):break\n            h=x'
        assert train.count(before) == 1 and train.count(after) == 1
        # Preserve the computation (including its ordering and dtypes) and the
        # original development evaluator. Capture *all* three candidates and
        # remove the workload-dependent cutoff only from the FP penalty loop.
        train = train.replace(before, '        capture_candidate(network,detail,mae,mse)\n' + before)
        train = train.replace(after, '        h=x')
        sys.path.insert(0, str(ORIG))
        def capture(network, detail, mae, mse):
            state = {k: v.detach().clone() for k, v in network.state_dict().items()}
            row = {'details': detail, 'dev_video_mae': mae, 'dev_pooled_mse': mse,
                   'typed_tensor_sha256': {}, 'object_tests': {}}
            for k, v in state.items():
                t = v.contiguous().cpu().numpy()
                row['typed_tensor_sha256'][k] = {'shape': list(t.shape), 'dtype': str(t.dtype),
                   'bytes_sha256': hashlib.sha256(t.tobytes()).hexdigest()}
            for name, frozen in sorted(original.items()):
                path = temp / name
                torch.save(state, path)
                checksum = sha(path)
                with zipfile.ZipFile(path) as z:
                    members = z.infolist()
                    dates = sorted({m.date_time for m in members})
                    packed = [(m.filename.partition('/')[2], m.CRC, m.file_size, m.compress_type) for m in members]
                test = {'sha256': checksum, 'original_sha256': frozen, 'matches_historical': checksum == frozen,
                        'all_zip_date_time_values': dates,
                        'zip_member_names_crcs_and_lengths_sha256': hashlib.sha256(json.dumps(packed).encode()).hexdigest()}
                if (prior / name).is_file():
                    test['matches_original_recipe_rerun'] = checksum == sha(prior / name)
                    if test['matches_original_recipe_rerun']:
                        # Roundtrip same state via the same basename; distinguishes
                        # the present serializer's repeatability from a lost header.
                        loaded = torch.load(path, weights_only=True, map_location='cpu')
                        r = temp / 'reserialized'
                        r.mkdir(exist_ok=True)
                        torch.save(loaded, r / name)
                        test['zip_read_write_same_bytes'] = sha(r / name) == checksum
                if checksum == frozen:
                    (OUT / 'authenticated').mkdir(exist_ok=True)
                    dest = OUT / 'authenticated' / name
                    if not dest.exists():
                        shutil.copyfile(path, dest)
                    assert sha(dest) == frozen
                row['object_tests'][name] = test
            records.append(row)
        code = compile(train, str(ORIG / 'train.py'), 'exec')
        namespace = {'__name__': '__main__', '__file__': str(ORIG / 'train.py'), 'capture_candidate': capture}
        sys.argv = ['train.py', str(BASE / 'reconstructed'), str(ORIG / 'law.npz'),
                    str(temp / 'original_endpoints'), str(width), arm, str(seed)]
        exec(code, namespace)
    assert [r['details']['penalty'] for r in records] == [.001, .03, .3]
    write(OUT / 'cells' / (key + '.json'), {'group': key, 'records': records, 'seconds': time.monotonic() - begin,
          'torch': str(torch.__version__), 'active_precision': torch.get_float32_matmul_precision(),
          'runtime_libraries': torch.__config__.show()})


def master():
    import fcntl

    OUT.mkdir(exist_ok=True); (OUT / 'cells').mkdir(exist_ok=True)
    lock = (OUT / 'lock').open('a'); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    seal = read(ORIG / 'SEAL.json')
    assert sha(ORIG / 'SEAL.json') == FROZEN_SEAL
    allkeys = sorted({k.rsplit('-r', 1)[0] for k in seal['weights']},
                     key=lambda k: (int(k.split('-')[0]), k.split('-')[1:]))
    keys = [k for k in allkeys if k.split('-')[1] in ('fp_h', 'fp_h_shuffle', 'fp_h_text', 'fp_r', 'random_h')]
    assert len(keys) == 33 and sum(len(filename_keys(seal, k)) for k in keys) == 39
    for key in keys:
        cell = OUT / 'cells' / (key + '.json')
        if not cell.exists():
            subprocess.run([sys.executable, __file__, '--cell', *key.split('-')], check=True)
        d = read(cell)
        assert d['group'] == key and len(d['records']) == 3
        print('finite_group', key, 'candidates', len(d['records']), 'seconds', round(d['seconds'], 1), flush=True)
    objs = {}; repeated = set(); dates = set()
    for key in keys:
        data = read(OUT / 'cells' / (key + '.json'))
        for row in data['records']:
            for name, z in row['object_tests'].items():
                objs.setdefault(name, [])
                if z['matches_historical']:
                    objs[name].append(row['details']['penalty'])
                if z.get('matches_original_recipe_rerun'):
                    assert z['zip_read_write_same_bytes']
                    repeated.add(name)
                dates.update(tuple(i) for i in z['all_zip_date_time_values'])
    output = {'historical_seal_sha256': FROZEN_SEAL, 'source_sha256': sha(Path(__file__)),
              'groups': len(keys),'candidates':3*len(keys),'finite_historical_objects':len(objs),
              'binary_tests': sum(3*len(filename_keys(seal, k)) for k in keys),
              'exact_historical_matches': {n:l for n,l in objs.items() if l},
              'newly_refitted_winners_reproduced_bitwise': sorted(repeated), 'archive_date_times_on_this_host': sorted(dates),
              'cells':{k:sha(OUT/'cells'/(k+'.json')) for k in keys},
              'data_access':'Train and validation only; no cold source opened or scored by the enumerator.'}
    write(OUT / 'terminal.json', output)
    print('finite terminal', sha(OUT / 'terminal.json'), len(output['exact_historical_matches']), flush=True)


if __name__ == '__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--cell', nargs=3);args=ap.parse_args()
    if args.cell:
        w,a,s=args.cell;child(int(w),a,int(s))
    else:
        master()
