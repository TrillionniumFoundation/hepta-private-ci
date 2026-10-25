"""Linux-only, exact source-only ZIP2 owner test. No raw stream publication."""
import hashlib,json,os,re,shutil,sys,time,tomllib,math
import xml.etree.ElementTree as ET
from pathlib import Path
import zip_native_owned as owned
BASE='c01cc098e2ba9a8eb6acd132a4dcbb3bbebc536f'
BASE_TREE='81198b9ca66ec85e02a4e623ed4eaa96ca6e7bc7'
BRANCH='research/dot-zip-owner-native-c01cc-20261025'
WORKFLOW='.github/workflows/zip-owner-native.yml'
CONTROL=['.github/scripts/zip_native_qualification.py','.github/scripts/zip_native_owned.py',
         '.github/scripts/zip_native_policy.json','.github/scripts/test_zip_native_qualification.py',
         '.github/scripts/zip_native_nextest.toml',WORKFLOW]
PROFILE_APPENDIX='\n# Owner diagnostic only: original defaults and overrides preserved above.\n[profile.zip-owner]\nretries = 0\ntest-threads = 1\n\n[profile.zip-owner.junit]\npath = "junit.xml"\nreport-name = "zip-owner"\n\n[[profile.zip-owner.overrides]]\nfilter = "package(codex-core-plugins) & test(startup_sync::tests::)"\nretries = 0\n'
NEXTTEST_BASE_BLOB='f0430497b34b5335929e24b9e19745f467362641'
DEADLINE=None
FINALIZING=False
CONTROL_PARENT='577c6d23316e59727bf7c42c9f02cc62b38216ee'
FINAL_READ_REPOS=frozenset()
FINAL_GIT_READS={('ls-files','-z'),('status','--porcelain','--untracked-files=all'),('rev-parse','HEAD'),('rev-parse','HEAD^{tree}')}
class Hold(Exception):pass

def sha(b):return hashlib.sha256(b).hexdigest()
def blob(b):return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
DIAGNOSTIC_STAGES={'initial','platform','budget','event','disk','control_admin','source_admin',
    'control_index','source_index','control_identity','source_identity','source_overlay',
    'locks','cargo_profile','cargo_config','native_commands','final_identity','complete'}
DIAGNOSTIC_PREDICATES={'gate_failed','platform','budget_origin','budget_elapsed','deadline',
    'event_ref','event_sha','workflow_sha','workflow_ref','initial_disk',
    'admin_directory','admin_forbidden_entry','admin_required_directory','admin_object_bound',
    'admin_promisor','admin_worktree_remnant','admin_file_symlink','admin_file_bound','admin_missing_file','admin_ref_bound',
    'admin_ref_type','admin_identity_changed','config_size','config_encoding','config_section',
    'config_syntax','config_key','config_duplicate','config_value','config_required','config_branch_pair',
    'index_empty','index_format','index_mode','index_gitmodules','index_duplicate','checkout_delta','physical_index','control_head','control_parent',
    'control_dirty','control_blob','source_head','source_tree','source_dirty','source_blob',
    'policy_identity','lock_identity','cargo_config_identity','permission_denied','io_error','unexpected_error'}
DIAGNOSTIC_ITEMS={'commondir','gitdir','worktrees','modules','config_worktree','config_lock','index_lock',
    'objects_info_alternates','objects_info_http_alternates','refs_replace','info_grafts',
    'info','objects','objects_info','objects_pack','refs','config','HEAD','index','shallow','packed-refs','info_attributes'}
DIAGNOSTIC={'stage':'initial','failure':None,'final_failure':None}

def diagnostic_stage(stage):
    if stage not in DIAGNOSTIC_STAGES:raise Hold()
    DIAGNOSTIC['stage']=stage

def diagnostic_failure(predicate,detail=None):
    # Never serialize arbitrary exception strings, configuration names/values or paths.
    if predicate not in DIAGNOSTIC_PREDICATES:predicate='unexpected_error'
    entry={'stage':DIAGNOSTIC['stage'] if DIAGNOSTIC.get('stage') in DIAGNOSTIC_STAGES else 'initial','predicate':predicate}
    if detail:
        safe={}
        if isinstance(detail.get('item'),str) and detail['item'] in DIAGNOSTIC_ITEMS:safe['item']=detail['item']
        if isinstance(detail.get('sha256'),str) and re.fullmatch('[a-f0-9]{64}',detail['sha256']):safe['sha256']=detail['sha256']
        for key in ['config_present','head_present','index_present']:
            if type(detail.get(key)) is bool:safe[key]=detail[key]
        for key in ['bytes','count']:
            if type(detail.get(key)) is int and 0<=detail[key]<=16384:safe[key]=detail[key]
        if safe:entry['detail']=safe
    key='final_failure' if FINALIZING else 'failure'
    if DIAGNOSTIC.get(key) is None:DIAGNOSTIC[key]=entry

def require(v,predicate='gate_failed',detail=None):
    if not v:
        diagnostic_failure(predicate,detail)
        raise Hold()
def guard():
    require(DEADLINE is not None and time.monotonic()<DEADLINE+(180 if FINALIZING else 0)-10,'deadline')
GIT_ADMIN_BASELINES={}
CARGO_CONFIG_BASELINE=None
CARGO_CONFIG_PATHS=[]
GIT_SAFE_FLAGS=['-c','core.fsmonitor=false','-c','core.untrackedCache=false',
    '-c','core.hooksPath=/dev/null','-c','core.attributesFile=/dev/null',
    '-c','submodule.recurse=false','-c','protocol.allow=never']

def safe_section_detail(line):
    # Hash only an unambiguous complete section header, never an inline RHS.
    if re.fullmatch(r'\[[A-Za-z][A-Za-z0-9.-]*(?: "[^"\\\]\r\n]*")?\]',line) is None:
        return None
    return {'sha256':sha(line.encode()),'bytes':len(line.encode()),'count':1}

def strict_git_config(data):
    require(len(data)<=16384,'config_size')
    section=None;values={}
    allowed={
      ('core','repositoryformatversion'):{'0'},('core','filemode'):{'true','false'},
      ('core','bare'):{'false'},('core','logallrefupdates'):{'true'},
      ('core','symlinks'):{'true','false'},('core','ignorecase'):{'true','false'},
      ('core','precomposeunicode'):{'true','false'},
      ('remote "origin"','url'):{'https://github.com/TrillionniumFoundation/hepta-private-ci','https://github.com/TrillionniumFoundation/hepta-private-ci.git'},
      ('remote "origin"','fetch'):{'+refs/heads/*:refs/remotes/origin/*'},
      ('extensions','objectformat'):{'sha1'},('gc','auto'):{'0'},
      ('branch \"'+BRANCH+'\"','remote'):{'origin'},
      ('branch \"'+BRANCH+'\"','merge'):{'refs/heads/'+BRANCH}}
    try:lines=data.decode('utf-8').splitlines()
    except UnicodeDecodeError:
        require(False,'config_encoding')
    for line in lines:
        line=line.strip()
        if not line or line.startswith(('#',';')):continue
        if line.startswith('['):
            require(line in {'[core]','[remote "origin"]','[extensions]','[http "https://github.com/"]','[gc]','[branch "'+BRANCH+'"]'},'config_section',safe_section_detail(line))
            section=line[1:-1];continue
        match=re.fullmatch(r'([A-Za-z][A-Za-z0-9]*)\s*=\s*([^\r\n]+)',line)
        require(match is not None and section is not None,'config_syntax')
        key=(section,match[1].lower());value=match[2].strip()
        require(key in allowed,'config_key',{'sha256':sha((section+'\0'+match[1].lower()).encode()),'bytes':len((section+'\0'+match[1].lower()).encode()),'count':1})
        require(key not in values,'config_duplicate')
        require(value in allowed[key],'config_value');values[key]=value
    require(values.get(('core','repositoryformatversion'))=='0' and values.get(('core','bare'))=='false','config_required')
    branch_section='branch \"'+BRANCH+'\"'
    require(((branch_section,'remote') in values)==((branch_section,'merge') in values),'config_branch_pair')
    return sha(data)

# Public output reproduced from pinned actions/checkout's non-sparse cleanup.
# Main config still rejects extensions.worktreeConfig, so this must be inactive.
INACTIVE_WORKTREE_REMNANT=b'[core]\n\tsparseCheckout = false\n\tsparseCheckoutCone = false\n[index]\n\tsparse = false\n'

def git_admin_snapshot(repo):
    # Fresh checkout only. No Git command is used to inspect its own configuration.
    admin=repo/'.git';require(admin.is_dir() and not admin.is_symlink(),'admin_directory')
    result={'admin_identity':[admin.stat().st_dev,admin.stat().st_ino]}
    for name in ['commondir','gitdir','worktrees','modules','config.lock','index.lock',
                 'objects/info/alternates','objects/info/http-alternates','refs/replace','info/grafts']:
        path=admin/name;require(not path.exists() and not path.is_symlink(),'admin_forbidden_entry',{'item':name.replace('/','_').replace('.','_')})
    remnant=admin/'config.worktree'
    require(not remnant.is_symlink(),'admin_worktree_remnant',{'item':'config_worktree'})
    result['config.worktree']={'present':False}
    if remnant.exists():
        require(remnant.is_file() and remnant.stat().st_size==len(INACTIVE_WORKTREE_REMNANT),'admin_worktree_remnant',{'item':'config_worktree'})
        with remnant.open('rb') as handle:data=handle.read(len(INACTIVE_WORKTREE_REMNANT)+1)
        require(data==INACTIVE_WORKTREE_REMNANT,'admin_worktree_remnant',{'item':'config_worktree'})
        result['config.worktree']={'present':True,'bytes':len(data),'sha256':sha(data),
            'device':remnant.stat().st_dev,'inode':remnant.stat().st_ino}
    for name in ['info','objects','objects/info','objects/pack','refs']:
        path=admin/name;require(path.is_dir() and not path.is_symlink(),'admin_required_directory',{'item':name.replace('/','_')})
        result[name]=[path.stat().st_dev,path.stat().st_ino]
    for index,path in enumerate((admin/'objects').rglob('*')):
        require(index<100000 and not path.is_symlink(),'admin_object_bound')
        require(not path.name.endswith('.promisor'),'admin_promisor')
        if DEADLINE is not None:guard()
    for name in ['config','HEAD','index','shallow','packed-refs','info/attributes']:
        path=admin/name;require(not path.is_symlink(),'admin_file_symlink',{'item':name.replace('/','_')})
        if path.exists():
            require(path.is_file() and path.stat().st_size<=16*1024**2,'admin_file_bound',{'item':name.replace('/','_')})
            data=path.read_bytes();result[name]={'sha256':sha(data),'device':path.stat().st_dev,'inode':path.stat().st_ino}
            if name=='config':strict_git_config(data)
        else:result[name]=None
    require(result['config'] is not None and result['HEAD'] is not None and result['index'] is not None,'admin_missing_file',{'config_present':result['config'] is not None,'head_present':result['HEAD'] is not None,'index_present':result['index'] is not None})
    for index,path in enumerate((admin/'refs').rglob('*')):
        require(index<100000 and not path.is_symlink(),'admin_ref_bound')
        if DEADLINE is not None:guard()
        if path.is_file():
            require(path.stat().st_size<=4096,'admin_ref_bound');result['ref:'+path.relative_to(admin).as_posix()]=sha(path.read_bytes())
        else:require(path.is_dir(),'admin_ref_type')
    return result

def cargo_config_identity():
    result={}
    for path in CARGO_CONFIG_PATHS:
        require(not path.is_symlink() and not path.parent.is_symlink())
        if path.exists():
            require(path.is_file() and path.stat().st_size<=1024*1024)
            result[str(path)]=sha(path.read_bytes())
        else:result[str(path)]=None
    return result

def recheck_cargo_config():
    require(CARGO_CONFIG_BASELINE is not None and cargo_config_identity()==CARGO_CONFIG_BASELINE,'cargo_config_identity')

def capture(argv,env,maximum,records,disk):
    guard()
    git_repo=None
    if argv and argv[0]=='cargo':recheck_cargo_config()
    if FINALIZING:
        # Only fixed identity reads may bypass the build disk-growth gate.
        # They retain the same remaining reserve and owned-process supervisor.
        require(not owned.OWNERSHIP_UNCERTAIN)
        require(len(argv)>=4 and argv[:2]==['git','-C'])
        require(argv[2] in FINAL_READ_REPOS and tuple(argv[3:]) in FINAL_GIT_READS)
        env=dict(env);env['GIT_OPTIONAL_LOCKS']='0'
        disk=None
    if argv and argv[0]=='git':
        require(len(argv)>=4 and argv[:2]==['git','-C'] and argv[2] in GIT_ADMIN_BASELINES)
        git_repo=Path(argv[2])
        require(git_admin_snapshot(git_repo)==GIT_ADMIN_BASELINES[str(git_repo)],'admin_identity_changed')
        env=dict(env);env.update({'GIT_OPTIONAL_LOCKS':'0','GIT_NO_LAZY_FETCH':'1',
            'GIT_NO_REPLACE_OBJECTS':'1','GIT_ATTR_NOSYSTEM':'1'})
        argv=['git',*GIT_SAFE_FLAGS,*argv[1:]]
    # Administrative/configuration preflight spends the same absolute budget.
    # Recompute only after all such checks, immediately before process launch.
    guard()
    seconds=min(maximum,DEADLINE+(180 if FINALIZING else 0)-time.monotonic()-10)
    require(seconds>0)
    result,streams=owned.capture(argv,env,seconds,disk)
    result['final_readonly']=FINALIZING
    result['cwd']=os.getcwd()
    records.append(result)
    if git_repo is not None and result['cleanup']['confirmed']:
        guard()
        require(git_admin_snapshot(git_repo)==GIT_ADMIN_BASELINES[str(git_repo)],'admin_identity_changed')
        guard()
    require(result['exit']==0 and result['stop'] is None and result['cleanup']['confirmed'])
    return streams

def checked(argv,env,records,disk):
    streams=capture(argv,env,20,records,disk)
    require(streams[0].count<=1024*1024)
    return streams[0].retained()
def git(repo,env,records,disk,*args):return checked(['git','-C',str(repo),*args],env,records,disk)
def parse_tracked_index(data):
    require(bool(data) and data.endswith(b'\0'),'index_empty')
    result={}
    for entry in data[:-1].split(b'\0'):
        require(b'\t' in entry,'index_format')
        fields,raw_name=entry.split(b'\t',1);parts=fields.split(b' ')
        require(len(parts)==3,'index_format');mode,oid,stage=parts
        require(mode in {b'100644',b'100755',b'120000'} and stage==b'0' and re.fullmatch(b'[0-9a-f]{40}',oid),'index_mode')
        require(raw_name and not raw_name.startswith(b'/') and all(part not in {b'',b'.',b'..'} for part in raw_name.split(b'/')),'index_format')
        require(raw_name.split(b'/')[-1]!=b'.gitmodules','index_gitmodules')
        name=os.fsdecode(raw_name);require(name not in result,'index_duplicate')
        result[name]=(mode.decode('ascii'),oid.decode('ascii'))
    return result

def validate_checkout_delta(source_map,control_map,policy,control_blobs):
    modifications={x['path'] for x in policy['source_files']};additions=set(CONTROL)
    allowed=modifications|additions
    require(len(modifications)==2 and len(additions)==6 and len(allowed)==8,'checkout_delta')
    require(set(control_map)-set(source_map)==additions and not set(source_map)-set(control_map),'checkout_delta')
    different={name for name in set(source_map)|set(control_map) if source_map.get(name)!=control_map.get(name)}
    require(different==allowed and set(control_blobs)==allowed,'checkout_delta')
    for name in allowed:require(control_map[name]==('100644',control_blobs[name]),'checkout_delta')
    for item in policy['source_files']:
        require(source_map[item['path']]==('100644',item['base_blob']),'checkout_delta')
        require(control_map[item['path']]==('100644',item['candidate_blob']),'checkout_delta')
    return {'source_entries':len(source_map),'control_entries':len(control_map),
        'source_map_sha256':sha(json.dumps(source_map,sort_keys=True).encode()),
        'control_map_sha256':sha(json.dumps(control_map,sort_keys=True).encode()),
        'added':sorted(additions),'modified':sorted(modifications),'removed_count':0,'other_delta_count':0}

def snapshot(repo,env,records,disk,expected_index=None):
    paths=git(repo,env,records,disk,'ls-files','-z').split(b'\0');result={}
    if expected_index is not None:require({os.fsdecode(raw) for raw in filter(None,paths)}==set(expected_index),'physical_index')
    for raw in filter(None,paths):
        guard();name=os.fsdecode(raw);p=repo/name
        if p.is_symlink():
            require(name=='codex-rs/vendor/bubblewrap/LICENSE')
            data=os.fsencode(os.readlink(p));result[name]=sha(b'link\0'+data)
            if expected_index is not None:require(expected_index[name]==('120000',blob(data)),'physical_index')
        else:
            require(p.is_file() and p.stat().st_size<=16*1024**2)
            data=p.read_bytes();result[name]=sha(b'file\0'+data)
            if expected_index is not None:require(expected_index[name]==('100755' if p.stat().st_mode & 0o100 else '100644',blob(data)),'physical_index')
    return result

def no_v8(lock):
    packages=tomllib.loads(lock.decode())['package'];by={};nodes={}
    for p in packages:
        key=(p['name'],p['version']);require(key not in nodes);nodes[key]=p;by.setdefault(p['name'],[]).append(key)
    require(len(by.get('codex-core-plugins',[]))==1)
    queue=by['codex-core-plugins'].copy();seen=set()
    while queue:
        key=queue.pop()
        if key in seen:continue
        seen.add(key);require(key[0] not in {'v8','rusty_v8'})
        for dep in nodes[key].get('dependencies',[]):
            fields=dep.split();matches=[(fields[0],fields[1])] if len(fields)>1 else by[fields[0]]
            require(len(matches)==1 and matches[0] in nodes);queue.append(matches[0])
    return len(seen)

def unique(items):
    value={}
    for key,item in items:
        require(key not in value);value[key]=item
    return value

def strict_json(data):
    require(len(data)<=1024*1024)
    def finite(value):
        result=float(value);require(math.isfinite(result));return result
    def invalid(value):raise Hold()
    return json.loads(data,object_pairs_hook=unique,parse_float=finite,parse_constant=invalid)

def source_inventory(text):
    names=[]
    for attrs,name in re.findall(r'((?:#\[[^\n]+\]\n)+)(?:async )?fn (\w+)\(',text):
        if '#[test]' not in attrs and '#[tokio::test]' not in attrs:continue
        require(all(a in {'#[test]','#[tokio::test]','#[cfg(unix)]'} for a in attrs.splitlines()))
        names.append('startup_sync::tests::'+name)
    require(len(names)==36 and len(set(names))==36)
    return sorted(names)

def validate_list(data,expected):
    obj=strict_json(data);selected=[]
    for key,suite in obj['rust-suites'].items():
        require(suite['binary-id']==key)
        for name,case in suite['testcases'].items():
            status=case['filter-match']['status'];require(status in {'matches','mismatch'})
            if status=='matches':
                require(key=='codex-core-plugins' and suite['status']=='listed' and case['ignored'] is False)
                selected.append(name)
    require(len(selected)==len(expected) and set(selected)==set(expected))
    return {'identities':sorted(selected),'count':len(selected),'sha256':sha(data),'bytes':len(data)}

def validate_junit(data,expected):
    require(len(data)<=1024*1024 and b'<!DOCTYPE' not in data.upper() and b'<!ENTITY' not in data.upper())
    root=ET.fromstring(data);require(set(root.attrib)<={'name','tests','failures','errors','skipped','disabled','uuid','timestamp','time'})
    require(root.tag=='testsuites' and root.get('name')=='zip-owner')
    require(len(root)==1 and root[0].tag=='testsuite' and root[0].get('name')=='codex-core-plugins')
    suite=root[0];require(set(suite.attrib)<={'name','tests','failures','errors','skipped','disabled','timestamp','time','hostname'});names=[]
    for case in suite:
        require(set(case.attrib)<={'name','classname','timestamp','time'})
        require(case.tag=='testcase' and case.get('classname')=='codex-core-plugins' and bool(case.get('timestamp')))
        require(all(child.tag in {'system-out','system-err'} for child in case))
        elapsed=float(case.get('time','nan'));require(math.isfinite(elapsed) and elapsed>=0)
        names.append(case.get('name'))
    require(len(names)==len(expected) and set(names)==set(expected))
    for node in [root,suite]:
        require(int(node.get('tests','-1'))==len(expected))
        for field in ['failures','errors','skipped','disabled']:
            require(int(node.get(field,'-1' if field in {'failures','errors'} else '0'))==0)
    return {'identities':sorted(names),'count':len(names),'failures':0,'errors':0,'skipped':0,'retries':0,
            'sha256':sha(data),'bytes':len(data)}

def command_plan(source,temp):
    manifest=str(source/'codex-rs/Cargo.toml');common=['cargo','+1.95.0']
    selection=['--manifest-path',manifest,'--locked','--all-features','-p','codex-core-plugins','--lib',
               '--cargo-profile','dev-small','--config-file',str(temp/'nextest.toml'),'--profile','zip-owner','-E','test(startup_sync::tests::)']
    commands=[['rustup','toolchain','install','1.95.0','--profile','minimal','--component','rustfmt'],
      ['rustc','+1.95.0','--version'],common+['--version'],common+['nextest','--version'],
      ['rustup','run','1.95.0','rustfmt','--check','--edition','2024','--config','skip_children=true',
       str(source/'codex-rs/core-plugins/src/startup_sync.rs'),str(source/'codex-rs/core-plugins/src/startup_sync_tests.rs')]]
    for offline in [[],['--offline']]:
        commands.extend([common+['metadata','--manifest-path',manifest,'--locked',*offline,'--all-features','--format-version=1'],
          common+['nextest','list',*selection,*offline,'--message-format','json'],
          common+['nextest','run',*selection,*offline,'--retries','0','--no-tests','fail','--success-output','never','--failure-output','never']])
    return commands

def main(control,source,temp):
    global DEADLINE,FINALIZING,FINAL_READ_REPOS,GIT_ADMIN_BASELINES,CARGO_CONFIG_BASELINE,CARGO_CONFIG_PATHS,DIAGNOSTIC
    FINALIZING=False
    DIAGNOSTIC={'stage':'initial','failure':None,'final_failure':None}
    FINAL_READ_REPOS=frozenset({str(control),str(source)})
    GIT_ADMIN_BASELINES={};CARGO_CONFIG_BASELINE=None;CARGO_CONFIG_PATHS=[]
    temp.mkdir(mode=0o700);public=temp/'public';public.mkdir(mode=0o700)
    initial_cwd=Path.cwd()
    records=[];report={'schema':1,'qualified':False,'raw_exported':False,'windows':'HOLD_unreviewed_job_object',
      'base':BASE,'base_tree':BASE_TREE,'dependency_upgrade':False,'native_execution_complete':False}
    env={'PATH':os.environ['PATH'],'HOME':str(temp/'home'),'CARGO_HOME':str(temp/'cargo'),
         'RUSTUP_HOME':str(temp/'rustup'),'CARGO_TARGET_DIR':str(temp/'target'),'CARGO_BUILD_JOBS':'2',
         'GIT_TERMINAL_PROMPT':'0','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null',
         'CARGO_TERM_COLOR':'never','CI':'true','LANG':'C.UTF-8','TMPDIR':str(temp/'tmp')}
    for key in ['HOME','CARGO_HOME','RUSTUP_HOME','CARGO_TARGET_DIR','TMPDIR']:Path(env[key]).mkdir(mode=0o700)
    try:
        diagnostic_stage('platform');require(sys.platform=='linux','platform')
        diagnostic_stage('budget')
        started=os.environ.get('ZIP_STARTED_MONOTONIC_NS','');require(bool(re.fullmatch('[0-9]{1,20}',started)),'budget_origin')
        origin=int(started)/1e9;require(0<=time.monotonic()-origin<1500,'budget_elapsed');DEADLINE=origin+1500
        diagnostic_stage('event')
        require(os.environ.get('GITHUB_EVENT_NAME')=='push' and os.environ.get('GITHUB_REF')=='refs/heads/'+BRANCH,'event_ref')
        event=os.environ.get('GITHUB_SHA','');require(bool(re.fullmatch('[a-f0-9]{40}',event)),'event_sha')
        require(event==os.environ.get('GITHUB_WORKFLOW_SHA'),'workflow_sha')
        require(os.environ.get('GITHUB_WORKFLOW_REF')=='TrillionniumFoundation/hepta-private-ci/'+WORKFLOW+'@refs/heads/'+BRANCH,'workflow_ref')
        diagnostic_stage('disk')
        free=shutil.disk_usage(temp).free
        require(type(free) is int and free>=0,'initial_disk')
        DIAGNOSTIC['initial_disk']={'preflight_free_bytes':free,'minimum_free_bytes':20*1024**3}
        require(free>=20*1024**3,'initial_disk');owned.DISK_INITIAL_FREE=shutil.disk_usage(temp).free
        require(type(owned.DISK_INITIAL_FREE) is int and owned.DISK_INITIAL_FREE>=0,'initial_disk')
        DIAGNOSTIC['initial_disk']['initial_free_bytes']=owned.DISK_INITIAL_FREE
        for repo in [control,source]:
            diagnostic_stage('control_admin' if repo==control else 'source_admin')
            GIT_ADMIN_BASELINES[str(repo)]=git_admin_snapshot(repo)
        report['git_admin_before_sha256']={repo:sha(json.dumps(value,sort_keys=True).encode()) for repo,value in GIT_ADMIN_BASELINES.items()}
        diagnostic_stage('control_identity')
        require(git(control,env,records,temp,'rev-parse','HEAD').decode().strip()==event,'control_head')
        require(git(control,env,records,temp,'rev-parse','HEAD^').decode().strip()==CONTROL_PARENT,'control_parent')
        control_tree=git(control,env,records,temp,'rev-parse','HEAD^{tree}').decode().strip()
        require(bool(re.fullmatch('[a-f0-9]{40}',control_tree)),'control_head')
        diagnostic_stage('source_identity')
        require(git(source,env,records,temp,'rev-parse','HEAD').decode().strip()==BASE,'source_head')
        require(git(source,env,records,temp,'rev-parse','HEAD^{tree}').decode().strip()==BASE_TREE,'source_tree')
        tracked={}
        for repo in [control,source]:
            diagnostic_stage('control_index' if repo==control else 'source_index')
            tracked[str(repo)]=parse_tracked_index(git(repo,env,records,temp,'ls-files','--stage','-z'))
        diagnostic_stage('control_identity')
        require(not git(control,env,records,temp,'status','--porcelain','--untracked-files=all'),'control_dirty')
        require(not git(source,env,records,temp,'status','--porcelain','--untracked-files=all'),'source_dirty')
        policy_path=control/'.github/scripts/zip_native_policy.json';policy=json.loads(policy_path.read_bytes())
        require(set(policy)=={'base','base_tree','source_files','locks','tests'} and policy['base']==BASE and policy['base_tree']==BASE_TREE,'policy_identity')
        paths=CONTROL+[x['path'] for x in policy['source_files']]
        require(len(paths)==8 and len(set(paths))==8)
        control_before={};control_blobs={}
        for name in paths:
            p=control/name;require(p.is_file() and not p.is_symlink() and p.stat().st_size<128*1024)
            b=p.read_bytes();require(blob(b)==git(control,env,records,temp,'rev-parse','HEAD:'+name).decode().strip(),'control_blob');control_before[name]=sha(b);control_blobs[name]=blob(b)
        report['control_before']={'head':event,'tree':control_tree,'files':control_before}
        delta=validate_checkout_delta(tracked[str(source)],tracked[str(control)],policy,control_blobs)
        report['checkout_delta']={**delta,'source_head':BASE,'source_tree':BASE_TREE,
            'control_head':event,'control_tree':control_tree}
        diagnostic_stage('source_identity')
        require(b'extraheader' not in (source/'.git/config').read_bytes().lower())
        original=snapshot(source,env,records,temp,expected_index=tracked[str(source)])
        report['original_snapshot_sha256']=sha(json.dumps(original,sort_keys=True).encode())
        diagnostic_stage('source_overlay')
        for item in policy['source_files']:
            p=source/item['path'];require(blob(p.read_bytes())==item['base_blob'],'source_blob')
            b=(control/item['path']).read_bytes();require(sha(b)==item['sha256'] and blob(b)==item['candidate_blob']);p.write_bytes(b)
        before=snapshot(source,env,records,temp)
        require({p for p in before if before[p]!=original[p]}=={x['path'] for x in policy['source_files']})
        report['source_before_sha256']=sha(json.dumps(before,sort_keys=True).encode())
        diagnostic_stage('locks')
        report['locks_before']={}
        for name,expected in policy['locks'].items():
            data=(source/name).read_bytes();require(blob(data)==expected,'lock_identity');report['locks_before'][name]={'blob':blob(data),'sha256':sha(data)}
        require(set(policy['locks'])=={'codex-rs/Cargo.lock','MODULE.bazel.lock'})
        report['no_v8_locked_reachable_count']=no_v8((source/'codex-rs/Cargo.lock').read_bytes())
        expected=source_inventory((source/'codex-rs/core-plugins/src/startup_sync_tests.rs').read_text())
        require(expected==policy['tests'])
        diagnostic_stage('cargo_profile')
        manifest_bytes=(source/'codex-rs/Cargo.toml').read_bytes()
        require(blob(manifest_bytes)=='d2703b590935ab17316e6c258657c0ce5ab7412a')
        cargo_config=source/'codex-rs/.cargo/config.toml'
        require(blob(cargo_config.read_bytes())=='8a6f2c11ee7afbb11f7033ef3390fb1c57b4cd44')
        # Cargo searches cwd ancestors as well as private CARGO_HOME. Unknown
        # configuration could override the profile; reject instead of bypassing.
        for directory in [source/'codex-rs',*(source/'codex-rs').parents]:
            for name in ['config','config.toml']:
                candidate=directory/'.cargo'/name
                if candidate!=cargo_config:require(not candidate.exists() and not candidate.is_symlink())
        for name in ['config','config.toml']:
            candidate=Path(env['CARGO_HOME'])/name
            require(not candidate.exists() and not candidate.is_symlink())
        diagnostic_stage('cargo_config')
        CARGO_CONFIG_PATHS=list(dict.fromkeys([
            directory/'.cargo'/name for directory in [source/'codex-rs',*(source/'codex-rs').parents]
            for name in ['config','config.toml']]+[Path(env['CARGO_HOME'])/name for name in ['config','config.toml']]))
        CARGO_CONFIG_BASELINE=cargo_config_identity()
        report['cargo_config_before_sha256']=sha(json.dumps(CARGO_CONFIG_BASELINE,sort_keys=True).encode())
        profiles=tomllib.loads(manifest_bytes.decode())['profile']
        require(profiles['dev-small']=={'inherits':'dev','opt-level':0,'debug':'none','strip':'symbols'})
        require(profiles['dev']=={'debug':'limited'})
        report['cargo_build_profile']={'name':'dev-small','manifest_blob':blob(manifest_bytes),
            'inherits':'dev','opt_level':0,'debug':'none','strip':'symbols',
            'debug_assertions':True,'overflow_checks':True,'features_unchanged':True}
        original_config=(source/'codex-rs/.config/nextest.toml').read_bytes()
        require(blob(original_config)==NEXTTEST_BASE_BLOB)
        profile=(control/'.github/scripts/zip_native_nextest.toml').read_bytes()
        require(profile==original_config+PROFILE_APPENDIX.encode())
        (temp/'nextest.toml').write_bytes(profile)
        report['config_before']={p:digest for p,digest in before.items() if '/.cargo/' in p or p.startswith('.cargo/') or p=='codex-rs/.config/nextest.toml'}
        report['profile_sha256']=sha(profile);report['test_inventory']=expected;report['test_phases']=[]
        os.chdir(source/'codex-rs')
        junit=temp/'target/nextest/zip-owner/junit.xml';pending=None
        diagnostic_stage('native_commands')
        for index,argv in enumerate(command_plan(source,temp)):
            recheck_cargo_config()
            is_list='nextest' in argv and 'list' in argv
            is_run='nextest' in argv and 'run' in argv
            if is_run:require(not junit.exists() and pending is not None)
            streams=capture(argv,env,900,records,temp)
            if index in (1,2,3):
                prefix={1:b'rustc 1.95.0 ',2:b'cargo 1.95.0 ',3:b'cargo-nextest 0.9.103'}[index]
                require(streams[0].count<1024 and streams[0].retained().startswith(prefix))
                if index==3:require(streams[0].retained()[len(prefix):len(prefix)+1] in {b' ',b'\n',b''})
            if is_list:
                require(streams[0].count<=1024*1024)
                pending=validate_list(streams[0].retained(),expected)
            if is_run:
                require(junit.is_file() and not junit.is_symlink() and junit.stat().st_size<=1024*1024)
                validated=validate_junit(junit.read_bytes(),expected)
                report['test_phases'].append({'phase':'offline' if '--offline' in argv else 'online','list':pending,'junit':validated})
                pending=None;junit.unlink()  # Remove only this validated owned report; stale reuse forbidden.
            require(all(blob((source/name).read_bytes())==version for name,version in policy['locks'].items()))
        require([x['phase'] for x in report['test_phases']]==['online','offline'])
        report['native_execution_complete']=True
    except Exception as error:
        diagnostic_failure('permission_denied' if isinstance(error,PermissionError) else 'io_error' if isinstance(error,OSError) else 'unexpected_error')
        report['hold']=True  # Fixed error only, no raw exceptions.
    finally:
        FINALIZING=True
        diagnostic_stage('final_identity')
        report['owned_commands_cleanup_confirmed']=not owned.OWNERSHIP_UNCERTAIN and all(x['cleanup']['confirmed'] for x in records)
        try:
            require(not owned.OWNERSHIP_UNCERTAIN)
            recheck_cargo_config()
            require('source_before_sha256' in report and 'control_before' in report)
            after=snapshot(source,env,records,temp)
            require(sha(json.dumps(after,sort_keys=True).encode())==report['source_before_sha256'])
            changed=git(source,env,records,temp,'status','--porcelain','--untracked-files=all').decode().splitlines()
            require(set(changed)=={' M '+x['path'] for x in policy['source_files']})
            require(not git(control,env,records,temp,'status','--porcelain','--untracked-files=all'),'control_dirty')
            require(git(control,env,records,temp,'rev-parse','HEAD').decode().strip()==event,'control_head')
            require(git(control,env,records,temp,'rev-parse','HEAD^{tree}').decode().strip()==report['control_before']['tree'])
            require(git(source,env,records,temp,'rev-parse','HEAD').decode().strip()==BASE)
            require(git(source,env,records,temp,'rev-parse','HEAD^{tree}').decode().strip()==BASE_TREE,'source_tree')
            control_after={name:sha((control/name).read_bytes()) for name in paths};require(control_after==control_before)
            report['config_after']={p:digest for p,digest in after.items() if '/.cargo/' in p or p.startswith('.cargo/') or p=='codex-rs/.config/nextest.toml'}
            require(report['config_before']==report['config_after'])
            report['source_after_sha256']=sha(json.dumps(after,sort_keys=True).encode());report['control_after']=report['control_before']
            report['locks_after']={name:{'blob':blob((source/name).read_bytes()),'sha256':sha((source/name).read_bytes())} for name in policy['locks']}
            require(report['locks_before']==report['locks_after'])
            recheck_cargo_config()
            report['cargo_config_after_sha256']=sha(json.dumps(cargo_config_identity(),sort_keys=True).encode())
            report['git_admin_after_sha256']={repo:sha(json.dumps(git_admin_snapshot(Path(repo)),sort_keys=True).encode()) for repo in GIT_ADMIN_BASELINES}
            require(report['git_admin_before_sha256']==report['git_admin_after_sha256'])
            report['cleanup_confirmed']=True
            report['qualified']=report['native_execution_complete'] and not report.get('hold',False)
        except Exception as error:
            diagnostic_failure('permission_denied' if isinstance(error,PermissionError) else 'io_error' if isinstance(error,OSError) else 'unexpected_error')
            report['hold']=True;report['cleanup_confirmed']=False
        report['preflight_diagnostic']=DIAGNOSTIC
        report['commands']=records
        os.chdir(initial_cwd)
        (public/'receipt.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    return 0 if report['qualified'] else 125
if __name__=='__main__':sys.exit(main(*(Path(x).resolve() for x in sys.argv[1:])))
