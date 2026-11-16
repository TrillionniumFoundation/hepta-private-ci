"""Explicit old-parent/new-task binding for the unchanged V3 loss experiment.

The original parent bytes and target contract remain authoritative material.
Only the execution admission may differ, and the original task-link verifier
checks that difference again after loading the actual model. No old V3 request
is broadened and no selection or installation authority is granted.
"""
import hashlib
import json
from pathlib import Path

import llm_answer_eos_research_v3 as objective
import llm_initial_trainable_setup_v2 as setup
import llm_runtime_parent_step as step
import llm_runtime_pilot as runtime

SCHEMA = 'llm-runtime-parent-step-input-v4'
PROFILE = 'canonical-positive-zero-answer-eos-balanced-new-task-v4'
PLAN = 'llm-runtime-answer-eos-task-research-plan-v4'
SCOPE = 'public-fixture-existing-parent-new-task-research-no-independent-quality-or-installation'


def is_research(value):
    return type(value) is dict and value.get('schema') == SCHEMA


def plan_record(value):
    from llm_runtime_parent_step_v2 import sources
    record = objective.plan_record(value)
    record.update(schema=PLAN, scope=SCOPE, source=sources(PROFILE),
        objective_profile=objective.PROFILE, task_profile=PROFILE,
        task_link=value['initial_setup']['task_link'],
        participants=list(runtime.PARTICIPANTS) + ['actual-source-parent'])
    return record


def context(value):
    return dict(plan_sha256=value['initial_setup']['research_plan']['sha256'],
        recipe=runtime.identity(objective.RECIPE), profile=PROFILE,
        objective_profile=objective.PROFILE,
        task_link=runtime.identity(value['initial_setup']['task_link']))


def preflight(value):
    from llm_runtime_parent_step_v2 import SCHEMA as old_schema, NEW_TASK_PROFILE, sources
    from llm_runtime_parent_step_task_v2 import preflight as original
    step.closed(value, 'schema scope attempt_id operation experiment source files parent candidate output flags initial_setup')
    runtime.require(value['schema'] == SCHEMA and value['scope'] == step.SCOPE and
        value['source'] == sources(PROFILE) and value['flags'] == step.FALSES and
        all(v is False for v in value['flags'].values()), 'RESEARCH_V4_SCOPE_SOURCE')
    runtime.require(value['operation'] == 'train', 'RESEARCH_V4_TRAIN_ONLY')
    request = value['initial_setup']
    step.closed(request, 'profile recipe parent_material task_link research_plan')
    runtime.require(request['profile'] == PROFILE and runtime.canonical(request['recipe']) ==
                    runtime.canonical(setup.RECIPE), 'RESEARCH_V4_SETUP_RECIPE')
    role = request['research_plan']
    step.closed(role, 'path sha256')
    runtime.require(type(role['path']) is str and 0 < len(role['path']) <= 4096 and
                    Path(role['path']).is_absolute(), 'RESEARCH_V4_PLAN_PATH')
    step.digest(role['sha256'])
    raw = step.parent.read_regular(role['path'], step.MAX_INPUT)
    runtime.require(hashlib.sha256(raw).hexdigest() == role['sha256'], 'RESEARCH_V4_PLAN_PIN')
    # Validation-only reuse. This frame is never persisted or executed as V2.
    base = dict(value, schema=old_schema, source=sources(NEW_TASK_PROFILE),
        initial_setup={k: v for k, v in request.items() if k != 'research_plan'})
    base['initial_setup']['profile'] = NEW_TASK_PROFILE
    checked = original(base)
    frozen = json.loads(raw, object_pairs_hook=runtime.unique)
    runtime.require(runtime.canonical(frozen) == runtime.canonical(plan_record(value)),
                    'RESEARCH_V4_EXACT_PLAN')
    return checked
