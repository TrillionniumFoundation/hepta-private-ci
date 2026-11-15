"""Validate typed real forwarding traces separately from unchanged public bytes."""
from collections import Counter
from . import observations

WORDS = 20


def validate(calls, observed):
    assert all(len(row) == WORDS and row[0] in (1, 2) for row in calls)
    parse = [row[1:18] for row in calls if row[0] == 1]
    assert all(row[18:] == (0, 0) for row in calls if row[0] == 1)
    counts = Counter({'parse_' + key: value for key, value in observations.native(parse, observed).items()})
    # Calls must follow the unchanged observer's parse/render stage sequence.
    sequence = [1, 2, 4, 10, 11, 12, 3] if observed['parse_tag'] == 0 else [1, 3]
    ranks = {stage: i for i, stage in enumerate(sequence)}
    assert all(row[1] in ranks for row in calls)
    assert [ranks[row[1]] for row in calls] == sorted(ranks[row[1]] for row in calls)
    render = [row for row in calls if row[0] == 2]
    if observed['parse_tag']:
        assert not render
        return counts
    for stage, outcome in zip((10, 11, 12, 3), observed['outcomes']):
        rows = [row for row in render if row[1] == stage]
        completed = outcome['events']['as_ref'] // 2
        if outcome['kind'] == 'panic' and outcome['payload'] in ('input fault 5', 'input fault 7'):
            completed -= 1
        assert completed >= 0
        keys = [row for row in rows if row[7] == 0]
        final = [row for row in rows if row[7] != 0]
        assert rows == keys + final and len(keys) == completed
        for index, row in enumerate(keys):
            check(row)
            error = row[15]
            assert row[3] == row[13] == row[14] == 80
            assert error in (0, 1)
            if error:
                assert index == len(keys) - 1 and row[16] == 1 and row[17] == index
            counts['render_check_candidate'] += 1
        if outcome['kind'] == 'panic':
            assert not final
            # Fault 8 can arise while dropping the tuple after a successful check.
            assert all(row[15] == 0 for row in keys)
        elif outcome['kind'] == 'error' and 'DuplicateValue' in outcome['error']['debug']:
            assert keys and keys[-1][15] == 1 and not final
            assert all(row[15] == 0 for row in keys[:-1])
        else:
            assert all(row[15] == 0 for row in keys)
            assert len(final) == (2 if outcome['kind'] == 'success' else 1)
            query = final[0]
            check(query)
            assert query[7] == 1 and query[3] == query[14] == 80
            counts['render_query'] += 1
            if outcome['kind'] == 'success':
                emit = final[1]
                check(emit)
                assert emit[7] == 2 and query[15:] == emit[15:] == (0, 0, 0, 0, 0)
                assert emit[2] == query[2] and emit[13] == query[13]
                assert emit[3] == emit[14] == emit[13] == 80 + outcome['rendered_bytes']
                counts['render_emit'] += 1
            else:
                debug = outcome['error']['debug']
                assert ('MissingValue' in debug, 'ExtraValue' in debug) in ((True, False), (False, True))
                wanted = 2 if 'MissingValue' in debug else 3
                assert query[15] == wanted and query[13] == 80
                assert query[16] == (2 if wanted == 2 else 1)
    assert sum(counts.values()) == len(calls)
    return counts


def check(row):
    symbol, _, source_len, capacity, workspace_len, status = row[:6]
    revision, op, zero0, zero1 = row[6:10]
    version, operation, source, required, written, error, origin, index, offset, size = row[10:]
    assert symbol == 2 and source_len >= 64 and capacity >= 80 and workspace_len == 32 and status == 0
    assert (revision, zero0, zero1, version, operation, source) == (1, 0, 0, 1, op, source_len)
    assert op in (0, 1, 2) and required >= 80 and written <= capacity
    if error:
        assert required == written == 80 and origin in (1, 2, 3)
        assert offset <= source_len and size <= source_len - offset
    else:
        assert origin == index == offset == size == 0
