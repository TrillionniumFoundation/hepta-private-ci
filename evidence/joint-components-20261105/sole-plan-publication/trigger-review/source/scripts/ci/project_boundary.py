#!/usr/bin/env python3
"""Read-only project/branch/source boundary; never changes remote policy."""
import json, pathlib, re, subprocess, sys, tomllib
ROOT=pathlib.Path(__file__).resolve().parents[2]
# GitHub checkout uses the HTTPS URL without .git. Keep an exact allowlist;
# do not normalize foreign hosts, repository suffixes, credentials or URL extras.
CANONICAL_ORIGINS=frozenset({
    'https://github.com/TrillionniumFoundation/Trillionnium-Chain',
    'https://github.com/TrillionniumFoundation/Trillionnium-Chain.git',
    'git@github.com:TrillionniumFoundation/Trillionnium-Chain.git',
})
def require(ok,msg):
    if not ok: raise ValueError(msg)
def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
def source(path,mode):
    if mode=='--staged': return git('show',':'+path)
    if mode=='--push': return git('show','HEAD:'+path)
    return (ROOT/path).read_text()
def check(mode):
    require(mode in {'--dev','--audit','--staged','--push'},'unsupported mode')
    p=json.loads(source('PROJECT_BOUNDARY.json',mode))
    require(source('PROJECT_ID',mode).strip()=='trillionnium-chain','project id mismatch')
    require(p['canonical_repository']=='TrillionniumFoundation/Trillionnium-Chain','repository mismatch')
    origin=git('remote','get-url','origin')
    require(origin in CANONICAL_ORIGINS,'origin mismatch')
    require(p['lane']=='chain-consensus','lane mismatch')
    require(p['consensus']['production_consensus_activation'] is False,'activation changed')
    require(p['consensus']['development_target']=='pon-nakamoto-v1','target mismatch')
    review=p['repository']
    require(review['required_pull_request_reviews']==0 and review['require_code_owner_review'] is False and review['require_last_push_approval'] is False,'review contract changed')
    require(review['block_force_push'] is True and review['block_branch_deletion'] is True,'remote preservation contract changed')
    branch=git('branch','--show-current')
    if mode!='--audit':
        require(branch not in p['branch']['protected'] and re.fullmatch(p['branch']['development_regex'],branch) is not None,'not an allowed development branch')
    members=tomllib.loads(source('trillionnium/Cargo.toml',mode))['workspace']['members']
    inventory=json.loads(source('config/portability-inventory-v1.json',mode))
    require(set(members)=={'crates/'+r['package'] for r in inventory['packages']},'workspace/source inventory mismatch')
    for member in members:
        manifest='trillionnium/'+member+'/Cargo.toml'
        data=tomllib.loads(source(manifest,mode))
        tables=[data.get(k,{}) for k in ['dependencies','dev-dependencies','build-dependencies']]
        for target in data.get('target',{}).values():
            tables.extend(target.get(k,{}) for k in ['dependencies','dev-dependencies','build-dependencies'])
        for table in tables:
            for dep in table.values():
                if isinstance(dep,dict) and 'path' in dep:
                    resolved=(ROOT/manifest).parent.joinpath(dep['path']).resolve()
                    require(resolved.is_relative_to(ROOT/'trillionnium/crates'),'external path dependency')
                    require(resolved.is_dir(),'missing path dependency')
    if mode=='--push':
        require(sys.argv[2]=='origin' and sys.argv[3] in CANONICAL_ORIGINS,'push target mismatch')
        updates=sys.stdin.read().splitlines()
        require(bool(updates),'no exact push updates supplied')
        for line in updates:
            local,sha,remote,old=line.split()
            require(sha==git('rev-parse','HEAD'),'only checked-out HEAD can be pushed')
            require(remote.startswith('refs/heads/') and re.fullmatch(p['branch']['development_regex'],remote.removeprefix('refs/heads/')) is not None,'protected/invalid remote branch')
            if old!='0'*40:
                require(subprocess.run(['git','merge-base','--is-ancestor',old,sha],cwd=ROOT).returncode==0,'non-fast-forward push rejected')
            else:
                require(remote == 'refs/heads/'+branch, 'new continuation must be the checked-out branch')
    print(json.dumps({'result':'PASS','mode':mode,'project':'trillionnium-chain','packages':len(members),'branch':branch,'remote_policy_mutated':False}))
if __name__=='__main__':
    try: check(sys.argv[1])
    except (ValueError,KeyError,OSError,subprocess.CalledProcessError) as e:
        print('project boundary failed: '+str(e),file=sys.stderr);sys.exit(2)
