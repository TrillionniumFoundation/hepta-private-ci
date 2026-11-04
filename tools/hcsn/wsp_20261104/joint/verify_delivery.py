"""Verify delivery identities and observed numerical gates; no efficacy claim."""
from pathlib import Path
import argparse,gzip,hashlib,json
import numpy as np

ROOT=Path(__file__).resolve().parent

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--results',help='optionally compare a fresh results.json with the recorded strict replay');args=ap.parse_args()
    manifest=json.loads((ROOT/'DELIVERY_MANIFEST.json').read_text())
    for name,ref in manifest['files'].items():
        b=(ROOT/name).read_bytes()
        assert len(b)==ref['bytes'] and hashlib.sha256(b).hexdigest()==ref['sha256'],name
    r=json.loads(gzip.decompress((ROOT/'records/results_strict.json.gz').read_bytes()))
    gates=[]
    for f in r['fits']:
        assert f['exact_semantic_restore_verified']
        for method in ('direct','gradient','random'):
            gain=f['selected_'+method]['validation_utility']-f['baseline_validation_utility']
            gates.append({'fit':f['fit'],'method':method,'validation_gain':gain,'common_gate_accept':gain>=.005})
        for split in ('iid','ood'):
            baseline=f['tests'][split]['arms']['no_edit']
            for arm,metrics in f['tests'][split]['arms'].items():
                assert np.isfinite(metrics['expected_utility'])
                assert metrics['belief_brier']==baseline['belief_brier']
    assert len(gates)==15 and all(g['common_gate_accept'] for g in gates)
    fixture=json.loads((ROOT/'fixtures/rust_fixture.json').read_text())
    x=np.asarray(fixture['features']);y=np.asarray(fixture['targets']);w=np.asarray(fixture['sample_weights']);base=np.asarray(fixture['base_weights']);lam=fixture['lambda_']
    with np.errstate(over='raise',invalid='raise',divide='raise'):
        actual=np.array([base[j]+np.linalg.solve(x.T@(w[:,j,None]*x)+lam*np.eye(49),x.T@(w[:,j]*(y[:,j]-x@base[j]))) for j in range(3)])
    error=float(np.max(abs(actual-np.asarray(fixture['expected_weights']))));assert error<=1e-10
    # Scientific evidence is intentionally OPEN; wide descriptive CIs include zero.
    for split in ('iid','ood'):
        lo,hi=r['summary'][split]['direct_gated']['paired_95_ci'];assert lo<0<hi
    fresh_error=None
    if args.results:
        fresh=json.loads(Path(args.results).read_text());assert len(fresh['fits'])==len(r['fits'])
        errors=[]
        for current,record in zip(fresh['fits'],r['fits']):
            assert current['fit']==record['fit'] and current['source_model_sha256']==record['source_model_sha256'] and current['source_data_sha256']==record['source_data_sha256']
            for method in ('direct','gradient','random'):assert current['selected_'+method]['name']==record['selected_'+method]['name']
            for split in ('iid','ood'):
                for arm in record['tests'][split]['arms']:
                    errors.append(abs(current['tests'][split]['arms'][arm]['expected_utility']-record['tests'][split]['arms'][arm]['expected_utility']))
        fresh_error=max(errors);assert fresh_error<=1e-10
    print(json.dumps({'verified_files':len(manifest['files']),'fixture_max_abs_error':error,'common_gate_accepts':sum(g['common_gate_accept'] for g in gates),'new_replay_max_utility_difference':fresh_error,'efficacy_qualified':False,'full_model_training_superiority_qualified':False},indent=2))

if __name__=='__main__':main()
