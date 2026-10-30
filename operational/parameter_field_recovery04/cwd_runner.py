"""Registered working-directory isolation around unchanged execution modules.

Torch may attach relative pseudo filenames to generated modules. Resolving such
names from the repository would incorrectly classify them as missing repository
sources. Children use an empty directory outside the source tree; all numerical
arguments, original admission checks, source checks and execution gates remain.
The analysis child additionally enables the explicitly registered historical
cost adapter; it never substitutes a missing historical preflight receipt.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
PREFIX='experiments.parameter_field_fullstudy_20261029.'
WORKERS={PREFIX+'run_v2',PREFIX+'architecture_run_v2',PREFIX+'endpoint_v2'}
ANALYSIS=PREFIX+'analysis_launch_v2'


def require(value,message):
    if not value:
        raise ValueError(message)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def descriptor(path):
    path=Path(path).absolute()
    return {'path':str(path),'bytes':path.stat().st_size,'sha256':digest(path)}


def write_new(path,value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as stream:
        json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def flags(argv):
    result={}
    i=0
    while i<len(argv):
        key=argv[i]
        require(key.startswith('--') and key not in result,'Invalid or duplicated original flag')
        if key in ('--execute','--child','--resume-admission','--recover-zero-work'):
            result[key]=True
            i+=1
        else:
            require(i+1<len(argv) and not argv[i+1].startswith('--'),'Missing original flag value')
            result[key]=argv[i+1]
            i+=2
    return result


def identity(pid):
    try:
        value=Path(f'/proc/{pid}/stat').read_text()
        fields=value[value.rfind(')')+2:].split()
        return {'pid':pid,'process_group':int(fields[2]),'session':int(fields[3]),
                'start_ticks':int(fields[19])}
    except (OSError,ValueError,IndexError):
        return None


def empty_directory(policy):
    source=Path(policy['source_root']).resolve()
    cwd=Path(policy['empty_cwd']).resolve()
    require(cwd.is_dir() and not cwd.is_relative_to(source),'Worker cwd must exist outside source')
    require(not any(cwd.iterdir()),'Registered worker cwd is not empty')
    return cwd


def validate_policy(path,expected):
    require(digest(path)==expected,'Cwd policy bytes differ')
    policy=json.loads(Path(path).read_bytes())
    require(policy['schema']=='hepta.fullstudy.cwd-policy.4'
            and policy['execution_episode']=='execution04_durable_20261030',
            'Unregistered cwd policy')
    require(Path(policy['source_root']).resolve()==ROOT,'Wrong source root')
    require(os.path.abspath(sys.executable)==policy['python'],'Use the registered venv interpreter without resolving its symlink')
    require(set(policy['worker_modules'])==WORKERS and policy['analysis_module']==ANALYSIS,
            'Worker module population differs')
    require(Path(policy['raw_root']).resolve()!=ROOT,'Raw output cannot be source root')
    for name,expected_sha in policy['source_files'].items():
        target=ROOT/name
        require(not Path(name).is_absolute() and '..' not in Path(name).parts
                and target.resolve().is_relative_to(ROOT) and digest(target)==expected_sha,
                'Cwd adapter source binding differs: '+name)
    require(descriptor(policy['amendment']['path'])==policy['amendment'],'Cwd amendment binding differs')
    empty_directory(policy)
    return policy


class CwdSubprocess:
    """Proxy only the two known original Popen sites; forward all other APIs."""
    def __init__(self,original,policy,policy_path,policy_sha,kind):
        self.original=original
        self.policy=policy
        self.policy_path=str(Path(policy_path).absolute())
        self.policy_sha=policy_sha
        self.kind=kind

    def __getattr__(self,name):
        return getattr(self.original,name)

    def Popen(self,argv,*args,**kwargs):
        require(not args and isinstance(argv,list) and all(isinstance(x,str) for x in argv),
                'Unexpected original Popen signature')
        require(len(argv)>=4 and argv[1:3]==['-B','-m'],'Unexpected original child invocation')
        require(os.path.abspath(argv[0])==self.policy['python'],'Child interpreter differs')
        require(Path(kwargs.get('cwd','')).resolve()==Path(self.policy['source_root']).resolve(),
                'Unexpected original requested cwd')
        require(not kwargs.get('shell',False),'No shell worker execution')
        original_flags=flags(argv[4:])
        require(Path(original_flags['--root']).resolve()==Path(self.policy['raw_root']).resolve(),
                'Child raw root differs')
        require(original_flags['--amendment']==self.policy['amendment']['path']
                and original_flags['--amendment-sha256']==self.policy['amendment']['sha256'],
                'Child amendment differs')
        effective=list(argv)
        module=argv[3]
        if self.kind=='controller':
            require(module in WORKERS,'Unexpected controller worker module')
            if module.endswith('.architecture_run_v2'):
                token='C'
            elif module.endswith('.endpoint_v2'):
                token=original_flags['--phase']+'_endpoint'
            else:
                phase=original_flags['--phase']
                token='W' if phase=='W' else phase+'-'+original_flags['--seed']
        else:
            require(module==ANALYSIS and original_flags.get('--child') is True,
                    'Unexpected analysis child module')
            token='ANALYSIS'
            effective=[argv[0],'-B',str(Path(__file__).resolve()),'--kind','analysis',
                '--policy',self.policy_path,'--expected-policy-sha256',self.policy_sha,'--',*argv[4:]]
        require(token in {'C','W','ANALYSIS','A_endpoint','B_endpoint','C_endpoint'}
                or token in {f'{p}-{s}' for p in ('A','B','R') for s in (17,29,43)},
                'Unexpected job identity')
        cwd=empty_directory(self.policy)
        env=dict(kwargs.get('env',os.environ))
        env['PYTHONPATH']=self.policy['source_root']
        env['PYTHONDONTWRITEBYTECODE']='1'
        changed=dict(kwargs,cwd=str(cwd),env=env)
        destination=Path(self.policy['ops_root'])/'cwd_launches'/token
        destination.mkdir(parents=True,exist_ok=False)
        record={'schema':'hepta.fullstudy.cwd-launch.4','job':token,
            'at_utc':datetime.now(timezone.utc).isoformat(),'policy_sha256':self.policy_sha,
            'requested_argv':argv,'effective_argv':effective,
            'requested_cwd':str(kwargs['cwd']),'effective_cwd':str(cwd),
            'numerical_arguments_changed':False,'environment_values_disclosed':False}
        write_new(destination/'REQUEST.json',record)
        try:
            process=self.original.Popen(effective,**changed)
        except BaseException as error:
            write_new(destination/'SPAWN_FAILED.json',{'error_type':type(error).__name__,
                'message':str(error),'scientific_execution_started_unknown':True})
            raise
        try:
            write_new(destination/'STARTED.json',{**record,'pid':process.pid,
                'observed_identity':identity(process.pid)})
        except BaseException:
            # The caller has not received this handle and cannot register or
            # reap it. Stop only the child just created by this Popen call.
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            raise
        return process


@contextmanager
def isolated_spawns(module,policy,path,expected,kind):
    original=module.subprocess
    module.subprocess=CwdSubprocess(original,policy,path,expected,kind)
    try:
        yield
    finally:
        module.subprocess=original


def main():
    sys.dont_write_bytecode=True
    parser=argparse.ArgumentParser()
    parser.add_argument('--kind',required=True,choices=('controller','analysis'))
    parser.add_argument('--policy',required=True)
    parser.add_argument('--expected-policy-sha256',required=True)
    parser.add_argument('original_arguments',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    require(args.original_arguments and args.original_arguments[0]=='--','Explicit original-argument boundary is required')
    original=args.original_arguments[1:]
    policy=validate_policy(args.policy,args.expected_policy_sha256)
    require(Path.cwd().resolve()==empty_directory(policy),'Adapter must itself run from the registered empty cwd')
    parsed=flags(original)
    require(Path(parsed['--root']).resolve()==Path(policy['raw_root']).resolve(),'Adapter root differs')
    require(parsed['--amendment']==policy['amendment']['path']
            and parsed['--amendment-sha256']==policy['amendment']['sha256'],'Adapter amendment differs')
    sys.path.insert(0,str(ROOT))
    old_argv=sys.argv
    try:
        if args.kind=='controller':
            core=importlib.import_module(PREFIX+'launch_v2')
            envelope=importlib.import_module(PREFIX+'controller_envelope_v2')
            sys.argv=[envelope.__name__,*original]
            with isolated_spawns(core,policy,args.policy,args.expected_policy_sha256,'controller'):
                envelope.main()
        else:
            module=importlib.import_module(ANALYSIS)
            sys.argv=[module.__name__,*original]
            if parsed.get('--child'):
                from operational.parameter_field_recovery04.historical_costs import apply_cost_adapter
                inputs=descriptor(parsed['--inputs'])
                require(inputs['sha256']==parsed['--expected-sha256'],'Analysis inputs differ')
                with apply_cost_adapter(inputs):
                    module.main()
            else:
                with isolated_spawns(module,policy,args.policy,args.expected_policy_sha256,'analysis'):
                    module.main()
    finally:
        sys.argv=old_argv


if __name__=='__main__':
    main()
