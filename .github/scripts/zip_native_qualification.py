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
CONTROL_PARENT='f61a23820d2ae6ac510d80e81f72d9638cc2f16a'
FINAL_READ_REPOS=frozenset()
FINAL_GIT_READS={('ls-files','-z'),('status','--porcelain','--untracked-files=all'),('rev-parse','HEAD'),('rev-parse','HEAD^{tree}')}
class Hold(Exception):pass

def sha(b):return hashlib.sha256(b).hexdigest()
def blob(b):return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
def require(v):
    if not v:raise Hold()
def guard():
    require(DEADLINE is not None and time.monotonic()<DEADLINE+(180 if FINALIZING else 0)-10)
GIT_ADMIN_BASELINES={}
CARGO_CONFIG_BASELINE=None
CARGO_CONFIG_PATHS=[]
GIT_SAFE_FLAGS=['-c','core.fsmonitor=false','-c','core.untrackedCache=false',
    '-c','core.hooksPath=/dev/null','-c','core.attributesFile=/dev/null',
    '-c','submodule.recurse=false','-c','protocol.allow=never']

def strict_git_config(data):
    require(len(data)<=16384)
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
    for line in data.decode('utf-8').splitlines():
        line=line.strip()
        if not line or line.startswith(('#',';')):continue
        if line.startswith('['):
            require(line in {'[core]','[remote "origin"]','[extensions]','[http "https://github.com/"]','[gc]','[branch "'+BRANCH+'"]'})
            section=line[1:-1];continue
        match=re.fullmatch(r'([A-Za-z][A-Za-z0-9]*)\s*=\s*([^\r\n]+)',line)
        require(match is not None and section is not None)
        key=(section,match[1].lower());value=match[2].strip()
        require(key in allowed and key not in values and value in allowed[key]);values[key]=value
    require(values.get(('core','repositoryformatversion'))=='0' and values.get(('core','bare'))=='false')
    branch_section='branch \"'+BRANCH+'\"'
    require(((branch_section,'remote') in values)==((branch_section,'merge') in values))
    return sha(data)

def git_admin_snapshot(repo):
    # Fresh checkout only. No Git command is used to inspect its own configuration.
    admin=repo/'.git';require(admin.is_dir() and not admin.is_symlink())
    result={'admin_identity':[admin.stat().st_dev,admin.stat().st_ino]}
    for name in ['commondir','gitdir','worktrees','modules','config.worktree','config.lock','index.lock',
                 'objects/info/alternates','objects/info/http-alternates','refs/replace','info/grafts']:
        path=admin/name;require(not path.exists() and not path.is_symlink())
    for name in ['info','objects','objects/info','objects/pack','refs']:
        path=admin/name;require(path.is_dir() and not path.is_symlink())
        result[name]=[path.stat().st_dev,path.stat().st_ino]
    for index,path in enumerate((admin/'objects').rglob('*')):
        require(index<100000 and not path.is_symlink())
        require(not path.name.endswith('.promisor'))
        if DEADLINE is not None:guard()
    for name in ['config','HEAD','index','shallow','packed-refs','info/attributes']:
        path=admin/name;require(not path.is_symlink())
        if path.exists():
            require(path.is_file() and path.stat().st_size<=16*1024**2)
            data=path.read_bytes();result[name]={'sha256':sha(data),'device':path.stat().st_dev,'inode':path.stat().st_ino}
            if name=='config':strict_git_config(data)
        else:result[name]=None
    require(result['config'] is not None and result['HEAD'] is not None and result['index'] is not None)
    for index,path in enumerate((admin/'refs').rglob('*')):
        require(index<100000 and not path.is_symlink())
        if DEADLINE is not None:guard()
        if path.is_file():
            require(path.stat().st_size<=4096);result['ref:'+path.relative_to(admin).as_posix()]=sha(path.read_bytes())
        else:require(path.is_dir())
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
    require(CARGO_CONFIG_BASELINE is not None and cargo_config_identity()==CARGO_CONFIG_BASELINE)

def capture(argv,env,maximum,records,disk):
    guard()
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
        require(git_admin_snapshot(Path(argv[2]))==GIT_ADMIN_BASELINES[argv[2]])
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
    require(result['exit']==0 and result['stop'] is None and result['cleanup']['confirmed'])
    return streams

def checked(argv,env,records,disk):
    streams=capture(argv,env,20,records,disk)
    require(streams[0].count<=1024*1024)
    return streams[0].retained()
def git(repo,env,records,disk,*args):return checked(['git','-C',str(repo),*args],env,records,disk)
def snapshot(repo,env,records,disk):
    paths=git(repo,env,records,disk,'ls-files','-z').split(b'\0');result={}
    for raw in filter(None,paths):
        guard();name=os.fsdecode(raw);p=repo/name
        if p.is_symlink():
            require(name=='codex-rs/vendor/bubblewrap/LICENSE')
            result[name]=sha(b'link\0'+os.fsencode(os.readlink(p)))
        else:
            require(p.is_file() and p.stat().st_size<=16*1024**2)
            result[name]=sha(b'file\0'+p.read_bytes())
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
    global DEADLINE,FINALIZING,FINAL_READ_REPOS,GIT_ADMIN_BASELINES,CARGO_CONFIG_BASELINE,CARGO_CONFIG_PATHS
    FINALIZING=False
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
        require(sys.platform=='linux')
        started=os.environ.get('ZIP_STARTED_MONOTONIC_NS','');require(bool(re.fullmatch('[0-9]{1,20}',started)))
        origin=int(started)/1e9;require(0<=time.monotonic()-origin<1500);DEADLINE=origin+1500
        require(os.environ.get('GITHUB_EVENT_NAME')=='push' and os.environ.get('GITHUB_REF')=='refs/heads/'+BRANCH)
        event=os.environ.get('GITHUB_SHA','');require(bool(re.fullmatch('[a-f0-9]{40}',event)))
        require(event==os.environ.get('GITHUB_WORKFLOW_SHA'))
        require(os.environ.get('GITHUB_WORKFLOW_REF')=='TrillionniumFoundation/hepta-private-ci/'+WORKFLOW+'@refs/heads/'+BRANCH)
        require(shutil.disk_usage(temp).free>=20*1024**3);owned.DISK_INITIAL_FREE=shutil.disk_usage(temp).free
        for repo in [control,source]:
            GIT_ADMIN_BASELINES[str(repo)]=git_admin_snapshot(repo)
            entries=git(repo,env,records,temp,'ls-files','--stage','-z').split(b'\0')
            require(any(entries))
            for entry in filter(None,entries):
                fields,name=entry.split(b'\t',1);mode,oid,stage=fields.split(b' ')
                require(mode in {b'100644',b'100755',b'120000'} and stage==b'0' and re.fullmatch(b'[0-9a-f]{40}',oid))
                require(name.split(b'/')[-1]!=b'.gitmodules')
        report['git_admin_before_sha256']={repo:sha(json.dumps(value,sort_keys=True).encode()) for repo,value in GIT_ADMIN_BASELINES.items()}
        require(git(control,env,records,temp,'rev-parse','HEAD').decode().strip()==event)
        require(git(control,env,records,temp,'rev-parse','HEAD^').decode().strip()==CONTROL_PARENT)
        require(not git(control,env,records,temp,'status','--porcelain','--untracked-files=all'))
        policy_path=control/'.github/scripts/zip_native_policy.json';policy=json.loads(policy_path.read_bytes())
        require(set(policy)=={'base','base_tree','source_files','locks','tests'} and policy['base']==BASE and policy['base_tree']==BASE_TREE)
        paths=CONTROL+[x['path'] for x in policy['source_files']]
        require(len(paths)==8 and len(set(paths))==8)
        control_before={}
        for name in paths:
            p=control/name;require(p.is_file() and not p.is_symlink() and p.stat().st_size<128*1024)
            b=p.read_bytes();require(blob(b)==git(control,env,records,temp,'rev-parse','HEAD:'+name).decode().strip());control_before[name]=sha(b)
        report['control_before']={'head':event,'tree':git(control,env,records,temp,'rev-parse','HEAD^{tree}').decode().strip(),'files':control_before}
        changed=git(control,env,records,temp,'diff','--name-only',BASE,event).decode().splitlines();require(set(changed)==set(paths))
        require(git(source,env,records,temp,'rev-parse','HEAD').decode().strip()==BASE)
        require(git(source,env,records,temp,'rev-parse','HEAD^{tree}').decode().strip()==BASE_TREE)
        require(not git(source,env,records,temp,'status','--porcelain','--untracked-files=all'))
        require(b'extraheader' not in (source/'.git/config').read_bytes().lower())
        original=snapshot(source,env,records,temp)
        report['original_snapshot_sha256']=sha(json.dumps(original,sort_keys=True).encode())
        for item in policy['source_files']:
            p=source/item['path'];require(blob(p.read_bytes())==item['base_blob'])
            b=(control/item['path']).read_bytes();require(sha(b)==item['sha256'] and blob(b)==item['candidate_blob']);p.write_bytes(b)
        before=snapshot(source,env,records,temp)
        require({p for p in before if before[p]!=original[p]}=={x['path'] for x in policy['source_files']})
        report['source_before_sha256']=sha(json.dumps(before,sort_keys=True).encode())
        report['locks_before']={}
        for name,expected in policy['locks'].items():
            data=(source/name).read_bytes();require(blob(data)==expected);report['locks_before'][name]={'blob':blob(data),'sha256':sha(data)}
        require(set(policy['locks'])=={'codex-rs/Cargo.lock','MODULE.bazel.lock'})
        report['no_v8_locked_reachable_count']=no_v8((source/'codex-rs/Cargo.lock').read_bytes())
        expected=source_inventory((source/'codex-rs/core-plugins/src/startup_sync_tests.rs').read_text())
        require(expected==policy['tests'])
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
    except Exception:
        report['hold']=True  # Fixed error only, no raw exceptions.
    finally:
        FINALIZING=True
        report['owned_commands_cleanup_confirmed']=not owned.OWNERSHIP_UNCERTAIN and all(x['cleanup']['confirmed'] for x in records)
        try:
            require(not owned.OWNERSHIP_UNCERTAIN)
            recheck_cargo_config()
            require('source_before_sha256' in report and 'control_before' in report)
            after=snapshot(source,env,records,temp)
            require(sha(json.dumps(after,sort_keys=True).encode())==report['source_before_sha256'])
            changed=git(source,env,records,temp,'status','--porcelain','--untracked-files=all').decode().splitlines()
            require(set(changed)=={' M '+x['path'] for x in policy['source_files']})
            require(not git(control,env,records,temp,'status','--porcelain','--untracked-files=all'))
            require(git(control,env,records,temp,'rev-parse','HEAD').decode().strip()==event)
            require(git(control,env,records,temp,'rev-parse','HEAD^{tree}').decode().strip()==report['control_before']['tree'])
            require(git(source,env,records,temp,'rev-parse','HEAD').decode().strip()==BASE)
            require(git(source,env,records,temp,'rev-parse','HEAD^{tree}').decode().strip()==BASE_TREE)
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
        except Exception:report['hold']=True;report['cleanup_confirmed']=False
        report['commands']=records
        os.chdir(initial_cwd)
        (public/'receipt.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    return 0 if report['qualified'] else 125
if __name__=='__main__':sys.exit(main(*(Path(x).resolve() for x in sys.argv[1:])))
