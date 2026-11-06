#!/usr/bin/env python3
"""Read-only source/receipt integrity, not independent security or product acceptance."""
from __future__ import annotations
import hashlib,json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def require(condition,message):
    if not condition:raise ValueError(message)

def unique(pairs):
    value={}
    for key,item in pairs:
        require(key not in value,'duplicate JSON key');value[key]=item
    return value

def load(path):return json.loads(path.read_text(),object_pairs_hook=unique)

def safe(root,relative):
    item=Path(relative)
    require(not item.is_absolute()and '..'not in item.parts,'unsafe evidence path')
    path=(root/item).resolve();require(path.is_relative_to(root.resolve())and path.is_file(),'missing evidence '+relative)
    return path

def source_bytes(root,commit,paths):
    require(re.fullmatch('[0-9a-f]{40}',commit)is not None,'invalid source identity')
    for relative in paths:
        require(not Path(relative).is_absolute()and '..'not in Path(relative).parts and '\n'not in relative,'invalid source path')
    queries=''.join(commit+':'+p+'\n'for p in paths).encode()
    run=subprocess.run(['git','cat-file','--batch'],cwd=root,input=queries,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
    cursor=0;values={}
    for relative in paths:
        end=run.stdout.index(b'\n',cursor);header=run.stdout[cursor:end].split()
        require(len(header)==3 and header[1]==b'blob','measured source unavailable; fetch complete candidate history')
        size=int(header[2]);start=end+1;values[relative]=run.stdout[start:start+size];cursor=start+size+1
    return values

def validate(root=ROOT,evidence=None,require_current_runtime=True):
    root=Path(root).resolve();folder=Path(evidence or root/'evidence/pon-v3').resolve()
    manifest=load(folder/'manifest.json')
    require(manifest['schema']=='pon-invariant-execution-evidence-v3','manifest schema')
    require(manifest['independent_accepted']is False and manifest['production_activation']is False,'unearned acceptance')
    required={'qualification/report.json','long-history/report.json','parallel/report.json','work/admission.json','work/structured.json','learning/report.json','multihost/report.json','multihost/source-manifest.json','multihost/disk-errors.json','multihost/disk-errors-initial-harness-failure.json'}
    require(required<=set(manifest['files']),'missing declared campaign')
    for relative,digest in manifest['files'].items():
        require(hashlib.sha256(safe(folder,relative).read_bytes()).hexdigest()==digest,'changed artifact '+relative)
    q=load(folder/'qualification/report.json');commit=q['source_commit']
    require(commit==manifest['implementation_commit']and q['source_tree']==manifest['implementation_tree'],'source identity mismatch')
    actual_tree=subprocess.check_output(['git','rev-parse',commit+'^{tree}'],cwd=root,text=True).strip()
    require(actual_tree==q['source_tree'],'source tree mismatch')
    require(q['all_commands_passed']is True and q['source_clean']is True,'qualification did not finish cleanly')
    require(q['independent_accepted']is False and q['production_activation']is False,'qualification scope')
    paths=list(q['source_files_sha256']);original=source_bytes(root,commit,paths)
    current_runtime=True
    runtime_parameters={'config/pon/devnet-v1.json','config/pon/ledger-v1.json','config/pon/work-profile-v1.json','config/pon/model-family-v1.json'}
    for relative,data in original.items():
        require(hashlib.sha256(data).hexdigest()==q['source_files_sha256'][relative],'incorrect measured source '+relative)
        if (relative.startswith(('formal/pon-nakamoto-v1/','trillionnium/'))and not relative.endswith('.md'))or relative in runtime_parameters:
            current=root/relative
            current_runtime=current_runtime and current.is_file()and current.read_bytes()==data
    def runtime_path(path):
        return ((path.startswith(('formal/pon-nakamoto-v1/','trillionnium/')) and not path.endswith('.md')) or path in runtime_parameters)
    tracked=set(subprocess.check_output(['git','ls-files'],cwd=root,text=True).splitlines())
    current_runtime=current_runtime and {p for p in tracked if runtime_path(p)}=={p for p in paths if runtime_path(p)}
    if require_current_runtime:require(current_runtime,'runtime changed: preserve historical evidence and requalify')
    logs=[];python_suites=0;native=None
    for row in q['results']:
        require(row['returncode']==0,'failed command presented as passed')
        text=safe(folder,'qualification/'+row['log']).read_text();logs.append(text)
        if row['command'][:2]==['cargo','test']and '--workspace'in row['command']and '--all-targets'in row['command']:native=row
        if row['command'][0].endswith('python3')and 'python_tests'in row:
            require(re.search(r'Ran '+str(row['python_tests'])+r' tests?\b',text)is not None and re.search(r'(?m)^OK\s*$',text)is not None,'missing Python execution summary')
            python_suites+=1
    require(native is not None and native['failed']==0 and native['passed']>0,'missing native execution')
    native_log=safe(folder,'qualification/'+native['log']).read_text()
    outcomes=[]
    for section in re.split(r'(?m)^\s*(?:Running (?:unittests|tests/)|Doc-tests )',native_log):
        matches=re.findall(r'test result: (\w+)\. (\d+) passed; (\d+) failed; (\d+) ignored',section)
        if matches:outcomes.append(matches[-1])
    require(sum(int(x[1])for x in outcomes)==native['passed'] and sum(int(x[2])for x in outcomes)==native['failed'],'native summary does not match raw harnesses')

    # Bind concrete selectors, not paragraph length or operation/class counts.
    measured_invariants=json.loads(original['config/pon/invariants-v2.json'])['invariants']
    aggregate='\n'.join(logs);selectors=set()
    for row in measured_invariants:
        for selector in row['tests']:
            _,symbol=selector.split('::',1);name=symbol.split('.')[-1]
            require(re.search(r'\b'+re.escape(name)+r'(?:\s|\))[^\n]*\bok\b',aggregate)is not None,'named invariant test not observed: '+selector)
            selectors.add(selector)
    long=load(folder/'long-history/report.json')
    require(long['canonical_height_before_fork']>4096 and long['actual_mined_and_verified_blocks']>4096,'long chain not generated')
    require(long['used_inserted_history_fixtures']is False and long['shallow_fork_verified']is True and long['effects_preserved']is True,'long-history scope')
    require(long['physical_power_loss']is False and long['public_network_security_accepted']is False,'long-history overclaim')
    parallel=load(folder/'parallel/report.json');groups={}
    for sample in parallel['samples']:
        groups.setdefault(sample['scenario'],set()).add(sample['workers'])
        require(sample['block_included']is None and sample['client_confirmed']is None,'executor rate relabelled chain throughput')
        require(sample['speculative_reexec']<=sample['transactions'],'unbounded retry')
    require(groups and all(x=={1,2,4,8}for x in groups.values()),'missing worker comparison')
    for scenario in groups:
        require(len({x['root']for x in parallel['samples']if x['scenario']==scenario})==1,'parallel state divergence')
    a=load(folder/'work/admission.json')
    require(a['attempted_public_jobs']==a['invalid_proofs_recomputed_and_rejected']+a['busy_before_work'],'admission accounting')
    require(a['local_recovery_verified']>0 and a['permissionless_honest_admission_guaranteed']is False,'capacity/fairness overclaim')
    work=load(folder/'work/structured.json');require(work['hardness_accepted']is False and work['fastest_adversary_implemented']is False,'adversarial cost not proven')
    learning=load(folder/'learning/report.json')
    require(learning['real_optimization']is True and learning['three_improving_public_generations']is False,'learning scope')
    require(learning['new_future_window']is False and learning['ordinary_hepta_entry']is False and learning['total_model_reward']==0,'unearned learning reward')
    for cycle in learning['cycles']:
        require(cycle['outcome']=='no_public_update'and cycle['reward']==0,'failed learning update rewarded')
        require(cycle['parent_actually_admitted_artifact']==cycle['public_artifact_after'],'public model changed without adoption')
    hosts=load(folder/'multihost/report.json');hostmanifest=load(folder/'multihost/source-manifest.json')
    require(hostmanifest['source_commit']==commit and hostmanifest['source_clean']is True,'host source mismatch')
    require(hosts['source_manifest']==hostmanifest,'host manifested sources differ')
    require(len({h['host']for h in hosts['hosts']})==len(hosts['hosts'])>=2,'not multiple hosts')
    for claim in ['independent_operators','native_full_node','ordinary_hepta_entry','physical_power_loss','public_network_security_accepted','public_tps_claimed','long_term_retention_accepted','production_activation']:
        require(hosts[claim]is False,'host campaign overclaim '+claim)
    require(hosts['recovered_admitted_block']is True and hosts['reorg_preserved_effects']is True and hosts['quota_depleted_replay_rejected']is True and hosts['consumer_paid']==0,'host behavior failed')
    require(hosts['confirmed_inclusion']['depth']>=6 and hosts['confirmed_inclusion']['work_delta']>0,'confirmation absent')
    disk=load(folder/'multihost/disk-errors.json');failure=load(folder/'multihost/disk-errors-initial-harness-failure.json')
    require(disk['source_commit']==commit and disk['all_cases_passed']is True and disk['independent_operators']is False and disk['physical_power_loss']is False,'disk evidence scope')
    require(failure['all_cases_passed']is False and any(x['returncode']!=0 for x in failure['results']),'initial failed harness erased')
    require({x['host']for x in disk['results']}=={h['host']for h in hosts['hosts']},'disk host set mismatch')
    for result in disk['results']:
        require(result['returncode']==0,'disk command failure')
        cases={x['case']:x for x in result['report']['cases']}
        require(set(cases)=={'extra-trigger','published-value-corruption','sqlite-page-limit-full','truncated-database'},'missing disk fault case')
        require(cases['extra-trigger']['rejection']=='SCHEMA'and cases['published-value-corruption']['rejection']=='ROOT','corrupt state not refused')
        require(cases['sqlite-page-limit-full']['rejection']=='SQLITE_FULL'and cases['sqlite-page-limit-full']['partial_rows_committed']is False,'disk-full atomicity')
        require(cases['sqlite-page-limit-full']['physical_device_full']is False and result['report']['physical_power_loss']is False,'page-limit error is not a physical outage')
        require(result['report']['original_database_modified']is False,'original database modified')

    for relative,digest in hostmanifest['files'].items():
        data=original.get(relative)
        require(data is not None,'unbound host source '+relative)
        if relative=='config/pon/devnet-v1.json':
            config=json.loads(data);overrides=hostmanifest['runtime_config_overrides']
            require(set(overrides)=={'chain_label','genesis_timestamp'},'unexpected live-clock override')
            config.update(overrides);data=(json.dumps(config,indent=2)+'\n').encode()
        require(hashlib.sha256(data).hexdigest()==digest,'host source hash mismatch '+relative)
    return {'implementation_commit':commit,'artifact_files':len(manifest['files']),'executed_invariant_selectors':len(selectors),'python_suites':python_suites,'native_tests':native['passed'],'runtime_matches_measured_source':current_runtime,'physical_hosts':len(hosts['hosts']),'independent_accepted':False,'production_activation':False}

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--historical',action='store_true')
    args=parser.parse_args()
    result=validate(require_current_runtime=not args.historical);manifest=load(ROOT/'evidence/pon-v3/manifest.json')
    tracked=set(subprocess.check_output(['git','ls-files'],cwd=ROOT,text=True).splitlines())
    require({'evidence/pon-v3/'+p for p in manifest['files']}<=tracked,'evidence absent from Git index')
    print(json.dumps(result,sort_keys=True))
