"""New assembly/authorization tests use explicit synthetic boundaries, never real C2."""
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

import build_report
import launch_analysis
import metadata_io
from metadata_io import Inputs, digest_bytes, identity
from resource_arithmetic import ARMS, roster
from test_audit_evidence_v2 import archive_spec, documents, raw
from test_candidate_v2 import fixture


def saved(root,name,value):
    path=root/name
    path.write_bytes(raw(value))
    return {'path':str(path),'identity':identity(path)}


def assembly(root,missing=False,bad_auditor=False):
    parents,outers,reports,proofs,bindings={},{},{},{},[]
    for i,name in enumerate(roster('hcsn')):
        parent,outer,report,spec,proof,support=fixture()
        seed,lr=int(name.split('-s')[1].split('-')[0]),float(name.split('-lr')[1])
        fit=parent['fit']; fit.update(name=name,seed=seed); fit['plan'].update(seed=seed,learning_rate=lr)
        report.update(seed=seed,learning_rate=lr)
        spec=saved(root,name+'.json',report)
        spec['source_path']='/synthetic/native/'+name+'/result.json'
        outer.update(name=name,pid=100+i,status='completed',result=spec['identity'])
        proof.chain.update(schema='independent-c2-chain-v1',name=name,inputs_unchanged=True,quality_checkpoint_bound=True,
            report_path=spec['source_path'],report_identity=spec['identity'],inputs={spec['source_path']:spec['identity']})
        proof.replay.update(schema='independent-c2-best-D-v1',name=name,status='passed',quality_reproducibility='passed',
            inputs_unchanged=True,confirmation_E_access=False,optimizer_construct_restore_step_calls=0,backward_calls=0,
            best_checkpoint=proof.chain['best']['identity'],best_epoch=3,tensor_digest_before='same',tensor_digest_after='same',
            inputs={spec['source_path']:spec['identity']})
        parents[name],outers[name],reports[name],proofs[name]=parent,outer,report,proof
        bindings.append({'name':name,'report':spec})
    if missing:
        bindings[-1]={'name':bindings[-1]['name'],'report':None,'missing_reason':'synthetic missing terminal artifact'}
    commands=[r for outer in outers.values() for r in (dict(outer,status='running'),outer)]
    commandpath=root/'commands.jsonl'
    commandpath.write_bytes(b''.join(raw(r) for r in commands))
    command={'path':str(commandpath),'source_path':'/synthetic/native/commands.jsonl','identity':identity(commandpath)}
    controller=saved(root,'controller.json',{'status':'completed_attempt_roster','execution_requested':True,
        'confirmation_access':False,'source_inputs_unchanged':True,'attempts':list(outers.values()),
        'commands':command['identity'],'costs':{'nested':True}})
    controller['source_path']='/synthetic/native/controller.json'
    terminal=saved(root,'terminal.json',{'state':'succeeded','job_id':'synthetic-only','output_complete':True,
        'output_durable':True,'terminal_publication_confirmed':True})
    docs=documents()
    docs['stages/context/CONTEXT.json'].update(attempts=outers,parents={n:p['fit']['outer'] for n,p in parents.items()},
        inputs={controller['source_path']:controller['identity'],command['source_path']:command['identity']})
    for entry in docs['SUMMARY.json']['entries']:
        name=entry['name']; proof=proofs[name]
        docs['stages/chain-'+name+'/CHAIN.json']=proof.chain
        docs['stages/chain-'+name+'/BEST-BINDING.json']=dict(proof.chain,inputs_unchanged=False)
        docs['stages/replay-'+name+'/REPLAY.json']=proof.replay
        entry.update(chain_result=digest_bytes(raw(proof.chain)),replay_result=digest_bytes(raw(proof.replay)),
                     fresh_development=proof.replay['fresh_development'])
    for stage in docs['SUMMARY.json']['stages']:
        label=stage['label']; prefix='stages/'+label
        artifact=docs[prefix+'/STAGE.json']
        kind=stage['stage']
        artifact['artifact']=digest_bytes(raw(docs[prefix+'/'+{'context':'CONTEXT','chain':'CHAIN','replay':'REPLAY'}[kind]+'.json']))
        if kind=='chain':
            artifact['BEST_BINDING']=digest_bytes(raw(docs[prefix+'/BEST-BINDING.json']))
        stage['artifact']=digest_bytes(raw(artifact))
    quality=next(iter(reports.values()))['epochs'][0]['development']['macro_f1_11_classes']
    docs['SUMMARY.json']['common_lr']={'common_lr':.001,'all_seed_means':{str(lr):{'mean':quality} for lr in (.001,.003)}}
    audit=archive_spec(root,docs,{'returncode':2} if bad_auditor else None)
    binding={'controller_result':controller,'controller_commands':command,'native_terminal':terminal,
             'native_job_id':'synthetic-only','independent_auditor':audit,'C2_reports':bindings}
    baselines=[]
    for name in roster():
        if name.startswith('hcsn-'): continue
        arm=name.split('-s')[0]; seed=int(name.split('-s')[1].split('-')[0]); lr=float(name.split('-lr')[1])
        baselines.append({'name':name,'arm':arm,'seed':seed,'learning_rate':lr,'quality':.2,'quality_verified':True,
            'independent_adequate':False,'full_chain_charged_wall_seconds':100.,'known_chain_wall_lower_bound_seconds':100.,
            'cumulative_full_CPU_seconds':None,'cumulative_CPU_lower_bound_seconds':5.,'max_attempt_RSS_bytes':1000})
    old={'controller_costs_overlap_attempts':{'nested':True}}
    return binding,(old,baselines,parents,{a:.001 for a in ARMS if a!='hcsn'},support,{'synthetic_old_boundary':True},
                    {'POINTS.json':digest_bytes(raw({'synthetic_old_points':True}))})


class IntegrationTests(unittest.TestCase):
    def assembled(self,real_native_gate=False,**kwargs):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); root=Path(temp.name)
        binding,loaded=assembly(root,**kwargs)
        output=root/'output';output.mkdir()
        result=build_report.skeleton()
        with ExitStack() as scope:
            scope.enter_context(patch.object(build_report,'load_old',return_value=loaded))
            if not real_native_gate:
                scope.enter_context(patch('audit_evidence.verify_native',return_value={
                    'original_C2_pids':list(range(99,106)),'original_C2_controller_pid':99}))
            build_report.build(binding,{},Inputs(),output,result)
        return result

    def test_actual_assembler_keeps42_and_requires_all6_for_choice(self):
        result=self.assembled()
        self.assertEqual(result['execution_status'],'completed_metadata')
        self.assertEqual(len(result['candidates']),42)
        self.assertEqual(result['longer_resource_core_table'][-1]['selected_common_learning_rate'],.001)
        self.assertEqual(result['all_42_opportunity_cost']['all_opportunity_wall_seconds'],4410.)
        self.assertFalse(result['independently_adequate_selected_comparison'])

    def test_bad_external_audit_and_missing_candidate_keep_all_charged(self):
        for options in ({'bad_auditor':True},{'missing':True}):
            result=self.assembled(**options)
            with self.subTest(options=options):
                self.assertEqual(result['execution_status'],'completed_metadata_with_explicit_holds')
                self.assertEqual(result['all_42_opportunity_cost']['opportunity_count'],42)
                self.assertEqual(result['all_42_opportunity_cost']['all_opportunity_wall_seconds'],4410.)
                self.assertIsNone(result['longer_resource_core_table'][-1]['selected_common_learning_rate'])

    def test_final_source_failure_withholds_selections_but_preserves_numbers(self):
        result=self.assembled()
        build_report.withhold(result,'synthetic post-read source change')
        self.assertFalse(result['derived_longer_resource_table_admitted'])
        self.assertTrue(all(not r['quality_verified'] for r in result['candidates']))
        self.assertTrue(all(t['selected_common_learning_rate'] is None for t in result['longer_resource_core_table']))
        self.assertTrue(all(r.get('quality') is not None for r in result['candidates']))
        self.assertEqual(result['all_42_opportunity_cost']['all_opportunity_wall_seconds'],4410.)

    def test_core_prefix_receipt_alone_cannot_admit_without_native_originals(self):
        result=self.assembled(real_native_gate=True)
        self.assertFalse(result['independent_auditor_admitted'])
        self.assertIsNone(result['longer_resource_core_table'][-1]['selected_common_learning_rate'])
        self.assertEqual(result['all_42_opportunity_cost']['all_opportunity_wall_seconds'],4410.)

    def test_old_budget_copies_exact_bytes_and_historical_identity_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            reviews={k:saved(root,k+'.json',{'only':'synthetic source binding'}) for k in ('baseline_v1','baseline_v2')}
            curves=saved(root,'curves.json',{})
            old={'input_identities':{'curves':curves['identity'],**{k:v['identity'] for k,v in reviews.items()}}}
            originals={suffix:saved(root,suffix.split('/')[-1],value)
                       for suffix,value in [('/output-v1/RESULT.json',old),('/output-v1/POINTS.json',{'keep':'exact whitespace'} )]}
            # Deliberate formatting retained verbatim by load_old.
            p=Path(originals['/output-v1/POINTS.json']['path']);p.write_bytes(b'{  "keep" : "exact whitespace" }\n')
            originals['/output-v1/POINTS.json']['identity']=identity(p)
            plan={'fixed_inputs':{k:v['identity'] for k,v in originals.items()}}
            binding={'fixed_inputs':{k:v['path'] for k,v in originals.items()},'old_curves':curves,'historical_reviews':reviews}
            output=root/'copy';output.mkdir()
            with patch.object(build_report,'check_old',return_value=([],{}, {},[],{})):
                build_report.load_old(binding,plan,Inputs(),output)
            self.assertEqual((output/'frozen-original-budget/POINTS.json').read_bytes(),p.read_bytes())
            reviews['baseline_v1']['identity']={'bytes':1,'sha256':'x'*64}
            output=root/'bad';output.mkdir()
            with self.assertRaises(ValueError): build_report.load_old(binding,plan,Inputs(),output)

    def test_execution_authorization_false_scope_and_limits_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for i,change in enumerate(({'execution_authorized':False},{'confirmation_E_access':True},
                                       {'resources':{'whole_hard_wall_seconds':121}})):
                auth={'execution_authorized':True,'scope':'c2-terminal-resource-metadata-only','confirmation_E_access':False,
                      'program_manifest_sha256':'synthetic','plan_sha256':metadata_io.PLAN_SHA,'binding_sha256':'bound',
                      'resources':{'whole_hard_wall_seconds':120,'peak_RSS_bytes':metadata_io.RSS,
                                   'workers':1,'threads':1,'automatic_retry':False}}
                auth.update(change);spec=saved(root,str(i)+'.json',auth)
                args=SimpleNamespace(authorization=spec['path'],authorization_sha=spec['identity']['sha256'],binding_sha='bound')
                with self.subTest(change=change),patch.object(metadata_io,'program_manifest',return_value='synthetic'),self.assertRaises(ValueError):
                    metadata_io.authorize(args,Inputs())

    def test_exit0_archive_still_requires_source_roster_and_actual_budget(self):
        for fault in (None,'source','roster','wall','RSS'):
            with tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary); source='synthetic'
                result=dict(build_report.skeleton(),execution_status='completed_metadata_with_explicit_holds',
                    program_manifest_before=source,program_manifest_after=source,inputs_unchanged=True,
                    metadata_worker_wall_seconds=1.,worker_self_peak_RSS_bytes=1000,input_identities={})
                if fault=='source': result['program_manifest_after']='changed'
                if fault=='roster': result['candidates'].pop()
                payload={'RESULT.json':raw(result)}
                payload['MANIFEST.json']=raw({'files':{'RESULT.json':digest_bytes(payload['RESULT.json'])}})
                path=root/'out.zip'
                with ZipFile(path,'x',compression=ZIP_DEFLATED) as zipped:
                    for name,value in payload.items(): zipped.writestr(name,value)
                peak=metadata_io.RSS+1 if fault=='RSS' else 1000
                wall=120.001 if fault=='wall' else 1.
                with patch.object(launch_analysis,'program_manifest',return_value=source):
                    if fault:
                        with self.subTest(fault=fault),self.assertRaises(ValueError):
                            launch_analysis.verify_output(path,source,peak,wall,Inputs())
                    else:
                        self.assertTrue(launch_analysis.verify_output(path,source,peak,wall,Inputs())['CRC_all_members_manifest_verified'])


if __name__=='__main__':
    unittest.main()

