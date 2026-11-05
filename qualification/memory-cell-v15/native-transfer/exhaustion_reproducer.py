"""Exercise real SQLite counter arithmetic; not reachable in practical time by counting."""
import importlib.util, json, pathlib, sys, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from authority_tests import authority, key, fixture_gate
from authority import COMPONENTS, bundle, digest, public, sign
MAX = 2**63 - 1
with tempfile.TemporaryDirectory() as d:
    a = authority(str(pathlib.Path(d)/'state.db'))
    item = bundle('scope', ['address'], [public(key(3))], [], {n:n.encode() for n in COMPONENTS})
    a.apply(sign(key(2), a.identity, 'create', dict(cell='cell', owner=public(key(3)), bundle=item)))
    a.db.execute('UPDATE cells SET epoch=? WHERE id=?', (MAX,'cell'))
    attempts = []
    for i, epoch in enumerate((MAX, MAX+1, MAX+1)):
        try:
            receipt = a.apply(sign(key(3), a.identity, 'restrict', dict(cell='cell', epoch=epoch,
                     expected=item['id'], acl=[]), f'exhaustion-{i}'))
            attempts.append(dict(outcome='accepted', receipt_epoch=receipt['result']['epoch']))
        except Exception as e:
            attempts.append(dict(outcome='rejected', error=type(e).__name__, reason=str(e)))
    row = a.db.execute('SELECT epoch,typeof(epoch) AS storage_type FROM cells').fetchone()
    print(json.dumps(dict(initial_epoch=MAX, stored=dict(row), attempts=attempts),indent=2))
