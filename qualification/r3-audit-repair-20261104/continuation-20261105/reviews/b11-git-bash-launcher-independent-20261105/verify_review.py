#!/usr/bin/env python3
"""Static source/patch verification; does not execute either candidate CLI."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parent
WORK=ROOT.parents[1]
AUTHOR=WORK/'architecture-audit/b11-git-bash-launcher-20261105'
ORIG=WORK/'architecture-audit/b11-pr4884-ci-20261105/terminal/probe-127545539398/members/b11-token-mechanism-probe/acl-identity-counterfactual'

def pin(path):
    raw=path.read_bytes()
    return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),git_blob=hashlib.sha1(f'blob {len(raw)}\0'.encode()+raw).hexdigest())

def read(path):
    return json.loads(path.read_text())

def functions(text):
    lines=text.splitlines(keepends=True)
    return {n.name:''.join(lines[n.lineno-1:n.end_lineno]) for n in ast.parse(text).body if isinstance(n,ast.FunctionDef)}

def constants(text):
    return {n.targets[0].id:ast.dump(n.value,include_attributes=False) for n in ast.parse(text).body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name)}

def argv_lists(text):
    return {n.targets[0].id:n.value for n in ast.walk(ast.parse(text)) if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ['argv','positive_argv'] and isinstance(n.value,ast.List)}

def main():
    maps=read(AUTHOR/'source-map.json')
    assert len(maps)==3
    pairs={}
    for r in maps:
        for key,label in [('preimage_file','preimage'),('postimage_file','postimage')]:
            actual=pin(Path(r[key]))
            assert all(actual[k]==r[label][k] for k in ['bytes','sha256','git_blob'])
        pairs[r['path']]=(Path(r['preimage_file']).read_text(),Path(r['postimage_file']).read_text())
    commands=[]
    with tempfile.TemporaryDirectory(prefix='b11-git-bash-static-') as tmp:
        owned=Path(tmp)
        for r in maps:
            path=owned/r['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(Path(r['preimage_file']).read_bytes());path.chmod(0o644)
        def run(args):
            result=subprocess.run(args,cwd=owned,env={**os.environ,'GIT_OPTIONAL_LOCKS':'0'},capture_output=True,check=False)
            commands.append(dict(argv=args,cwd=str(owned),exit_code=result.returncode,stdout=result.stdout.decode(),stderr=result.stderr.decode()))
            assert result.returncode==0,commands[-1]
        run(['git','init','-q'])
        patch=str(AUTHOR/'full.patch')
        run(['git','-c','core.autocrlf=false','apply','--check',patch])
        run(['git','-c','core.autocrlf=false','apply',patch])
        for r in maps:assert (owned/r['path']).read_bytes()==Path(r['postimage_file']).read_bytes()
        run(['git','-c','core.autocrlf=false','apply','--reverse','--check',patch])
        run(['git','-c','core.autocrlf=false','apply','--reverse',patch])
        for r in maps:assert (owned/r['path']).read_bytes()==Path(r['preimage_file']).read_bytes()
    equality={}
    counter='.github/scripts/run_b11_acl_identity_counterfactual.py'
    helper='.github/scripts/run_b11_read_acl_readiness.py'
    for path in [counter,helper]:
        before,after=pairs[path]
        oldf,newf=functions(before),functions(after)
        assert set(newf)-set(oldf)==({'git_bash_record'} if path==counter else set())
        common=sorted(set(oldf)-{'main'})
        assert all(oldf[name]==newf[name] for name in common)
        assert before[before.index('    finally:\n',before.index('def main():')):]==after[after.index('    finally:\n',after.index('def main():')):]
        oldargs,newargs=argv_lists(before),argv_lists(after)
        assert set(oldargs)==set(newargs)
        for key in oldargs:
            assert ast.literal_eval(oldargs[key].elts[0])=='bash'
            assert ast.dump(newargs[key].elts[0],include_attributes=False)=="Subscript(value=Name(id='bash', ctx=Load()), slice=Constant(value='path'), ctx=Load())"
            assert ast.dump(ast.List(elts=oldargs[key].elts[1:],ctx=ast.Load()),include_attributes=False)==ast.dump(ast.List(elts=newargs[key].elts[1:],ctx=ast.Load()),include_attributes=False)
        oldc,newc=constants(before),constants(after)
        if path==helper:
            assert ast.literal_eval(next(n.value for n in ast.parse(after).body if isinstance(n,ast.Assign) and n.targets[0].id=='CONTROL_BLOB'))==maps[0]['postimage']['git_blob']
            oldc.pop('CONTROL_BLOB');newc.pop('CONTROL_BLOB')
        assert oldc==newc
        assert after.count('parser.add_argument("--bash-executable", type=Path, required=True)')==1
        equality[path]=dict(complete_non_main_functions_equal=common,argv_tails_equal=sorted(oldargs),entire_finally_and_terminal_tail_equal=True,original_constants_equal_except_helper_control_blob=True)
    oldw,neww=pairs['.github/workflows/hepta-windows-token-mechanism-probe.yml']
    split='      - name: Check the ACL identity counterfactual and restore its source'
    tail='      # The unchanged wrapper already retains this exact target on both failure'
    assert oldw[:oldw.index(split)]==neww[:neww.index(split)]
    assert oldw[oldw.index(tail):]==neww[neww.index(tail):]
    declaration='''          bash_executable="$BASH"
          if [[ "$bash_executable" != *.exe ]]; then
            bash_executable="${bash_executable}.exe"
          fi
          test -f "$bash_executable"
'''
    assert neww.count(declaration)==2
    old_argument='            --evidence "$(cygpath -w "$evidence")"'
    new_argument=old_argument+' '+chr(92)+'\n'+'            --bash-executable "$(cygpath -aw "$bash_executable")"'
    revert=neww.replace(declaration,'').replace(new_argument,old_argument)
    assert revert==oldw
    assert 'timeout-minutes: 120' in neww
    command=read(ORIG/'positive-01/command.json');terminal=read(ORIG/'positive-01/command-terminal.json');counter_terminal=read(ORIG/'counterfactual-terminal.json')
    console=(ORIG/'positive-01/console.log').read_bytes()
    assert command['argv'][0]=='bash' and terminal['exit_code']==1
    assert len(console)==504 and 'Windows Subsystem for Linux has no installed distributions.' in console.decode('utf-16-le')
    assert counter_terminal['status']=='INVALID_OR_NOT_RUN' and not counter_terminal['source_mutated'] and not counter_terminal['source_mutation_attempted']
    assert counter_terminal['positive_scopes']==[] and counter_terminal['physical_counterfactual_qualified'] is False
    assert (ORIG/'positive-01/source-before.json').read_bytes()==(ORIG/'positive-01/source-after.json').read_bytes()
    originals=[pin(ORIG/n) for n in ['positive-01/command.json','positive-01/command-terminal.json','positive-01/console.log','positive-01/source-before.json','positive-01/source-after.json','counterfactual-terminal.json']]
    report=dict(schema='b11-git-bash-independent-static-verification/v1',result='STATIC_ACCEPT',native_or_ref_execution=False,
        source_map=pin(AUTHOR/'source-map.json'),patch=pin(AUTHOR/'full.patch'),source_identity=maps,
        isolated_git_forward_reverse=commands,three_postimages_and_three_preimages_exact=True,structural_equality=equality,
        workflow_original_whole_step_and_upload_tail_equal=True,workflow_only_two_explicit_bash_arguments_and_derivation_blocks=True,
        native8_originals=originals,native8_observed=dict(job_id='127545539398',run_id='42113095723',command=command,terminal=terminal,counterfactual_terminal=counter_terminal,console_decoded=console.decode('utf-16-le')),
        mechanism_review=[
            'Each existing workflow step derives its current shell executable from $BASH, adds the Windows .exe suffix when the MSYS path omits it, verifies the file and converts that same path with cygpath -aw. Both values remain quoted.',
            'Each Python CLI requires --bash-executable. The shared validator accepts only a native-Windows absolute existing bash.exe file and records its complete bytes/SHA256/Git blob before running a test subprocess.',
            'All three actual subprocess argv[0] values use that recorded absolute path. Every argv element after0, cwd, environment construction, output file and return-code handling is unchanged. There is no PATH search fallback or WSL installation.',
            'Helper load_control pins the exact new counterfactual script and imports definitions under a non-main module name. Its ten other source pins and all guards stay unchanged.',
            'Original whole library status remains authoritative; four exact positives, sole precise physical negative, pre-restore source/index/lock checks, exact owned restoration and the unfiltered helper target are unchanged.',
            'Native8 stopped before its first exact test due to WSL shell resolution, with unchanged source. This source repair is not proof that a new exact positive/negative/helper scope has executed.'
        ],limits=['No Windows CLI or native test was run by this review. Only cloud Git apply/check/reverse and AST/source identity comparison.','No product Rust code, scope, original timeout120min, retry, oracle, collector, original failure or ref changes.','The original full library147P7F2I remains independent; B11 stays OPEN pending its actual product gates.'])
    out=ROOT/'independent-review.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(pin(out)))

if __name__=='__main__':
    main()
