import copy
import json
from pathlib import Path
import tempfile
import unittest

from parametric_model import SourceMemoryCell
from parametric_evolution import run_evolution
from parametric_network_trial import read_network
from parametric_lifecycle_trial import run_lifecycle
from parametric_trial import MODEL_SEED, read_worker, write_json
from test_parametric_model import SourceMemoryCellTests, TEMPLATES, fact
from test_parametric_evolution import ParametricEvolutionTests

suite = unittest.TestSuite([ParametricEvolutionTests('test_selection_keeps_parent_when_candidates_regress')])
unit = unittest.TextTestRunner(verbosity=2).run(suite)
assert unit.wasSuccessful()

SourceMemoryCellTests.setUpClass()
try:
    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary)
        model = SourceMemoryCellTests.base
        cell = SourceMemoryCell(model, rank=8, seed=MODEL_SEED)
        cell.reset('alpha')
        facts = [fact('one', 'red', 'a'), fact('two', 'blue', 'b'), fact('three', 'green', 'c'), fact('four', 'red', 'd')]
        cell.fit_sources(facts, 4, 0.001, TEMPLATES)
        parent = output / 'parent'
        parent_sha = cell.save(parent)
        evolution = run_evolution(cell, parent_dir=parent, parent_sha=parent_sha, facts=facts,
            output=output / 'evolution', steps=4, learning_rate=0.001,
            templates=TEMPLATES, selection_template='What {relation} for {entity}?')
        diagnostic_evolution = copy.deepcopy(evolution)
        diagnostic_evolution['chosen_arm'] = 'nochange'
        diagnostic_evolution['chosen_cells'] = diagnostic_evolution['arms']['nochange']['cells']
        network = read_network(cell, model=model, evolution=diagnostic_evolution, facts=facts,
            output=output / 'network', read_worker=read_worker, write_json=write_json)
        assert network['chosen_arm'] == 'nochange'
        assert set(network['metrics']) == {'nochange', 'continue', 'split'}
        nochange_calls = [call for call in network['routed_calls'] if call['cell'].startswith('nochange-')]
        assert nochange_calls and sum(len(call['query_indices']) for call in nochange_calls) == len(facts)
        assert all(call['manifest_sha256'] == parent_sha for call in nochange_calls)
        persisted = json.loads((output / 'network' / 'precommitted-selection.json').read_text())
        assert persisted['chosen_arm'] == 'nochange' and not persisted['test_scores_used']
        descendants = [version for arm in ('continue', 'split') for version in evolution['arms'][arm]['cells']]
        lifecycle = run_lifecycle(cell, model=model, parent_dir=parent, parent_sha=parent_sha,
            facts=facts, output=output / 'lifecycle', steps=4, learning_rate=0.001,
            templates=TEMPLATES, derived_cells=descendants, read_worker=read_worker, write_json=write_json)
        assert len(lifecycle['withdrawal_rejections']) == 5
        assert lifecycle['forward_calls_on_revoked'] == 0
        assert lifecycle['clean_base_replay_verified']
        assert lifecycle['current_generation'] == 2
        assert set(lifecycle['exact_replayed_roots']).isdisjoint(lifecycle['deleted_roots'])
        print(json.dumps({'scope': 'tiny real decoder integration only, no capability claim',
            'selection_policy_scenarios': 4,
            'forced_nochange_dispatch': True,
            'network_arms_read': list(network['metrics']),
            'network_actual_fresh_processes': network['fresh_decoder_processes'],
            'nochange_queries': sum(len(call['query_indices']) for call in nochange_calls),
            'lifecycle_fresh_processes': 3,
            'revoked_descendants_and_parent_rejected': len(lifecycle['withdrawal_rejections']),
            'revoked_forward_calls': lifecycle['forward_calls_on_revoked'],
            'clean_base_replay_verified': lifecycle['clean_base_replay_verified'],
            'current_generation': lifecycle['current_generation']}, sort_keys=True))
finally:
    SourceMemoryCellTests.tearDownClass()
