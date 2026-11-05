"""A one-file source-only repair; no wrapper, Bazel, native or test execution."""
from pathlib import Path
import hashlib
import json
import difflib

ROOT=Path(__file__).resolve().parent
FIXED=Path('research-audit/published-0e139-ci-20261105/terminal/mac-arm-native-wrapper-127089468398').resolve()
PRE=FIXED/'fixed-source'/'run-bazel-ci.sh.source.txt'
TESTS=FIXED/'fixed-source'/'test_run_bazel_ci.py.source.txt'
PATH='.github/scripts/run-bazel-ci.sh'
def identity(data):
 return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
         'blob':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()}
def record(path):return {'path':str(path),**identity(path.read_bytes())}
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
old=PRE.read_text();assert identity(old.encode())['blob']=='204c0ac2481f70cc977f777eb2299b740f7ddc17'
assert identity(TESTS.read_bytes())['blob']=='ed8276016bcf8ff7738c1769907ae1c145438add'
old_scan='  local copy_next=0\n  for arg in "${bazel_args[@]}" "${post_config_bazel_args[@]}"; do\n'
new_scan='''  local -a bazel_log_lookup_args=("${bazel_args[@]}")
  if (( ${#post_config_bazel_args[@]} > 0 )); then
    bazel_log_lookup_args+=("${post_config_bazel_args[@]}")
  fi
  local copy_next=0
  for arg in "${bazel_log_lookup_args[@]}"; do
'''
assert old.count(old_scan)==1
start=old.index('  for target in "${failed_targets[@]}"; do\n')
end=old.index('\n  # Preserve complete existing shard/attempt logs',start)
old_tail=old[start:end]
assert old_tail.endswith('  done\n')
new_tail='  if (( ${#failed_targets[@]} > 0 )); then\n'+''.join('  '+line if line.strip() else line for line in old_tail.splitlines(True))+'  fi\n'
new=old.replace(old_scan,new_scan).replace(old_tail,new_tail)
assert new.replace(new_scan,old_scan).replace(new_tail,old_tail)==old
pre=ROOT/'preimage'/PATH;post=ROOT/'candidate'/PATH
pre.parent.mkdir(parents=True,exist_ok=True);post.parent.mkdir(parents=True,exist_ok=True)
pre.write_text(old);post.write_text(new)
patch='diff --git a/'+PATH+' b/'+PATH+'\nindex '+identity(old.encode())['blob']+'..'+identity(new.encode())['blob']+' 100755\n'
patch+=''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+PATH,tofile='b/'+PATH))
(ROOT/'macos-empty-array.patch').write_text(patch)
occurrences=[]
import re
for lineno,line in enumerate(old.splitlines(),1):
 for match in re.finditer(r'\$\{([^}]*\[(?:@|\*)\][^}]*)\}',line):
  occurrences.append({'line':lineno,'expression':match.group(0),'source':line})
proof={
 'schema':'hepta-macos-bash-empty-array-source-preservation-v1',
 'inverse_two_transformations_reconstruct_original_exactly':True,
 'tail_body_unchanged_except_two_space_indentation':True,
 'lookup_sequence':'bazel_args followed by post_config_bazel_args; optional empty post array contributes zero elements, with all original quoting and element order preserved.',
 'new_bash_features':False,'full_script_array_expansion_inventory':occurrences,
 'array_safety':[
  {'array':'bazel_startup_args','status':'existing length guard before value expansion'},
  {'array':'failed_targets','status':'new length guard protects tail loop; collector printf already has an existing positive-length guard'},
  {'array':'post_config_bazel_args','status':'new lookup-copy append guard; original actual-run append already guarded'},
  {'array':'bazel_args / bazel_targets','status':'both are validated nonempty before these functions or their value expansions execute'},
  {'array':'bazel_info_args','status':'constructed with info then config, always nonempty'},
  {'array':'bazel_run_args','status':'initialized from validated nonempty args, then config appended; nonempty before invocation or archival printf'},
  {'array':'required_windows_action_env_vars / windows_action_env_vars','status':'fixed nonempty literals'},
  {'array':'missing_windows_action_env_vars','status':'existing length guard before [*] value expansion'},
 ],
 'unchanged':{'test_file':record(TESTS),'original_test_definitions_and_assertions':True,'collector_source':True,
              'actual_bazel_run_block':old[old.index('bazel_console_log="$(mktemp)"'):]==new[new.index('bazel_console_log="$(mktemp)"'):],
              'retention_and_collection_blocks':old[old.index('  # Preserve complete existing shard/attempt logs'):old.index('\nprint_bazel_action_failure_summary()')]==new[new.index('  # Preserve complete existing shard/attempt logs'):new.index('\nprint_bazel_action_failure_summary()')],
              'filters_retries_deadlines_targets_exit_status':True},
 'native_or_original57_execution':False,
}
write(ROOT/'preservation.json',proof)
manifest={
 'schema':'hepta-macos-bash-empty-array-repair-v1','status':'STATIC_CANDIDATE_NATIVE_AND_ORIGINAL_57_PENDING',
 'repository':'TrillionniumFoundation/hepta-private-ci','base_head':'0e139b599f0fe451f80fb7db4b2913bb9c679dce',
 'base_tree':'091e659e0da6602299fd14cfa93889191405edd8',
 'files':[{'path':PATH,'mode':'100755','preimage':identity(old.encode()),'postimage':identity(new.encode())}],
 'patch':record(ROOT/'macos-empty-array.patch'),
 'original_failure':{'job_id':127089468398,'platform':'macOS ARM workflow job; test fixture intentionally sets RUNNER_OS=Windows while using the host Bash',
  'raw':record(FIXED/'job.log'),'failure_block':record(FIXED/'original-three-failures-block.log.txt'),
  'original_command':"python -m unittest discover -s .github/scripts -p 'test_run_bazel*.py'",
  'tests':57,'failures':3,'duration_seconds':5.184,
  'cases':['test_run_bazel_ci.RunBazelCiIntegrationTest.test_conflicting_selected_summaries_do_not_read_existing_logs',
           'test_run_bazel_ci.RunBazelCiIntegrationTest.test_missing_selected_logs_preserve_success_and_failure_status (original_status=0)',
           'test_run_bazel_ci.RunBazelCiIntegrationTest.test_success_retains_reported_targets_and_preserves_status_scope'],
  'observed_stderr':'run-bazel-ci.sh: line 98: failed_targets[@]: unbound variable',
  'line_scope':'98 is the function definition. The unguarded value expansion is the tail loop at original line 163, after an empty failed_targets array passes the retained-target path.',
  'bash_version_observed':None},
 'cause':{
  'observed':'An empty failed-target list with nonempty selected-retention results reaches an unconditional array value expansion under nounset. Collection stops before the selected-target manifest is written.',
  'minimal_repair':'Only iterate the failed-target tail loop when its original array length is positive. Keep selected-target collection outside this guard.',
  'same_problem_full_context':'The output-root lookup loop also directly expands potentially empty post_config_bazel_args. Build its same ordered input from the already-nonempty bazel_args and append post-config entries only when nonempty.',
  'latent_scope':'The optional-post-config path is a directly reachable static hazard, not an additional reproduced failure. The three failed wrapper tests inherit Windows/repo-cache post flags from their common setUp.',
  'no_version_inference':'The original log does not print Bash --version; no exact Bash version or new platform reproduction is claimed.'},
 'preservation':record(ROOT/'preservation.json'),
 'pending_gates':['Root/independent static review of the one-file patch.','Original complete 57-test Python command using the unchanged tests; record actual host/Bash version without labeling other hosts as macOS qualification.','Fresh original macOS hosted workflow gate; Windows original 57-test scope remains unchanged.'],
 'not_changed':['set -euo pipefail','collector Python and its tests','success/FLAKY/SKIP/cache distinctions','retention allowlist','Bazel arguments and target order','test filters/retries/deadlines','failed tail200','selected/failure artifact provenance','original Bazel exit status'],
 'native_executed':False,'refs_changed':False,
}
mode_map=Path('hepta-audit-fourth/inputs/app-epoch2-decoded/source-map.json').resolve()
mode_entry=next(e for e in json.loads(mode_map.read_text())['files'] if e['path']==PATH)
assert mode_entry['mode']=='100755' and mode_entry['git_blob']==identity(old.encode())['blob']
manifest['mode_evidence']={'source_map':record(mode_map),'source_tree':'f8251e1d14fa8524ab469281296cd4cf708f173c',
                          'entry':mode_entry,'scope':'Inherited executable mode; no mode change is proposed. Exact current source bytes are independently pinned at 0e139.'}
if (ROOT/'static-verification.json').exists():
 manifest['isolated_static_verification']=record(ROOT/'static-verification.json')
 manifest['static_verification_scope']='Six isolated cloud Git/syntax commands, all exit zero. No original CI test, wrapper invocation, Bazel, or native-host execution.'
write(ROOT/'repair-manifest.json',manifest)
print(json.dumps({'source':manifest['files'][0],'patch':manifest['patch'],'manifest':record(ROOT/'repair-manifest.json')},indent=2))
