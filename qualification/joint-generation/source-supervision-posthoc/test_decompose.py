import copy,unittest
from decompose import analyze,flags,METRICS,REPLICATION_SHA,ABLATION_SHA

def fixture():
    def bundle(f,value):return {ch:{n:{pop:{m:value for m in METRICS} for pop in ('all','partial')} for n in (str(3701+10*f),str(3702+10*f),'pooled')} for ch in ('full','low','macro')}
    records=[]
    for arms,status,noise_field in [(('direct','source'),'COMPLETE_SOURCE_SCENE_REPLICATION','new_fixed_heldout_noise_seeds_by_fold'),(('visible','masked'),'COMPLETE_SOURCE_INSTRUCTION_MASK_ABLATION','previously_studied_heldout_noise_seeds_by_fold')]:
        r=dict(status=status,model_seeds=[103,107],folds=[0,1],overall_gate=False,TEST_requested=False,checkpoints_saved_or_restored=False,all_models_then_all_calibrators_before_heldout_noise=True,datasets={'literal':'same'},results={},FIT_calibrators={},base_results={},new_base_preparation={});r[noise_field]={'0':[3701,3702],'1':[3711,3712]};models={'models':{},'bases':{}}
        for m in arms:
            for f in (0,1):
                for s in (103,107):
                    bk=f'{m}-f{f}-{s}';models['bases'][bk]={'fold':f,'digest':'samebase'};r['new_base_preparation'][bk]={};r['base_results'][bk]=bundle(f,.2)
                    for a in ('additive','ndu'):
                        k=bk+'-'+a;models['models'][k]={'fold':f,'updates':300,'digest':'samemodel'}
                        r['results'][k]={service:bundle(f,.4 if m=='visible' else .2) for service in ('uncalibrated','FIT_calibrated')}
                        fit=dict(rows=1560,evaluations=28,bisection_steps=24,interval=[.125,8.]);r['FIT_calibrators'][k]=dict(model_digest='samemodel',profile_key='sameprofile',text=fit.copy(),image=fit.copy())
        records.extend([r,models])
    return records[0],records[2],records[1],records[3]
def run(f):return analyze(*f,replication_sha=REPLICATION_SHA,ablation_sha=ABLATION_SHA)
class DecompositionTests(unittest.TestCase):
    def test_direction_and_boundaries(self):
        result=run(fixture());self.assertEqual(len(result['contrasts']),48);self.assertAlmostEqual(result['contrasts'][0]['delta']['macro']['partial']['rho'],.2);self.assertIsNone(result['new_primary_gate'])
        row=dict(rho=.005,text_mass=-1e-10,text_greedy=-1e-10,joint_success=-1e-10,pixel_mse=1e-10);self.assertTrue(all(flags(row).values()));row['rho']=.004999;self.assertFalse(flags(row)['rho_gain_at_least_005'])
    def test_exact_paired_control_refusal(self):
        for field in ('digest','metrics','base','profile'):
            f=fixture()
            if field=='digest':f[3]['models']['masked-f0-103-additive']['digest']='changed'
            if field=='metrics':f[1]['results']['masked-f0-103-additive']['FIT_calibrated']['full']['3701']['all']['rho']+=1e-14
            if field=='base':f[3]['bases']['masked-f0-103']['digest']='changed'
            if field=='profile':f[1]['FIT_calibrators']['masked-f0-103-additive']['profile_key']='changed'
            with self.assertRaises(ValueError):run(f)
    def test_seed_noise_hash_and_missing_metric_refusal(self):
        for field in ('seed','noise','metric'):
            f=fixture()
            if field=='seed':f[0]['model_seeds']=[71,89]
            if field=='noise':f[0]['new_fixed_heldout_noise_seeds_by_fold']['0']=[2701,2702]
            if field=='metric':del f[1]['results']['visible-f0-103-additive']['uncalibrated']['low']['3701']['partial']['rho']
            with self.assertRaises(ValueError):run(f)
        with self.assertRaises(ValueError):analyze(*fixture(),replication_sha='wrong',ablation_sha=ABLATION_SHA)
