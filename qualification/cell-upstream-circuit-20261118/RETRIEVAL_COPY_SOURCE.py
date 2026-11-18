"""Describe reference copying in completed raw outputs; execute no task or model."""
import ast
import collections
import json
from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parent
RUN = ROOT / 'originals/run-1'


def normalized(answer):
    edits = json.loads(answer)['edits']
    assert len(edits) == 1
    return ast.dump(ast.parse(textwrap.dedent(edits[0]['new'])), include_attributes=False)


def main():
    report = json.loads((RUN / 'RESULT.json').read_text())
    counts, rows = collections.defaultdict(collections.Counter), []
    for outcome in report['outcomes']:
        if not outcome['arm'].endswith('_retrieval'):
            continue
        for path in sorted((RUN / outcome['path']).glob('node-*')):
            if not (path / 'OUTPUT.json').is_file():
                continue
            request, output = [json.loads((path / name).read_text()) for name in ('REQUEST.json', 'OUTPUT.json')]
            references = []
            for message in request['task']['messages']:
                if message['role'] != 'tool':
                    continue
                try:
                    value = json.loads(message['content'])
                except ValueError:
                    continue
                if value.get('schema') == 'hepta.training-reference.v1':
                    references.append(value)
            assert len(references) == 1
            counts[outcome['arm']]['calls'] += 1
            try:
                equal = normalized(output['answer']) == normalized(references[0]['answer'])
            except (ValueError, SyntaxError, KeyError, AssertionError, TypeError):
                equal = None
            counts[outcome['arm']]['copy_A_reference_AST'] += equal is True
            counts[outcome['arm']]['unparseable_AST'] += equal is None
            rows.append({'task': outcome['task_id'], 'arm': outcome['arm'], 'slot': path.name, 'copies_A_reference_AST': equal})
    result = {'schema': 'hepta.retrieval-answer-copy-readout.v1',
              'scope': 'descriptive AST comparison of already-complete raw outputs; no model, verifier or source modification',
              'counts': counts, 'rows': rows}
    (ROOT / 'RETRIEVAL_COPY_READOUT.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(counts, sort_keys=True))


if __name__ == '__main__':
    main()
