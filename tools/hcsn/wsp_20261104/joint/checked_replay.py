"""Replay fixed experiment using explicit reductions, audit every BLAS matmul.

macOS NumPy emitted FP-status warnings despite finite bounded inputs and
outputs. This replay checks each product independently and uses the explicit
reduction result throughout. It changes no candidate grid, data, or gate.
"""
import ast,json,sys,time
from pathlib import Path
import numpy as np
AUDIT=dict(count=0,max_abs_difference=0.,max_input_abs=0.,max_output_abs=0.,nonfinite_count=0)

def checked_mm(a,b):
    a,b=np.asarray(a),np.asarray(b)
    if not np.isfinite(a).all() or not np.isfinite(b).all():raise ArithmeticError('nonfinite matmul input')
    if a.ndim==1 and b.ndim==1:ref=np.sum(a*b)
    elif a.ndim==1 and b.ndim==2:ref=np.sum(a[:,None]*b,axis=0)
    elif a.ndim==2 and b.ndim==1:ref=np.sum(a*b[None,:],axis=1)
    elif a.ndim==2 and b.ndim==2:ref=np.einsum('ij,jk->ik',a,b,optimize=False)
    else:raise ValueError('unsupported audit dimensions')
    with np.errstate(all='ignore'):product=np.matmul(a,b)
    if not np.isfinite(product).all() or not np.isfinite(ref).all():raise ArithmeticError('nonfinite matmul output')
    error=float(np.max(np.abs(product-ref)));bound=2e-12*(1+float(np.max(np.abs(ref))))
    if error>bound:raise ArithmeticError(('matmul disagrees with explicit sum',error,bound))
    AUDIT['count']+=1;AUDIT['max_abs_difference']=max(AUDIT['max_abs_difference'],error)
    AUDIT['max_input_abs']=max(AUDIT['max_input_abs'],float(np.max(abs(a))),float(np.max(abs(b))))
    AUDIT['max_output_abs']=max(AUDIT['max_output_abs'],float(np.max(abs(ref))))
    return ref

class MM(ast.NodeTransformer):
    def visit_BinOp(self,node):
        self.generic_visit(node)
        if isinstance(node.op,ast.MatMult):return ast.copy_location(ast.Call(func=ast.Name(id='checked_mm',ctx=ast.Load()),args=[node.left,node.right],keywords=[]),node)
        return node

root=Path(__file__).resolve().parent
source=(root/'run_head_edit.py').read_text()
source=source.replace("tree=ast.parse((ROOT/file).read_text(),filename=file)","tree=ast.parse((ROOT/file).read_text(),filename=file)\n    tree=ast.fix_missing_locations(MM().visit(tree));ns['checked_mm']=checked_mm")
tree=ast.fix_missing_locations(MM().visit(ast.parse(source)))
ns=dict(__name__='__main__',__file__=str(root/'run_head_edit.py'),checked_mm=checked_mm,MM=MM)
start=time.process_time();exec(compile(tree,str(root/'run_head_edit.py'),'exec'),ns)
AUDIT['audit_replay_cpu_seconds']=time.process_time()-start
Path(sys.argv[2],'matmul_audit.json').write_text(json.dumps(AUDIT,indent=2)+'\n')
print(json.dumps({'matmul_audit':AUDIT}),flush=True)
