"""Independent binary64 forward loss and scalar Adam; no kernel imports."""
import math
import numpy as np
CALLS=0
MACS=0
def loss(arm,weights,inputs,targets,labels):
    global CALLS,MACS
    CALLS+=1
    MACS+=len(inputs)*{'A':35328,'B':35328,'C':36068,'L':4736}[arm]
    # Separate control flow, einsum contraction, scalar CE/MSE accumulation.
    def affine(x,w,b):return np.einsum('bi,ij->bj',x,weights[w],optimize=False)+weights[b]
    if arm=='L':
        joint=affine(inputs,'WL','bL');logits=joint[:,:10];pixels=joint[:,10:]
    else:
        first=affine(inputs,'W1','b1');first[first<0]=0
        if arm=='C':
            second=affine(first,'Ws','bs');second[second<0]=0
            joint=affine(second,'Wo','bo');logits=joint[:,:10];pixels=joint[:,10:]
        else:
            logits=affine(first,'Wc','bc')
            probability=np.empty_like(logits)
            for row in range(len(inputs)):
                top=max(float(z) for z in logits[row]);terms=[math.exp(float(z)-top) for z in logits[row]];total=sum(terms)
                probability[row]=[t/total for t in terms]
            joined=np.hstack([first,probability*(1.0 if arm=='A' else 0.0)])
            second=affine(joined,'Wr','br');second[second<0]=0
            pixels=affine(second,'Wi','bi')
    total=0.
    for i in range(len(inputs)):
        top=max(float(v) for v in logits[i])
        ce=math.log(sum(math.exp(float(v)-top) for v in logits[i]))+top-float(logits[i,labels[i]])
        mse=sum((1/(1+math.exp(-float(pixels[i,j])))-float(targets[i,j]))**2 for j in range(64))/64
        total+=ce+mse
    return total/len(inputs)

def scalar_adam(value,gradient,step,moment=0.,variance=0.):
    # Each operator rounded separately to binary32, independent scalar expression.
    f=np.float32
    moment=f(f(f(.9)*f(moment))+f(f(.1)*f(gradient)))
    variance=f(f(f(.999)*f(variance))+f(f(.001)*f(f(gradient)*f(gradient))))
    mhat=f(moment/f(1-.9**step));vhat=f(variance/f(1-.999**step))
    update=f(f(f(.001)*mhat)/f(f(math.sqrt(float(vhat)))+f(1e-8)))
    return f(f(value)-update),moment,variance
