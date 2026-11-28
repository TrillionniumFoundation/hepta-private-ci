"""Deterministically split an archived Allen spike-time cohort before fitting."""
import argparse
import hashlib
import json
import zipfile
from collections import defaultdict
from pathlib import Path


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_once(path, value):
    raw=(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
    if path.exists():
        assert path.read_bytes()==raw, path
    else:
        temp=path.with_suffix('.new')
        temp.write_bytes(raw)
        temp.replace(path)
    return sha(raw)


def main(source,out):
    out.mkdir(parents=True,exist_ok=True)
    raw=source.read_bytes()
    assert sha(raw)=='5418ceb3cff7dc563490807f5051243c454d8055bef5c5a5e0ab44d719578d07'
    with zipfile.ZipFile(source) as archive:
        member=archive.read('nwb_predictions.json')
        assert sha(member)=='d7ce39c34ba3fc8892d2b9c33360b68359db8ab026f65f421ef4d1dd35a57491'
        data=json.loads(member)
        cells=sorted(map(int,data))
        assert len(cells)==36 and 313861934 in cells
        order=sorted((i for i in cells if i!=313861934),
                     key=lambda i:sha(f'hepta-microdomain-isi-cell-v1/{i}'.encode()))
        partitions={**dict.fromkeys([313861934,*order[:17]],'training'),
                    **dict.fromkeys(order[17:23],'development'),**dict.fromkeys(order[23:],'new_cell')}
        shards=defaultdict(list);assignments={};nwb={}
        for cell in cells:
            rawrows=data[str(cell)]['sweeps']
            levels=sorted({round(r['I_pA']) for r in rawrows},
                          key=lambda i:sha(f'hepta-microdomain-isi-current-v1/{cell}/{i}'.encode()))
            held=levels[2::3] if partitions[cell]!='new_cell' else []
            assignments[cell]={'partition':partitions[cell],'ordered_amplitudes_pA':levels,'heldout_amplitudes':held}
            nwb[cell]=json.loads(archive.read(f'fits/{cell}.json'))['nwb']
            for r in rawrows:
                group='new_current' if round(r['I_pA']) in held else partitions[cell]
                times=list(map(float,r['true_relative_times']));d=r['duration']
                assert all(0<=t<d for t in times) and all(b>a for a,b in zip(times,times[1:]))
                shards[group].append({'cell':cell,'row_id':r['row_id'],'sweep':r['sweep'],'current':r['I_pA'],
                                      'duration':d,'spikes_s':times})
    assert set(shards)=={'training','development','new_cell','new_current'}
    observed=[(r['cell'],r['row_id'],r['sweep']) for part in shards.values() for r in part]
    assert len(set(observed))==len(observed)
    hashes={};sizes={}
    for name,rows in shards.items():
        hashes[name]=write_once(out/(name+'.json'),rows)
        sizes[name]={'sweeps':len(rows),'specimens_in_metadata':len({r['cell'] for r in rows})}
    seal={'input_archive_sha256':sha(raw),'input_member_sha256':sha(member),
          'role':assignments,'source_nwb':nwb,'shards':hashes,'sizes_by_observed_metadata':sizes,
          'protocol_sha256':sha(Path(__file__).with_name('PROTOCOL.md').read_bytes()),
          'prepare_sha256':sha(Path(__file__).read_bytes())}
    write_once(out/'cohort_seal.json',seal)
    print(json.dumps(sizes,sort_keys=True))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();main(a.source,a.output)
