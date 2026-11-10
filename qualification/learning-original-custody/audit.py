#!/usr/bin/env python3
"""Non-authoritative, fail-closed completeness precheck for an original learning loop.

Hashes bytes but cannot authenticate a signature, an owner, a human operator, or
an economic benefit. NEVER emits CLOSED or grants any runtime capability.
"""
import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import stat

STAGES = ('experience', 'dataset', 'training', 'evaluation', 'proposal',
          'selection', 'published_current', 'final_use', 'next_use',
          'learning_next_use')
EVALUATION_NO_UPDATE_STAGES = tuple(stage for stage in STAGES if stage != 'proposal')
TRAINER_NO_UPDATE_STAGES = tuple(stage for stage in STAGES if stage not in ('evaluation', 'proposal'))
HEX64 = re.compile(r'^[0-9a-f]{64}$')
HEX40 = re.compile(r'^[0-9a-f]{40}$')
ATTEMPT_STATES = frozenset(('completed', 'failed', 'cancelled', 'pending', 'unknown'))
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_RECEIPT_BYTES = 64 * 1024 * 1024


def _unique_json_object(pairs):
    # A last-key-wins parse can hide conflicting custody/version declarations.
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _reject_nonfinite_json(_token):
    raise ValueError('non-finite JSON constant')


def inspect(manifest: Path) -> dict:
    issues = []
    total = Decimal('0')
    checks = 0
    def fail(code):
        if code not in issues:
            issues.append(code)

    try:
        root = manifest.resolve(strict=True).parent
        # Limit the read itself, not merely the size of an already loaded blob.
        with manifest.open('rb') as stream:
            raw_manifest = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(raw_manifest) > MAX_MANIFEST_BYTES:
            raise ValueError('manifest exceeds maximum bytes')
        record = json.loads(raw_manifest.decode('utf-8'),
                            object_pairs_hook=_unique_json_object,
                            parse_constant=_reject_nonfinite_json)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        return {'status': 'HOLD', 'integrity': 'FAIL', 'issues': [f'bad_manifest:{type(exc).__name__}'],
                'owner_authenticated': False, 'benefit_established': False}
    if not isinstance(record, dict) or record.get('schema') != 'hepta-original-learning-custody-precheck-v1':
        fail('schema')
        record = record if isinstance(record, dict) else {}
    if not isinstance(record.get('source_head'), str) or not HEX40.fullmatch(record['source_head']):
        fail('source_head')
    ids = [record.get(field) for field in ('operation_id', 'next_operation_id', 'source_task_id', 'next_task_id')]
    if any(not isinstance(x, str) or not x or len(x) > 160 for x in ids):
        fail('operation_or_task_id')
    if ids[0] == ids[1]:
        fail('next_operation_not_distinct')
    if ids[2] == ids[3]:
        fail('next_task_not_distinct')
    baseline, chosen = record.get('baseline_bundle'), record.get('selected_bundle')
    if any(not isinstance(x, str) or not HEX64.fullmatch(x) for x in (baseline, chosen)):
        fail('version_digest')
    decision = record.get('decision')
    if decision not in ('adopt', 'no_update'):
        fail('selection_decision')
    elif (decision == 'adopt' and chosen == baseline) or (decision == 'no_update' and chosen != baseline):
        fail('selection_version_mismatch')

    # The original coordinator admits three different no-update cuts:
    # TrainingNoUpdateV2 -> Selection; Evaluation(NoUpdate) -> Selection;
    # Evaluation(Qualified) -> Proposal(NoAdmissibleUpdate) -> Selection.
    # Adopt also requires its original anchored Proposal(UpdateCandidates).
    # Never invent Evaluation or Proposal when that stage was not executed.
    origin = record.get('no_update_origin')
    if decision == 'no_update':
        if origin not in ('trainer', 'evaluation', 'proposal'):
            fail('no_update_origin')
    elif origin is not None:
        fail('no_update_origin_not_applicable')
    trainer_no_update = decision == 'no_update' and origin == 'trainer'
    evaluator_no_update = decision == 'no_update' and origin == 'evaluation'
    stages = (TRAINER_NO_UPDATE_STAGES if trainer_no_update else
              EVALUATION_NO_UPDATE_STAGES if evaluator_no_update else STAGES)

    # Claimed roles do not prove authentic custody or independent operators.
    # The original trainer, selector and observer remain separate on both paths.
    custody = record.get('operator_custody')
    custody = custody if isinstance(custody, dict) else {}
    roles = ('trainer', 'selector', 'observer') if trainer_no_update else (
        'trainer', 'evaluator', 'holdout', 'selector', 'observer')
    operators = [custody.get(name) for name in roles]
    if any(not isinstance(x, str) or not x.strip() for x in operators):
        fail('operator_custody_missing')
    elif len(set(operators)) != len(operators):
        fail('same_operator_multiple_roles')

    entries = record.get('original_receipts')
    if not isinstance(entries, dict) or set(entries) != set(stages):
        fail('receipt_coverage')
        entries = entries if isinstance(entries, dict) else {}
    seen_paths = set()
    seen_digests = set()
    for stage in stages:
        entry = entries.get(stage)
        if not isinstance(entry, dict):
            fail(f'missing_receipt:{stage}')
            continue
        path, sha = entry.get('file'), entry.get('sha256')
        if not isinstance(path, str) or not path or Path(path).is_absolute() or '..' in Path(path).parts:
            fail(f'unsafe_receipt_path:{stage}')
            continue
        if not isinstance(sha, str) or not HEX64.fullmatch(sha):
            fail(f'invalid_receipt_digest:{stage}')
            continue
        if path in seen_paths or sha in seen_digests:
            fail(f'duplicate_receipt:{stage}')
        seen_paths.add(path)
        seen_digests.add(sha)
        try:
            p = root / path
            if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(root):
                raise ValueError('unsafe file')
            # Pin the opened descriptor: a file may be replaced or grow after
            # path checks. Never stream unlimited bytes from an untrusted owner.
            flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
            fd = os.open(p, flags)
            try:
                opened = os.fstat(fd)
                if not stat.S_ISREG(opened.st_mode) or opened.st_size > MAX_RECEIPT_BYTES:
                    raise ValueError('receipt not regular or exceeds maximum bytes')
                digest = hashlib.sha256()
                consumed = 0
                while True:
                    chunk = os.read(fd, min(1024 * 1024, MAX_RECEIPT_BYTES - consumed + 1))
                    if not chunk:
                        break
                    consumed += len(chunk)
                    if consumed > MAX_RECEIPT_BYTES:
                        raise ValueError('receipt grew beyond maximum bytes')
                    digest.update(chunk)
                digest = digest.hexdigest()
            finally:
                os.close(fd)
            if digest != sha:
                fail(f'receipt_bytes_mismatch:{stage}')
            else:
                checks += 1
        except (OSError, ValueError):
            fail(f'receipt_unreadable:{stage}')
        expected_operation = ids[1] if stage == 'next_use' else ids[0]
        if entry.get('operation_id') != expected_operation:
            fail(f'foreign_operation:{stage}')
        if stage == 'next_use' and entry.get('learning_operation_id') != ids[0]:
            fail('next_use_unbound_to_learning')
        # The ordinary consumer and the learning coordinator's terminal
        # NextUse are DIFFERENT originals. The coordinator receipt is part of
        # the learning operation; it cannot be replaced with a consumer receipt.
        if stage == 'learning_next_use':
            if entry.get('next_operation_id') != ids[1]:
                fail('learning_next_use_unbound_to_consumer_operation')
            if entry.get('next_task_id') != ids[3]:
                fail('learning_next_use_unbound_to_consumer_task')
        expected_task = ids[3] if stage == 'next_use' else ids[2]
        if entry.get('task_id') != expected_task:
            fail(f'foreign_task:{stage}')
        if stage in ('published_current', 'final_use', 'next_use', 'learning_next_use') and entry.get('bundle_sha256') != chosen:
            fail(f'wrong_consumed_version:{stage}')

    # Each admitted attempt must have a terminal or explicitly unresolved
    # record, including failed/cancelled attempts; UNKNOWN is never success.
    admitted, attempts = record.get('admitted_attempt_ids'), record.get('attempts')
    if not isinstance(admitted, list) or not isinstance(attempts, list):
        fail('attempt_inventory_missing')
        admitted, attempts = [], []
    if not admitted or any(not isinstance(x, str) or not x for x in admitted) or len(set(x for x in admitted if isinstance(x, str))) != len(admitted):
        fail('attempt_inventory_invalid')
    got = []
    for n, attempt in enumerate(attempts):
        if not isinstance(attempt, dict):
            fail(f'attempt_type:{n}')
            continue
        aid = attempt.get('id')
        if not isinstance(aid, str) or not aid:
            fail(f'attempt_id:{n}')
        got.append(aid)
        state = attempt.get('state')
        if not isinstance(state, str) or state not in ATTEMPT_STATES:
            fail(f'attempt_state:{n}')
        if state in ('pending', 'unknown'):
            fail('unresolved_attempts')
        if not isinstance(attempt.get('cost_usd'), str):
            fail(f'attempt_cost:{n}')
            continue
        try:
            amount = Decimal(attempt['cost_usd'])
            if not amount.is_finite() or amount < 0:
                raise InvalidOperation()
            total += amount
        except InvalidOperation:
            fail(f'attempt_cost:{n}')
    if len(got) != len(set(x for x in got if isinstance(x, str))) or (
        all(isinstance(x, str) for x in admitted) and set(x for x in got if isinstance(x, str)) != set(admitted)
    ):
        fail('attempt_inventory_mismatch')
    # This checks supplied files and self-declarations, not their signatures,
    # current trust, live owner isolation, actual custody or opportunity cost.
    return {'status': 'HOLD', 'integrity': 'PASS' if not issues else 'FAIL',
            'receipt_bytes_matched': checks, 'receipt_bytes_required': len(stages),
            'declared_attempt_cost_usd': str(total), 'issues': issues,
            'owner_authenticated': False, 'independent_holdout_proved': False,
            'original_stage_replay_proved': False, 'full_cost_completeness_proved': False,
            'benefit_established': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    result = inspect(args.manifest)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result['integrity'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
