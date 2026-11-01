"""Prepare fixed C++ coefficient words from the sealed Python V1 source."""
import argparse
import ast
import hashlib
import importlib
from pathlib import Path
import sys


def run(root, output):
    if output.exists():raise ValueError('Constants output is create-only')
    expected={'float32_pair.py':'63010529b91de196698c7b096a5bac94f73460f3a811f70b61a95d53ffd87ae9',
              'frozen_kernel.py':'69f5b28c61301bcb89d1c860212e7532fa292538214967e6871ed355e5e367b0'}
    for name,sha in expected.items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=sha:raise ValueError('Frozen source mismatch')
    sys.path.insert(0,str(root));fp=importlib.import_module('float32_pair');model=importlib.import_module('frozen_kernel')
    literals={}
    for node in ast.parse((root/'float32_pair.py').read_text()).body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            name=node.targets[0].id
            if name in ('LN2','INV_SQRT2','INV_SQRT2PI','LOG_SQRT2PI'):
                literals[name]=ast.literal_eval(node.value.args[0])
            elif name in ('P','Q','R','S','T','U'):
                literals[name]=ast.literal_eval(node.value.generators[0].iter)
    hx=lambda value:float(value).hex()
    def constant(value, nominal=None):
        p=fp.Pair(value);native=float(p.hi)+float(p.lo) if nominal is None else float(nominal)
        return '{'+hx(native)+','+hx(p.hi)+'f,'+hx(p.lo)+'f}'
    lines=['// Generated fixed constants only; no financial input is evaluated.','#pragma once','namespace hx {']
    for name in ['LN2','INV_SQRT2','INV_SQRT2PI','LOG_SQRT2PI']:
        lines.append('inline constexpr Fixed '+name+'='+constant(getattr(fp,name),float(literals[name]))+';')
    for name in ['P','Q','R','S','T','U']:
        values=getattr(fp,name)
        lines.append('inline constexpr std::array<Fixed,'+str(len(values))+'> CDF_'+name+' = {{'+','.join(constant(v,float(n)) for v,n in zip(values,literals[name]))+'}};')
    for name,values in [('NODES',model._NODES),('WEIGHTS',model._WEIGHTS)]:
        lines.append('inline constexpr std::array<Fixed,8> '+name+' = {{'+','.join(constant(v,v) for v in values)+'}};')
    import math
    lines.append('inline constexpr std::array<Fixed,17> FACTORIAL = {{'+','.join(constant(math.factorial(n),math.factorial(n)) for n in range(17))+'}};')
    lines.append('}')
    text='\n'.join(lines)+'\n'
    with output.open('x') as handle:handle.write(text)
    print(hashlib.sha256(text.encode()).hexdigest())


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--frozen-root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();run(args.frozen_root.resolve(),args.output)
