"""Read-only source and score replay of the frozen candidate-space experiment.

Recomputes every prompt/option/token binding and answer-space score ordering.
Never performs model inference, authenticates the experimenter, or grants
production qualification. Full original source scope IS a choice-space oracle.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

from offline_event_reader_trial import ARMS, inputs, messages, write
from offline_smol_reader import ByteLevel, PINS, PROFILE, digest, verify_files
from reader_candidate_capacity import SCHEMA, INPUT_LIMIT, candidates


def validate_choice_scores(row, choices, tokenizer):
    if len(row['candidates']) != len(choices) or len(choices) != len(set(choices)):
        raise ValueError('incomplete candidate score census')
    scores = row['candidates']
    if [s.get('value') for s in scores] != list(choices):
        raise ValueError('candidate score identities drifted')
    for s in scores:
        tokens = tokenizer.encode(' '+s['value'])
        if (type(s.get('token_count')) is not int or s['token_count'] != len(tokens)
            or s.get('token_digest') != digest(tokens)):
            raise ValueError('candidate tokenization changed')
        summation, average = s.get('log_likelihood'), s.get('mean_log_likelihood')
        if any(type(v) not in (float,int) or not math.isfinite(v) or v > 0 for v in (summation,average)):
            raise ValueError('nonfinite or positive log probabilities')
        if not math.isclose(average * len(tokens), summation, abs_tol=1e-4):
            raise ValueError('candidate score normalization changed')
    ranked = sorted(scores, key=lambda s: (-s['mean_log_likelihood'], list(choices).index(s['value'])))
    if row.get('ranking') != [s['value'] for s in ranked] or row.get('chosen') != ranked[0]['value']:
        raise ValueError('winner changed after inference')


def audit(archive, model, run_directory, output, generating_commit):
    verify_files(model)
    tokenizer = ByteLevel(model)
    plan, originals, _ = inputs(archive)
    root = Path(run_directory)
    fixed = json.loads((root/'preregistered.json').read_text())
    if (fixed.get('schema') != SCHEMA or fixed.get('source_commit') != generating_commit
        or fixed.get('weights_sha256') != PINS['model.safetensors']
        or fixed.get('candidate_pool_is_oracle') is not True
        or fixed.get('ranking_policy') != 'highest_mean_next_token_log_probability'
        or fixed.get('groups') is None or len(fixed['groups']) != 8):
        raise ValueError('preregistration drifted')
    raw_file = root/'candidate-scores.jsonl'
    if raw_file.is_symlink() or not raw_file.is_file() or raw_file.stat().st_size > 2*1024*1024:
        raise ValueError('bounded original journal required')
    raw = raw_file.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines()]
    if len(rows) != 48:
        raise ValueError('incomplete original score population')
    checked = 0
    for case in plan['cases']:
        qid = case['query']['identity']
        choices = candidates(case, originals)
        group = fixed['groups'][checked//len(ARMS)]
        if (group['question_id'] != qid or group['candidates'] != list(choices)
            or group['option_digest'] != digest(choices)
            or group['candidate_digest'] != case['candidate_digest']):
            raise ValueError('preinference candidate drift')
        for arm in ARMS:
            row = rows[checked]
            checked += 1
            requests = messages(case, arm, originals)
            tokens = tokenizer.encode(tokenizer.render(requests))
            if (row['question_id'] != qid or row['arm'] != arm
                or row['kind'] != case['kind'] or row['reader_profile'] != PROFILE
                or row['reader_identity'] != digest(PINS)
                or row['input_digest'] != digest(tokens)
                or row['input_tokens'] != len(tokens)
                or not 1 <= len(tokens) <= INPUT_LIMIT
                or row['option_digest'] != digest(choices)
                or row['candidate_digest'] != case['candidate_digest']
                or row['actually_evaluated_hypotheses'] != len(choices)):
                raise ValueError('source/request/reader binding drift')
            validate_choice_scores(row, choices, tokenizer)
    with __import__('zipfile').ZipFile(archive) as z:
        label_bytes = z.read('observations/labels.json')
    if hashlib.sha256(label_bytes).hexdigest() != plan['labels_sha']:
        raise ValueError('original labels digest changed')
    labels = {r['id']:r for r in json.loads(label_bytes)}
    counters = {}
    for arm in ARMS:
        subset = [r for r in rows if r['arm']==arm]
        counters[arm] = dict(
            planned=len(subset),
            correct=sum(r['chosen'] == labels[r['question_id']]['expected'] for r in subset),
            gold_options=sum(labels[r['question_id']]['expected'] in [s['value'] for s in r['candidates']] for r in subset),
            hypotheses=sum(len(r['candidates']) for r in subset),
            prompt_tokens=sum(r['input_tokens'] for r in subset),
        )
    reported=json.loads((root/'result.json').read_text())
    if (reported['source_commit'] != generating_commit
        or reported['raw_scores_sha256'] != hashlib.sha256(raw).hexdigest()
        or reported['actual_inferences'] != 48):
        raise ValueError('reported score journal identity changed')
    for arm, measured in counters.items():
        o = reported['by_arm'][arm]
        if (o['planned'] != measured['planned'] or o['chosen_correct'] != measured['correct']
            or o['oracle_answer_in_pool'] != measured['gold_options']
            or o['scored_candidates'] != measured['hypotheses']
            or o['prompt_tokens'] != measured['prompt_tokens']):
            raise ValueError('reported candidate score census changed')
    result = dict(
        schema='hepta.memory.candidate-score-replay.v1',
        original_journal_sha256=hashlib.sha256(raw).hexdigest(),
        original_generating_commit=generating_commit,
        source_archive_digest=fixed['source_archive_sha256'],
        validated_requests=checked, reexecuted_model_calls=0,
        original_weight_bytes_rechecked=True, original_prompt_bytes_reconstructed=True,
        source_labels_accessed_after_score_verification=True,
        candidate_space_is_oracle=True, human_sufficiency_review=False,
        production_accepted=False, arm_results=counters,
    )
    write(Path(output),result)
    return result


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('archive','model','run_dir','output'):
        p.add_argument(name,type=Path)
    p.add_argument('--generating-commit',required=True)
    a=p.parse_args()
    print(json.dumps(audit(a.archive,a.model,a.run_dir,a.output,a.generating_commit)))
