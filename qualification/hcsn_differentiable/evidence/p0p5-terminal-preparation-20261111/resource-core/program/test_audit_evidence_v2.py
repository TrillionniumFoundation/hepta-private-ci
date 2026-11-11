"""New synthetic archive/terminal failures; no production C2 input or model import."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

from audit_evidence import Auditor, terminal_roster
from metadata_io import AUDIT_RSS, AUDITOR_SHA, Inputs, digest_bytes, identity
from resource_arithmetic import roster


def raw(value):
    return (json.dumps(value,sort_keys=True)+'\n').encode()


def documents():
    docs, stages, entries = {}, [], []
    def stage(kind,name,value,failed=False):
        label=kind+('-'+name if name else '')
        prefix='stages/'+label
        output=prefix+'/'+{'context':'CONTEXT','chain':'CHAIN','replay':'REPLAY'}[kind]+'.json'
        docs[output]=value
        artifact={'schema':'independent-c2-audit-stage-v1','stage':kind,'name':name,
            'status':'failed_recording_chain' if failed else 'passed','inputs_unchanged':True,
            'declared_wall_seconds':100.,'declared_RSS_bytes':AUDIT_RSS,
            'process_wall_seconds':1.,'self_peak_rss_bytes':1000,
            'program_before':AUDITOR_SHA,'program_after':AUDITOR_SHA,'artifact':digest_bytes(raw(value))}
        if kind=='chain':
            best=copy.deepcopy(value)
            best['inputs_unchanged']=False
            docs[prefix+'/BEST-BINDING.json']=best
            artifact['BEST_BINDING']=digest_bytes(raw(best))
        outer={'status':'completed','process_started':True,'returncode':0,'CPU_cost_complete':True,
            'wall_limit_seconds':100.,'RSS_limit_bytes':AUDIT_RSS,'whole_child_wall_seconds':2.,
            'waited_child_CPU_seconds':1.,'sampled_peak_rss_bytes':1000,'wait4_peak_rss_bytes':2000}
        row={'label':label,'stage':kind,'name':name,'planned_grant_seconds':100.,
             'admitted':True,'outer':outer,'artifact':digest_bytes(raw(artifact)),'result':artifact}
        docs[prefix+'/STAGE.json']=artifact
        docs[prefix+'-process/OUTER.json']=outer
        docs[prefix+'-admission.json']=row
        stages.append(row)
    stage('context',None,{'schema':'independent-c2-context-v1','status':'passed_terminal_context',
          'no_E':True,'attempts':{n:{'pid':100+i} for i,n in enumerate(roster('hcsn'))},'parents':dict.fromkeys(roster('hcsn'),{})})
    for i,name in enumerate(roster('hcsn')):
        seed,lr=int(name.split('-s')[1].split('-')[0]),float(name.split('-lr')[1])
        best={'identity':{'bytes':1,'sha256':'a'*64},'epoch':3}
        chain={'schema':'independent-c2-chain-v1','name':name,'inputs_unchanged':True,
               'quality_checkpoint_bound':True,'status':'FAILED_OR_INCOMPLETE_CHAIN',
               'best':best,'report_identity':{'bytes':1,'sha256':'b'*64},'independent_adequacy_supported':False}
        replay={'schema':'independent-c2-best-D-v1','name':name,'status':'passed',
            'quality_reproducibility':'passed','inputs_unchanged':True,'confirmation_E_access':False,
            'optimizer_construct_restore_step_calls':0,'backward_calls':0,'best_checkpoint':best['identity'],
            'best_epoch':3,'fresh_development':{'macro_f1_11_classes':.4},
            'tensor_digest_before':'same','tensor_digest_after':'same'}
        stage('chain',name,chain,True)
        stage('replay',name,replay)
        entries.append({'name':name,'seed':seed,'learning_rate':lr,'quality_reproducibility':'passed',
            'chain_result':digest_bytes(raw(chain)),'replay_result':digest_bytes(raw(replay)),
            'best_epoch':3,'fresh_development':replay['fresh_development'],'independent_adequacy_supported':False})
    docs['SUMMARY.json']={'schema':'independent-c2-terminal-audit-v1','execution_status':'completed_fixed_audit_roster',
        'program_manifest_before':AUDITOR_SHA,'program_manifest_after':AUDITOR_SHA,
        'confirmation_E_access':False,'training_steps':0,'optimizer_construct_restore_step_calls':0,
        'complete_process_wall_seconds':50.,'own_peak_rss_bytes':1000,'entries':entries,'stages':stages}
    return docs


def archive_spec(root,docs,outer_changes=None,bad_manifest=False):
    payload={k:raw(v) for k,v in docs.items()}
    manifest={'files':{k:digest_bytes(v) for k,v in payload.items()}}
    if bad_manifest:
        manifest['files']['SUMMARY.json']['sha256']='0'*64
    payload['MANIFEST.json']=raw(manifest)
    path=root/'audit.zip'
    with ZipFile(path,'x',compression=ZIP_DEFLATED) as zipped:
        for k,v in payload.items(): zipped.writestr(k,v)
    external={'schema':'independent-c2-audit-launch-v1','status':'completed','process_started':True,
        'returncode':0,'whole_hard_wall_seconds':1800,'archive_finalized':True,'CRC_members_manifest_verified':True,
        'CPU_is_lower_bound':False,'whole_wall_seconds':60.,'waited_controller_and_descendant_CPU_seconds':20.,
        'sampled_controller_peak_rss_bytes':1000,'exact_waited_peak_rss_bytes':2000,'waited_peak_rss_bytes':2000,
        'archive':identity(path),'summary':digest_bytes(payload['SUMMARY.json']),'members':len(payload)}
    external.update(outer_changes or {})
    receipt=root/'external.json'; receipt.write_bytes(raw(external))
    return {'external_receipt':{'path':str(receipt),'identity':identity(receipt)},
            'native_complete_envelope':{'path':'/synthetic/native-gate-isolated-in-unit-tests','identity':{'bytes':1,'sha256':'0'*64}},
            'archive':{'path':str(path),'identity':identity(path)}}


def terminal_fixture():
    rows=[{'name':n,'process_started':True,'pid':100+i,'returncode':2,'status':'failed'} for i,n in enumerate(roster('hcsn'))]
    commands=[item for r in rows for item in [dict(r,status='running'),r]]
    return ({'status':'completed_attempt_roster','execution_requested':True,'confirmation_access':False,
             'source_inputs_unchanged':True,'attempts':rows},commands,
            {'state':'succeeded','output_complete':True,'output_durable':True,'terminal_publication_confirmed':True})


class EvidenceTests(unittest.TestCase):
    def load(self,docs=None,outer=None,bad_manifest=False):
        temporary=tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        spec=archive_spec(Path(temporary.name),docs or documents(),outer,bad_manifest)
        # Native originals are a separate source-bound gate tested in test_native_envelope_v2.
        with patch('audit_evidence.verify_native',return_value={'original_C2_pids':list(range(99,106)),
                   'original_C2_controller_pid':99}):
            return Auditor(spec,Inputs()),spec

    def test_bound_archive_keeps_recording_failure_diagnostic_only(self):
        auditor,_=self.load()
        self.assertEqual(len(auditor.entries),6)
        chain,replay=auditor.candidate(roster('hcsn')[0])
        self.assertEqual(replay['quality_reproducibility'],'passed')
        self.assertFalse(chain['independent_adequacy_supported'])

    def test_bad_external_or_missing_original_receipt_refused(self):
        changes=[{'returncode':2},{'CPU_is_lower_bound':True},{'whole_wall_seconds':1800.1},
                 {'whole_hard_wall_seconds':1801},{'exact_waited_peak_rss_bytes':AUDIT_RSS+1}]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(ValueError): self.load(outer=change)
        auditor,spec=self.load()
        Path(spec['external_receipt']['path']).unlink()
        with self.assertRaises(ValueError): Auditor(spec,Inputs())

    def test_archive_hash_and_members_manifest_both_required(self):
        with self.assertRaises(ValueError): self.load(bad_manifest=True)
        auditor,spec=self.load()
        spec['archive']['identity']={'bytes':1,'sha256':'0'*64}
        with self.assertRaises(ValueError): Auditor(spec,Inputs())

    def test_stage_actual_wall_RSS_and_missing_artifact_refused(self):
        for field,value in [('whole_child_wall_seconds',100.001),('wait4_peak_rss_bytes',AUDIT_RSS+1),
                            ('CPU_cost_complete',False),('RSS_limit_bytes',3*1024**3)]:
            docs=documents()
            docs['stages/context-process/OUTER.json'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError): self.load(docs)
        docs=documents(); del docs['stages/context/STAGE.json']
        with self.assertRaises((KeyError,ValueError)): self.load(docs)

    def test_source_and_missing_seed_are_not_summary_passes(self):
        docs=documents(); docs['SUMMARY.json']['program_manifest_after']='0'*64
        with self.assertRaises(ValueError): self.load(docs)
        docs=documents(); docs['SUMMARY.json']['entries'].pop()
        with self.assertRaises(ValueError): self.load(docs)

    def test_terminal_unknown_duplicate_or_extra_opportunity_refused(self):
        for change in ('live','duplicate','extra','missing','unknown'):
            controller,commands,terminal=terminal_fixture()
            if change=='live': controller['attempts'][0]['status']='running'
            if change=='duplicate': commands.insert(0,copy.deepcopy(commands[0]))
            if change=='extra': commands.append({'name':'unexpected'})
            if change=='missing': controller['attempts'].pop()
            if change=='unknown': terminal['output_durable']=False
            with self.subTest(change=change),self.assertRaises(ValueError): terminal_roster(controller,commands,terminal)

    def test_failed_terminal_attempts_are_retained_not_dropped(self):
        controller,commands,terminal=terminal_fixture()
        result=terminal_roster(controller,commands,terminal)
        self.assertEqual(set(result),set(roster('hcsn')))
        self.assertTrue(all(r['returncode']==2 for r in result.values()))

    def test_wrong_checkpoint_replay_binding_refused(self):
        auditor,_=self.load()
        auditor.entries[roster('hcsn')[0]]['best_epoch']=4
        with self.assertRaises(ValueError): auditor.candidate(roster('hcsn')[0])


if __name__=='__main__':
    unittest.main()

