"""New-round actual cost DAG; shared full per cell, disjoint physical scopes once."""
from support import CELLS,CAP,number,cell_id,canonical,decode,metadata,digest
from decimal import Decimal
CATEGORIES=('P','T','O','S','M')

def vector(v):
    if type(v) is not dict or set(v)!=set(CATEGORIES):raise ValueError('exact categories')
    return {k:number(v[k]) for k in CATEGORIES}

def inventory(rows, *, verify_receipts=True):
    rows=decode(canonical(rows));index={};covered=set()
    for r in rows:
        if set(r)!={'id','dependencies','physical_scope_ids','actual_cpu_seconds','measured_categories',
                    'charge_categories','basis','beneficiaries','success','receipt','proof'}:raise ValueError('exact paid event')
        if type(r['id']) is not str or not r['id'] or r['id'] in index:raise ValueError('event identity')
        if type(r['success']) is not bool:raise ValueError('explicit failed ancestors retained')
        scopes=r['physical_scope_ids']
        if not scopes or len(scopes)!=len(set(scopes)) or any(type(s) is not str or not s for s in scopes) or covered.intersection(scopes):
            raise ValueError('physical scope overlap or omission')
        covered.update(scopes)
        total=number(r['actual_cpu_seconds']);charges=vector(r['charge_categories'])
        if sum(charges.values())<total:raise ValueError('full known cost, no silent zero')
        if r['basis']=='MEASURED_PARTITION':
            if vector(r['measured_categories'])!=charges or sum(charges.values())!=total:raise ValueError('measured partition exact')
        elif r['basis']=='WHOLE_MEASURED_CONSERVATIVE_P':
            if r['measured_categories'] is not None or any(charges[k]!=0 for k in ('T','O','S','M')) or charges['P']<total:
                raise ValueError('whole actual total is not an invented measured partition')
        elif r['basis']=='WHOLE_MEASURED_CONSERVATIVE_T':
            if r['measured_categories'] is not None or any(charges[k]!=0 for k in ('P','O','S','M')) or charges['T']!=total:raise ValueError('failed worker conservativeT')
        elif r['basis']=='WHOLE_MEASURED_TERMINAL_S':
            if r['measured_categories'] is not None or any(charges[k]!=0 for k in ('P','T','O','M')) or charges['S']!=total:raise ValueError('whole terminal actualS')
        elif r['basis']=='OBSERVED_M_CONSERVATIVE_PARENT_P_REMAINDER':
            if r['measured_categories'] is not None or any(charges[k]!=0 for k in ('T','O','S')) or sum(charges.values())!=total:raise ValueError('explicit residual basis')
        else:raise ValueError('unknown/nominal cost not ready')
        if not r['beneficiaries'] or len(r['beneficiaries'])!=len(set(r['beneficiaries'])) or not set(r['beneficiaries'])<={cell_id(c) for c in CELLS}:
            raise ValueError('exact standalone beneficiaries')
        if verify_receipts:
            import evidence
            evidence.validate(r,rows)
        if type(r['dependencies']) is not list or len(r['dependencies'])!=len(set(r['dependencies'])):raise ValueError('dependency list')
        index[r['id']]=r
    visited=set();active=set()
    def visit(key):
        if key in active or key not in index:raise ValueError('closed acyclic event DAG')
        if key in visited:return
        active.add(key)
        for dep in index[key]['dependencies']:visit(dep)
        active.remove(key);visited.add(key)
    for key in index:visit(key)
    # Physical provenance dependency does not make another arm's own T/O shared.
    # Allocation is explicit: P/M/S shared in full; own fitting/finalization one cell.
    all_cells={cell_id(c) for c in CELLS}
    for r in rows:
        v=vector(r['charge_categories'])
        if any(v[k]>0 for k in ('P','M','S')) and set(r['beneficiaries'])!=all_cells:raise ValueError('shared debit omitted from cell')
        if any(v[k]>0 for k in ('T','O')) and len(r['beneficiaries'])!=1:
            import evidence
            if not evidence.exact_shared_failed_T(r):raise ValueError('own T/O allocation; only exact pinned prior failure shared')
    if verify_receipts:
        import evidence
        evidence.require_carry(rows)
    return rows

def standalone(rows,cell, *, parent_p='0',parent_m='0',verify_receipts=True):
    rows=inventory(rows,verify_receipts=verify_receipts);cid=cell_id(cell)
    v={k:Decimal(0) for k in CATEGORIES}
    for r in rows:
        if cid in r['beneficiaries']:
            for k,x in vector(r['charge_categories']).items():v[k]+=x
    v['P']+=number(parent_p);v['M']+=number(parent_m)
    if v['P']>40 or v['O']>180 or v['S']>60 or v['M']>120:raise ValueError('category ceiling')
    debit=v['P']+v['T']+v['O']+v['S']+max(Decimal(20),v['M'])
    if debit>CAP:raise ValueError('actual standalone ceiling')
    future_m=max(Decimal(0),Decimal(120)-max(Decimal(20),v['M']))
    future_p=Decimal(40)-v['P']
    return {'categories':{k:str(x) for k,x in v.items()},'debit':str(debit),'future_M_planning_reserve':str(future_m),'future_P_planning_reserve':str(future_p),
            'remaining_O':str(180-v['O']),'remaining_S':str(60-v['S']),
            'fitting_room':str(CAP-debit-(180-v['O'])-(60-v['S'])-future_m-future_p)}

def inherited(account):
    return number(account['debit'])+number(account['remaining_O'])+number(account['remaining_S'])+number(account['future_M_planning_reserve'])+number(account['future_P_planning_reserve'])

def protect(account,process_cpu,next_unit,publication):
    # Estimates are admission planning, not bounds. The post-unit true check is separate.
    return inherited(account)+number(process_cpu)+number(next_unit)+number(publication)<=CAP

def actual_protected(account,process_cpu):return inherited(account)+number(process_cpu)<=CAP

def physical_total(rows,*,verify_receipts=True):
    return str(sum((number(r['actual_cpu_seconds']) for r in inventory(rows,verify_receipts=verify_receipts)),Decimal(0)))
