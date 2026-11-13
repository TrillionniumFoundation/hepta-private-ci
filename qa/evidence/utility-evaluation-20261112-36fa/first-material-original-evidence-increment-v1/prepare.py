from pathlib import Path
import hashlib, json, difflib

ROOT=Path('/tmp/hepta-36fa-first-material-original-evidence-increment-v1')
BASE=Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3/overlay-local-capability-v1')
PREFIX='codex-rs/hepta-agentd/src/'
EXPECTED={
 'circuit_model_selection_material_support_tests.rs':'e7e83057862baaba3c39c09ae4a3f9faa95753ee',
 'circuit_resident_candidate_provider_material_support_tests.rs':'fe5c07068d9ea1a59b05260f48d39ecfc22ebf96',
}

def pin(raw):
 return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
         'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
changes=[]; substitutions={}; patches=[]
for name,expected in EXPECTED.items():
 path=PREFIX+name; before=(BASE/path).read_bytes(); assert pin(before)['git_blob']==expected
 text=before.decode(); edits=[]
 def replace(old,new):
  global text
  assert text.count(old)==1,(name,old[:90],text.count(old))
  text=text.replace(old,new); edits.append((old,new))
 if name.startswith('circuit_model_selection_'):
  old='''pub(super) fn decision(
    writer: &mut LedgerWriter,
    credentials: &Credentials,
    publication: &CircuitTaskSourcePublicationV1,
) -> anyhow::Result<()> {
'''
  new='''/// Exact inputs and signature admitted by one original Decision append.
/// Retaining these bytes does not append, re-sign or authorize another event.
#[derive(Clone)]
pub(super) struct OriginalDecisionEvidence {
    pub(super) request: ProductionDecisionV2,
    pub(super) evidence: SignedLearningEvidenceV1,
    pub(super) admitted_at: u64,
}

/// Exact inputs and signature admitted by one original Outcome append.
/// The independent fixture target and original credential windows are unchanged.
#[derive(Clone)]
pub(super) struct OriginalOutcomeEvidence {
    pub(super) outcome: AuthenticatedOutcomeV1,
    pub(super) evidence: SignedLearningEvidenceV1,
    pub(super) admitted_at: u64,
}

pub(super) fn decision(
    writer: &mut LedgerWriter,
    credentials: &Credentials,
    publication: &CircuitTaskSourcePublicationV1,
) -> anyhow::Result<()> {
    decision_with_original_evidence(writer, credentials, publication).map(|_| ())
}

pub(super) fn decision_with_original_evidence(
    writer: &mut LedgerWriter,
    credentials: &Credentials,
    publication: &CircuitTaskSourcePublicationV1,
) -> anyhow::Result<OriginalDecisionEvidence> {
'''
  replace(old,new)
  replace('''    writer.append_decision(Digest32::ZERO, record, &evidence, at)?;
    Ok(())
''','''    let original = OriginalDecisionEvidence {
        request: record.clone(), evidence: evidence.clone(), admitted_at: at,
    };
    writer.append_decision(Digest32::ZERO, record, &evidence, at)?;
    Ok(original)
''')
  replace('''// The caller fixes this explicit test measurement before material or Training.
// It is never computed from the model output or a subsequent training result.
pub(super) fn terminal_outcome_with_value(
    writer: &mut LedgerWriter,
    credentials: &Credentials,
    publication: &CircuitTaskSourcePublicationV1,
    value: FixedQ32,
) -> anyhow::Result<()> {
''','''pub(super) fn terminal_outcome_with_original_evidence(
    writer: &mut LedgerWriter,
    credentials: &Credentials,
    publication: &CircuitTaskSourcePublicationV1,
) -> anyhow::Result<OriginalOutcomeEvidence> {
    terminal_outcome_with_value_and_original_evidence(
        writer, credentials, publication, FixedQ32::from_raw(2_i64 << 32),
    )
}

// The caller fixes this explicit test measurement before material or Training.
// It is never computed from the model output or a subsequent training result.
pub(super) fn terminal_outcome_with_value(
    writer: &mut LedgerWriter,
    credentials: &Credentials,
    publication: &CircuitTaskSourcePublicationV1,
    value: FixedQ32,
) -> anyhow::Result<()> {
    terminal_outcome_with_value_and_original_evidence(writer, credentials, publication, value)
        .map(|_| ())
}

fn terminal_outcome_with_value_and_original_evidence(
    writer: &mut LedgerWriter,
    credentials: &Credentials,
    publication: &CircuitTaskSourcePublicationV1,
    value: FixedQ32,
) -> anyhow::Result<OriginalOutcomeEvidence> {
''')
  replace('''    writer.append_outcome(writer.snapshot()?.head_digest, outcome, &evidence, at)?;
    Ok(())
''','''    let original = OriginalOutcomeEvidence {
        outcome: outcome.clone(), evidence: evidence.clone(), admitted_at: at,
    };
    writer.append_outcome(writer.snapshot()?.head_digest, outcome, &evidence, at)?;
    Ok(original)
''')
 else:
  replace('''    pub(super) original_material_inputs: material::OriginalMaterialConstructorInputs,
''','''    pub(super) original_material_inputs: material::OriginalMaterialConstructorInputs,
    pub(super) original_decision: material::OriginalDecisionEvidence,
    pub(super) original_outcome: material::OriginalOutcomeEvidence,
''')
  replace('''            material::decision(&mut ledger, &credentials, &previous)?;
''','''            let original_decision = material::decision_with_original_evidence(
                &mut ledger, &credentials, &previous,
            )?;
''')
  replace('''            material::terminal_outcome(&mut ledger, &credentials, &previous)?;
''','''            let original_outcome = material::terminal_outcome_with_original_evidence(
                &mut ledger, &credentials, &previous,
            )?;
''')
  replace('''            Ok::<_, anyhow::Error>((material, material_owner, trainer, ledger, previous, original_material_inputs))
''','''            Ok::<_, anyhow::Error>((material, material_owner, trainer, ledger, previous,
                original_material_inputs, original_decision, original_outcome))
''')
  replace('''        let (material, material_owner, trainer, ledger, previous, original_material_inputs) = match built {
''','''        let (material, material_owner, trainer, ledger, previous, original_material_inputs,
            original_decision, original_outcome) = match built {
''')
  replace('''            trainer, material_owner, material, original_trust, original_material_inputs,
''','''            trainer, material_owner, material, original_trust, original_material_inputs,
            original_decision, original_outcome,
''')
 inverse=text
 for old,new in reversed(edits):
  assert inverse.count(new)==1
  inverse=inverse.replace(new,old)
 assert inverse.encode()==before
 after=text.encode()
 for kind,raw in [('before',before),('after',after)]:
  p=ROOT/kind/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
 changes.append({'path':path,'mode':'100644','before':pin(before),'after':pin(after),
                 'before_text':before.decode(),'after_text':text})
 substitutions[path]=[{'before':a,'after':b} for a,b in edits]
 patches.extend(difflib.unified_diff(before.decode().splitlines(True),text.splitlines(True),
              fromfile='a/'+path,tofile='b/'+path))
packet={'format':'hepta-isolated-source-proposal-v1','status':'PREPARED_UNFORMATTED_UNCOMPILED_UNEXECUTED',
        'base_source_commit':'cc57c7198db6293ccca562253c42fffbe2a04633',
        'base_overlay':'f4066cf562953650ae7a10129c9a90d496630fca','changes':changes}
(ROOT/'SOURCE_PACKET.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2)+'\n')
(ROOT/'SOURCE_DELTA.patch').write_text(''.join(patches))
report={'format':'hepta-original-material-evidence-preservation-v1',
        'status':'PURE_STATIC_BYTE_REVIEW_ONLY','inverse_full_files_equal':True,
        'files':[{k:v for k,v in c.items() if not k.endswith('_text')} for c in changes],
        'substitutions':substitutions,
        'preserved':['one original sign and one original append for each Decision/Outcome call',
                     'same actual Source publication, independent fixed terminal value and wall-time samples',
                     'same original append validation and error propagation before evidence is returned',
                     'same old unit-returning helper interfaces and caller behavior',
                     'complete retained original request, signature and admission time; no reconstructed signature'],
        'not_proved':['first Root admission from a child','public three-UID Fresh completion',
                      'Rust compile or test success','real user-authorized A or independent utility'],
        'formatter':False,'compiler':False,'tests':False,'H':False}
(ROOT/'STATIC_PRESERVATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'directory':str(ROOT),'packet':pin((ROOT/'SOURCE_PACKET.json').read_bytes()),
                  'after':[{c['path']:c['after']} for c in changes]},indent=2))
