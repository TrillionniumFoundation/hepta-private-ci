"""Validate all original dense parameters, and replay the selected per-image measurements."""
import argparse
from cold import *


@torch.inference_mode()
def run(work,replayed):
    d=Held(work);rr={};param=0;exact=0
    for arec in sorted((work/'fits').glob('*')):
        arm,seed=arec.name.rsplit('-',1);seed=int(seed)
        for h in json.loads((arec/'history.json').read_bytes()):
            if not h['prefix']:continue
            state=arec/h['state'];assert sha(state)==h['state_sha']
            rec=torch.load(state,weights_only=True,map_location='cpu');m=rebuild(seed,d,rec)
            p=m.base if isinstance(m,Probe) else m
            expected=json.loads((arec/h['candidate_parts']['parameter_record']).read_bytes())
            seen={k:tensor_sha(v) for k,v in p.named_parameters()}
            if isinstance(m,Probe):seen['independent_probe.weight']=tensor_sha(m.probe_weight)
            assert expected==seen;param+=1
    for f in sorted((work/'cold').glob('*.npz')):
        g=replayed/f.name
        with np.load(f) as a,np.load(g) as b:
            assert set(a.files)==set(b.files) and all(np.array_equal(a[k],b[k]) for k in a.files)
            rr[f.stem]={'score_sha256':sha(f),'regenerated_sha256':sha(g),'identical_npz_bytes':sha(f)==sha(g),'paired_image_loss_sums':int(len(a['ids'])*2)}
            exact+=len(a['ids'])*2
    write(replayed/'REPLAY.json',{'all_original_dense_parameter_hashes_match':True,'noninitial_candidates_dense_weights_verified':param,
        'distinct_replayed_models':len(rr),'all_matched_and_shifted_image_loss_sums_exact':exact,'cases':rr})


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('work',type=Path);ap.add_argument('replayed',type=Path);a=ap.parse_args();torch.set_num_threads(1);run(a.work,a.replayed)
