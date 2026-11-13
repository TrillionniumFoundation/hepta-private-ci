"""Pure token/context diagnostics for the frozen 62-file packet; no Rust execution."""
import collections
import json
from pathlib import Path
from classify_fmt_items import inventories, groups
from inspect_fmt_tokens import HERE, ident

def main():
    report = json.loads((HERE / 'ITEM_INVENTORY_REVIEW.json').read_bytes())
    out = []
    for row in report['rows']:
        path = row['path']
        for side in ('before', 'after'):
            ts = inventories((HERE / side / path).read_text())[0]
            pairs, depth = groups(ts)
            stack, contexts = [], []
            for k, t in enumerate(ts):
                contexts.append(tuple(stack))
                if t[0] == 'punct' and t[1] in '([{':
                    stack.append(k)
                elif t[0] == 'punct' and t[1] in ')]}':
                    stack.pop()
            for c in row['residuals']:
                is_add = side == 'after' and c['before'] == [] and c['after'] == [',']
                is_remove = side == 'before' and c['before'] == [','] and c['after'] == []
                if not (is_add or is_remove):
                    continue
                i = c[side + '_range'][0]
                ctx = contexts[i]
                parent = ctx[-1] if ctx else None
                macro = [ts[o-2][1] for o in ctx if o > 1 and ts[o-1][1] == '!']
                out.append({
                    'path': path, 'side': side, 'i': i,
                    'next': ts[i+1][1] if i+1 < len(ts) else None,
                    'group': ts[parent][1] if parent is not None else None,
                    'group_intro': ' '.join(t[1] for t in ts[max(0, (parent or 0)-6):(parent or 0)+1]),
                    'macros': macro,
                    'context': ' '.join(t[1] for t in ts[max(0,i-12):i+6]),
                    'parent_content': ' '.join(t[1] for t in ts[parent+1:pairs[parent]]) if parent is not None and ts[parent][1] == '(' else None,
                })
    raw = (json.dumps(out, sort_keys=True, indent=2)+'\n').encode()
    with (HERE / 'COMMA_CONTEXT_REVIEW.json').open('xb') as f:
        f.write(raw)
    print(json.dumps({'identity': ident(raw), 'count':len(out),
                      'next_counts':{str(k):v for k,v in collections.Counter((x['side'],x['next']) for x in out).items()},
                      'macro_counts':{str(k):v for k,v in collections.Counter(tuple(x['macros']) for x in out).items()}}, indent=2))

if __name__ == '__main__':
    main()
