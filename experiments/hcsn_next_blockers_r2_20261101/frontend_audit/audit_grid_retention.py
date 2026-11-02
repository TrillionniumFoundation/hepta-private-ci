"""Verify the GRID retention-only amendment against archived model source."""
import ast
import difflib
import json
from pathlib import Path

from audit_audio_candidate import read, sha


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
GRID = ROOT / 'experiments/hcsn_grid_frontend_r2_20261101'


def function(tree, name):
    return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)


def main():
    before = (GRID / 'study_features_v1.py').read_text()
    after = (GRID / 'study.py').read_text()
    first, second = ast.parse(before), ast.parse(after)
    unchanged = ['model_guard', 'sha', 'save', 'text_feature', 'features', 'infer', 'head_features', 'episodes', 'evaluate']
    for name in unchanged:
        assert ast.dump(function(first, name)) == ast.dump(function(second, name))
    for name in ('Encoders',):
        a = next(n for n in first.body if isinstance(n, ast.ClassDef) and n.name == name)
        b = next(n for n in second.body if isinstance(n, ast.ClassDef) and n.name == name)
        assert ast.dump(a) == ast.dump(b)
    # The complete optimizer objective and its minimize invocation are unchanged.
    a, b = function(first, 'fit'), function(second, 'fit')
    assert ast.dump(function(a, 'objective')) == ast.dump(function(b, 'objective'))
    calls = []
    for item in (a, b):
        calls.append(next(n for n in ast.walk(item) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'minimize'))
    assert ast.dump(calls[0]) == ast.dump(calls[1])
    # Retention changes only add checkpoint writes; every training fit call,
    # held mask, inference call and episode construction remains identical.
    train_before, train_after = function(first, 'train'), function(second, 'train')
    def calls_named(tree, name):
        return [ast.dump(n) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name]
    for name in ('fit', 'infer', 'episodes', 'head_features'):
        assert calls_named(train_before, name) == calls_named(train_after, name)
    masks_before = [ast.dump(n.value) for n in ast.walk(train_before) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'held' for t in n.targets)]
    masks_after = [ast.dump(n.value) for n in ast.walk(train_after) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'held' for t in n.targets)]
    assert masks_before == masks_after
    oldfreeze = read(GRID / 'MODEL_SOURCE_FREEZE_FEATURES_V1.json')
    frozen = read(GRID / 'MODEL_SOURCE_FREEZE.json')
    assert sha(GRID / 'study_features_v1.py') == oldfreeze['files']['study.py']
    for name, digest in frozen['files'].items():
        assert sha(GRID / name) == digest
    for name, digest in frozen['dependencies'].items():
        assert sha(ROOT / name) == digest
    assert frozen['dependencies'] == oldfreeze['dependencies']
    assert frozen['admitted_feature_source_freezes'] == [sha(GRID / 'MODEL_SOURCE_FREEZE_FEATURES_V1.json')]
    assert frozen['train_features_extracted'] and not frozen['train_heads_fitted']
    feature = GRID / 'features/train'
    assert sha(feature / 'FEATURES.npz') == frozen['train_feature_bank_sha256']
    assert sha(feature / 'IDENTITY.json') == frozen['train_feature_identity_sha256']
    assert read(feature / 'IDENTITY.json')['model_source_freeze_sha256'] == sha(GRID / 'MODEL_SOURCE_FREEZE_FEATURES_V1.json')
    provenance = read(GRID / 'PROVENANCE_ADDENDUM.json')
    assert provenance['new_payload_count_at_v2_freeze'] is None and not provenance['qualification_changed']
    result = dict(schema='hcsn.grid-retention-amendment.independent-review.v1',
        source_freeze_sha256=sha(GRID / 'MODEL_SOURCE_FREEZE.json'), previous_source_freeze_sha256=sha(GRID / 'MODEL_SOURCE_FREEZE_FEATURES_V1.json'),
        checks=dict(unchanged_encoder_class=True, unchanged_objective_optimizer=True, unchanged_fit_arguments=True, unchanged_actor_masks=True,
            unchanged_episode_and_head_features=True, unchanged_evaluation=True, all_frozen_sources_verified=True, same_encoder_dependencies=True,
            exact_original_feature_bank_admitted=True, original_source_preserved=True, stale_payload_count_corrected_by_preserved_addendum=True),
        diff=''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile='study_features_v1.py', tofile='study.py')),
        registration_state='Frozen amended source declares features extracted and no classifier/head fit; parent remote publication receipt supplies chronology.',
        held_media_decoded=False, fit_performed=False, review_issue_closed=True, all_blockers_closed=False)
    target = HERE / 'REVIEW_GRID_RETENTION.json'
    with target.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(path=str(target.relative_to(ROOT)), sha256=sha(target), review_issue_closed=True), sort_keys=True))


if __name__ == '__main__':
    main()
