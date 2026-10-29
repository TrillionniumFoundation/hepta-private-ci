"""Second paid local controller: shared preflight, exact12 DEV cells, report."""
import os,sys

def _deny_workspace_bytecode(event,args):
    if event=='open' and args and isinstance(args[0],(str,bytes)):
        p=os.fsdecode(args[0])
        if p.startswith('/workspace/') and p.endswith('.pyc'):raise FileNotFoundError('source only')
sys.addaudithook(_deny_workspace_bytecode)
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import time
from support import ROOT,SCHEMA,CELLS,metadata,write,read,sha,canonical,number,cell_id
import runtime,accounting,evidence,controller
from support import produced_bytes
from worker import admission


def stage_row(ref,config,dependencies,*,accepted=True):
    s=metadata(ref);raw_ref=s['raw_wait'];raw,total=evidence.raw_child(raw_ref)
    shared=config['stage']!='evaluate';cat='S' if shared else 'O';settled=accepted and s['status']=='FULLY_WAITED_EXIT0'
    r=controller.row('stage:'+config['round_id']+':'+config['source_sha256']+':'+config['segment_id'],raw_ref,total,
        {k:str(total) if k==cat else '0' for k in accounting.CATEGORIES},
        [cell_id(x) for x in CELLS] if shared else [cell_id(config['cell'])],dependencies)
    r['physical_scope_ids']=[evidence.child_scope(raw_ref)];r['success']=settled
    r['proof']={'kind':'LOCAL_STAGE' if settled else 'LOCAL_STAGE_FAILED'}
    if settled:r['proof']['result_ref']=s['result']
    return r


def main():
    if len(sys.argv)!=4:raise ValueError('CONFIG_PATH CONFIG_SHA SOURCE_SHA')
    p,h,source=sys.argv[1:];config=metadata({'path':p,'sha256':h});f=runtime.verify(source);a=admission(config['admission_ref'],source)
    scope=metadata(a['evaluation_scope_ref']);profile=metadata(a['local_profile_ref'])
    if (scope['worker']['path']!=str(ROOT/'eval_worker.py') or scope['segment_ids']!=profile['evaluation_segment_ids']
        or scope['limits']!=profile['evaluation_limits'] or scope['source_manifest']['sha256']!=source):raise ValueError('fixed prospective evaluation scope')
    path=ROOT.parent/'endpoint-local-supervisor-v2-250ms/local_supervisor.py';sup=runtime.load('_eval_owner_supervisor',path,f['source_sha256'][str(path)])
    owner=sup.LocalSupervisor(a['evaluation_scope_ref']);out=Path(scope['run_root'])
    initial=metadata(config['fitting_provisional']);rows=accounting.inventory(initial['operations'])
    evidence.require_carry(rows,a['required_validation_event_ids'])
    # No unmetered fitting closure: shared child performs settle_all12 and payload checks.
    prep=time.process_time();m_start=time.process_time();reports=[];settlements=[];barrier=None;preflight=None;comparison=None;failure=None;dev_may=False
    try:
        for sid in scope['segment_ids']:
            stage='preflight' if sid=='PREFLIGHT' else 'report' if sid=='REPORT' else 'evaluate'
            cell=None if stage!='evaluate' else next(c for c in CELLS if sid=='DEV-'+cell_id(c))
            m_prefix=time.process_time()-m_start
            accounts={cell_id(c):accounting.standalone(rows,c,parent_p=prep,parent_m=m_prefix) for c in CELLS}
            # Prospective S allocation: at most20 preflight +36 report +4 terminal.
            if stage=='preflight':allowance=min(number(20),min(number(v['remaining_S'])-40 for v in accounts.values()))
            elif stage=='report':allowance=min(number(36),min(number(v['remaining_S'])-4 for v in accounts.values()))
            else:allowance=min(number(60),number(accounts[cell_id(cell)]['remaining_O']))
            if allowance<1:raise ValueError('no paid whole-second stage opportunity')
            snapshot=write(out/(sid+'-ACCOUNT.json'),{'operations':rows,'accounts':accounts})
            c={'schema':SCHEMA+'/evaluation-config','stage':stage,'segment_id':sid,'source_sha256':source,
                'round_id':a['round_id'],'cell':list(cell) if cell else None,'scope_ref':a['evaluation_scope_ref'],
                'admission_ref':config['admission_ref'],'out':str(out/sid/'output'),'stage_cpu_allowance':str(allowance),
                'account_ref':snapshot,'parent_P_prefix':str(prep),'parent_M_prefix':str(m_prefix),
                'fitting_provisional':config['fitting_provisional'],'fitting_outer':config['fitting_outer'],
                'barrier':barrier,'preflight_settlement':preflight,'reports':reports,
                'predecessor_settlement':settlements[-1] if settlements else None}
            roots=[Path(metadata(a['scope_ref'])['run_root']),out,Path(config['fitting_outer']['path']).parent]
            produced=produced_bytes([ROOT])
            if produced+scope['limits']['output_bytes']+len(canonical(c))+profile['final_metadata_reserve_bytes']>profile['aggregate_output_admission_cap_bytes']:raise ValueError('whole-round produced-output headroom')
            cr=write(out/(sid+'-CONFIG.json'),c)
            if stage=='evaluate':dev_may=True  # Conservative even if child fails before claim/report.
            ref=owner.run_segment(cr,sid,predecessor=c['predecessor_settlement']);s=metadata(ref)
            raw=metadata(s['raw_wait']);pending=None;before=list(rows)
            if raw.get('complete_wait') is True:
                pending=stage_row(ref,c,[x['id'] for x in rows],accepted=False);rows.append(pending)
            if s['status']!='FULLY_WAITED_EXIT0':raise RuntimeError('failed/unknown stage; no partial rescue/retry')
            r=metadata(s['result'])
            if (r.get('status')!='STAGE_COMPLETE' or r.get('stage')!=stage or r.get('segment_id')!=sid
                    or r.get('source_sha256')!=source or (stage=='evaluate' and r.get('cell')!=c['cell'])):raise ValueError('same actual stage result')
            if pending is None or number(pending['actual_cpu_seconds'])>allowance:raise ValueError('actual complete stage exceeds prospective allowance')
            accepted_prefix=before
            if stage=='preflight':
                b=metadata(r['barrier'])
                by_id={x['id']:x for x in b['operations']}
                if any(by_id.get(x['id'])!=x for x in before):raise ValueError('fitting costs omitted by preflight')
                accepted_prefix=b['operations'];barrier=r['barrier'];preflight=ref
            event=stage_row(ref,c,[x['id'] for x in accepted_prefix])
            rows=accepted_prefix+[event];settlements.append(ref)
            for ccell in CELLS:
                acct=accounting.standalone(rows,ccell,parent_p=prep,parent_m=time.process_time()-m_start)
                if number(acct['remaining_S'])<4:raise ValueError('terminal validation reserve spent')
            if stage=='evaluate':reports.append(r['report'])
            if stage=='report':comparison=r['comparison']
    except BaseException as exc:failure={'type':type(exc).__name__,'message':str(exc)[:1024]}
    result={'schema':SCHEMA+'/provisional-evaluation','source_sha256':source,'round_id':a['round_id'],
        'status':'ALL_REPORTS_AWAITING_COMPLETE_WAIT' if failure is None and len(reports)==12 and comparison else 'INCOMPLETE',
        'operations':rows,'barrier':barrier,'preflight':preflight,'reports':reports,'comparison':comparison,
        'settlements':settlements,'parent_preparation_observed_CPU':prep,
        'parent_instrumentation_observed_lower_CPU':time.process_time()-m_start,'parent_final_tail':'UNSETTLED',
        'DEV_may_have_been_released':dev_may,'official_TEST_read':False,'failure':failure,'scientific_acceptance':False}
    write(out/'PROVISIONAL.json',result)
    return 0 if result['status']=='ALL_REPORTS_AWAITING_COMPLETE_WAIT' else 2
if __name__=='__main__':sys.exit(main())
