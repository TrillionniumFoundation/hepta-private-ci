"""AST-only frozen semantics: no truth tables, experiment entrypoint or expm."""
from pathlib import Path
from types import SimpleNamespace
from functools import lru_cache
import ast
import copy
import time
import numpy as np
from data_contract import canonical, digest, verify


def selected(path, names, constants, namespace, transformer=None):
    tree = ast.parse(Path(path).read_text(), filename=str(path))
    body = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names:
            body.append(node)
        elif isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) for t in node.targets):
            if any(t.id in constants for t in node.targets):
                body.append(node)
    found = {n.name for n in body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    if found != set(names):
        raise ValueError('missing selected source definitions: ' + str(path))
    module = ast.Module(body=body, type_ignores=[])
    if transformer is not None:
        module = transformer().visit(module)
    exec(compile(ast.fix_missing_locations(module), str(path), 'exec'), namespace)
    return namespace


def load(source_pins):
    for item in source_pins.values():
        verify(item)
    paths = {k: v['path'] for k, v in source_pins.items()}
    arithmetic = selected(paths['checked_replay'], {'checked_mm', 'MM'}, {'AUDIT'},
                          {'np': np, 'ast': ast})
    common = {'np': np, 'Path': Path, 'copy': copy, 'lru_cache': lru_cache,
              'checked_mm': arithmetic['checked_mm']}
    transform = arithmetic['MM']
    legacy = selected(paths['legacy_task'], {'public_features'}, {'ACTIONS', 'PUBLIC_NAMES'},
                      dict(common), transform)
    task_names = {'validate_public', 'initial', 'legal', 'due_request', 'successor',
                  'public_features', 'history_features', 'Oracle', 'evaluate_terminal'}
    task = selected(paths['joint_task'], task_names, {'SCHEMA', 'ACTIONS'},
                    dict(common, legacy_public_features=legacy['public_features']), transform)
    deployment = selected(paths['joint_deploy'], {'prior_mass', 'NumpyPolicy'},
                          {'SCHEMA', 'THRESHOLDS'},
                          dict(common, public_features=task['public_features']), transform)
    head_ns = dict(common)
    head_ns.update({key: task[key] for key in task_names})
    head_ns['NumpyPolicy'] = deployment['NumpyPolicy']
    head_names = {'head', 'predicted', 'outcomes', 'policy_value'}
    selected(paths['run_head_edit'], head_names, set(), head_ns, transform)
    plan_ns = {'np': np, 'time': time, 'canonical': canonical, 'sha': digest}
    selected(paths['planning'], {'OwnTableLaw', 'WorldPolicy', 'markov_key'}, set(), plan_ns)
    exported = {key: head_ns[key] for key in task_names | head_names}
    exported.update(NumpyPolicy=deployment['NumpyPolicy'], deploy=deployment,
                    OwnTableLaw=plan_ns['OwnTableLaw'], WorldPolicy=plan_ns['WorldPolicy'],
                    checked_mm=arithmetic['checked_mm'], arithmetic_audit=arithmetic['AUDIT'],
                    schema=task['SCHEMA'])
    return SimpleNamespace(**exported)
