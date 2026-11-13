"""Isolated exact replacements for test fixtures; no Rust/control execution."""
import difflib
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = Path('/tmp/hepta-36fa-fresh-training-b-fixture-proposal-v1/after')
OBSERVER = Path('/tmp/hepta-36fa-training-completion-observer-increment-v1/after')
PREFIX = Path('codex-rs/hepta-agentd/src')
changes, patches, replacements = [], [], []


def pin(b):
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()}


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as f:
        f.write(raw)


def replace(s, old, new, label):
    assert s.count(old) == 1, label
    replacements.append({'label': label, 'before': old, 'after': new})
    return s.replace(old, new, 1)


def save(name, before, after, expected):
    assert pin(before)['git_blob'] == expected
    path = (PREFIX / name).as_posix()
    write(HERE / 'before' / path, before)
    write(HERE / 'after' / path, after)
    changes.append({'path': path, 'before': pin(before), 'after': pin(after),
                    'before_content': before.decode(), 'after_content': after.decode()})
    patches.extend(difflib.unified_diff(before.decode().splitlines(True), after.decode().splitlines(True),
                   fromfile='a/' + path, tofile='b/' + path))


name = 'circuit_original_evaluation_panel_member_support_tests.rs'
before = (BASE / PREFIX / name).read_bytes()
s = before.decode()
start = s.index('    pub(crate) fn complete_from_original_trainer')
end = s.index('    async fn complete_with_trainer', start)
old_wrapper = s[start:end]
shared_wrapper = old_wrapper.replace('complete_from_original_trainer', 'complete_from_shared_original_trainer', 1).replace(
    'trainer: crate::LearningIterationEvidenceClientV1,', 'trainer: Arc<crate::LearningIterationEvidenceClientV1>,', 1)
wrapper = old_wrapper.replace('Some(trainer),', 'Some(Arc::new(trainer)),', 1)
s = replace(s, old_wrapper, wrapper + '    /// Both B tasks keep the same original read-only client, not a new peer.\n' + shared_wrapper, 'add shared member entry; preserve by-value adapter')
s = replace(s, 'original_trainer: Option<crate::LearningIterationEvidenceClientV1>,',
            'original_trainer: Option<Arc<crate::LearningIterationEvidenceClientV1>>,', 'private member input Arc')
s = replace(s, '(trainer, Some(thread))', '(Arc::new(trainer), Some(thread))', 'old synthetic peer still owns its one Arc')
s = replace(s, '            trainer: Arc::new(trainer),\n            cohort,',
            '            trainer,\n            cohort,', 'move exact original Arc into existing production member')
save(name, before, s.encode(), '66314778d0dff6ff760361e624f89180024f087d')

name = 'circuit_original_evaluation_fresh_training_support_tests.rs'
before = (BASE / PREFIX / name).read_bytes()
s = before.decode()
needle = '''        retention_trainer: LearningIterationEvidenceClientV1,
    ) -> impl std::future::Future<Output = anyhow::Result<CompletedBPanel>> + 'a {
        Box::pin(async move {'''
replacement = '''        retention_trainer: LearningIterationEvidenceClientV1,
    ) -> impl std::future::Future<Output = anyhow::Result<CompletedBPanel>> + 'a {
        self.complete_with_trainers(input, Arc::new(primary_trainer), Arc::new(retention_trainer))
    }

    /// Existing production PanelMemberOwners already takes Arc evidence-only
    /// clients. Sequential B reads share one original channel and its limits.
    pub(in super::super) fn complete_with_shared_original_trainer<'a>(
        self,
        input: &'a CompletedTrainingInputs<'a>,
        trainer: Arc<LearningIterationEvidenceClientV1>,
    ) -> impl std::future::Future<Output = anyhow::Result<CompletedBPanel>> + 'a {
        self.complete_with_trainers(input, Arc::clone(&trainer), trainer)
    }

    fn complete_with_trainers<'a>(
        self,
        input: &'a CompletedTrainingInputs<'a>,
        primary_trainer: Arc<LearningIterationEvidenceClientV1>,
        retention_trainer: Arc<LearningIterationEvidenceClientV1>,
    ) -> impl std::future::Future<Output = anyhow::Result<CompletedBPanel>> + 'a {
        Box::pin(async move {'''
s = replace(s, needle, replacement, 'one shared B entry with unchanged common completion body')
s = replace(s, '    trainer: LearningIterationEvidenceClientV1,\n) -> anyhow::Result<PanelMemberFixture>',
            '    trainer: Arc<LearningIterationEvidenceClientV1>,\n) -> anyhow::Result<PanelMemberFixture>', 'complete_member receives the same Arc')
s = replace(s, 'Box::pin(PanelMemberFixture::complete_from_original_trainer(',
            'Box::pin(PanelMemberFixture::complete_from_shared_original_trainer(', 'call actual shared member entry')
save(name, before, s.encode(), 'fa08441db86ad7918a79b86e7b25d6fb0c3dd855')

name = 'cell_q24_training_bootstrap_original_ports_tests.rs'
before = (OBSERVER / PREFIX / name).read_bytes()
addition = (HERE / 'shared_ports_append.rs.txt').read_bytes()
save(name, before, before + addition, '3284b902f9f77f760c0246d34c6bec7c82581fe6')

# Reproduce every exact before by inverse explicit text changes. The ports
# file is additive only. This proves textual preservation, not Rust typing.
for row in changes[:2]:
    restored = row['after_content']
    for item in reversed(replacements):
        if item['after'] in restored:
            assert restored.count(item['after']) == 1, item['label']
            restored = restored.replace(item['after'], item['before'], 1)
    assert restored == row['before_content'], row['path']
assert changes[2]['after_content'] == changes[2]['before_content'] + addition.decode()
packet = {'format': 'hepta-test-only-shared-original-B-trainer-increment-v1',
          'status': 'HOLD_UNFORMATTED_UNCOMPILED_UNEXECUTED',
          'canonical_source': 'cc57c7198db6293ccca562253c42fffbe2a04633',
          'base_fixture_packet': '8d5b1eeea4e63ae04bb77c91abc996a34cdeccfa',
          'observer_increment': '85d28ef8d6dd6f4fd48f5380b68b4e389a7427c1',
          'changes': changes, 'production_changes': 0,
          'source_activated': False, 'H_Cargo_format_tests': 0, 'qualification': False}
write(HERE / 'SOURCE_PACKET.json', (json.dumps(packet, indent=2, sort_keys=True) + '\n').encode())
write(HERE / 'SOURCE_DELTA.patch', ''.join(patches).encode())
write(HERE / 'EXACT_REPLACEMENTS.json', (json.dumps(replacements, indent=2, sort_keys=True) + '\n').encode())
manifest = {k:v for k,v in packet.items() if k != 'changes'}
manifest['changes'] = [{k:v for k,v in row.items() if not k.endswith('_content')} for row in changes]
manifest['packet'] = pin((HERE / 'SOURCE_PACKET.json').read_bytes())
manifest['patch'] = pin((HERE / 'SOURCE_DELTA.patch').read_bytes())
manifest['inverse_restores_exact_frozen_inputs'] = True
write(HERE / 'MANIFEST.json', (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode())
print(json.dumps(manifest, indent=2, sort_keys=True))
