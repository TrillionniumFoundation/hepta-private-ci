"""V26 source-only safety audit and pinned historical public Qwen observation.

Scientific scope: a real, single *public* pretrained inference was logged on
GitHub run 38930227899, whose final result FAILED after generation because its
source-scanning safety guard matched its own forbidden literal. Nothing in this
module downloads weights, replays an original model, adjudicates answers, or
waives a failing CI run / production gate.
"""
from __future__ import annotations

import argparse
import ast
from hashlib import sha256
import json
import math
from pathlib import Path
import re


SCHEMA = 'hepta.stem.v26.public-qwen-physical-observation.no-go.v1'
RUN_ID = 38930227899
JOB_ID = 117072021837
HEAD = '182ddd103bd6ec1ac1d82721ecd4876d5d5a1229'
REVISION = '16706fc57485378d4ffaf54139b29ccc66ae08fa'
SOURCE_STEP = 'Pin public Qwen bytes and execute one genuine public-input model forward'
CHECK_STEP = 'No private-source/semantic-success promotion'
# Exact reviewed GitHub Actions bytes. Without third-party YAML installed, this
# digest is the fail-closed fallback rather than skipping workflow checks.
WORKFLOW_SHA256 = 'b56afa2c471ae25229daf3f5d29a981a7f9b9236b66a58b51f3f2c5698fcfdcf'
ALLOWED_USES = ('actions/checkout@v4', 'actions/setup-python@v5')
STEP_NAMES = (
    '', '',
    'Source-only tests before any pretrained model call',
    'Install pinned CPU inference dependencies',
    'Exercise actual pinned Transformers Qwen3 constructor with tiny synthetic weights',
    SOURCE_STEP,
    CHECK_STEP,
)


def strict_json(path):
    def uniq(rows):
        record = {}
        for key, value in rows:
            if key in record:
                raise ValueError('duplicate observation JSON key')
            record[key] = value
        return record
    return json.loads(Path(path).read_bytes(), object_pairs_hook=uniq,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON: '+x)))


def validate_observed_receipt(report):
    """Only validate the *reported* public log fields; never claim live attestation."""
    expected = {
        'schema', 'github_run_id', 'github_job_id', 'exact_source_head',
        'github_job_conclusion', 'pretrained_generation_step_conclusion',
        'failed_step', 'pinned_model_repo', 'pinned_model_revision',
        'model_spec_sha256', 'public_prompt_sha256', 'public_input_token_sha256',
        'public_output_token_sha256', 'public_answer_sha256', 'input_tokens',
        'output_tokens', 'generation_cpu_seconds', 'private_source_requests',
        'original_128_reference_requests', 'independent_semantic_accuracy',
        'original_task_gain_verified', 'independent_host_attestation',
        'production_authorized', 'decision',
    }
    if type(report) is not dict or set(report) != expected:
        raise ValueError('extra/missing original physical receipt fields')
    pinned = {
        'schema': SCHEMA,
        'github_run_id': RUN_ID,
        'github_job_id': JOB_ID,
        'exact_source_head': HEAD,
        'github_job_conclusion': 'failure',
        'pretrained_generation_step_conclusion': 'success',
        'failed_step': CHECK_STEP,
        'pinned_model_repo': 'Qwen/Qwen3-0.6B',
        'pinned_model_revision': REVISION,
        'model_spec_sha256': '411fd9bb4632905d528e479bbfb81ffb368994f8d410f107b2c07d25ef7c2607',
        'public_prompt_sha256': 'ec6560c4d0010e2dfacfe878e76425501e2fee8d829003145cb4ded90ff17a1e',
        'public_input_token_sha256': '32e496ce60ebf8c8f7561f8944d3776ddf903050bff6041b62cebdca267ae7e4',
        'public_output_token_sha256': '3b55fb1e2ddaa6eb49f9f98deb332aa3c64e7b18a0919d0b508b29a1e7f4713c',
        'public_answer_sha256': '001ab62b3b13855ff5c8ae51075c9cbe8dfeb61a8465b13082db82b47c39d97f',
        'input_tokens': 67,
        'output_tokens': 11,
        'private_source_requests': 0,
        'original_128_reference_requests': 0,
        'independent_semantic_accuracy': None,
        'original_task_gain_verified': False,
        'independent_host_attestation': False,
        'production_authorized': False,
        'decision': 'PUBLIC_PRETRAINED_FORWARD_OBSERVED_WORKFLOW_FAILED_NO_GO',
    }
    for k, value in pinned.items():
        if type(report[k]) is not type(value) or report[k] != value:
            raise ValueError('fabricated or altered public forward log field: '+k)
    cpu = report['generation_cpu_seconds']
    if type(cpu) is not float or not math.isfinite(cpu) or cpu != 2.822091619:
        raise ValueError('observed CPU data altered/nonfinite')
    return {
        'status': 'FIXED_SOURCE_OBSERVATION_CONSISTENT_NOT_HOST_ATTESTED',
        'real_public_forward_observed_in_prior_gh_log': True,
        'original_128_model_requests': 0,
        'production_authorized': False,
    }


def audit_workflow(workflow_text, smoke_source):
    """Analyze *structural YAML steps*, never search the audit step's own text.

    The old gate rejected the single public forward after success because it
    searched the YAML text containing its own string literal. This gate still
    disallows upload actions in EVERY step (including after the guard).
    """
    if type(workflow_text) is not str or type(smoke_source) is not str:
        raise ValueError('source not text')
    if sha256(workflow_text.encode('utf-8')).hexdigest() != WORKFLOW_SHA256:
        raise ValueError('public-only workflow differs from immutable reviewed bytes')
    # The full 1,200+ source-only regression matrix intentionally does not
    # install third-party packages. Preserve rigorous YAML parsing where it is
    # installed; if it is absent, only the frozen, pre-reviewed byte identity
    # may pass. Changed workflow bytes fail closed in *both* environments.
    try:
        import yaml
    except ModuleNotFoundError:
        data = None
    else:
        data = yaml.safe_load(workflow_text)
    if data is not None:
        if type(data) is not dict or data.get('permissions') != {'contents': 'read'}:
            raise ValueError('source-only workflow must have read-only permissions')
        jobs = data.get('jobs')
        if type(jobs) is not dict or set(jobs) != {'public-only-neural-forward'}:
            raise ValueError('unreviewed Qwen job/parallel upload destination')
        steps = jobs['public-only-neural-forward'].get('steps')
        if type(steps) is not list or len(steps) != len(STEP_NAMES):
            raise ValueError('missing/extra workflow step')
        for i, (step, expected_name) in enumerate(zip(steps, STEP_NAMES)):
            if type(step) is not dict or step.get('name', '') != expected_name:
                raise ValueError('unexpected workflow step ordering')
            action = step.get('uses')
            if i < 2:
                if action != ALLOWED_USES[i]:
                    raise ValueError('foreign action or hidden artifact upload')
                continue
            if action is not None:
                raise ValueError('public reference workflow cannot upload via actions')
            command = step.get('run')
            if type(command) is not str:
                raise ValueError('missing audited shell')
            if i != len(steps)-1:
                prohibited = ('upload-artifact@', 'gh api', 'scp ', 'curl ', 'wget ',
                              'requests.post', 'aws s3', 'base64 -w', 'source-only.json',
                              'locomo.json', 'original-bm25-private-routes.json')
                if any(token in command.lower() for token in prohibited):
                    raise ValueError('unreviewed private-data exfiltration in workflow')
            else:
                # Inspect the ENTIRE final shell. A command appended after this
                # check must not be able to exfiltrate private material.
                slash = chr(92)
                final_guard = (
                    'set -euo pipefail\n'
                    'export PYTHONPATH=qualification/stem-cell-v1\n'
                    + 'python qualification/stem-cell-v1/v26_public_smoke_audit.py ' + slash + '\n'
                    + '  --workflow .github/workflows/hepta-stem-v18-qwen-public-smoke.yml ' + slash + '\n'
                    + '  --source qualification/stem-cell-v1/v18_reference_public_smoke.py ' + slash + '\n'
                    + '  --receipt qualification/stem-cell-v1/V26_PUBLIC_QWEN_ORIGINAL_FORWARD_20261016.json\n'
                )
                if command != final_guard:
                    raise ValueError('final safety shell altered or extra action appended')
        source_step = steps[5]['run']
        if ('v18_reference_material_stage.py' not in source_step
            or 'v18_reference_public_smoke.py' not in source_step
            or 'umask 077' not in source_step or 'trap ' not in source_step
            or 'rm -rf' not in source_step):
            raise ValueError('altered pretrained-model/private staging protocol')
    source_tree = ast.parse(smoke_source)
    calls = [x for x in ast.walk(source_tree) if isinstance(x, ast.Call)
             and isinstance(x.func, ast.Attribute) and x.func.attr == 'generate']
    if len(calls) != 1 or 'attention_mask' not in {kw.arg for kw in calls[0].keywords}:
        raise ValueError('model generation omitted explicit full attention mask')
    return {'status': ('STRUCTURED_SOURCE_ONLY_NO_UPLOAD_GATE_VALID' if data is not None
                   else 'BYTE_FROZEN_SOURCE_ONLY_NO_UPLOAD_GATE_VALID'),
            'previous_false_positive_string_guard_replaced': True,
            'private_source_requests': 0,
            'production_authorized': False}


def cli():
    ap = argparse.ArgumentParser()
    for key in ('workflow', 'source', 'receipt'):
        ap.add_argument('--'+key, required=True)
    args = ap.parse_args()
    result = validate_observed_receipt(strict_json(args.receipt))
    result.update(audit_workflow(Path(args.workflow).read_text(), Path(args.source).read_text()))
    print(json.dumps(result, sort_keys=True))

if __name__ == '__main__':
    cli()
