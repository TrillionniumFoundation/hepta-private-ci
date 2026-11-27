"""Equity and monetary-loss continuation operators and matched causal acquisition scores."""
import numpy as np
from scipy.special import ndtr
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import HistGradientBoostingRegressor
def make_table():
    r=.08;delta=.02;sigma=.23;tau=.27;c=6.39;p=61.68;alpha=.6;q=.09
    var=sigma**2;a=(r-delta-var/2)/var;z=np.sqrt(a*a+2*r/var);zb=np.sqrt(a*a+2*q/var)
    eta=z-a;gamma=z+a;discount=np.exp(-q);adj=p-c/q
    little=lambda y:discount*(ndtr(y*sigma)-np.exp(r)*ndtr(-z*sigma))/(z+y)
    big=lambda y:(ndtr(y*sigma)-np.exp((z*z-y*y)*var/2)*ndtr(-z*sigma))/(z+y)
    coeff=(1-tau)*c+(1-discount)*adj
    b=(coeff/eta+adj*(little(a)+little(-a))+c/q*(big(zb)+big(-zb)))/(delta/(eta-1)+alpha*(big(zb)+big(-zb)))
    x=np.linspace(0,1.2,1201)
    def tail(y,j):
        sc=((j-a)**2-y*y)*var/2
        return np.exp(sc-j*x)*ndtr((-x+(j-a)*var)/sigma)-np.exp(-(a+y)*x)*ndtr((-x+y*var)/sigma)
    def full(y):
        j=gamma
        return (ndtr(y*sigma)-np.exp(((j-a)**2-y*y)*var/2)*ndtr((j-a)*sigma))*np.exp(-j*x)+tail(y,j)
    aux=lambda y:(full(y)+tail(-y,-eta))/(z-y)+(full(-y)+tail(y,-eta))/(z+y)
    eq=b*np.exp(x)+(-delta*b*np.exp(-gamma*x)/(gamma+1)-coeff*(1/eta-np.expm1(-gamma*x)/gamma)+discount*adj*aux(a)-(alpha*b-c/q)*aux(zb))/(z*var)
    def hit(y):
        return np.exp(-(a-y)*x)*ndtr((-x-y*var)/sigma)+np.exp(-(a+y)*x)*ndtr((-x+y*var)/sigma)
    loss=discount*adj*hit(a)+(c/q-alpha*b)*hit(zb)
    v=np.c_[eq,loss]/20
    return x,v,v[180],(v[181]-v[179])/.002
TABLE=make_table()
def gate_inputs(p,segment):
    grid,values,center,slopes=TABLE
    uncertainty=-(p*np.log(np.maximum(p,1e-12))).sum(1)/np.log(p.shape[1])
    sorted_p=np.sort(p,axis=1);margin=sorted_p[:,-1]-sorted_p[:,-2]
    z=[];literal=[];tangent=[]
    for j in range(len(p)):
        if j==0 or segment[j]!=segment[j-1]:
            state=np.full(2,.18);ema=.5;last=0.;z.append([.5,0.,.5,0.])
            literal.append([0.,0.,.18]);tangent.append([0.,0.,.18]);continue
        shock=float(uncertainty[j-1]);ema=.75*ema+.25*shock
        z.append([shock,margin[j-1],ema,shock-last]);last=shock
        for k,ans in enumerate([literal,tangent]):
            x=state[k]
            channel=np.array([np.interp(x,grid,values[:,i]) for i in range(2)])-center if k==0 else (x-.18)*slopes
            ans.append([*channel,x])
            pressure=.09*np.tanh(channel[0])+.09*np.tanh(channel[1])
            trial=.18+.65*(x-.18)+.28*(.5-shock)+pressure
            state[k]=.30 if trial<=0 else np.clip(trial,0.,1.2)
    return np.array(z),np.array(literal),np.array(tangent)
def fit_gates(z,lit,tan,y):
    models={}
    for name,arm in [('literal',lit),('tangent',tan)]:
        models[name]=make_pipeline(StandardScaler(),Ridge(alpha=20.)).fit(np.c_[z,arm],y)
    models['learned']=HistGradientBoostingRegressor(max_iter=65,max_leaf_nodes=9,l2_regularization=3.,early_stopping=False,random_state=719).fit(z,y)
    return models
def scores(models,z,lit,tan):
    return dict(literal=models['literal'].predict(np.c_[z,lit]),tangent=models['tangent'].predict(np.c_[z,tan]),learned=models['learned'].predict(z),entropy=z[:,0],periodic=np.zeros(len(z)))
def eligible(seg):
    parts=np.split(np.arange(len(seg)),np.flatnonzero(np.diff(seg))+1)
    return np.concatenate([v[:len(v)//4*4] for v in parts])
def choose(score,segment,quota,cut,periodic=False):
    out=np.zeros(len(score),bool)
    for block in eligible(segment).reshape(-1,4):
        slots=quota
        for j,i in enumerate(block):
            buy=(j%(4//quota)==0) if periodic else slots>0 and (score[i]>=cut or 4-j<=slots)
            if buy:out[i]=True;slots-=1
        assert slots==0
    return out
