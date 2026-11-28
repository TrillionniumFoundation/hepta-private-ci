"""Preserve the results of additional, SHA-only historical reconstruction tests."""
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

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source'
EXPECTED_SEAL = '75ec41f336ab20aded67a94ac8c435861fe7fc1e2fc4276e8a5ceb5d4b31d256'


def sha(path):
    with path.open('rb') as fp:
        return hashlib.file_digest(fp, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, sort_keys=True, indent=1, allow_nan=False) + '\n')
    tmp.replace(path)


def materialize(src, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        os.link(src, dest)
    if sha(src) != sha(dest):
        raise ValueError(f'custody {dest.name}')


def source_report():
    path = SOURCE / 'SEAL.json'
    assert sha(path) == EXPECTED_SEAL
    return read(path)


def finite_tests(dest):
    r = ROOT / 'finite_replay'; t = read(r / 'terminal.json')
    assert t['groups'] == 33 and t['candidates'] == 99 and t['binary_tests'] == 117
    assert t['source_sha256'] == sha(ROOT / 'finite_replay.py') and t['historical_seal_sha256'] == EXPECTED_SEAL
    materialize(r / 'terminal.json', dest / 'enumeration.json')
    materialize(ROOT / 'finite_replay.py', dest / 'finite_replay.py')
    objective = {}
    for k, h in t['cells'].items():
        p = r / 'cells' / (k + '.json'); assert sha(p) == h
        materialize(p, dest / 'cells' / p.name)
        for record in read(p)['records']:
            for n, z in record['object_tests'].items():
                assert z['original_sha256'] == source_report()['weights'][n]
                assert z['matches_historical'] == (z['original_sha256'] == z['sha256'])
                objective.setdefault(n, [])
                if z['matches_historical']:
                    objective[n].append(record['details']['penalty'])
    assert {n:v for n,v in objective.items() if v} == t['exact_historical_matches']
    return {n:r / 'authenticated' / n for n in t['exact_historical_matches']}


def bp_tests(dest):
    import torch
    fresh = ROOT / 'fresh'
    orig = source_report()['weights']; seal = read(fresh / 'FRESH_SEAL.json')
    assert len(seal['fits']) == 36 and seal['historical_seal_sha256'] == EXPECTED_SEAL
    candidates = {}; matches = {}; previous = []
    for name, h in sorted(seal['weights'].items()):
        width, method, seed, rung = name.split('-')
        if method not in ('bp_h', 'transformer', 'transformer_text'):
            continue
        assert width == '64' and seed in ('413', '677', '941')
        p = fresh / 'models' / name; assert sha(p) == h
        pre = f'{width}-{method}-{seed}-'
        with tempfile.TemporaryDirectory(dir=dest) as td:
            temp = Path(td)
            state = torch.load(p, weights_only=True, map_location='cpu')
            for hist_name, original in sorted(orig.items()):
                if not hist_name.startswith(pre):
                    continue
                new = temp / hist_name
                torch.save(state, new)
                v = sha(new)
                if hist_name == name:
                    assert v == h, 'same-basename serialization differs'
                candidates.setdefault(hist_name, []).append({'fresh_source':name,'fresh_sha256':h,
                                'new_object_sha256':v,'historical_sha256':original,'exact':v==original})
                if v == original:
                    out = dest / 'selected' / hist_name; out.parent.mkdir(exist_ok=True)
                    if not out.exists(): shutil.copyfile(new, out)
                    assert sha(out) == original
                    matches[hist_name] = out
        previous.append(name)
    assert len(candidates) == 23
    write(dest / 'enumeration.json', {'fresh_seal_sha256':sha(fresh/'FRESH_SEAL.json'), 'historical_seal_sha256':EXPECTED_SEAL,
          'comparisons':candidates,'historical_objects':len(candidates),'fresh_sealed_bp_states':len(previous),
          'tested_serializations':sum(map(len,candidates.values())),'exact_historical_matches':sorted(matches),
          'scope':'Only the development-selected fresh width-64 BP states; step and LR of missing originals remain unknown.'})
    return matches


def cold_selected(dest, matched):
    if not matched: return {}
    import numpy as np
    import torch
    sys.path.insert(0,str(SOURCE))
    from cold import derangement
    from models import model, modalities, predict, SLICES
    from verify import summary
    raw = ROOT / 'reconstructed/test.npz'
    assert sha(raw) == source_report()['test_input_sha256']
    with np.load(raw) as z:
        x,y,ids,video = torch.from_numpy(z['x']),z['y'],z['clip'],z['video']
    assert len(y) == 686 and len(np.unique(video)) == 31
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.backends.mha.set_fastpath_enabled(False)
    results={}
    for name,p in matched.items():
        assert sha(p) == source_report()['weights'][name]
        tgt=dest/'selected'/name
        if p != tgt: materialize(p,tgt)
        w,arm,seed,rung=name.split('-')
        net=model(int(w),arm,SOURCE/'law.npz');net.load_state_dict(torch.load(p,weights_only=True,map_location='cpu'))
        base=modalities(x,arm);pred=predict(net,base)
        vectors={'intact':pred,'clip':ids,'video':video,'y':y}
        for m,sl in {**SLICES,'av':slice(768,793)}.items():
            mod=base.clone();mod[...,sl]=0
            vectors['drop_'+m]=predict(net,mod)
            for i,s in enumerate((21901,65741,89303)):
                mod=base.clone();mod[...,sl]=base[derangement(video,s)][...,sl]
                vectors[f'swap_{m}_{i}']=predict(net,mod)
        fd=dest/'cold';fd.mkdir(exist_ok=True)
        f=fd/(name+'.npz')
        if not f.exists(): np.savez_compressed(f,**vectors)
        with np.load(f) as z:
            assert all(np.array_equal(z[k],v) for k,v in vectors.items())
        stats=summary(pred,y,video)
        if np.ptp(pred)==0: stats.update(pearson=None,calibration_slope=None)
        results[name]={'sha256':sha(f),'weights_sha256':sha(p),'metrics':stats}
    return results


def run(kind):
    from publish_mosi import native,git,BRANCH,PREFIX
    trigger = ROOT / ('finite_replay/terminal.json' if kind=='finite_grid' else 'fresh/FRESH_SEAL.json')
    while not trigger.is_file(): time.sleep(18)
    root=ROOT/'publication';key='mosi_recovery_raw/'+kind
    dest=root/key;dest.mkdir(parents=True,exist_ok=True)
    receipt=root/(kind+'-receipt.json')
    if receipt.exists(): print(receipt.read_text());return
    matched=(finite_tests if kind=='finite_grid' else bp_tests)(dest)
    doc={'scope':kind,'enumeration_sha256':sha(dest/'enumeration.json'),'eligible_matches':{n:sha(p) for n,p in matched.items()},
         'source_frozen_seal':EXPECTED_SEAL}
    write(dest/'supplemental_hash_seal.json',doc)
    final={'matched':len(matched),'hash_seal_sha256':sha(dest/'supplemental_hash_seal.json'),'authenticated_cold':cold_selected(dest,matched)}
    write(dest/'terminal.json',final)
    materialize(Path(__file__),dest/'supplemental_recovery.py')
    files=[p for p in sorted(dest.rglob('*')) if p.is_file() and p != dest/'verified_objects.json']
    write(dest/'verified_objects.json',{str(p.relative_to(dest)):{'sha256':sha(p),'size':p.stat().st_size} for p in files})
    files.append(dest/'verified_objects.json')
    while True:
        try:
            commit=native(root,key,files)
            idx=dest/'verified_objects.json'
            b=idx.read_bytes();expected=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
            assert git(root/(key+'.git'),['rev-parse',commit+':'+PREFIX+key+'/verified_objects.json'])==expected
            write(receipt,{'branch':BRANCH,'commit':commit,'prefix':PREFIX+key+'/','file_count':len(files),
                           'manifest_sha256':sha(idx),'manifest_blob':expected,'terminal_sha256':sha(dest/'terminal.json'),
                           'exact_additional_matches':len(matched)})
            print('published supplemental',receipt.read_text(),flush=True);return
        except (RuntimeError,TimeoutError,subprocess.TimeoutExpired) as e:
            print('retrying original verified source',str(e)[-400:],flush=True);time.sleep(50)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('kind',choices=['finite_grid','selected_bp'])
    run(parser.parse_args().kind)
