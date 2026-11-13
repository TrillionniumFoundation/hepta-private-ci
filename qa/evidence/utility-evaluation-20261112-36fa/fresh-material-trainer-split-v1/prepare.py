from pathlib import Path
import hashlib
import difflib
import json

OUT = Path('/tmp/hepta-36fa-fresh-material-trainer-split-v1')
BEFORE = Path('/tmp/hepta-36fa-first-material-preheld-deadline-increment-v1/after/codex-rs/hepta-agentd/src/circuit_resident_candidate_provider_material_support_tests.rs')
PREFIX = 'codex-rs/hepta-agentd/src/'
PARENT = 'circuit_resident_candidate_provider_material_support_tests.rs'
CHILD = 'circuit_resident_candidate_provider_unstarted_material_tests.rs'


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}


def one(text, old, new):
    assert text.count(old) == 1, old[:120]
    return text.replace(old, new)


old = BEFORE.read_text()
assert pin(old.encode())['git_blob'] == 'e54fe13095d93a559de5c2816a15f5171774f7cf'
method_start = old.index('    pub(super) async fn new_with_original_work_deadline(')
method_end = old.index('    pub(super) fn original_bytes(', method_start)
old_method = old[method_start:method_end]
signature_end = old_method.index('        let ProviderAdmission')
old_signature = old_method[:signature_end]
body = old_method[signature_end:]

# These original subranges are retained byte for byte, in the same sequential
# constructor chain. The A-only entry returns before creating custody for T or
# starting any of the old cfg(test) Material transports.
custody_start = body.index('            // Open the real custody files')
trainer_end = body.index('            Ok::<_, anyhow::Error>((material, material_owner, trainer, ledger, previous,')
trainer_body = body[custody_start:trainer_end]
trainer_prefix = '            // Open the real custody files before starting the original\n'
assert trainer_body.startswith(trainer_prefix)
preserved_setup = body[body.index('            let previous = execute(&a, 1).await?;'):custody_start]
source_paths_start = body.index('        let source_paths = [')
source_paths_end = body.index('        Ok(Self {', source_paths_start)
source_paths = body[source_paths_start:source_paths_end]

material_fields = old[old.index('pub(super) struct UnstartedProvider {'):old.index('\nimpl UnstartedProvider {')]
material_fields = material_fields.replace('pub(super) struct UnstartedProvider {', 'pub(in super::super) struct UnstartedMaterialProvider {')
material_fields = material_fields.replace('    pub(super) trainer: Arc<Trainer>,\n', '')
material_fields = material_fields.replace('    material_peers: MaterialPeers,\n', '')
material_fields = material_fields.replace('pub(super)', 'pub(in super::super)')
material_fields = material_fields.replace('    source_paths: [PathBuf; 2],', '    pub(super) source_paths: [PathBuf; 2],\n    pub(super) optimizer: crate::CellQ24SgdRuleV1,')
material_fields = material_fields.replace('    // Retain actual files until original Trainer clients and peers are closed.\n    _directory: tempfile::TempDir,',
    '    // This owner has no Trainer or transport. Retain its actual A and ledger\n    // files until all consumers of the original Material owner have closed.\n    pub(super) _directory: tempfile::TempDir,')

child_body = body[:custody_start] + '''            Ok::<_, anyhow::Error>((material, material_owner, optimizer, ledger, previous,
                original_material_inputs, original_decision, original_outcome))
        }.await;

        let (material, material_owner, optimizer, ledger, previous, original_material_inputs,
            original_decision, original_outcome) = match built {
            Ok(original) => original,
            Err(error) => {
                let a_cleanup = a.stop().await;
                return Err(error.context(format!(
                    "same-A Material-only setup cleanup: A={a_cleanup:?}",
                )));
            }
        };
''' + source_paths + '''        Ok(Self {
            material_owner, material, original_trust, original_material_inputs,
            original_decision, original_outcome,
            baseline, bundle, definition, ledger,
            credentials, previous, source_a, config_a, a: Some(a), c: Some(c),
            source_c, version, root, source_paths, optimizer,
            _directory: directory,
        })
    }

    pub(in super::super) fn original_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        let mut bytes = [
            "positive-ledger", "positive-ledger-witness",
            "positive-experience", "positive-experience-witness",
            "positive-dataset", "positive-dataset-witness",
            "base", "encoder", "heads",
        ].into_iter().map(|name| fs::read(self.root.join(name)).map_err(anyhow::Error::from))
            .collect::<anyhow::Result<Vec<_>>>()?;
        for path in &self.source_paths {
            bytes.push(fs::read(path)?);
        }
        Ok(bytes)
    }

    /// Public service tasks must be stopped and joined by the caller before
    /// this owner is released. This method joins the original A task; it does
    /// not claim to have joined a future caller's transport or Trainer task.
    pub(in super::super) async fn finish(mut self) -> anyhow::Result<()> {
        let a_cleanup = match self.a.as_mut() {
            Some(a) => a.stop().await,
            None => Ok(()),
        };
        let material_clones = Arc::strong_count(&self.material_owner);
        let Self { material_owner, a, c, version, _directory, .. } = self;
        drop(material_owner);
        drop(a);
        drop(c);
        drop(version);
        drop(_directory);
        a_cleanup.context("same original A stop/join")?;
        anyhow::ensure!(material_clones == 1, "external original Material services still held");
        Ok(())
    }
}
'''
child_body = one(child_body, '        let mut peers = MaterialPeers::new();\n', '')
child_body = one(child_body,
    '        // On any Result error, the block drops its partially built clients\n        // before the outer cleanup stops A and joins all already started peers.\n',
    '        // Result errors explicitly stop and join the same A. This entry\n        // creates no Trainer, internal Material peer, or duplicate writer.\n')

child = '''//! Material-only mechanism fixture for a later public cross-UID Trainer.
//! This returns after the same real A/Decision/Outcome/Material construction,
//! before any Trainer custody or cfg(test) Material transport is created.
//! Its VersionFixture still uses the original test Current store: this is not
//! a replacement for production RootAuthorityDirectory or Root authorization.

use super::*;

/// Own the still-live original A, its one ledger writer and actual Material
/// owner without also constructing a Trainer in this process. Only the caller
/// can start original public transports whose actual connected streams are
/// bound by another process; no endpoint or authority is fabricated here.
''' + material_fields + '\nimpl UnstartedMaterialProvider {\n' + old_signature.replace('pub(super)', 'pub(in super::super)') + child_body

# Retain the old constructor's same-UID transport branch as the old API's only
# path. A new Material-only caller does not visit this branch.
new_method = old_signature + '''        let mut original = UnstartedMaterialProvider::new_with_original_work_deadline(
            admission, evaluation_profile, work_deadline,
        ).await?;
        let mut peers = MaterialPeers::new();
        let built = (|| -> anyhow::Result<Arc<Trainer>> {
            let root = &original.root;
            let baseline = &original.baseline;
            let material = &original.material;
            let material_owner = &original.material_owner;
            let credentials = &original.credentials;
            let objective = original.material.initial.request.envelope.objective_digest;
            let optimizer = original.optimizer;
''' + trainer_body + '''            Ok(trainer)
        })();
        let trainer = match built {
            Ok(trainer) => trainer,
            Err(error) => {
                let a_cleanup = match original.a.as_mut() {
                    Some(a) => a.stop().await,
                    None => Ok(()),
                };
                let peer_cleanup = peers.finish();
                return Err(error.context(format!(
                    "same-A setup cleanup: A={a_cleanup:?}, original Material peers={peer_cleanup:?}",
                )));
            }
        };
        let UnstartedMaterialProvider {
            material_owner, material, original_trust, original_material_inputs,
            original_decision, original_outcome, baseline, bundle, definition,
            ledger, credentials, previous, source_a, config_a, a, c, source_c,
            version, root, source_paths, _directory, optimizer: _,
        } = original;
        Ok(Self {
            trainer, material_owner, material, original_trust, original_material_inputs,
            original_decision, original_outcome, baseline, bundle, definition,
            ledger, credentials, previous, source_a, config_a, a, c, source_c,
            version, root, material_peers: peers, source_paths, _directory,
        })
    }

'''
parent = one(old, old_method, new_method)
mount = '''#[path = "circuit_resident_candidate_provider_unstarted_material_tests.rs"]
mod unstarted_material;
pub(super) use unstarted_material::UnstartedMaterialProvider;

'''
mount_anchor = '/// Preview is not RunStart authority.'
parent = one(parent, mount_anchor, mount + mount_anchor)

# Avoid relying on double-reference Clone method resolution. These are the
# same owned inputs as the original branch, not new owner or client instances.
new_method_before_refs = new_method
for old_expr, new_expr in [
    ('opened(&root,', 'opened(root,'),
    ('&root, "positive-native-witness"', 'root, "positive-native-witness"'),
    ('&root, "positive-training-receipt-witness"', 'root, "positive-training-receipt-witness"'),
    ('Arc::clone(&material_owner)', 'Arc::clone(material_owner)'),
    ('material.clone()', '(*material).clone()'),
    ('&material,', 'material,'),
    ('into_original_dataset_readback(&material)', 'into_original_dataset_readback(material)'),
    ('Arc::clone(&baseline)', 'Arc::clone(baseline)'),
]:
    new_method = new_method.replace(old_expr, new_expr)
parent = one(parent, new_method_before_refs, new_method)

# Full inverse preservation of the parent. Material construction is a verbatim
# extracted original subrange; the binding statements above only borrow the
# same fields in the old same-UID attachment path.
inverse = one(one(parent, mount, ''), new_method, old_method)
assert inverse == old
assert preserved_setup in child
assert 'material_ports::' not in child
assert 'Trainer::' not in child and 'BootstrapCustodyV1 {' not in child
assert old[method_end:] == parent[parent.index('    pub(super) fn original_bytes('):]
assert parent.count('commands_for_original(') == old.count('commands_for_original(') == 1
assert parent.count('source_for_original(') == old.count('source_for_original(') == 1
assert parent.count('evidence_for_original(') == old.count('evidence_for_original(') == 2
assert child.count('let previous = execute(&a, 1).await?;') == 1
assert child.count('decision_with_original_evidence(') == 1
assert child.count('terminal_outcome_with_original_evidence(') == 1
assert child.count('VersionFixture::new_initial(') == 1

rows = []
patch = ''
for name, before, after in [(PARENT, old, parent), (CHILD, None, child)]:
    path = PREFIX + name
    for side, text in [('before', before), ('after', after)]:
        if text is not None:
            target = OUT/side/path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
    rows.append({'path': path, 'mode': '100644', 'before': pin(before.encode()) if before is not None else None,
                 'after': pin(after.encode()), 'before_text': before, 'after_text': after})
    patch += ''.join(difflib.unified_diff((before or '').splitlines(True), after.splitlines(True),
        fromfile='a/'+path if before is not None else '/dev/null', tofile='b/'+path))

packet = {'format': 'hepta-isolated-source-proposal-v1', 'status': 'PREPARED_UNFORMATTED_UNCOMPILED_UNEXECUTED',
          'dependencies': ['7e7469819f3729305d6da386d6ae000e157b5925'], 'qualification': False,
          'changes': rows}
(OUT/'SOURCE_PACKET.json').write_text(json.dumps(packet, ensure_ascii=False, indent=2)+'\n')
(OUT/'SOURCE_DELTA.patch').write_text(patch)
review = {
    'format': 'hepta-material-trainer-construction-split-static-v1',
    'status': 'PREPARED_UNFORMATTED_UNCOMPILED_UNEXECUTED',
    'parent_preimage': pin(old.encode()),
    'parent_full_inverse_equal': True,
    'original_A_decision_outcome_material_body_retained_byte_for_byte': True,
    'same_A_execution_count_in_material_constructor': 1,
    'same_original_Decision_and_Outcome_append_count_each': 1,
    'new_material_only_entry_constructs_Trainer_or_test_ports': False,
    'old_new_and_new_with_original_work_deadline_still_attach_all_four_test_peers_once': True,
    'old_parent_original_bytes_and_finish_entire_suffix_unchanged': True,
    'work_deadline_sampling_and_original_signing_body_unchanged': True,
    'custody_files_still_open_before_first_transport_in_old_entry': True,
    'test_Current_is_not_production_Root_custody': True,
    'production_Root_Current_cross_UID_interface_complete': False,
    'new_public_Trainer_cross_UID_service_executed': False,
    'rust_fmt_or_compilation_or_test': False,
    'real_qualified_task_chains': 0,
    'sources': [{k:v for k,v in row.items() if not k.endswith('_text')} for row in rows],
}
(OUT/'STATIC_PRESERVATION.json').write_text(json.dumps(review, indent=2)+'\n')
print(json.dumps({'packet': pin((OUT/'SOURCE_PACKET.json').read_bytes()), 'sources': review['sources']}, indent=2))
