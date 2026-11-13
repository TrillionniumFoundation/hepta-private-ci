from pathlib import Path
import difflib
import hashlib
import json

OUT = Path('/tmp/hepta-36fa-b-preheld-objective-increment-v1')
BASE = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3/overlay-local-tests-codec-v2/codex-rs/hepta-agentd/src')
PREFIX = 'codex-rs/hepta-agentd/src/'


def pin(b):
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(),
            'git_blob': hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}


def one(text, before, after):
    assert text.count(before) == 1, before[:140]
    return text.replace(before, after)


changes = []
patch = ''


def save(name, old, after, replacements):
    global patch
    inverse = after
    for before, post in reversed(replacements):
        inverse = one(inverse, post, before)
    assert inverse == old
    path = PREFIX + name
    for side, data in [('before', old), ('after', after)]:
        file = OUT/side/path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(data)
    changes.append({'path':path,'mode':'100644','before':pin(old.encode()),'after':pin(after.encode()),
                    'before_text':old,'after_text':after,'full_inverse_equal':True})
    patch += ''.join(difflib.unified_diff(old.splitlines(True),after.splitlines(True),
                      fromfile='a/'+path,tofile='b/'+path))


name = 'circuit_original_evaluation_source_support_tests.rs'
old = (BASE/name).read_text()
assert pin(old.encode())['git_blob'] == '9528b169dd57d71dd30d087d8732eeaec90c6d02'
borrowed = '''/// Complete borrowed comparison objective, not an A admission or Source
/// publication. A trusted test host supplies these four compiled fields; this
/// value carries no task identity, authority, history, issuer or signature.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(in super::super) struct BorrowedOriginalObjective<'a> {
    pub(super) objective_digest: Digest32,
    pub(super) objective_semantic_bytes: &'a [u8],
    pub(super) objective_function_v1_digest: Digest32,
    pub(super) objective_function_v1_bytes: &'a [u8],
}

impl<'a> BorrowedOriginalObjective<'a> {
    pub(super) fn from_original_record(record: &'a RunStartRecordV1) -> Self {
        Self {
            objective_digest: record.snapshot.objective_digest,
            objective_semantic_bytes: &record.objective_semantic_bytes,
            objective_function_v1_digest: record.objective_function_v1_digest,
            objective_function_v1_bytes: &record.objective_function_v1_bytes,
        }
    }

    /// Pure consistency checks use the same full-byte identities and limits
    /// as the original RunStart record. They do not authenticate an ingress or
    /// create a completed A. The caller must retain its pre-held full contract.
    pub(in super::super) fn from_preheld_compiled_objective(
        objective_digest: Digest32,
        objective_semantic_bytes: &'a [u8],
        objective_function_v1_digest: Digest32,
        objective_function_v1_bytes: &'a [u8],
    ) -> anyhow::Result<Self> {
        anyhow::ensure!(!objective_digest.is_zero()
            && !objective_function_v1_digest.is_zero()
            && (1..=256 * 1024).contains(&objective_semantic_bytes.len())
            && (1..=256 * 1024).contains(&objective_function_v1_bytes.len())
            && Digest32::of_bytes(objective_semantic_bytes) == objective_digest
            && Digest32::of_bytes(objective_function_v1_bytes) == objective_function_v1_digest,
            "complete pre-held compiled objective bytes and original identities");
        Ok(Self { objective_digest, objective_semantic_bytes,
            objective_function_v1_digest, objective_function_v1_bytes })
    }
}

'''
start = old.index('    pub(super) async fn populate_from_original_training(')
end = old.index('        let rule = self.rule.clone();',start)
signature = old[start:end]
new_signature = signature.replace('populate_from_original_training(', 'populate_from_preheld_objective(').replace(
    '        previous: &CircuitTaskSourcePublicationV1,', '        objective: BorrowedOriginalObjective<\'_>,')
wrapper = signature + '''        self.populate_from_preheld_objective(
            BorrowedOriginalObjective::from_original_record(previous.original_record()),
            baseline, candidate, mode, changed_candidate_action, decision_binding,
        ).await
    }

''' + new_signature
population_end = old.index('    fn input(',end)
pop_body = old[end:population_end]
new_pop_body = pop_body.replace('.execute(previous,', '.execute(objective,').replace('                    previous,', '                    objective,').replace('                previous,', '                objective,')
assert new_pop_body.count('previous') == 0
exec_start = old.index('    async fn execute(')
exec_end = old.index('    pub(super) fn training(',exec_start)
exec_body = old[exec_start:exec_end]
new_exec_body = exec_body.replace('        previous: &CircuitTaskSourcePublicationV1,', '        objective: BorrowedOriginalObjective<\'_>,')
new_exec_body = one(new_exec_body,'        let objective = previous.original_record();\n','')
new_exec_body = one(new_exec_body,'objective.snapshot.objective_digest,','objective.objective_digest,')
new_exec_body = one(new_exec_body,'objective.objective_semantic_bytes.clone()','objective.objective_semantic_bytes.to_vec()')
new_exec_body = one(new_exec_body,'objective.objective_function_v1_bytes.clone()','objective.objective_function_v1_bytes.to_vec()')
replacements = [('pub(super) enum ObservationMode {',borrowed+'pub(super) enum ObservationMode {'),
                (signature,wrapper),(pop_body,new_pop_body),(exec_body,new_exec_body)]
after = old
for before, post in replacements:
    after = one(after,before,post)
save(name,old,after,replacements)

name = 'circuit_original_evaluation_fresh_training_support_tests.rs'
old = (BASE/name).read_text()
assert pin(old.encode())['git_blob'] == '6c3438d982449daf16e5ed3aec829f3b616a3ff3'
method_start = old.index('    pub(in super::super) fn from_original_completion(')
method_end = old.index('\n}\n\n/// Created before Material/T;',method_start)
method = old[method_start:method_end]
shared_method = method.replace('from_original_completion(', 'from_preheld_objective_and_original_completion(')
shared_method = one(shared_method, '        previous: &\'a CircuitTaskSourcePublicationV1,',
    '        objective: BorrowedOriginalObjective<\'a>,')
shared_method = one(shared_method,'        source_a: &crate::CircuitTaskSourceInputV1,',
    '        source_a: &crate::CircuitTaskSourceInputV1,\n        expected_completed_a: Digest32,')
shared_method = one(shared_method,'        anyhow::ensure!(previous.input() == source_a);\n', '''        // The source input and expected history are trusted host inputs,
        // not fields chosen by an unauthenticated child report. The actual D
        // is the original owner attestation that checked the live Source.
        anyhow::ensure!(objective.objective_digest == source_a.objective_digest);
        anyhow::ensure!(source_a.scope.agent_id == material.initial.request.agent_id
            && source_a.scope.cell_id == material.initial.request.cell_id
            && source_a.scope.principal_digest.to_string() == material.initial.request.principal_id.as_str(),
            "complete pre-held A source identity matches original Material");
''')
shared_method = one(shared_method,'''        anyhow::ensure!(previous.history_digest().as_str().parse::<Digest32>()?
            == material.initial.request.completed_task_receipt);''', '''        anyhow::ensure!(!expected_completed_a.is_zero()
            && dataset.snapshot().request.completed_task_receipt == expected_completed_a,
            "pre-held A history is certified by the actual original D prefix");''')
shared_method = one(shared_method,'''        let baseline_manifest = support::configuration(
            baseline, baseline_bundle, &baseline_definition, source_a, 1,
        )?.manifest;''', '''        let baseline_config = support::configuration(
            baseline, baseline_bundle, &baseline_definition, source_a, 1,
        )?;
        anyhow::ensure!(baseline_config.task_digest == config_a.task_digest
            && baseline_config.source_frontier == config_a.source_frontier
            && baseline_config.initial.scope == config_a.initial.scope,
            "complete pre-held A input remains bound to its original task config");
        let baseline_manifest = baseline_config.manifest;''')
shared_method = one(shared_method,'            previous,','            objective,')
shared_method = '''

    /// Receive a complete pre-held comparison objective separately from A's
    /// Source owner. The original opaque D/T/Candidate checks still execute;
    /// expected A history is compared to authenticated D, never to itself in
    /// initial. This test-only view grants neither Root nor Training authority.
''' + shared_method
replacements = [
    ('use material::evaluation_provider::DecisionBinding;','use material::evaluation_provider::DecisionBinding;\npub(in super::super) use super::source::BorrowedOriginalObjective;'),
    ('    previous: &\'a CircuitTaskSourcePublicationV1,','    objective: BorrowedOriginalObjective<\'a>,'),
    ('            previous,','            objective: BorrowedOriginalObjective::from_original_record(previous.original_record()),'),
    ('\n}\n\n/// Created before Material/T;',shared_method+'\n}\n\n/// Created before Material/T;'),
    ('    b.populate_from_original_training(\n        input.previous, input.baseline, input.candidate,',
     '    b.populate_from_preheld_objective(\n        input.objective, input.baseline, input.candidate,'),
]
# The field line also occurs in the old method's parameter list. Limit that
# first replacement to the struct range rather than deleting the old Source
# parameter or its original input/history assertions.
field_before, field_after = replacements[1]
assert old.count(field_before) == 2
struct_end = old.index('\nimpl<\'a> CompletedTrainingInputs')
field_block = old[:struct_end]
replacements[1] = (field_block, one(field_block,field_before,field_after))
# Apply the struct-only replacement before adding the import above it.
replacements[0], replacements[1] = replacements[1], replacements[0]
after = old
for before, post in replacements:
    after = one(after,before,post)
assert 'anyhow::ensure!(previous.input() == source_a);' in after
assert 'previous.history_digest().as_str().parse::<Digest32>()?' in after
save(name,old,after,replacements)

name = 'circuit_resident_candidate_provider_stage_tests.rs'
old = (BASE/name).read_text()
test = '''

/// This uses actual Fresh E/D/T/Candidate handlers and the original A's full
/// record as local trusted fixture data. It does not certify parent-before-
/// child preholding, cross-UID transport or deployed independent B.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn fresh_original_b_inputs_keep_actual_source_history_when_objective_is_borrowed() -> anyhow::Result<()> {
    use super::super::evaluation_provider::fresh_training::{
        BorrowedOriginalObjective, CompletedTrainingInputs,
    };
    let mut fixture = Box::pin(FreshStages::new()).await?;
    let result: anyhow::Result<()> = async {
        Box::pin(fixture.complete_training()).await?;
        let before = fixture.original_bytes()?;
        let original = fixture.original()?;
        let record = original.previous.original_record();
        let objective = BorrowedOriginalObjective::from_preheld_compiled_objective(
            record.snapshot.objective_digest, &record.objective_semantic_bytes,
            record.objective_function_v1_digest, &record.objective_function_v1_bytes,
        )?;
        let dataset = fixture.dataset_receipt.as_ref().context("actual D")?;
        let training = fixture.training.as_ref().context("actual T")?;
        let candidate = fixture.candidate.as_ref().context("actual Candidate")?;
        let expected_history = original.previous.history_digest().as_str().parse::<Digest32>()?;
        let old = CompletedTrainingInputs::from_original_completion(
            &original.material, dataset, training, candidate, original.baseline.as_ref(),
            &original.previous, &original.source_a, &original.config_a, &original.credentials,
        )?;
        let received = CompletedTrainingInputs::from_preheld_objective_and_original_completion(
            &original.material, dataset, training, candidate, original.baseline.as_ref(),
            objective, &original.source_a, expected_history, &original.config_a, &original.credentials,
        )?;
        drop((old, received));

        anyhow::ensure!(CompletedTrainingInputs::from_preheld_objective_and_original_completion(
            &original.material, dataset, training, candidate, original.baseline.as_ref(),
            objective, &original.source_a, d("another-A-history"), &original.config_a, &original.credentials,
        ).is_err(), "full objective bytes cannot replace actual original A history");
        let mut wrong_source = original.source_a.clone();
        wrong_source.scope.run_id = id("another-original-A-run");
        anyhow::ensure!(CompletedTrainingInputs::from_preheld_objective_and_original_completion(
            &original.material, dataset, training, candidate, original.baseline.as_ref(),
            objective, &wrong_source, expected_history, &original.config_a, &original.credentials,
        ).is_err(), "actual D/T cannot be rebound to another source run");
        let mut wrong_input = original.source_a.clone();
        wrong_input.observation.push(0);
        anyhow::ensure!(CompletedTrainingInputs::from_preheld_objective_and_original_completion(
            &original.material, dataset, training, candidate, original.baseline.as_ref(),
            objective, &wrong_input, expected_history, &original.config_a, &original.credentials,
        ).is_err(), "same run and objective do not replace the original full A input");
        let mut changed_material = original.material.clone();
        changed_material.initial.request.completed_task_receipt = d("rewritten-Material-A-history");
        anyhow::ensure!(CompletedTrainingInputs::from_preheld_objective_and_original_completion(
            &changed_material, dataset, training, candidate, original.baseline.as_ref(),
            objective, &original.source_a, expected_history, &original.config_a, &original.credentials,
        ).is_err(), "actual original D still authenticates the complete original Material");
        let mut wrong_function = record.objective_function_v1_bytes.clone();
        wrong_function.push(0);
        anyhow::ensure!(BorrowedOriginalObjective::from_preheld_compiled_objective(
            record.snapshot.objective_digest, &record.objective_semantic_bytes,
            record.objective_function_v1_digest, &wrong_function,
        ).is_err(), "complete original objective function bytes remain mandatory");
        anyhow::ensure!(fixture.original_bytes()? == before,
            "borrowing objectives and rejected input substitutions do not change original evidence");
        Ok(())
    }.await;
    finish_case(result, fixture).await
}
'''
save(name,old,old+test,[(old,old+test)])

packet = {'format':'hepta-isolated-source-proposal-v1','status':'PREPARED_UNFORMATTED_UNCOMPILED_UNEXECUTED',
          'root86_preimages':'3f7d40d4933669da33d2aef3491efb431c5771ae',
          'read_only_basis':'50a182e905aca1e388bafe4dffe28277a7c568d9','qualification':False,'changes':changes}
(OUT/'SOURCE_PACKET.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2)+'\n')
(OUT/'SOURCE_DELTA.patch').write_text(patch)
report = {'format':'hepta-B-objective-source-separation-static-v1','all_three_full_inverse_equal':True,
    'old_Source_wrapper_keeps_whole_input_and_history_assertions':True,
    'old_B_population_loop_preserved_except_borrowed_argument':True,
    'old_B_execute_keeps_independent_admission_run_time_and_all_assertions':True,
    'no_Source_publication_or_RunStart_constructed_from_new_objective_view':True,
    'actual_D_authenticates_full_original_Material_before_new_expected_history_comparison':True,
    'actual_T_Candidate_cut_and_manifest_checks_preserved':True,
    'new_material_initial_history_is_not_compared_to_itself_as_proof':True,
    'old_two_stage_test_methods_full_prefix_unchanged':True,
    'new_Fresh_mechanism_methods':1,'new_test_executed':False,'rust_compiled':False,'formatted':False,
    'public_three_UID_or_Root_chain_proven':False,'real_qualified_task_chains':0,
    'sources':[{k:v for k,v in c.items() if not k.endswith('_text')} for c in changes]}
(OUT/'STATIC_PRESERVATION.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'packet':pin((OUT/'SOURCE_PACKET.json').read_bytes()),'sources':report['sources']},indent=2))
