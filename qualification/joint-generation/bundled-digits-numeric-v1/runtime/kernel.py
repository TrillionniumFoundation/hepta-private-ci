"""Full-size synthetic-only numerical kernel; no data loaders or persistence."""
import hashlib, json, math, struct
import numpy as np
F=np.float32
SHAPES={'A': [('W1',(64,128)),('b1',(128,)),('Wc',(128,10)),('bc',(10,)),('Wr',(138,128)),('br',(128,)),('Wi',(128,64)),('bi',(64,))], 'C':[('W1',(64,128)),('b1',(128,)),('Ws',(128,138)),('bs',(138,)),('Wo',(138,74)),('bo',(74,))], 'L':[('WL',(64,74)),('bL',(74,))]}
SHAPES['B']=SHAPES['A']
COUNTS={'models':0,'updates':0,'forward_calls':0,'forward_examples':0,'backward_calls':0,'backward_examples':0,'dense_forward_macs':0,'dense_backward_macs':0,'forward_matmuls':0,'backward_matmuls':0}
MAC={'A':35328,'B':35328,'C':36068,'L':4736}
def key(purpose,name,counter=0,epoch=0):
    return json.dumps(['digits-train-design-v2',purpose,'qualification',701,epoch,name,counter],separators=(',',':'),ensure_ascii=True).encode('ascii')
def uniform(purpose,name,counter=0,epoch=0):
    k=int.from_bytes(hashlib.sha256(key(purpose,name,counter,epoch)).digest()[:8],'big')
    return ((k>>12)+0.5)/2**52
def noise(clean,name):
    vals=[]
    for j in range(32):
        u=uniform('noise',name,2*j);v=uniform('noise',name,2*j+1)
        r=math.sqrt(-2*math.log(u)); a=2*float.fromhex('0x1.921fb54442d18p+1')*v
        for g in (r*math.cos(a),r*math.sin(a)):
            vals.append(min(1.,max(0.,float(clean[len(vals)])+.25*g)))
    return np.array(vals,dtype=F)
def order(names,epoch):
    return sorted(names,key=lambda name:(hashlib.sha256(key('order',name,0,epoch)).digest(),name))
def initialize(arm):
    COUNTS['models']+=1
    p={}
    for name,shape in SHAPES[arm]:
        if len(shape)==1: p[name]=np.zeros(shape,dtype=F)
        else:
            b=math.sqrt(6/(shape[0]+shape[1]))
            p[name]=np.array([b*((2*uniform('init',name,i))-1) for i in range(math.prod(shape))],dtype=F).reshape(shape)
    return p

def forward(arm,p,x,replacement=None):
    COUNTS['forward_calls']+=1;COUNTS['forward_examples']+=len(x);COUNTS['dense_forward_macs']+=len(x)*MAC[arm]
    cache={};n=[0]
    def dense(v,w,b):
        n[0]+=1;cache[w]=v
        return v@p[w]+p[b]
    if arm in ('A','B'):
        h=np.maximum(dense(x,'W1','b1'),F(0));z=dense(h,'Wc','bc')
        e=np.exp(z-z.max(axis=1,keepdims=True));prob=e/e.sum(axis=1,keepdims=True)
        cond=prob if replacement is None else replacement(prob)
        q=np.concatenate((h,cond*F(arm=='A')),axis=1)
        r=np.maximum(dense(q,'Wr','br'),F(0));v=dense(r,'Wi','bi')
        cache.update(h=h,r=r,prob=prob)
    elif arm=='C':
        h=np.maximum(dense(x,'W1','b1'),F(0));u=np.maximum(dense(h,'Ws','bs'),F(0));o=dense(u,'Wo','bo');z=o[:,:10];v=o[:,10:];cache.update(h=h,u=u)
    else:
        o=dense(x,'WL','bL');z=o[:,:10];v=o[:,10:]
    y=F(1)/(F(1)+np.exp(-v));cache.update(z=z,y=y)
    COUNTS['forward_matmuls']+=n[0]
    return z,y,cache

def backward(arm,p,c,clean,labels):
    batch=len(clean);z=c['z'];y=c['y'];shift=z-z.max(axis=1,keepdims=True)
    e=np.exp(shift);prob=e/e.sum(axis=1,keepdims=True)
    loss=(np.log(e.sum(axis=1))-shift[np.arange(batch),labels]).mean()+((y-clean)**2).mean()
    dz=prob.copy();dz[np.arange(batch),labels]-=F(1);dz/=F(batch)
    dv=(F(2)/F(batch*64))*(y-clean)*y*(F(1)-y);g={};n=[0]
    def dense(d,w,b):
        # Always compute both products, including first-layer dx and B zero route.
        g[w]=c[w].T@d;g[b]=d.sum(axis=0);dx=d@p[w].T;n[0]+=2;return dx
    if arm in ('A','B'):
        dr=dense(dv,'Wi','bi')*(c['r']>0)
        dq=dense(dr,'Wr','br');dp=dq[:,128:]*F(arm=='A')
        dz=dz+c['prob']*(dp-(dp*c['prob']).sum(axis=1,keepdims=True))
        dh=dense(dz,'Wc','bc')+dq[:,:128]
        dx=dense(dh*(c['h']>0),'W1','b1')
    elif arm=='C':
        du=dense(np.concatenate((dz,dv),axis=1),'Wo','bo')*(c['u']>0)
        dh=dense(du,'Ws','bs')*(c['h']>0);dx=dense(dh,'W1','b1')
    else: dx=dense(np.concatenate((dz,dv),axis=1),'WL','bL')
    COUNTS['backward_calls']+=1;COUNTS['backward_examples']+=batch;COUNTS['dense_backward_macs']+=2*batch*MAC[arm];COUNTS['backward_matmuls']+=n[0]
    return loss,g,dx

def adam(p,g,m,v,step):
    for name in p:
        m[name]=F(.9)*m[name]+F(1-.9)*g[name]
        v[name]=F(.999)*v[name]+F(1-.999)*(g[name]*g[name])
        mh=m[name]/F(1-.9**step);vh=v[name]/F(1-.999**step)
        p[name]-=F(.001)*mh/(np.sqrt(vh)+F(1e-8))
    COUNTS['updates']+=1

def singleton(arm,p,payload,replacement=None):
    if len(payload)!=256: raise ValueError('wire_size')
    x=np.frombuffer(payload,dtype='<f4').copy().reshape(1,64)
    if not np.isfinite(x).all() or (x<0).any() or (x>1).any():raise ValueError('wire_range')
    z,y,c=forward(arm,p,x,replacement)
    words=('zero','one','two','three','four','five','six','seven','eight','nine')
    body={'digit_word':words[int(z.argmax(axis=1)[0])],'image':[struct.pack('<f',float(v)).hex() for v in y[0]]}
    return json.dumps(body,separators=(',',':')).encode('ascii'),c
