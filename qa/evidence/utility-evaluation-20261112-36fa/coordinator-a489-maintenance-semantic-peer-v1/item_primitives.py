"""Pure import and delimiter primitives extracted unchanged; no original main."""

from lexical_primitives import lex

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
