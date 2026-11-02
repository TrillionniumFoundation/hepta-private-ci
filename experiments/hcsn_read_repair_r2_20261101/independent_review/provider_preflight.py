"""Train-only independent paid-service, receipt and retrospective-replay checks."""
import ast
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from experiments.hcsn_read_repair_r2_20261101 import provider,worlds

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reject(call):
    try:call()
    except ValueError:return
    raise AssertionError('Malformed service operation unexpectedly accepted')


def main():
    sessions=queries=source_slots=negative_checks=0
    for task in ('mqar','selective','binding'):
        for condition in (*worlds.PRIMARY,*worlds.SECONDARY):
            full,partial,prices=worlds.batch(task,8,424131,'train',condition)
            for i,price in enumerate(prices):
                for policy in provider.POLICIES:
                    result,inputs=provider.plan(task,full['x'][i],partial['x'][i],partial['dt'][i],partial['observed'][i],float(price),policy,2/3,.16)
                    acquired={};markers={};timestamps=np.cumsum(partial['dt'][i],dtype=np.float64)
                    fees=0.;paid_slots=set()
                    for query,(digest,replayed) in zip(result['queries'],inputs,strict=True):
                        cursor=query['cursor'];wait=0.
                        for reply in query['receipts']:
                            slot=reply['slot'];assert slot<=cursor and not partial['observed'][i,slot]
                            assert np.array_equal(reply['event'],full['x'][i,slot])
                            assert reply['original_timestamp']==timestamps[slot]
                            assert slot not in paid_slots;paid_slots.add(slot);acquired[slot]=np.asarray(reply['event'],np.float32)
                            fees+=reply['charge'];wait+=reply['wait']
                        if wait:markers[cursor]=wait
                        assert np.isclose(query['paid_so_far'],fees)
                        assert np.isclose(query['answer_timestamp'],timestamps[cursor]+wait)
                        assert np.isclose(replayed['dt'].astype(np.float64).sum(),query['answer_timestamp'],atol=1e-6)
                        position=0;replay_clock=np.cumsum(replayed['dt'],dtype=np.float64)
                        for source in range(cursor+1):
                            expected=acquired.get(source,partial['x'][i,source])
                            assert np.array_equal(replayed['x'][position],expected)
                            assert replayed['observed'][position]==(partial['observed'][i,source] or source in acquired)
                            assert np.isclose(replay_clock[position],timestamps[source],atol=1e-6)
                            position+=1;source_slots+=1
                            if source in markers:
                                assert not replayed['observed'][position] and not replayed['x'][position].any()
                                assert np.isclose(replayed['dt'][position],markers[source])
                                assert replayed['observed'][position+1] and np.array_equal(replayed['x'][position+1],partial['x'][i,source])
                                assert replayed['dt'][position+1]==0;position+=2
                        assert position==len(replayed['dt'])
                        h=hashlib.sha256()
                        for key in ('x','dt','observed'):h.update(replayed[key].tobytes())
                        assert h.hexdigest()==digest==query['replay_sha256'];queries+=1
                    assert np.isclose(fees,result['fee']) and result['reads']==len(paid_slots)
                    assert np.isclose(result['read_wait'],.1*len(paid_slots))
                    if policy=='always_read':assert np.array_equal(result['answer'],full['y'][i,-4:])
                    sessions+=1
    full,partial,prices=worlds.batch('selective',1,424137,'train','missing')
    x,dt,observed=full['x'][0],partial['dt'][0],partial['observed'][0];slot=int(np.flatnonzero(~observed)[0]);price=.16
    service=provider.RawProvider(x,dt,observed,price)
    reject(lambda:service.read(slot));negative_checks+=1
    service.advance(len(x)-4);at=service.now;reply=service.read(slot)
    assert np.array_equal(provider.accept_reply(reply,slot,service.timestamps,price,at),x[slot])
    cached_at=service.now;cached=service.read(slot)
    assert cached['charge']==cached['wait']==0 and service.reads==1 and service.fees==price
    provider.accept_reply(cached,slot,service.timestamps,price,cached_at,cached=True)
    for name in ('original_timestamp','arrival_timestamp','charge','wait'):
        for bad in (float('nan'),float('inf'),-1.):
            changed=copy.deepcopy(reply);changed[name]=bad
            reject(lambda c=changed:provider.accept_reply(c,slot,service.timestamps,price,at));negative_checks+=1
    changed=copy.deepcopy(reply);changed['event'][4:12]=[.5,.5,0,0,0,0,0,0]
    reject(lambda:provider.accept_reply(changed,slot,service.timestamps,price,at));negative_checks+=1
    changed=copy.deepcopy(reply);changed['target_probability']=.9
    reject(lambda:provider.accept_reply(changed,slot,service.timestamps,price,at));negative_checks+=1
    reject(lambda:provider.accept_reply(reply,slot,service.timestamps,price,at,cached=True));negative_checks+=1
    q0=len(x)-4
    reject(lambda:provider.replay(partial['x'][0],dt,observed,{}, {q0:float(dt[q0+1])+1.0}));negative_checks+=1
    # The client implementation may hand the hidden raw table only to the
    # service constructor; no controller expression may inspect it directly.
    tree=ast.parse(Path(provider.__file__).read_text())
    plan=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='plan')
    loads=[n for n in ast.walk(plan) if isinstance(n,ast.Name) and n.id=='full_x' and isinstance(n.ctx,ast.Load)]
    assert len(loads)==1
    payload=dict(schema='hcsn.read-repair-r2.independent-preflight.v1',passed=True,
        source_hashes={str(Path(p).relative_to(ROOT)):sha(p) for p in [provider.__file__,worlds.__file__,__file__]},
        fixtures='Train-only seeds424131/424137; no dev/confirm or neural model execution',
        sessions=sessions,query_replays=queries,original_source_slot_checks=source_slots,negative_checks=negative_checks,
        cache_once_per_slot=True,all_conservative_repaired_answers_match_environment=True,
        client_full_table_uses='Exactly one full_x load, passed only to RawProvider construction; no client peek',
        scope='Supplied local provider contract and prefix reconstruction only; no task efficacy, external provider ownership or production qualification',
        all_blockers_closed=False,production_activation=False)
    with (HERE/'READ_PROVIDER_PREFLIGHT.json').open('w') as stream:json.dump(payload,stream,indent=2,sort_keys=True);stream.write('\n')
    print(json.dumps({k:payload[k] for k in ('passed','sessions','query_replays','original_source_slot_checks','negative_checks')},sort_keys=True))


if __name__=='__main__':main()
