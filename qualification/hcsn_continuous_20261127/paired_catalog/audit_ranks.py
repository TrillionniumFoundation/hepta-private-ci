"""Independent aggregation of all gallery rankings and timing interpretation from saved originals."""
from pathlib import Path
import numpy as np,json,hashlib,statistics
HERE=Path(__file__).resolve().parent;root=HERE/'paired_catalog'
def main():
    meta=json.loads((HERE/'RESULTS.json').read_bytes());seal=json.loads((HERE/'SEAL.json').read_bytes())
    assert meta['sealed']==hashlib.sha256((HERE/'SEAL.json').read_bytes()).hexdigest()
    paths=sorted((root/'catalog_confirmed').glob('*.npz'))
    assert len(paths)==len(seal['items'])==18
    hashes={};count=0
    for path in paths:
        hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
        with np.load(path) as a:
            for tag,info in meta['galleries'].items():
                selected=info['per_model'][path.stem]
                for way in ['image_to_text','text_to_image']:
                    r=a[tag+'_'+way]
                    assert r.dtype.kind=='i' and r.shape==(info['size'],3) and r.min()>=1 and r.max()<=info['size']
                    assert np.all(r[:,2]<=r[:,1]) and np.all(r[:,1]<=r[:,0])
                    for j in [1,5,10]:assert abs((r[:,0]<=j).mean()-selected['directions'][way]['R'+str(j)])<1e-10
                    assert abs((r[:,1]==1).mean()-selected['directions'][way]['title_R1'])<1e-10
                    count+=r.size
    pre=json.loads((root/'dataset.json').read_bytes());ref=json.loads((root/'time_matched/reference.json').read_bytes())
    timing={'common_decode_and_split_s':pre['wall_s'],'selected_direct_cold_pipeline_s':statistics.median(v['outer_complete_s'] for v in ref),'selected_direct_fit_budget_s':statistics.median(v['fit_s'] for v in ref)}
    for k in ['conventional','physical_bp']:
        docs=[json.loads(p.read_bytes()) for p in (root/'neural_fitted').glob(k+'-*.json')]
        ordinary=sorted([d['complete_wall_s'] for d in docs])
        assert len(ordinary)==3
        matched=[json.loads(l) for l in (root/'time_matched/outer.jsonl').read_text().splitlines()]
        matched=[v for v in matched if v['arm']==k]
        times=[json.loads(p.read_bytes()) for p in (root/'time_matched').glob(k+'-*.json')]
        timing[k]={'three_full_fit_dev_wall_s':ordinary,'median_full_s':statistics.median(ordinary),'matched_complete_s':statistics.median(v['seconds'] for v in matched),'matched_steps':[v['steps'] for v in times]}
    primary=meta['galleries']['standard'];summ={'train':pre['counts'][0],'dev':pre['counts'][1],'test':pre['counts'][2],'final_groups':pre['groups'][2],'ranks_checked':count,'data_source':pre['input'],'rank_archives':hashes,'times':timing,'strong':meta['strong'],'quality_pass':primary['pass_quality_gate_vs_selected_conventional'],'raw_primary':primary['metrics'],'contrasts':primary['literal_minus'],'gray_disjoint':meta['galleries']['gray_disjoint']['metrics']}
    (HERE/'VERIFIED.json').write_text(json.dumps(summ,indent=1));print(count,timing,flush=True)
if __name__=='__main__':main()
