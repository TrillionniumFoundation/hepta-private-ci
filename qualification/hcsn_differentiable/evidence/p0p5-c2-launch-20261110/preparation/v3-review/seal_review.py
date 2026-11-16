"""Freeze independent static findings without changing any C2 candidate."""
import hashlib
import json
from pathlib import Path
import re
import shutil
from zipfile import ZipFile, ZIP_DEFLATED

BASE=Path('/workspace/scratch/c385a7439f8e')
OUT=Path(__file__).resolve().parent
CANDIDATE=BASE/'c2-execution-candidate-v3'
VALIDATION=BASE/'c2-execution-validation-attempt-04'


def identity(path):
    raw=Path(path).read_bytes()
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def save(path,value):
    with Path(path).open('x') as stream:stream.write(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n')


def main():
    manifest=json.loads((CANDIDATE/'PROGRAM-MANIFEST.json').read_bytes())
    for name,item in manifest['files'].items():
        assert identity(CANDIDATE/name)==item
    validation=json.loads((VALIDATION/'RESULT.json').read_bytes())
    assert validation['all_passed'] and validation['source_before']==validation['source_after']
    for name,digest in validation['source_after'].items():
        assert identity(CANDIDATE/name)['sha256']==digest
    tests=0
    for attempt in validation['attempts']:
        assert attempt['returncode']==0
        log=VALIDATION/(attempt['name']+'.stderr')
        assert identity(log)==attempt['stderr']
        text=log.read_text();m=re.search(r'Ran (\d+) tests?',text)
        assert m and text.rstrip().endswith('OK')
        tests+=int(m.group(1))
    assert tests==53
    assert identity(VALIDATION/'TESTED-SOURCE.zip')==dict(bytes=201153,sha256='daa7e510ef6d790afe2b4c9db3afbf4a9e3a024565da1ee4c1d8301b802b17e7')
    (OUT/'frozen-candidate').mkdir()
    for name in ['PROGRAM-MANIFEST.json','CONTRACT.json','POSTERIOR-POLICY.json','OPTIMIZATION-POSTERIOR-POLICY-v2.json',
                 'c2_runner.py','c2_io.py','c2_controller.py','c2_recording.py','c2_boundary.py']:
        shutil.copy2(CANDIDATE/name,OUT/'frozen-candidate'/name)
    shutil.copytree(VALIDATION,OUT/'owner-validation-attempt-04')
    shutil.copytree(BASE/'c2-optimization-trace-counterexample-v1',OUT/'old-trace-counterexample')
    controller_case=BASE/'c2-controller-result-counterexample-v1/RESULT.json'
    if controller_case.exists():shutil.copy2(controller_case,OUT/'old-controller-counterexample.json')
    findings=[
        dict(id='C2-01',severity='blocking_for_production_in_old_v1',status='closed_in_v2_and_retained_in_v3',
             description='Old controller could label exit0 plus missing result as completed.',
             closure='terminal_result_gate now requires identified JSON, matching parent/fit/config/source and all success artifacts. Missing or corrupt evidence is failed_terminal_evidence, while measured wait4 cost remains recorded.'),
        dict(id='C2-02',severity='blocking_for_trace_admission_in_old_v2',status='closed_in_v3',
             description='Exact old finish_pending AST accepted duplicated positions and wrong batch/dt/model identity with unchanged row count.',
             closure='Frozen v3 binds every position, valid sample index, actual dt, network hash, update/episode/capture/layer, probability dimensions and pad exclusions. Independent AST positive control plus nine corruptions pass the intended accept/reject behavior.'),
        dict(id='C2-03',severity='reporting_ambiguity_for_future_execution',status='open_in_reviewed_v3_not_a_readonly_preflight_blocker',
             description='Both runner and controller initialize formal_fits_started=0 and never change it even on the execute path. actual_continuations_started separately counts processes.',
             recommendation='Remove or explicitly rename the constant as new_original_roster_fits_started; never use it to claim that executed continuations performed zero training. Production execution reports need unambiguous actual continuation and optimizer update counts.'),
    ]
    result=dict(schema='independent-C2-v3-static-review-v1',
        disposition='no_blocking_finding_for_existing_authorized_native_software_tests_and_six_parent_validate_only',
        production_execution_authorized_by_this_review=False,real_production_checkpoint_reads=0,real_production_forwards=0,
        real_production_backward_calls=0,real_production_optimizer_steps=0,
        reviewed_program_manifest=identity(CANDIDATE/'PROGRAM-MANIFEST.json'),
        reviewed_source_capsule=identity(VALIDATION/'TESTED-SOURCE.zip'),
        owner_validation_result=identity(VALIDATION/'RESULT.json'),owner_tests=tests,
        owner_validation_scope=validation['scope'],owner_source_unchanged=True,
        independent_gate_closure=identity(OUT/'TRACE-GATE-CLOSURE.json'),
        independent_gate_closure_outer=json.loads((OUT/'TRACE-CLOSURE-OUTER.json').read_bytes()),
        old_trace_counterexample=identity(OUT/'old-trace-counterexample/RESULT.json'),
        findings=findings,limits=[
            'Static source review and model-free closure do not prove six real native parent admissions; those must have separate native original receipts.',
            'Native validate-only code instantiates models and optimizer state for structural checking but performs no forward/backward/optimizer step; it must not be labelled zero optimizer construction.',
            'C2 is adaptive extra active budget up to43200s and200 epochs, outside original common-budget views; original parent wall and discarded partial work are not refunded.',
            'Scheduled actual-gradient traces and separate supplemental evaluation windows are bounded samples; neither grants whole-training numerical qualification.',
            'Controller completed_attempt_roster describes complete accounting, not all fits successful or adequate.',
            'Finalization reserve600s is inside the unchanged active cap and is not a guaranteed successful final evaluation; every timeout/failed/missing artifact remains explicit.'
        ],scientific_admission='HOLD',whole_training_numerical_admission='HOLD')
    save(OUT/'RESULT.json',result)
    (OUT/'REVIEW.md').write_text('''# Independent static review of C2 candidate v3

The reviewed source presents no blocker for the already authorized native software tests and six-parent validation-only check. This conclusion does not authorize production continuation, establish that the six native parents passed admission, or grant training/numerical/scientific credit. The exact reviewed program manifest is ed02f75a65fd1a5958e289d9b6a812a2feddb0096b787fbcc5b37331d0965648; source ZIP is 201,153 B with SHA256 daa7e510ef6d790afe2b4c9db3afbf4a9e3a024565da1ee4c1d8301b802b17e7. No real training checkpoint was loaded in this independent review.

## Closed findings and remaining reporting issue

The old v1 controller could report a successful continuation from return code zero even when result.json was absent. In the reviewed source, terminal_result_gate checks the exact report/parent/model configuration, unchanged source/shared weights, successful status, complete epoch/update counters, resource envelope, stopping/adequacy semantics, and hashes of required results/checkpoints/logits/journal/resume-start artifacts. An invalid or missing artifact is failed_terminal_evidence. Independently measured exit wall and wait4 CPU are retained even when result evidence is incomplete. Controller completed_attempt_roster still means accounting has reached a terminal roster; it does not mean every fit succeeded.

An independent model-free execution of the exact old OptimizationRecorder.finish_pending method exposed a second gap: two rows with duplicated time position, wrong batch membership, altered dt and network digest could pass the old row-count gate. The original red case and its 0.077372033 s full process wall /0.076567 s CPU are preserved. The v3 validator now checks exact positions; per-position valid sample indices and original dt; network, source, update, episode, capture and layer identities; each probability-vector dimension; valid sample totals; and excluded padding. An independent positive control plus nine isolated corruptions of the exact v3 AST all produced the intended result. That closure cost 0.041496945 s complete child wall and0.04072 s CPU, with no Torch import, model, forward, backward or optimizer execution. The result demonstrates admission logic; it does not allege that an original production recorder wrote corrupt data.

One reporting issue remains in this reviewed v3: runner and controller hardcode formal_fits_started to zero even on the future execute path. Their actual_continuations_started and optimizer update fields supply the meaningful counts. Before using future production reports, remove or explicitly rename the constant as new original-roster fits, and never cite it as zero continuation training. This issue does not invalidate a validation-only run that performs no forward or update.

## Parent chain and restoration boundary

bind_parent requires the exact final original42 roster and outer row, original report/plan hashes, actual v8 source paths and file hashes, full Python/runtime package identity and Torch build, initial/last/best checkpoint commitments, terminal journal and ABC/D inputs. The data reader requires all-development mode and confirmation_access false. It verifies the retained complete prefix and seeded batch order, strict best within that prefix, saved order RNG, AdamW parameter ordering/hyperparameters/moment age and finite moments, frozen common/physical state, terminal wall cause, no RSS failure, passed inherited memorization and absence of a previously reached plateau. An older rollback boundary, hard-kill/missing terminal report, or best checkpoint ahead of the retained prefix remains ineligible.

Production restoration, if later separately authorized, loads the complete saved construction config, model, optimizer, Torch RNG and order RNG. It writes an exclusive resume-start checkpoint, reloads it and compares full state to original last.pt, then writes a hash-bound resume receipt before the first optimizer_started event. The snapshot and receipt are checked again before each step. This is a reviewed future witness mechanism; this static review has not observed a real production resume-start artifact.

Each successful epoch produces an exclusive checkpoint and an immutable commit with its metrics, strict best and previous commit. The retained boundary advances only after that commit exists. Convenience last/best aliases are copied atomically from immutable files. A failure before commit leaves the previous complete anchor. Interrupted live state is preserved separately before terminal last/best observations, and is not silently substituted for the complete anchor. The original partial executed work is counted and charged in full; only the logical optimizer state rolls back to last complete epoch. The software owner retained a real tiny-model partial-step/cold-cache equality test against uninterrupted training; that is a synthetic software result, not proof of the six real native continuations.

## Recording and stopping boundaries

Actual optimization recording attaches to the unchanged before_forward callback for the declared first gradient microbatch at the resume epoch and scheduled absolute epochs. It closes and verifies the retained trace before a later microbatch or in finally, before clip/optimizer.step. A truncated or mismatched scheduled trace raises RecordingHold before that step. Logical resumed update indices and total already executed updates, including discarded original partial work, are reported separately.

Supplemental windows remain separate no-grad evaluation captures on three fixed ABC episodes at the checkpoint schedule. They verify model, existing gradients, Torch/order RNG, mode, source and checkpoint neutrality. Their posteriors must not be presented as the original optimization trajectory. Both families are bounded observations and retain whole-training numerical HOLD. Original truncated training traces are neither appended to nor retroactively repaired.

The strict-best and plateau state derives from the complete parent prefix plus every new epoch, preserving inherited memorization rather than rerunning it. A completed development report can still be inadequate at an epoch cap; the heuristic adequacy flag additionally requires development plateau and the inherited diagnostic pass. It is never independent E confirmation or evidence of an HCSN advantage.

## Resources and execution status

The extra C2 phase has cumulative active wall at most43,200 s and at most200 logical epochs per fit. Original actual full outer wall is deducted, including partial work and diagnostics. The600 s finalization reserve is within that same allowance. The controller sets the child deadline from dispatch and imports/admission/prelaunch bookkeeping consume it. wait4 records exact per-child exit CPU; aggregate RUSAGE_CHILDREN is a second view, not additive to those per-child values. Attempt, wrapper and controller times overlap. Failed/missing terminal records stay explicit, with cost completeness separate from evidence completeness. No energy is measured.

C2 is a later adaptive extension and cannot replace the original common-budget300/900/1800 s comparisons or the original budget-censored results. Its calendar phase may extend beyond the original campaign calendar deadline. Reporting must retain all six LR/seed opportunities and costs. Structural validation instantiates model/optimizer state but does not forward or step; it should be described precisely rather than as zero optimizer construction.

The owner validation logs were independently hash-checked and counted:21 frozen guards+19 runner tests+8 terminal artifact tests+5 trace coverage tests,53 total, source unchanged. Owner cost was11.557616989998 s whole child-test wall and11.141105 s CPU. These tests used synthetic fixtures and read no real production checkpoint. This independent review did not repeat those tests, models, numerical oracles, or any production continuation.
''')
    files={str(p.relative_to(OUT)):identity(p) for p in sorted(OUT.rglob('*')) if p.is_file()}
    save(OUT/'MANIFEST.json',dict(schema='independent-C2-static-review-manifest-v1',files=files))
    target=BASE/'c2-execution-independent-review-v1.zip'
    with ZipFile(target,'x',compression=ZIP_DEFLATED) as zipped:
        for p in sorted(OUT.rglob('*')):
            if p.is_file():zipped.write(p,str(p.relative_to(OUT)))
    with ZipFile(target) as zipped:assert zipped.testzip() is None
    print(json.dumps(dict(directory=str(OUT),archive=dict(path=str(target),**identity(target)),
        result=identity(OUT/'RESULT.json'),review=identity(OUT/'REVIEW.md'),manifest=identity(OUT/'MANIFEST.json'))))


if __name__=='__main__':main()
