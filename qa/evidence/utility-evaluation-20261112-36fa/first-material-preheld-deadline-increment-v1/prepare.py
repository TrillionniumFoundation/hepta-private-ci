from pathlib import Path
import hashlib, json, difflib

OUT = Path('/tmp/hepta-36fa-first-material-preheld-deadline-increment-v1')
MATERIAL = Path('/tmp/hepta-36fa-first-material-original-evidence-increment-v1/after/codex-rs/hepta-agentd/src')
PENDING = Path('/tmp/hepta-36fa-first-material-admission-v1/after/codex-rs/hepta-agentd/src')
PREFIX = 'codex-rs/hepta-agentd/src/'

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def one(text, before, after):
    assert text.count(before) == 1, before[:140]
    return text.replace(before, after)

changes = []
diffs = []
def save(name, original, after, replacements):
    inverse = after
    for before, post in reversed(replacements):
        inverse = one(inverse, post, before)
    assert inverse == original
    path = PREFIX + name
    for directory, text in [('before', original), ('after', after)]:
        file = OUT/directory/path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
    changes.append({'path': path, 'mode': '100644', 'before': pin(original.encode()), 'after': pin(after.encode()),
                    'before_text': original, 'after_text': after, 'exact_inverse_equal': True})
    diffs.append(''.join(difflib.unified_diff(original.splitlines(True), after.splitlines(True),
                     fromfile='a/'+path, tofile='b/'+path)))

name = 'circuit_model_selection_material_support_tests.rs'
old = (MATERIAL/name).read_text()
assert pin(old.encode())['git_blob'] == '149dcd8140f543e4da9a5d5b715963ed81e6fd0f'
signature = old[old.index('pub(super) fn unstarted_material_with_original_inputs('):old.index('    let input = publication.input();', old.index('pub(super) fn unstarted_material_with_original_inputs('))]
enum = '''/// The old fixture samples its deadline at the original freeze point. A
/// first-admission parent can instead fix the same bounded work window before
/// A starts; the child cannot renew it when creating Material.
#[derive(Clone, Copy)]
pub(super) enum OriginalMaterialWorkDeadline {
    AtOriginalFreeze,
    PreheldExact(u64),
}

impl OriginalMaterialWorkDeadline {
    fn at_original_freeze(self) -> anyhow::Result<u64> {
        match self {
            Self::AtOriginalFreeze => Ok(now()? + 900),
            Self::PreheldExact(expiry) => {
                let at = now()?;
                let original_limit = at.checked_add(900).ok_or_else(|| anyhow::anyhow!("original work deadline overflow"))?;
                anyhow::ensure!(at < expiry && expiry <= original_limit,
                    "pre-held absolute work expiry is current and does not extend the original window");
                Ok(expiry)
            }
        }
    }
}

'''
wrapper = signature + '''    unstarted_material_with_original_work_deadline(
        _root, writer, credentials, source, identity, baseline, bundle, publication,
        evaluation_profile, next_use_observer, OriginalMaterialWorkDeadline::AtOriginalFreeze,
    )
}

'''
new_signature = signature.replace('unstarted_material_with_original_inputs(', 'unstarted_material_with_original_work_deadline(').replace(
    '    next_use_observer: StableId,\n', '    next_use_observer: StableId,\n    work_deadline: OriginalMaterialWorkDeadline,\n')
replacements = [(signature, enum + wrapper + new_signature),
                ('expiry_unix_seconds: now()? + 900,', 'expiry_unix_seconds: work_deadline.at_original_freeze()?,')]
post = old
for before, after in replacements:
    post = one(post, before, after)
save(name, old, post, replacements)

name = 'circuit_resident_candidate_provider_material_support_tests.rs'
old = (MATERIAL/name).read_text()
assert pin(old.encode())['git_blob'] == 'f1f8add8a7d3055e64479d1fb0f239f127a15a84'
before = '''    pub(super) async fn new(
        admission: ProviderAdmission,
        evaluation_profile: Digest32,
    ) -> anyhow::Result<Self> {
'''
after = before + '''        Self::new_with_original_work_deadline(
            admission, evaluation_profile, material::OriginalMaterialWorkDeadline::AtOriginalFreeze,
        ).await
    }

    pub(super) async fn new_with_original_work_deadline(
        admission: ProviderAdmission,
        evaluation_profile: Digest32,
        work_deadline: material::OriginalMaterialWorkDeadline,
    ) -> anyhow::Result<Self> {
'''
replacements = [(before, after),
                ('material::unstarted_material_with_original_inputs(', 'material::unstarted_material_with_original_work_deadline('),
                ('                next_use_observer.clone(),\n', '                next_use_observer.clone(), work_deadline,\n')]
post = old
for before, after in replacements:
    post = one(post, before, after)
save(name, old, post, replacements)

name = 'circuit_resident_candidate_first_material_tests.rs'
old = (PENDING/name).read_text()
assert pin(old.encode())['git_blob'] == 'f6b6ba838fa70a9d8175655a26574cfcbc78f916'
replacements = [
    ('    trust: LearningEvidenceTrustV1,\n) -> PreheldMaterialInputs {',
     '    trust: LearningEvidenceTrustV1,\n    original_expiry: u64,\n) -> anyhow::Result<PreheldMaterialInputs> {'),
    ('    PreheldMaterialInputs {\n', '    let trust_digest = LearningEvidenceVerifierV1::new(trust.clone())?.trust_digest();\n    Ok(PreheldMaterialInputs {\n'),
    ('selected_bundle: fixture.bundle.clone(), envelope: fixture.material.initial.request.envelope.clone(),',
     '''selected_bundle: fixture.bundle.clone(), envelope: IterationEnvelopeV1 {
                envelope_id: id("positive-original-envelope"),
                base_commit: d("0bfe47e53bae47977c4423362e4d3823edac99fd"),
                base_tree: d("8663f89daca111ba7f681d2c36442f6f4ded97f5"),
                objective_digest: source.objective_digest, grammar_digest: d("explicit-positive-single-head-grammar"),
                maximum_files: 1, maximum_diff_bytes: 4_096, maximum_candidates: 1,
                maximum_parallel_sandboxes: 1, expiry_unix_seconds: original_expiry,
            },'''),
    ('evidence_trust_digest: fixture.material.verifier.trust_digest(),', 'evidence_trust_digest: trust_digest,'),
    ('        maximum_signature_lifetime_seconds: 600,\n    }\n}', '        maximum_signature_lifetime_seconds: 600,\n    })\n}'),
    ('    let protocol = panel.registration().clone();\n    let fixture = Box::pin(UnstartedProvider::new(admission, protocol.evaluation_profile())).await?;',
     '''    let protocol = panel.registration().clone();
    let original_expiry = admission.trust_time.checked_add(900).context("original absolute work expiry")?;
    let fixture = Box::pin(UnstartedProvider::new_with_original_work_deadline(
        admission, protocol.evaluation_profile(), material::OriginalMaterialWorkDeadline::PreheldExact(original_expiry),
    )).await?;'''),
    ('let held = held_fixture_policy(&fixture, protocol, trust);', 'let held = held_fixture_policy(&fixture, protocol, trust, original_expiry)?;'),
    ('assert_eq!(pending.admission_binding()?, crate::RootResidentLearningProfileV3::admission_binding(\n            &fixture.material.initial, &fixture.material.scope, &fixture.material.verifier)?);',
     'anyhow::ensure!(pending.admission_binding()? == crate::RootResidentLearningProfileV3::admission_binding(\n            &fixture.material.initial, &fixture.material.scope, &fixture.material.verifier)?, "same original Root binding");'),
    ('assert_eq!(pending.material.initial, fixture.material.initial);',
     'anyhow::ensure!(pending.material.initial == fixture.material.initial, "same full original initial cut");'),
    ('assert_eq!(pending.material.scope, fixture.material.scope);',
     'anyhow::ensure!(pending.material.scope == fixture.material.scope, "same complete original frozen scope");'),
    ('assert_eq!(pending.material.freeze_evidence, fixture.material.freeze_evidence);',
     'anyhow::ensure!(pending.material.freeze_evidence == fixture.material.freeze_evidence, "same complete original freeze signature");'),
]
post = old
for before, after in replacements:
    post = one(post, before, after)
save(name, old, post, replacements)

packet = {'format': 'hepta-isolated-source-proposal-v1', 'status': 'PREPARED_UNFORMATTED_UNCOMPILED_UNEXECUTED',
          'dependencies': ['d656853ee0fb0e4bf7aedbd371916607d7dcb619', '641999aa0c288941e17d343c3fabeb48b93e0eae'],
          'changes': changes, 'qualification': False}
(OUT/'SOURCE_PACKET.json').write_text(json.dumps(packet, ensure_ascii=False, indent=2)+'\n')
(OUT/'SOURCE_DELTA.patch').write_text(''.join(diffs))
(OUT/'STATIC_PRESERVATION.json').write_text(json.dumps({'format':'hepta-exact-preheld-work-deadline-increment-v1',
    'all_three_inverse_transforms_restore_complete_preimages': True,
    'old_material_constructor_delegates_once_to_same_body': True,
    'old_provider_constructor_delegates_once_to_same_body': True,
    'old_default_deadline_still_sampled_at_same_freeze_field': True,
    'new_preheld_expiry_fixed_before_actual_A_and_never_renewed': True,
    'original_window_seconds': 900, 'original_transport_limits_unchanged': True,
    'no_parent_envelope_or_trust_digest_read_from_Material': True,
    'four_whole_value_assertions_preserved_as_Result_before_explicit_cleanup': True,
    'original_signature_and_append_calls_unchanged': True,
    'rust_compilation':False,'tests_run':0,'qualification':False,
    'changes': [{k:v for k,v in r.items() if not k.endswith('_text')} for r in changes]},indent=2)+'\n')
print(json.dumps({'packet':pin((OUT/'SOURCE_PACKET.json').read_bytes()),
                 'sources':[{k:v for k,v in r.items() if not k.endswith('_text')} for r in changes]},indent=2))
