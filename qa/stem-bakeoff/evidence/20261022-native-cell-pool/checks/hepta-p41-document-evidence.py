"""Index the completed P41 run without altering its report or measurements."""
import hashlib,json,subprocess
from pathlib import Path

root=Path('/tmp/hepta-p41-native-pools-f8855a7')
repo=Path('/tmp/hepta-p41-pool')
sha=lambda raw:hashlib.sha256(raw).hexdigest()
encode=lambda value:(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
raw=(root/'report.json').read_bytes()
assert sha(raw)=='f4ed9cce8f33cb26764933cbc2b950239c9b7e2f8360410b051467a50ca8abe0'
report=json.loads(raw)
binary=Path('/tmp/hepta-p40-target/release/examples/native_task_head_pool').read_bytes()
assert sha(binary)==report['native_binary_sha256']
with (root/'native_task_head_pool.bin').open('xb') as stream:stream.write(binary)
assert sha(Path('/tmp/hepta-p40-target/release/examples/native_task_head').read_bytes())=='86ff023ed2be26b85b9ad47d7f2efb5f0e91a0cb41b7c9bf9df4bef4351eea90'
paths={
 'crosscheck':'/tmp/hepta-p41-native-pools-crosscheck.json',
 'crosscheck_source':'/tmp/hepta-p41-verify-results.py',
 'python_tests':'/tmp/hepta-p41-python-tests-final.log',
 'rust_tests':'/tmp/hepta-p41-neuron-tests-final.log',
 'clippy':'/tmp/hepta-p41-scoped-clippy-check.log',
 'just_fix_environment_block':'/tmp/hepta-p41-scoped-clippy.log',
 'clean_release_build':'/tmp/hepta-p41-clean-release-build.log',
 'initial_release_build':'/tmp/hepta-p41-pool-release-build.log',
 'native_fixture_probe':'/tmp/hepta-p41-driver-probe/receipt.json',
 'native_fixture_probe_source':'/tmp/hepta-p41-driver-probe.py',
 'replay_stdout':'/tmp/hepta-p41-pool-replay.log'}
proofs={key:{'path':path,'sha256':sha(Path(path).read_bytes()),'bytes':Path(path).stat().st_size}
        for key,path in paths.items()}
assert 'Ran 11 tests' in Path(paths['python_tests']).read_text() and '\nOK\n' in Path(paths['python_tests']).read_text()
assert '110 tests run: 110 passed, 0 skipped' in Path(paths['rust_tests']).read_text()
crosscheck=json.loads(Path(paths['crosscheck']).read_bytes())
assert crosscheck['status']=='PASS' and crosscheck['report_sha256']==sha(raw)
validation={'schema':'hepta.p41-resource-validation.v1','status':'PASS_RESEARCH_RESOURCE_OBSERVATION',
 'source_commit':report['source_identity']['git_head_sha'],'source_tree':report['source_identity']['git_tree_sha'],
 'base_source_commit':'9fce673cabd927ff6166d7974da2e0005f19e17d',
 'source_commits':['1f903bb1a8dc8f2ac087fae91c394a9c8fc096ab','3f414cf69ed191ad7de2c8252fda76c345cf8551','f8855a7ac07af47b618199a3a9ccb87ff9552a5c'],
 'report_path':str(root/'report.json'),'report_sha256':sha(raw),'plan_sha256':report['plan_sha256'],
 'binary_sha256':sha(binary),'preserved_binary_path':str(root/'native_task_head_pool.bin'),
 'p40_report_sha256':report['p40_report_sha256'],'p40_binary_sha256_unchanged':'86ff023ed2be26b85b9ad47d7f2efb5f0e91a0cb41b7c9bf9df4bef4351eea90',
 'request_stream_sha256':report['request_stream_sha256'],'input_rows':256,
 'experiments_completed':8,'head_counts_per_template':[1,32,256,4096],
 'independently_trained_templates_total':2,'independent_tasks_demonstrated':False,
 'raw_dispatch_observations':32768,'raw_fanout_observations':128,
 'total_native_predict_calls_including_reference_validation':184034,
 'original_reference_predictions_compared':2048,'max_reference_error_vs_p40':0.0,
 'memory_budget_bytes':800*1024*1024,'memory_enforcement':'Linux RLIMIT_AS soft and hard; native self proc RSS/HWM checks',
 'max_private_weights_payload_bytes':554008576,'max_observed_post_load_rss_bytes':581398528,
 'max_reported_post_exec_hwm_bytes':582201344,'child_wall_timeout_seconds':90,
 'total_wall_budget_seconds':720,'observed_total_wall_seconds':report['total_wall_seconds'],
 'test_results':{'python':{'passed':11,'scope':'resource accounting, input integrity, subprocess limits'},
     'rust':{'passed':110,'skipped':0,'scope':'codex-hepta-neuron lib','nextest_version':'0.9.149'},
     'native_fixture_probes':{'valid_pool_runs':2,'rejections':6,'semantic_quality_evidence':False},
     'clippy':{'status':'PASS','scope':'release native_task_head_pool example','warnings_denied':True},
     'just_fix':{'status':'BLOCKED_ENVIRONMENT','reason':'Cargo fix TCP locking listener returned EPERM; scoped read-only Clippy passed without requiring edits'},
     'just_fmt':{'exit_code':0},'release_build':{'status':'PASS','clean_source':True},
     'remote_ci_complete':False},
 'test_source_scope':'Tests checked the final file contents before the three commits; clean release build and resource replay use the final commit.',
 'proofs':proofs,'source_identity_is_compiler_attestation':False,
 'head_only':True,'native_encoder_executed':False,'encoder_sharing_cost_measured':False,
 'new_training_or_calibration':False,'new_independent_quality_trial':False,'full_policy_learning_qualified':False,
 'architecture_cost_ranking_established':False,'target_device_qualified':False,'energy_joules':None,
 'mode':'SHADOW_ONLY','authority':'DENY_ALL','production_activation_allowed':False,
 'task_admission_allowed':False,'action_execution_allowed':False,
 'original_measurement_bytes_modified':False}
validation_path=Path('/tmp/hepta-p41-validation.json')
with validation_path.open('xb') as stream:stream.write(encode(validation))
memory=[];timings=[]
for n in (1,32,256,4096):
 g,l=(report['experiments'][f'{mode}-{n}'] for mode in ('gated','linear'))
 memory.append(f"| {n} | {g['private_weights_payload_bytes']:,} | {g['post_load']['rss_bytes']/1048576:.3f} | {l['post_load']['rss_bytes']/1048576:.3f} |")
 for mode,e in (('gated',g),('linear',l)):
  d,f=e['timings']['dispatch'],e['timings']['fanout']
  timings.append(f"| {mode} | {n} | {d['p50_ms']:.6f} | {d['p95_ms']:.6f} | {d['p99_ms']:.6f} | {f['median_ms']:.6f} | {f['max_ms']:.6f} |")
readme=f'''# P41: actual private Head pools on a shared Linux host

The completed run allocated 1, 32, 256 and 4096 private native Head instances for
each of the two already trained P40 artifacts. Every instance owns its parameter
vector through `LoadedTaskHeadV1::from_artifact`; each was exercised by a real
prediction before measurement. This is replication of **two fixed artifacts**,
not evidence for thousands of independently learned tasks.

## Identity and scope

- Final source: `{validation['source_commit']}`; tree `{validation['source_tree']}`.
- Original P40 report: `{report['p40_report_sha256']}`.
- P41 report: `{sha(raw)}`.
- Release pool binary: `{sha(binary)}`; a byte-identical copy is retained in the run directory.
- Exact paired request stream: `{report['request_stream_sha256']}`; 256 rows, 16,988,720 bytes.

The eight new processes ran serially and completed in {report['total_wall_seconds']:.3f} seconds.
Each required an 800 MiB address-space hard limit, checked its own proc RSS and
HWM, and had an external 90 second wall timeout. The total budget was 12 minutes.
These are head-only, zero-state, cached-feature observations. No Encoder or
optimizer ran, no thresholds changed, and no new quality trial was conducted.
All task/action admission stays false with `SHADOW_ONLY` and `DENY_ALL`.

## Actual resident storage

Both artifacts retain the same 135,256-byte parameter layout, including the
linear control's retained adapter slots. RSS includes the cached inputs, source
artifact buffers, manifest allocations, private weights, allocator and runtime.
The raw reports preserve baseline, post-load, post-warmup and final RSS/RssAnon.
Native `/proc/self/status` is read inside each child; no parent PID lookup or
`wait4` peak is substituted for its resident memory. One MiB means 1,048,576 bytes.

| Heads in one process | Private parameter bytes | Gated post-load RSS MiB | Linear post-load RSS MiB |
|---:|---:|---:|---:|
{chr(10).join(memory)}

At 4096 Heads, the private payload was 554,008,576 bytes, post-load RSS was
581,398,528 bytes, and anonymous RSS was 580,161,536 bytes for both artifacts.
The largest sampled post-exec HWM was 582,201,344 bytes. Ownership follows the
source-bound owned-Vec API and observed scaling; this is not physical-page
attestation or a measurement of a resident Encoder.

## Dispatch and full fanout

Each process first scored all 256 reference rows through Head 0 and warmed every
private Head once. It then measured 4096 round-robin indexed single-Head calls,
followed by 16 calls that each score one input through all resident Heads.
Fanout timing includes collecting every output. Reference comparisons are
outside those timing intervals. An additional 16 reference calls are recorded.
The total observed execution schedule contains 184,034 native predictions.

These timers run inside the native process: JSON parsing, pipe IO and response
serialization are excluded. P40 round-trip timings include IO and therefore
measure a different interval. Raw integer-nanosecond samples are retained.
Single-Head quantiles use nearest rank; the 16 fanout observations report only
median and maximum, not tail quantiles.

| Artifact | Heads | Dispatch p50 ms | p95 ms | p99 ms | Fanout median ms | Fanout max ms |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(timings)}

The gated 4096-Head run contains substantial timing variation. All observations
are retained, with no outcome-driven rerun or sample selection. A sequential
shared-host run cannot establish an intrinsic gated-versus-linear cost ranking,
target-device performance, an end-to-end routing budget, or energy consumption.

## Verification

The separate crosscheck rehashed all 256 complete request lines, including their
trailing newlines, against the original P40 per-row request digests. It checked
2048 reference predictions with exact equality to P40, all 32,768 single-Head
timings, all 128 fanout timings, source Git objects, Head bytes and the binary.
The closed processes' proc measurements are retained observations, not later
reobservations. The unchanged P40 report and its binary remain independently pinned.

Validation retains 11 Python regression tests, 110 owning Rust library tests
(0 skipped, local nextest 0.9.149), and warning-free scoped release Clippy.
Two tiny native fixture pools and six invalid-input rejections are execution
checks only. Cargo's automatic fix command could not open its local locking
listener in this environment; the read-only scoped Clippy check passed.
No remote CI completion is claimed by these local results.

## Reproduction without encoding or retraining

Use a fresh clean checkout at the recorded source. Build the release example
`native_task_head_pool` with `--locked --offline`. Materialize a P40 input directory
by copying the retained `native-results/` evidence from
`qa/stem-bakeoff/evidence/20261022-native-task-head/`, and restore the existing
`20261022-real-multimodal` archive into its `restored/` subdirectory with
`multimodal_evidence.restore_evidence` and the fixed archive manifest pin
`2a853d6c975b30d98a8c79348f01bb3f5b26f36793f2986826a5deed3ea4454e`.
This reconstructs cached features and original cohorts without an Encoder.

Run `qa/stem-bakeoff/native_task_head_pool.py --help` for the required original
report, binary and clean-source pins and a new external output directory.
`prepare_inputs` must reproduce the exact request-stream hash above before any
child starts. A new run creates new resource observations; it does not replace
this retained run. The full original request stream, raw child reports, raw
sample arrays, original Head bytes and copied binary are retained in
`{root}`. The evidence index lists every byte hash and accompanying log.
'''
readme_path=Path('/tmp/hepta-p41-README.md')
with readme_path.open('xb') as stream:stream.write(readme.encode())
inventory={str(path):{'sha256':sha(path.read_bytes()),'bytes':path.stat().st_size}
 for path in sorted(root.rglob('*')) if path.is_file()}
inventory.update({entry['path']:{'sha256':entry['sha256'],'bytes':entry['bytes']} for entry in proofs.values()})
for path in (validation_path,readme_path,Path(__file__)):
 inventory[str(path)]={'sha256':sha(path.read_bytes()),'bytes':path.stat().st_size}
index={'schema':'hepta.p41-evidence-index.v1','report_sha256':sha(raw),'source_commit':validation['source_commit'],
       'files':inventory,'original_results_modified':False,'repository_modified':False,
       'large_reconstructible_input':'requests.jsonl is 16,988,720 bytes; its pinned source reconstruction is preserved in the runner and P40 archive.',
       'scope':'head-only shared-host resource observation; no target device, energy or independent task learning qualification'}
index_path=Path('/tmp/hepta-p41-evidence-index.json')
with index_path.open('xb') as stream:stream.write(encode(index))
print(json.dumps({'status':'INDEXED','files':len(inventory),'index_path':str(index_path),'index_sha256':sha(index_path.read_bytes()),
                  'readme_sha256':sha(readme_path.read_bytes()),'validation_sha256':sha(validation_path.read_bytes()),
                  'copied_binary_bytes':len(binary)}))
