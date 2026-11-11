"""Execute the frozen gate method with model-free trace metadata fixtures."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace, ModuleType

SOURCE = Path('/workspace/scratch/c385a7439f8e/c2-execution-candidate-v2/c2_recording.py')
OUT = Path(__file__).resolve().parent


def identity(path):
    raw = Path(path).read_bytes()
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def require(condition, text):
    if not condition:
        raise ValueError(text)


def exclusive_json(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, sort_keys=True) + '\n')
    return identity(path)


def main():
    raw = SOURCE.read_bytes()
    tree = ast.parse(raw)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'OptimizationRecorder')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'finish_pending')
    namespace = dict(require=require, identity=identity, exclusive_json=exclusive_json, Path=Path,
                     semantic_digest=lambda value: 'fixed-synthetic-state', time=time,
                     RecordingHold=RuntimeError, __builtins__=__builtins__)
    import traceback
    namespace['traceback'] = traceback
    exec(compile(ast.Module(body=[copy.deepcopy(method)], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    finish = namespace['finish_pending']
    rows = []
    with tempfile.TemporaryDirectory(prefix='c2-model-free-gate-') as tmp:
        root = Path(tmp)
        for bad in [False, True]:
            folder = root / ('bad' if bad else 'control')
            folder.mkdir()
            visits = [dict(position=0, batch_indices=[0, 1], update_index=12, episode_id='A+B',
                           dt=[0.1, 0.2], model_digest='expected-network'),
                      dict(position=1, batch_indices=[0], update_index=12, episode_id='A+B',
                           dt=[0.3], model_digest='expected-network')]
            if bad:
                for row in visits:
                    row.update(position=0, batch_indices=[0], dt=[9.0], model_digest='wrong-network')
            header = dict(data_sha256='data', configuration_sha256='policy')
            footer = dict(source_unchanged=True, truncated=False, captures=1, seen_records=2,
                          retained_records=2, seen_states=3, retained_states=3, padded_states_excluded=1)
            trace = folder/'trace.jsonl'
            trace.write_text(json.dumps(dict(header=header, visits=visits, footer=footer))+'\n')
            module = ModuleType('qualification.hcsn_differentiable.training_domain')
            module.read_trace = lambda path: (header, visits, footer, 'fixture-digest')
            sys.modules[module.__name__] = module
            row = dict(path=trace, expected_rows=2, logical_completed_updates_before_step=12,
                       microbatch_episode_ids=['A', 'B'], model_semantic_sha256='fixed-synthetic-state',
                       source_before={'fixture': 'source'}, started_wall=time.monotonic(),
                       started_cpu=time.process_time(), directory=folder, labels=['slot'], slot='slot')
            model = SimpleNamespace(core=SimpleNamespace(recorder=None, record_context=None), state_dict=lambda: {})
            obj = SimpleNamespace(pending=SimpleNamespace(close=lambda: None), current=row,
                  bound=SimpleNamespace(plan={'manifest_sha256':'data'}, study=SimpleNamespace(sources=lambda m:{'fixture':'source'})),
                  policy_identity={'sha256':'policy'}, results={})
            raised = None
            try:
                finish(obj, model)
            except Exception as exc:
                raised = repr(exc)
            rows.append(dict(case='duplicated_position_wrong_batch_dt_and_digest' if bad else 'valid_control',
                accepted=raised is None, output_status=row.get('status'), exception=raised,
                trace=json.loads(trace.read_bytes()), expected_positions=[0,1],
                expected_batch_indices=[[0,1],[0]], expected_dt=[[0.1,0.2],[0.3]],
                actual_retained_sample_count=sum(len(v['batch_indices']) for v in visits)))
    require(rows[0]['accepted'] and rows[1]['accepted'], 'counterexample did not demonstrate the frozen gap')
    result = dict(schema='C2-model-free-frozen-trace-gate-counterexample-v1',
        frozen_source=dict(path=str(SOURCE), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
        scope='Exact AST-extracted frozen finish_pending method, mocked recorder metadata and model digest; no Torch import, model, forward, backward, or optimizer execution.',
        original_source_unchanged=SOURCE.read_bytes()==raw,
        cases=rows, finding='Gate accepts duplicate time position, incorrect batch membership and dt/model identity despite correct record count. Existing recorder source may emit correct data; this exposes independent admission weakness, not measured production corruption.',
        expected_new_gate='Reject the bad fixture before any optimizer step; bind rows and footer state counts to the actual microbatch mask, dt and network digest.')
    (OUT/'frozen-c2_recording.py').write_bytes(raw)
    exclusive_json(OUT/'RESULT.json',result)
    print(json.dumps(dict(control_accepted=rows[0]['accepted'],bad_fixture_accepted=rows[1]['accepted'],source_sha256=result['frozen_source']['sha256'])))


if __name__ == '__main__':
    main()
