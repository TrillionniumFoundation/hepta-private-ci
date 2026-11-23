"""Recover five fully observed prefixes from a source with a genuinely truncated sixth."""
import argparse
import hashlib
import json
from pathlib import Path
import types

import numpy as np

if __package__:
    from . import build,recording_features
else:
    import build,recording_features

HERE=Path(__file__).resolve().parent
FROZEN='ebc217b0c6df641311030c591fb11ac942fefea1ea927d76a5140845f895c7e3'


def five_step_module():
    filename=HERE/'recording_features.py'
    assert build.digest(filename)==FROZEN
    code=filename.read_text()
    changes=(('STEPS = 6','STEPS = 5'),('ab.shape!=(6,52)','ab.shape!=(5,52)'),('vb.shape!=(6,76)','vb.shape!=(5,76)'))
    for original,adapted in changes:
        assert code.count(original)==1
        code=code.replace(original,adapted)
    m=types.ModuleType('five_observed_steps')
    exec(compile(code,str(filename),'exec'),m.__dict__)
    return m


def main():
    cli=argparse.ArgumentParser(description=__doc__);cli.add_argument('--root',type=Path,required=True)
    ns=cli.parse_args();root=ns.root.resolve()
    roster_path=root/'roster/test.json';coverage_path=root/'test_audio_coverage.json'
    roster={q['query_id']:q for q in json.loads(roster_path.read_text())}
    cov=json.loads(coverage_path.read_text());assert cov['roster_sha256']==build.digest(roster_path)
    states={q['query_id']:q for q in cov['queries']}
    truncated='commons-31045040-w04'; control='commons-31045040-w03'
    m=five_step_module(); r=roster[truncated]; c=roster[control]; s=states[truncated]
    rate=cov['streams'][r['recording']]['rate']
    window_start=round(r['start_seconds']*rate);cutoff=round((r['start_seconds']+5*m.DT)*rate)
    assert states[control]['missing_original_samples']==0 and len(s['intervals_halfopen'])==1
    assert window_start<cutoff<=s['intervals_halfopen'][0][0]
    nominal=recording_features.extract(c['local_media'],c['start_seconds'])
    probe=m.extract(c['local_media'],c['start_seconds'])
    for k in nominal:np.testing.assert_array_equal(nominal[k][:5],probe[k])
    items={k:a[None] for k,a in m.extract(r['local_media'],r['start_seconds']).items()}
    for k in ('label','group','recording','query_id','start_seconds','split'):
        items[k]=np.asarray([r[k]])
    items['dt']=np.asarray([r['dt'][:5]])
    target=root/'features/valid_prefix_tail.npz'
    np.savez_compressed(target,**items)
    info={'query_id':truncated,'observed_prefixes':[1,2,3,4,5],'missing_prefixes':[6],
          'control_query_id':control,'control_arrays_equal_bitwise':list(nominal),
          'control_modules':'original six-step output truncated AFTER computation vs independently decoded five-step adapter',
          'verified_audio_sample_interval_halfopen':[window_start,cutoff],'missing_samples':s['intervals_halfopen'],
          'recording_sha256':build.digest(Path(r['local_media'])), 'coverage_sha256':build.digest(coverage_path),
          'media_source_sha256':FROZEN,'adapter_sha256':build.digest(Path(__file__)),
          'shard_sha256':build.digest(target),'input_synthesis':False}
    build.save_json(root/'receipts/valid_prefix_tail.json',info)
    print(json.dumps(info))
if __name__=='__main__':main()
