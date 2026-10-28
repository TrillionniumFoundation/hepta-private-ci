"""Preregistered maintenance mutations; never imported by the fresh reader."""

from common import canonical, executions, sha, validate_program


def mutate(previous, seed, stage):
    """Change the four opcodes and behavior on at least one fixed public probe."""
    validate_program(previous['value'])
    old = [r['result']['value'] for r in executions(previous['value'])]
    start = (37*stage + 17*previous['index'] + seed) % 216
    for offset in range(216):
        code = (start+offset) % 216
        program = [code//36, (code//6) % 6, code % 6, 6]
        if program != previous['value'] and [r['result']['value'] for r in executions(program)] != old:
            row = {**previous, 'version': previous['version']+1, 'active': True, 'value': program}
            row['source_id'] = sha(canonical(['hepta.adapter.skill-longrun.source.v1', seed,
                                            row['index'], row['version'], stage, program]))
            return row
    raise ValueError('no distinct bounded program in the declared vocabulary')
