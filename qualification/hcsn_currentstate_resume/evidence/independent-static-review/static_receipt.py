"""Read source text/AST and hashes only. Never import target modules."""
import ast
import hashlib
import json
from pathlib import Path

ROOT=Path('/workspace/scratch/c06d659c1e72/currentstate-resume-raw')
OLD=Path('/workspace/scratch/c06d659c1e72/currentstate-packets')
OUT=Path(__file__).resolve().parent

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    oldfreeze=json.loads((OLD/'FREEZE.json').read_text())
    newpaths=[f'qualification/hcsn_currentstate_resume/{x}' for x in ('run_saved.py','PLAN.json','SPEC.md')]
    allpaths=list(oldfreeze['source_sha256'])+newpaths
    inputs=[f'qualification/hcsn_currentstate/evidence/currentstate-attempt001/{name}' for name in
            ('mixed.resume.json','rare.resume.json','mixed.final.json','rare.final.json','ROWS.json')]
    before={name:sha(ROOT/name) for name in allpaths}
    input_before={name:sha(ROOT/name) for name in inputs}
    assert {name:before[name] for name in oldfreeze['source_sha256']} == oldfreeze['source_sha256']
    for name in inputs:
        basename=Path(name).name
        assert sha(ROOT/name)==sha(OLD/'evidence/currentstate-attempt001'/basename)
    tree=ast.parse((ROOT/newpaths[0]).read_text())
    imports=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.Import): imports.extend(x.name for x in node.names)
        if isinstance(node,ast.ImportFrom): imports.append(node.module)
    assert not any('reference' in x or 'audit' in x for x in imports)
    assert before[newpaths[0]]=='63cb7b8e3ef5772d4dd1e0b28b55a09f4848090a5b670699513cefe65d662b01'
    after={name:sha(ROOT/name) for name in allpaths}
    input_after={name:sha(ROOT/name) for name in inputs}
    assert before==after and input_before==input_after
    result={
        'identity':'currentstate-saved-continuation-fullraw-static-review-v1',
        'new_stage_identity':'currentstate-saved-continuation-fullraw-attempt001',
        'source_sha256_before':before,'source_sha256_after':after,
        'input_sha256_before':input_before,'input_sha256_after':input_after,
        'old_seven_files_equal_de3d937_source_freeze':True,
        'five_inputs_equal_independently_reviewed_a9a7fc_raw':True,
        'imports_ast_only':imports,
        'new_numerical_executions':0,'new_candidate_calls':0,'new_reference_calls':0,'new_expm_calls':0,
        'new_quadratures':0,'initial_trajectory_replays':0,'old72_replays':0,
        'blocking_findings':[],
        'static_checks':[
            'Each trajectory loads the retained exact .201 state; fixture constructs only physics and an unused initial object, which is never advanced.',
            'Warm and fresh-process cold schedules .28/.36 each write INPUT, STATE-028, STATE-036 and full observation vectors. Coarse writes INPUT and STATE-036 and full observation vectors.',
            'Warm/cold INPUT, .28 and .36 raw files are compared directly with read_bytes equality, alongside both SHA256s.',
            'Coarse .36 full vectors are retained; comparison uses each active/upper/M/H/A/R/Z coordinate.',
            'New warm .36 raw is directly compared with retained old warm final raw as a diagnostic. This does not create or claim the missing old cold raw.',
            'Original ROWS reference64 vectors are read only; no reference module import or reference evaluation.',
            'All outputs use fresh exist_ok=False directories; source and five immutable inputs are read only.',
            'Six fixed trajectory ledgers use maximum=100 with inherited 20-segment cap: fixed upper bounds 600 exponentials and 120 segments.',
            'Parent CPU limits20/21 and two children5/6 give total hard CPU upper bound33; each process RLIMIT_AS536870912 bytes.',
            'Parent and child ru_maxrss fields are distinguished and combined peak RSS is explicitly unmeasured.',
            'The unchanged1e-12 relative floor uses null below floor; finite absolute tolerance remains2e-11; HOLD_NO_GO/all_closed=false.'
        ],
        'pre_execution_requirements':[
            'Git checkpoint this exact ten-source roster and five-input roster; driver guarded() trusts the manifest membership rather than asserting a mandatory roster.',
            'Freeze.source_commit and identity must name the new stage; all hashes must equal the reviewed roster.',
            'Actual launcher must apply GNU timeout -s KILL45s and OPENBLAS_NUM_THREADS=1/OMP_NUM_THREADS=1. A SPEC statement alone is not a launch receipt.'
        ],
        'limitations':[
            'This is a static go-ahead for a new saved-state continuation only; it reports no numerical result.',
            'Guarded comparisons do not reconstruct absent historical coarse vectors or cold snapshots.',
            'CLI/freezefile roster and external wall guard require separate pre-execution roster/launcher verification.'
        ],
        'conclusion':'no_static_blocker_conditional_on_exact_complete_git_freeze_and_guarded_launcher',
        'admission':'HOLD_NO_GO','all_closed':False,
        'reviewer_source_sha256':sha(Path(__file__))
    }
    raw=(json.dumps(result,indent=2)+'\n').encode();(OUT/'REVIEW.json').write_bytes(raw)
    print(json.dumps({'static_only':True,'source_files':len(before),'input_files':len(input_before),
                      'source_unchanged':before==after,'inputs_unchanged':input_before==input_after,
                      'candidate_calls':0,'reference_calls':0,'expm_calls':0,'blocking_findings':[],
                      'review_sha256':hashlib.sha256(raw).hexdigest()}))

if __name__=='__main__':main()
