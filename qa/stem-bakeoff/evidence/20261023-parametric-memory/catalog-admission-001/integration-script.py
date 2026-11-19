"""One real fresh decoder read; typed unknown/withdrawn requests never forward."""

import hashlib
import json
from pathlib import Path
import shutil

from metadata_catalog import MetadataCatalog, SCHEMA
from parametric_cohort import fact, VALUES
from parametric_owner import Frontier, ParametricOwner
from parametric_trial import identity, read_worker, write_json

ROOT = Path('/workspace/scratch/1d69f04ee9f4')
REPO = ROOT / 'hepta-private-ci'
RUN = ROOT / 'parametric-runs/confirmation-001'
OUTPUT = ROOT / 'parametric-runs/catalog-admission-001'
MODEL = Path('/tmp/hepta-parametric-smol135m')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    return {
        'core': identity(),
        'catalog': {
            p.name: sha(p)
            for p in sorted((REPO / 'scripts/memory_cell_catalog').glob('*.py'))
        },
        'integration_script_sha256': sha(Path(__file__)),
    }


def run():
    OUTPUT.mkdir(exist_ok=False)
    (OUTPUT / 'reader-cwd').mkdir()
    before = sources()
    write_json(OUTPUT / 'source-identity.json', before)
    write_json(OUTPUT / 'protocol.json', {
        'schema': 'hepta.parametric-memory.catalog-integration.protocol.v1',
        'known_entity': 'Bob',
        'unknown_entities': ['Zelda', 'Alice'],
        'required_model_callbacks': 1,
        'known_raw_exact_match_required': True,
        'stale_and_withdrawn_zero_callbacks_required': True,
        'retraining_allowed': False,
        'production_accepted': False,
    })
    lifecycle = json.loads((RUN / 'lifecycle/result.json').read_text())
    facts = json.loads((RUN / 'source-facts.json').read_text())
    scope = facts[0]['scope']
    corrected = [dict(item) for item in facts]
    for index in (0, 1):
        old = facts[index]
        corrected[index] = fact(
            scope, old['entity'],
            VALUES[(VALUES.index(old['value']) + 1) % len(VALUES)], revision=1,
        )
    kept = corrected[1:]
    view = Frontier(scope, 1, tuple(lifecycle['deleted_roots']))
    # Preserve the original completed experiment's database and all raw files.
    shutil.copyfile(RUN / 'lifecycle/owner.sqlite3', OUTPUT / 'owner.sqlite3')
    owner = ParametricOwner(OUTPUT / 'owner.sqlite3')
    active = owner.current('memory', scope)
    assert active.manifest_sha256 == lifecycle['current_manifest_sha256']
    assert active.generation == 2
    assert set(active.roots) == {item['source_digest'] for item in kept}

    def catalog(name, manifest, rows):
        path = OUTPUT / name
        write_json(path, {
            'schema': SCHEMA, 'scope': scope, 'cell_id': 'memory',
            'manifest_sha256': manifest, 'production_accepted': False,
            'entries': [{key: row[key] for key in ('entity', 'relation', 'source_digest')}
                        for row in rows],
        })
        return MetadataCatalog(path, sha(path))

    clean = catalog('clean-catalog.json', active.manifest_sha256, kept)
    model_calls = []

    def execute(selected, question):
        model_calls.append({'manifest_sha256': selected.manifest_sha256,
                            'question': question})
        return read_worker(
            MODEL, selected.directory, selected.manifest_sha256, scope,
            selected.roots, [question], OUTPUT, 'known',
        )

    unknown = {}
    for entity in ('Zelda', 'Alice'):
        unknown[entity] = clean.read(owner, entity=entity, relation='color',
                                    provider=lambda: view, callback=execute)
        assert unknown[entity] == {'status': 'unknown', 'response': 'unknown'}
        assert len(model_calls) == 0
    known = clean.read(owner, entity='Bob', relation='color',
                       provider=lambda: view, callback=execute)
    known_text = known['response']['rows'][0]['text']
    assert known['status'] == 'known'
    assert known_text == corrected[1]['value']
    assert len(model_calls) == 1

    parent_sha = sha(RUN / 'written-cell/lineage.json')
    old = catalog('old-catalog.json', parent_sha, facts)
    errors = {}
    try:
        old.read(owner, entity='Alice', relation='color',
                 provider=lambda: view, callback=execute)
    except ValueError as error:
        errors['stale'] = str(error)
    else:
        raise AssertionError('stale catalog accepted')
    assert len(model_calls) == 1

    # A separately activated old checkpoint has matching catalog identity, so
    # this admission must be stopped specifically by the withdrawal frontier.
    withdrawn_owner = ParametricOwner(OUTPUT / 'withdrawn-owner.sqlite3')
    withdrawn_owner.activate(
        'memory', RUN / 'written-cell', parent_sha, scope=scope,
        expected_current=None, generation=0, provider=lambda: Frontier(scope),
        allowed_roots={row['source_digest'] for row in facts},
    )
    try:
        old.read(withdrawn_owner, entity='Alice', relation='color',
                 provider=lambda: view, callback=execute)
    except ValueError as error:
        errors['withdrawn'] = str(error)
        assert 'withdrawn' in errors['withdrawn']
    else:
        raise AssertionError('withdrawn catalog admitted a model')
    assert len(model_calls) == 1
    after = sources()
    write_json(OUTPUT / 'source-identity-after.json', after)
    assert before == after
    result = {
        'schema': 'hepta.parametric-memory.catalog-integration.result.v1',
        'all_gates_passed': True,
        'existing_full_confirmation_source_commit': before['core']['git_head'],
        'active_manifest_sha256': active.manifest_sha256,
        'active_generation': active.generation,
        'catalog_sha256': sha(OUTPUT / 'clean-catalog.json'),
        'metadata_has_answer_values': False,
        'known': {'entity': 'Bob', 'raw_text': known_text,
                  'expected_value': corrected[1]['value'], 'raw_exact_match': True},
        'unknown': unknown,
        'rejections': errors,
        'model_callback_calls': model_calls,
        'model_callbacks_for_unknown_stale_or_withdrawn': 0,
        'fresh_worker_processes': 1,
        'training_updates': 0,
        'source_files_unchanged': before == after,
        'model_intrinsic_abstention_proven': False,
        'parameter_unlearning_proven': False,
        'provider_authenticated': False,
        'production_accepted': False,
    }
    write_json(OUTPUT / 'result.json', result)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    run()
