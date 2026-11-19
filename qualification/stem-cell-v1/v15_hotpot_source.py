"""V15 original HotpotQA validation-distractor source owner; public/secret separation.

Source is human-written questions on Wikipedia, but this script does not run a
Reader and does not generate novel future/prospective independent cohorts.
Original HotpotQA content CC BY-SA 4.0; no benchmark rows committed to Git.
"""
import argparse
import hashlib
import json
from pathlib import Path

# Immutable official source identified by HF dataset-info checksum (7405 rows).
URL = 'https://curtis.ml.cmu.edu/datasets/hotpot/hotpot_dev_distractor_v1.json'
SOURCE_SHA256 = '4e9ecb5c8d3b719f624d66b60f8d56bf227f03914f5f0753d6fa1b359d7104ea'
SCHEMA = 'hepta.v15.hotpotqa-dev-distractor-source.v1'
N_EXPECTED = 7405


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                                   allow_nan=False).encode()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_once(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
        stream.write('\n')


def convert(raw, *, exact_count=None):
    if exact_count is None:
        exact_count = N_EXPECTED
    if not isinstance(raw, list) or len(raw) != exact_count or not 1 <= exact_count <= N_EXPECTED:
        raise ValueError('original complete expected dev cohort required')
    public, hidden, seen = [], {}, set()
    for row in raw:
        if not isinstance(row, dict) or not {'_id', 'question', 'context', 'answer', 'supporting_facts', 'type', 'level'} <= set(row):
            raise ValueError('complete HotpotQA official row required')
        ident, question, context = row['_id'], row['question'], row['context']
        if (not isinstance(ident, str) or not 1 <= len(ident) <= 128 or ident in seen
                or not isinstance(question, str) or not 1 <= len(question) <= 2048
                or not isinstance(context, list) or not 1 <= len(context) <= 32):
            raise ValueError('bounded unique public source required')
        seen.add(ident)
        articles, candidates = [], set()
        for entry in context:
            if not isinstance(entry, list) or len(entry) != 2:
                raise ValueError('source paragraph structure invalid')
            title, sentences = entry
            if (not isinstance(title, str) or not 1 <= len(title) <= 512
                    or not isinstance(sentences, list) or not 1 <= len(sentences) <= 256
                    or any(not isinstance(s, str) or len(s) > 16000 for s in sentences)):
                raise ValueError('source paragraph content/geometry invalid')
            if title in {a[0] for a in articles}:
                raise ValueError('duplicate public article title cannot anchor evidence')
            articles.append([title, sentences])
            candidates.update((title, i) for i in range(len(sentences)))
        facts = row['supporting_facts']
        if (not isinstance(facts, list) or not 1 <= len(facts) <= 16
                or any(not isinstance(x, list) or len(x) != 2 or not isinstance(x[0], str)
                       or type(x[1]) is not int or (x[0], x[1]) not in candidates for x in facts)):
            raise ValueError('hidden supporting facts not grounded in provided articles')
        if (not isinstance(row['answer'], str) or not 1 <= len(row['answer']) <= 2048
                or row['type'] not in ('bridge', 'comparison')
                or row['level'] not in ('easy', 'medium', 'hard')):
            raise ValueError('registered original answer/type/level required')
        public.append(dict(id=ident, question=question, context=articles))
        hidden[ident] = dict(answer=row['answer'], supporting_facts=[list(x) for x in facts],
                             type=row['type'], level=row['level'])
    return public, hidden


def source_owner(original_file, output):
    raw_bytes = Path(original_file).read_bytes()
    if hashlib.sha256(raw_bytes).hexdigest() != SOURCE_SHA256:
        raise ValueError('official upstream raw HotpotQA source SHA256 mismatch')
    raw = json.loads(raw_bytes)
    public, secret = convert(raw)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    manifest = dict(schema=SCHEMA, original_url=URL, original_sha256=SOURCE_SHA256,
                    source_license='CC-BY-SA-4.0', original_cases=len(public),
                    public_sha256=digest(public), hidden_sha256=digest(secret),
                    hidden_support_only_review=True, dataset_split='distractor_validation',
                    human_written_questions=True, actual_final_answers_generated=False,
                    source_time_prospective=False, training_examples=0, held_examples=len(public),
                    authority='DENY_ALL', model_selected=False, production_accepted=False)
    write_once(output/'public.json', public)
    write_once(output/'hidden-restricted.json', secret)
    write_once(output/'manifest.json', manifest)
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--official-source', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    m = source_owner(a.official_source, a.output)
    print(json.dumps(dict(schema=m['schema'],cases=m['original_cases'],public_sha256=m['public_sha256'])))


if __name__ == '__main__':
    main()
