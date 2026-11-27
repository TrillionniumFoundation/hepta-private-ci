"""POSTHOC CROSS-RUN aggregate subtraction, never a model or evaluation engine."""
import math
REPLICATION_SHA='44b0ff5ac6b1a103876bd4496120a52286d4f879aaf0c1abe0bb5a80df4804a9'
ABLATION_SHA='1eeabc12d03a5eed880f56eeda4c981ac288e409ef65a0f094b84782918497a2'
METRICS=('consistency','expected_reward','greedy_joint_success','joint_MAP_success','joint_success','pixel_mse','preserve_unspecified_image','preserve_unspecified_text','rho','text_greedy','text_mass')
def require(ok,message):
    if not ok:raise ValueError(message)
def flags(d):
    return dict(rho_gain_at_least_005=d['rho']>=.005,text_mass_no_regression=d['text_mass']>=-1e-10,text_greedy_no_regression=d['text_greedy']>=-1e-10,joint_success_no_regression=d['joint_success']>=-1e-10,pixel_MSE_no_regression=d['pixel_mse']<=1e-10)
def check_metrics(bundle,fold):
    noises={str(3701+10*fold),str(3702+10*fold),'pooled'}
    require(set(bundle)=={'full','low','macro'},'channels')
    for ch in bundle.values():
        require(set(ch)==noises,'noise domain')
        for populations in ch.values():
            require(set(populations)=={'all','partial'},'populations')
            for row in populations.values():
                require(set(row)==set(METRICS),'metric inventory')
                require(all(type(x) in (int,float) and math.isfinite(x) for x in row.values()),'finite scalars')
def analyze(rep,abl,rep_models,abl_models,*,replication_sha,ablation_sha):
    require(replication_sha==REPLICATION_SHA and ablation_sha==ABLATION_SHA,'source hashes')
    for obj,status in ((rep,'COMPLETE_SOURCE_SCENE_REPLICATION'),(abl,'COMPLETE_SOURCE_INSTRUCTION_MASK_ABLATION')):
        require(obj['status']==status and obj['model_seeds']==[103,107] and obj['folds']==[0,1],'status/seeds/folds')
        require(obj['overall_gate'] is False and not obj['TEST_requested'] and not obj['checkpoints_saved_or_restored'],'original outcomes/scope')
        require(obj['all_models_then_all_calibrators_before_heldout_noise'] is True,'barrier')
    domain={'0':[3701,3702],'1':[3711,3712]}
    require(rep['new_fixed_heldout_noise_seeds_by_fold']==domain and abl['previously_studied_heldout_noise_seeds_by_fold']==domain,'fixed noise')
    require(rep['datasets']==abl['datasets'],'same data manifests')
    for obj,models,arms in ((rep,rep_models,('direct','source')),(abl,abl_models,('visible','masked'))):
        expected={f'{m}-f{f}-{s}-{a}' for m in arms for f in (0,1) for s in (103,107) for a in ('additive','ndu')}
        bases={f'{m}-f{f}-{s}' for m in arms for f in (0,1) for s in (103,107)}
        require(set(obj['results'])==set(obj['FIT_calibrators'])==set(models['models'])==expected,'all16 models')
        require(set(obj['base_results'])==set(models['bases'])==set(obj['new_base_preparation'])==bases,'all8 bases')
        for key in expected:
            require(set(obj['results'][key])=={'FIT_calibrated','uncalibrated'},'services')
            f=models['models'][key]['fold']
            require(f in (0,1) and key.split('-')[1]==f'f{f}','model fold')
            require(models['models'][key]['updates']==300,'updates')
            require(obj['FIT_calibrators'][key]['model_digest']==models['models'][key]['digest'],'model identity')
            for h in ('text','image'):
                fit=obj['FIT_calibrators'][key][h]
                require(fit['rows']==1560 and fit['evaluations']==28 and fit['bisection_steps']==24 and fit['interval']==[.125,8.],'FIT protocol')
            for service in obj['results'][key].values():check_metrics(service,f)
        for key in bases:check_metrics(obj['base_results'][key],models['bases'][key]['fold'])
    for f in (0,1):
        for seed in (103,107):
            base=f'f{f}-{seed}';rk='source-'+base;ak='masked-'+base
            require(rep_models['bases'][rk]['digest']==abl_models['bases'][ak]['digest'],'paired base digest')
            require(rep['base_results'][rk]==abl['base_results'][ak],'paired base metrics')
            for a in ('additive','ndu'):
                rk='source-'+base+'-'+a;ak='masked-'+base+'-'+a
                require(rep_models['models'][rk]['digest']==abl_models['models'][ak]['digest'],'paired model digest')
                require(rep['results'][rk]==abl['results'][ak],'paired complete metrics')
                require(rep['FIT_calibrators'][rk]['profile_key']==abl['FIT_calibrators'][ak]['profile_key'],'paired profile')
    contrasts=[]
    for f in (0,1):
        for seed in (103,107):
            for a in ('additive','ndu'):
                for service in ('uncalibrated','FIT_calibrated'):
                    left=abl['results'][f'visible-f{f}-{seed}-{a}'][service];right=rep['results'][f'direct-f{f}-{seed}-{a}'][service]
                    for noise in (str(3701+10*f),str(3702+10*f),'pooled'):
                        delta={ch:{pop:{k:left[ch][noise][pop][k]-right[ch][noise][pop][k] for k in METRICS} for pop in ('all','partial')} for ch in ('full','low','macro')}
                        contrasts.append(dict(fold=f,seed=seed,objective=a,service=service,noise_seed=noise,direction='visible-source minus direct-target',delta=delta,descriptive_threshold_flags=flags(delta['macro']['partial'])))
    require(len(contrasts)==48,'48 comparisons')
    return dict(status='COMPLETE_POSTHOC_CROSS_RUN_AGGREGATE_DECOMPOSITION',analysis_kind='POSTHOC CROSS-RUN, not preregistered primary or fresh blind evidence',contrasts=contrasts,paired_controls_verified=dict(models=8,bases=4,complete_metrics=True),original_overall_gates=dict(replication=False,mask_ablation=False),new_primary_gate=None,scope='Source-label versus target-label pretraining under instruction-visible input; matched source proof required separately. Not NDU attribution, no model selection or new metric evaluation.')
