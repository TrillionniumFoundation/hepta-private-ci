"""Read/AST/hash only: final static resource-guard review, no target imports."""
import ast
import hashlib
import json
from pathlib import Path

ROOT=Path('/workspace/scratch/c06d659c1e72/currentstate-resume-raw')
OUT=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def blob(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

def main():
    freeze=json.loads((ROOT/'FREEZE.json').read_text())
    old=json.loads((OUT/'FREEZE-b7280e.json').read_text())
    previous=json.loads((OUT/'REVIEW.json').read_text())
    git=json.loads((OUT/'GIT_SOURCE_9e9dc3f.json').read_text())
    assert freeze['source_commit']==git['commit']=='9e9dc3fb698ce53046790e09497420eaaee8df5f'
    assert freeze['identity']=='currentstate-saved-continuation-fullraw-attempt001'
    assert set(freeze['source_sha256'])==set(old['source_sha256']) and len(freeze['source_sha256'])==10
    assert freeze['input_sha256']==old['input_sha256']==previous['input_sha256_before']
    assert len(freeze['input_sha256'])==5
    before={p:sha(ROOT/p) for p in freeze['source_sha256']}
    inputs_before={p:sha(ROOT/p) for p in freeze['input_sha256']}
    assert before==freeze['source_sha256'] and inputs_before==freeze['input_sha256']
    for p in before:
        if '/hcsn_currentstate/' in p:assert before[p]==old['source_sha256'][p]
    for item in json.loads(git['retrieved']['content']):
        path=ROOT/'qualification/hcsn_currentstate_resume'/item['name']
        raw=path.read_bytes(); assert len(raw)==item['size'] and blob(raw)==item['sha']
    src=(ROOT/'qualification/hcsn_currentstate_resume/run_saved.py').read_text()
    ast.parse(src)
    assert 'cmd = ["/usr/bin/prlimit", "--cpu=5:6", "--as=536870912:536870912", "--",' in src
    spec=(ROOT/'qualification/hcsn_currentstate_resume/SPEC.md').read_text()
    command='timeout -s KILL 45s env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 /usr/bin/prlimit --cpu=20:21 --as=536870912:536870912 -- python -m qualification.hcsn_currentstate_resume.run_saved --freeze FREEZE.json --output evidence/saved-fullraw-attempt001'
    assert command in spec
    plan=json.loads((ROOT/'qualification/hcsn_currentstate_resume/PLAN.json').read_text())
    assert plan['fixed_roster_CPU_hard_upper_bound']==21+2*6==33
    assert plan['max_expm_global_fixed_roster']==6*100==600
    assert plan['max_segments_global_fixed_roster']==6*20==120
    after={p:sha(ROOT/p) for p in before}
    inputs_after={p:sha(ROOT/p) for p in inputs_before}
    assert before==after and inputs_before==inputs_after
    rawfreeze=(ROOT/'FREEZE.json').read_bytes();(OUT/'FREEZE-9e9dc3f.json').write_bytes(rawfreeze)
    result={
      'identity':'currentstate-saved-continuation-fullraw-final-static-review-v2',
      'source_freeze_commit':freeze['source_commit'],'source_freeze_sha256':hashlib.sha256(rawfreeze).hexdigest(),
      'source_sha256_before':before,'source_sha256_after':after,
      'input_sha256_before':inputs_before,'input_sha256_after':inputs_after,
      'roster_source_count':10,'roster_input_count':5,
      'old_seven_frozen_bytes_unchanged':True,'five_input_original_bytes_unchanged':True,
      'new_three_source_files_match_remote_git_blobs':True,
      'supersedes_blocker':'ADDENDUM-BLOCKER.json: 63cb7b8e child imported third-party modules before installing CPU limit',
      'resource_blocker_closed':True,
      'closure':'Child prlimit5/6 +AS runs before Python exec; documented parent prlimit20/21 +AS likewise precedes Python. External GNU timeout45 and BLAS/OMP1 remain required in the actual launch.',
      'blocking_findings':[],
      'fullraw_checks':previous['static_checks'][:7],
      'fixed_limits':{'parent_CPU_soft_hard':[20,21],'child_CPU_soft_hard':[5,6],
                      'children':2,'total_Python_CPU_hard_bound':33,'expm':600,'segments':120,
                      'wall_guard_seconds':45,'per_process_RLIMIT_AS':536870912},
      'required_launcher':command,
      'new_numerical_executions':0,'new_candidate_calls':0,'new_reference_calls':0,'new_expm_calls':0,
      'new_quadratures':0,'initial_trajectory_replays':0,'old72_replays':0,
      'conclusion':'no_static_blocker_for_the_single_new_saved_state_continuation_under_the_frozen_launcher',
      'limitations':['No numerical result is asserted by this static review.',
                     'This new stage cannot restore missing historical old cold/coarse raw.',
                     'Full network, continuum, gradients, training and production checkpoint qualification remain outside scope.'],
      'admission':'HOLD_NO_GO','all_closed':False,'reviewer_source_sha256':sha(Path(__file__))
    }
    raw=(json.dumps(result,indent=2)+'\n').encode();(OUT/'FINAL-REVIEW.json').write_bytes(raw)
    print(json.dumps({'static_only':True,'source_files':10,'inputs':5,'hashes_unchanged':True,
                      'resource_blocker_closed':True,'blocking_findings':[],
                      'new_candidate_calls':0,'new_reference_calls':0,'new_expm_calls':0,
                      'review_sha256':hashlib.sha256(raw).hexdigest()}))

if __name__=='__main__':main()
