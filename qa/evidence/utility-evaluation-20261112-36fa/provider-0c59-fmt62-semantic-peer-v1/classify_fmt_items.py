"""Pure helper for manual review: exact use/mod inventories and residual tokens."""
import collections
import difflib
import json
from pathlib import Path
from inspect_fmt_tokens import HERE, ident, lex

def groups(tokens):
    stack, pairs, depths = [], {}, []
    close = {')':'(',']':'[','}':'{'}
    for i,t in enumerate(tokens):
        depths.append(len(stack))
        s=t[1]
        if t[0]=='punct' and s in '([{':stack.append((s,i))
        elif t[0]=='punct' and s in close:
            assert stack and stack[-1][0]==close[s], ('delimiter',i,s)
            _,j=stack.pop();pairs[i]=j;pairs[j]=i
    assert not stack
    return pairs, depths

def use_paths(values):
    # This only enumerates actual Rust use-tree leaves; it never edits source.
    def part(seq,prefix):
        if '{' in seq:
            k=seq.index('{'); assert seq[-1]=='}'
            pre=seq[:k]
            if pre and pre[-1]=='::':pre=pre[:-1]
            added=prefix+(['::'] if prefix and pre else [])+pre
            content=seq[k+1:-1];depth=0;start=0;out=[]
            for i,x in enumerate(content+['END']):
                if x=='{':depth+=1
                elif x=='}':depth-=1
                if (x==',' and depth==0) or x=='END':
                    if i>start:out+=part(content[start:i],added)
                    start=i+1
            return out
        if 'as' in seq:
            k=seq.index('as');leaf,alias=seq[:k],seq[k:]
        else:leaf,alias=seq,[]
        if leaf==['self'] and prefix:path=prefix
        else:path=prefix+(['::'] if prefix and leaf else [])+leaf
        return [tuple(path+alias)]
    return part(values,[])

def inventories(text):
    tok,comments=lex(text);pairs,depth=groups(tok);removed=set();uses=[];mods=[];use_raw=[];mod_raw=[]
    for i,t in enumerate(tok):
        if depth[i]!=0 or t[0]!='identifier' or t[1] not in ['use','mod']:continue
        if i in removed:continue
        if t[1]=='mod' and not (i+2<len(tok) and tok[i+1][0]=='identifier' and tok[i+2][1]==';'):continue
        j=i-1;vis=[]
        if j>=0 and tok[j][1]==')' and pairs[j]>0 and tok[pairs[j]-1][1]=='pub':
            start=pairs[j]-1;vis=[x[:2] for x in tok[start:i]];j=start-1
        elif j>=0 and tok[j][1]=='pub':
            vis=[tok[j][:2]];j-=1
        attrs=[]
        while j>=0 and tok[j][1]==']' and pairs[j]>0 and tok[pairs[j]-1][1]=='#':
            start=pairs[j]-1;attrs=[x[:2] for x in tok[start:j+1]]+attrs;j=start-1
        start=j+1
        end=i+1
        while end<len(tok) and not(depth[end]==0 and tok[end][1]==';'):end+=1
        assert end<len(tok)
        raw=text[tok[start][2]:tok[end][3]]
        common=[tuple(map(tuple,attrs)),tuple(map(tuple,vis))]
        if t[1]=='use':
            uses += [tuple(common+[leaf]) for leaf in use_paths([x[1] for x in tok[i+1:end]])]
            use_raw.append(raw)
        else:
            assert not any(x[1]=='macro_use' for x in tok[start:end])
            mods.append(tuple(common+[(tok[i+1][1],)]));mod_raw.append(raw)
        removed.update(range(start,end+1))
    return [t for i,t in enumerate(tok) if i not in removed],uses,mods,use_raw,mod_raw,comments

def main():
    rows=[];residuals=[]
    d=json.loads((HERE/'LEXICAL_DIAGNOSTIC.json').read_text())
    for entry in d['rows']:
        path=entry['path'];before=(HERE/'before'/path).read_text();after=(HERE/'after'/path).read_text()
        a,au,am,aur,amr,ac=inventories(before);b,bu,bm,bur,bmr,bc=inventories(after)
        assert collections.Counter(au)==collections.Counter(bu),('changed use',path)
        assert collections.Counter(am)==collections.Counter(bm),('changed mod',path)
        assert [x[:2] for x in ac]==[x[:2] for x in bc],('changed comments',path)
        assert [x[:2] for x in a if x[0]=='literal']==[x[:2] for x in b if x[0]=='literal'],('changed literal',path)
        av,bv=[x[:2] for x in a],[x[:2] for x in b]
        changes=[]
        for op,i,j,k,l in difflib.SequenceMatcher(a=av,b=bv,autojunk=False).get_opcodes():
            if op=='equal':continue
            row={'op':op,'before_range':[i,j],'after_range':[k,l],
                 'before':[x[1] for x in av[i:j]],'after':[x[1] for x in bv[k:l]],
                 'before_context':' '.join(x[1] for x in av[max(0,i-14):min(len(av),j+14)]),
                 'after_context':' '.join(x[1] for x in bv[max(0,k-14):min(len(bv),l+14)])}
            changes.append(row)
        rows.append({'path':path,'use_leaf_count':len(au),'module_item_count':len(am),'use_inventory_equal':True,
                     'module_inventory_equal':True,'use_items_before':aur,'use_items_after':bur,
                     'module_items_before':amr,'module_items_after':bmr,
                     'comments_exact_equal':True,'remaining_literal_sequence_exact_equal':True,
                     'residuals':changes})
        for x in changes:
            if (x['before'],x['after']) not in [([],[',']),([','],[])]:residuals.append({'path':path,**x})
    out={'schema':'hepta-fmt62-exact-import-module-inventories-v1','rows':rows,
         'scope':'Inventory equality is exact after resolving use trees; attributes and visibility remain attached. All module records exclude macro_use. Residual control-flow/optional punctuation requires concrete manual review.'}
    raw=(json.dumps(out,sort_keys=True,indent=2)+'\n').encode()
    with (HERE/'ITEM_INVENTORY_REVIEW.json').open('xb') as f:f.write(raw)
    with (HERE/'RESIDUAL_NONCOMMA_HUNKS.json').open('x') as f:json.dump(residuals,f,indent=2);f.write('\n')
    print(json.dumps({'inventory':ident(raw),'files':len(rows),'strict_body_token_equal_after_imports':sum(not x['residuals'] for x in rows),'remaining_noncomma_hunks':len(residuals),'files_with_noncomma':sorted(set(Path(x['path']).name for x in residuals))},indent=2))

if __name__=='__main__':main()
