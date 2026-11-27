"use strict";
const H=16, C=26, D=36, F=2*H;
const vec=n=>new Float64Array(n);
const asArray=v=>Array.from(v);
const dot=(a,b)=>{let s=0;for(let i=0;i<a.length;i++)s+=a[i]*b[i];return s;};
function rng(seed){return ()=>{seed^=seed<<13;seed^=seed>>>17;seed^=seed<<5;return(seed>>>0)/4294967296;};}
function shuffled(items,random){let a=items.slice();for(let j=a.length-1;j>0;j--){let k=Math.floor(random()*(j+1));[a[j],a[k]]=[a[k],a[j]];}return a;}
function sampleTrace(strokes){
  const all=strokes.flat(), xs=all.map(p=>p[0]),ys=all.map(p=>p[1]);
  const lo=[Math.min(...xs),Math.min(...ys)], hi=[Math.max(...xs),Math.max(...ys)];
  const scale=Math.max(1,hi[0]-lo[0],hi[1]-lo[1]), seg=[];let total=0;
  for(let j=0;j<strokes.length;j++)for(let k=1;k<strokes[j].length;k++){
    const a=strokes[j][k-1],b=strokes[j][k],length=Math.hypot(b[0]-a[0],b[1]-a[1]);
    if(length>0){seg.push([total,total+length,a,b,j]);total+=length;}
  }
  if(!seg.length)seg.push([0,1,all[0],all[0],0]);const x=vec(D);let k=0,prior=-1;
  for(let t=0;t<12;t++){const pos=t*total/11;while(k+1<seg.length&&pos>seg[k][1])k++;
    const [p,q,a,b,j]=seg[k],w=(pos-p)/(q-p);
    x[3*t]=(2*(a[0]+w*(b[0]-a[0]))-lo[0]-hi[0])/scale;x[3*t+1]=(2*(a[1]+w*(b[1]-a[1]))-lo[1]-hi[1])/scale;
    x[3*t+2]=j===prior?0:1;prior=j;
  } return x;
}
function parseWriter(raw,writer){
  let letter=null,strokes=[],active=null,rec=[];
  function finish(){if(letter&&/^[a-zA-Z]$/.test(letter))rec.push({x:sampleTrace(strokes),label:letter.toLowerCase().charCodeAt(0)-97,group:letter===letter.toLowerCase()?'old':'new',writer,id:writer+'-'+letter+'-'+rec.filter(r=>r.letter===letter).length,letter});}
  for(const line of raw.split(/\r?\n/)){if(line.startsWith('.SEGMENT CHARACTER ')){
    finish();const match=/"([^"]+)"\s*$/.exec(line);if(!match)throw Error(line);letter=match[1];strokes=[];active=null;
  }else if(line.startsWith('.PEN_DOWN')){active=[];strokes.push(active);}
  else if(line.startsWith('.PEN_UP'))active=null;
  else if(active&&/^\s*-?\d+\s+-?\d+/.test(line))active.push(line.trim().split(/\s+/).map(Number));}
  finish();if(rec.length!==104||new Set(rec.map(r=>r.id)).size!==104)throw Error('invalid writer '+writer);
  return rec;
}
// Regularized gamma, using the converged series below 1.5 and the upper-tail
// continued fraction above it. Avoids the ~1e-7 CDF bias of short erfc fits.
function cdf(z){
  if(z===0)return .5;const x=z*z/2,front=Math.exp(-x+.5*Math.log(x)-.5*Math.log(Math.PI));let q;
  if(x<1.5){let ap=.5,term=2,sum=term;for(let n=1;n<140;n++){term*=x/(++ap);sum+=term;if(Math.abs(term)<Math.abs(sum)*2e-16)break;}q=1-front*sum;}
  else{let b=x+.5,c=1e300,d=1/b,h=d;for(let i=1;i<140;i++){const a=-i*(i-.5);b+=2;d=a*d+b;if(Math.abs(d)<1e-300)d=1e-300;c=b+a/c;if(Math.abs(c)<1e-300)c=1e-300;d=1/d;const ratio=d*c;h*=ratio;if(Math.abs(ratio-1)<3e-16)break;}q=front*h;}
  return z<0?.5*q:1-.5*q;
}
function makeLaw(){
  const r=.08,delta=.02,s=.23,var0=s*s,alpha=.6,tax=.27,C0=6.39,P0=61.68,m=1,q=.09;
  const a=(r-delta-var0/2)/var0,mu=a*var0,z=Math.sqrt(a*a+2*r/var0),zb=Math.sqrt(a*a+2*q/var0),eta=z-a,gamma=z+a,disc=Math.exp(-q*m),c=C0/m;
  function small(y){return disc*(cdf(y*s)-Math.exp(r*m)*cdf(-z*s))/(z+y);}
  function big(y){return (cdf(y*s)-Math.exp((z*z-y*y)*s*s/2)*cdf(-z*s))/(z+y);}
  const t=small(a)+small(-a),u=big(zb)+big(-zb),den=delta/(eta-1)+alpha*u/m,w=(1-disc)/eta+t;
  const bc=((1-tax)/eta+(u-w)/(m*q))/den,bp=w/(m*den),B0=bc*C0+bp*P0;
  function literal(input){
    const P=P0*(1+.28*Math.tanh(input)),B=bc*C0+bp*P,x=.18-Math.log(B/B0);
    if(x<=0)return [0,1];const j=gamma,ys=[a,-a,zb,-zb],full=[],tail=[];
    for(const y of ys){function k(v){return Math.exp(((v-a)**2-y*y)*s*s*.5-v*x)*cdf((-x+(v-a)*s*s)/s)-Math.exp(-(a+y)*x)*cdf((-x+y*s*s)/s);}
      const coeff=cdf(y*s)-Math.exp(((j-a)**2-y*y)*s*s*.5)*cdf((j-a)*s);
      full.push(coeff*Math.exp(-j*x)+k(j));tail.push(k(-eta));
    }const aux=(n)=>(full[n]+tail[n+1])/(z-ys[n])+(full[n+1]+tail[n])/(z+ys[n]);
    const adj=P/m-c/q,cost=((1-tax)*C0+(1-disc)*adj)*(1/eta-Math.expm1(-j*x)/j);
    const payout=-delta*B*Math.exp(-j*x)/(j+1),gap=alpha*B/m-c/q;
    const A=B*Math.exp(x)+(payout-cost+disc*adj*aux(0)-gap*aux(2))/(z*var0);
    const hit=cdf((-x-mu*m)/s)+Math.exp(-2*a*x)*cdf((-x+mu*m)/s);
    return [A/20,hit];
  }
  const N=16384,step=24/N,raw0=literal(0),table=[vec(N+1),vec(N+1)];
  for(let j=0;j<=N;j++){const p=literal(j*step-12);for(let c=0;c<2;c++)table[c][j]=p[c]-raw0[c];}
  function calc(input,kind,deriv=false){
    if(kind==='smooth'){const h=Math.tanh(input),h2=Math.tanh(2*input);
      return deriv?[1-h*h,2*(1-h2*h2)]:[h,h2];}
    const q=(Math.max(-12,Math.min(12,input))+12)/step,i=Math.min(N-1,Math.floor(q)),f=q-i;
    if(deriv)return Math.abs(input)>=12?[0,0]:[(table[0][i+1]-table[0][i])/step,(table[1][i+1]-table[1][i])/step];
    return [table[0][i]+(table[0][i+1]-table[0][i])*f,table[1][i]+(table[1][i+1]-table[1][i])*f];
  }
  let maxerr=0;for(let i=0;i<321;i++){const v=-11.95+23.9*(i+.381)/321,raw=literal(v),pred=calc(v,'physical');for(let j=0;j<2;j++)maxerr=Math.max(maxerr,Math.abs(raw[j]-raw0[j]-pred[j]));}
  return {calc, literal, anchor:raw0,B0,bc,bp,maxerr};
}
const law=makeLaw();
function linear(x,w,b,n){const y=b?Float64Array.from(b):vec(n);for(let i=0;i<x.length;i++)for(let j=0;j<n;j++)y[j]+=x[i]*w[i*n+j];return y;}
function unit(u,kind,deriv=false){const f=vec(F);for(let j=0;j<H;j++){const v=law.calc(u[j],kind,deriv);f[j]=v[0];f[H+j]=v[1];}return f;}
function forward(x,m){
  if(m.kind==='ridge')return {z:linear(x,m.v,m.vb,C)};
  const u=linear(x,m.w1,m.b1,H),h=unit(u,m.kind),v=linear(h,m.w2,m.b2,H),f=unit(v,m.kind);
  return {u,h,v,f,z:linear(f,m.v,m.vb,C)};
}
function model(seed,kind){const r=rng(seed), rand=(n,inDim)=>Float64Array.from({length:n},()=>Math.sqrt(3/inDim)*(2*r()-1));return {kind,w1:rand(D*H,D),b1:rand(H,D),w2:rand(F*H,F),b2:rand(H,F),v:rand(F*C,F),vb:vec(C)};}
function copy(m){return Object.fromEntries(Object.entries(m).map(([k,v])=>[k,typeof v==='string'?v:Float64Array.from(v)]));}
function jsonModel(m){return Object.fromEntries(Object.entries(m).map(([k,v])=>[k,typeof v==='string'?v:asArray(v)]));}
function probs(z){const best=Math.max(...z),p=Float64Array.from(z,v=>Math.exp(v-best)),n=p.reduce((a,b)=>a+b,0);for(let j=0;j<p.length;j++)p[j]/=n;return p;}
function score(m,data,save=false){const by={},preds=[];let correct=0,loss=0;
  for(const row of data){const z=forward(row.x,m).z,p=probs(z),win=z.indexOf(Math.max(...z)),hit=Number(win===row.label);correct+=hit;loss-=Math.log(Math.max(1e-250,p[row.label]));(by[row.writer]??=[0,0]);by[row.writer][0]+=hit;by[row.writer][1]++;if(save)preds.push([row.id,win,row.label,...asArray(z)]);}
  return {accuracy:correct/data.length,loss:loss/data.length,n:data.length,by,...(save?{preds}:{})};
}
function solve(A,B,d,c){const L=vec(d*d),out=Float64Array.from(B);
  for(let i=0;i<d;i++){for(let j=0;j<=i;j++){let s=A[i*d+j];for(let k=0;k<j;k++)s-=L[i*d+k]*L[j*d+k];if(i===j){if(!(s>0))throw Error('nonpositive normal '+s);L[i*d+j]=Math.sqrt(s);}else L[i*d+j]=s/L[j*d+j];}}
  for(let j=0;j<c;j++){for(let i=0;i<d;i++){let s=out[i*c+j];for(let k=0;k<i;k++)s-=L[i*d+k]*out[k*c+j];out[i*c+j]=s/L[i*d+i];}
    for(let i=d-1;i>=0;i--){let s=out[i*c+j];for(let k=i+1;k<d;k++)s-=L[k*d+i]*out[k*c+j];out[i*c+j]=s/L[i*d+i];}}return out;}
function regress(X,T,lambda){const d=X[0].length,n=X.length,c=T[0].length,mu=vec(d),mean=vec(c),A=vec(d*d),B=vec(d*c);for(let i=0;i<n;i++){for(let j=0;j<d;j++)mu[j]+=X[i][j]/n;for(let k=0;k<c;k++)mean[k]+=T[i][k]/n;}
  for(let i=0;i<n;i++){const a=X[i];for(let j=0;j<d;j++){const val=a[j]-mu[j];for(let k=0;k<=j;k++)A[j*d+k]+=val*(a[k]-mu[k]);for(let k=0;k<c;k++)B[j*c+k]+=val*(T[i][k]-mean[k]);}}
  let tr=0;for(let j=0;j<d;j++)tr+=A[j*d+j];for(let j=0;j<d;j++)A[j*d+j]+=lambda*Math.max(tr/d,1e-9)+1e-8;
  const W=solve(A,B,d,c),bias=Float64Array.from(mean);for(let j=0;j<c;j++)for(let k=0;k<d;k++)bias[j]-=mu[k]*W[k*c+j];return [W,bias];
}
function timestamp(){return Date.now()/1000;}

function onehot(y){const v=vec(C);v[y]=1;return v;}
function fitReadout(m,data,lam){const X=data.map(d=>m.kind==='ridge'?d.x:forward(d.x,m).f),T=data.map(d=>onehot(d.label));[m.v,m.vb]=regress(X,T,lam);return m;}
function directedLayer(X,y,random,gain){
  const n=X.length,d=X[0].length,targets=y.map(onehot),[beta,b0]=regress(X,targets,.05),fitted=X.map(x=>linear(x,beta,b0,C));
  const meanF=vec(C);for(const v of fitted)for(let j=0;j<C;j++)meanF[j]+=v[j]/n;
  const cov=vec(C*C);for(const v of fitted)for(let j=0;j<C;j++)for(let k=0;k<C;k++)cov[j*C+k]+=(v[j]-meanF[j])*(v[k]-meanF[k])/n;
  const W=vec(d*H),b=vec(H),basis=[];
  for(let cell=0;cell<H;cell++){
    let v=Float64Array.from({length:C},()=>random()-.5);
    for(let it=0;it<35;it++){v=linear(v,cov,null,C);for(const u of basis){const a=dot(v,u);for(let j=0;j<C;j++)v[j]-=a*u[j];}
      const norm=Math.sqrt(dot(v,v))+1e-10;for(let k=0;k<C;k++)v[k]/=norm;}
    basis.push(v);const weights=vec(d);for(let k=0;k<d;k++)for(let j=0;j<C;j++)weights[k]+=beta[k*C+j]*v[j];
    const projected=X.map(x=>dot(x,weights)),mu=projected.reduce((a,b)=>a+b)/n,sd=Math.sqrt(projected.reduce((a,b)=>a+(b-mu)**2,0)/n)+1e-7;
    for(let k=0;k<d;k++)W[k*H+cell]=gain*weights[k]/sd;b[cell]=-gain*mu/sd;
  }return [W,b];
}
function bestDev(cand,best){return !best||cand.accuracy>best.accuracy+1e-12||(Math.abs(cand.accuracy-best.accuracy)<1e-12&&cand.loss<best.loss);}
function trainConstruct(data,dev,seed,kind,arm){
  const start=timestamp(),front=[],work={};let win=null,best=null;
  const random=rng(seed),y=data.map(d=>d.label),sup=arm==='shuffle'?shuffled(y,random):y;
  for(const gain of (arm==='ridge'||arm==='random'?[1]:[.5,1.2])){
    const m=model(seed,kind);if(arm==='ridge')m.kind='ridge';
    if(arm==='construct'||arm==='shuffle'){const r=rng(seed+312);[m.w1,m.b1]=directedLayer(data.map(d=>d.x),sup,r,gain);
      const lower=data.map(d=>unit(linear(d.x,m.w1,m.b1,H),kind));[m.w2,m.b2]=directedLayer(lower,sup,r,gain);}
    for(const lam of [.001,.03,.2]){fitReadout(m,data,lam);const metric=score(m,dev);front.push({gain,lam,...metric,elapsed:timestamp()-start});
      if(bestDev(metric,best)){best=metric;win=copy(m);}}
  }return {m:win,front,elapsed:timestamp()-start};
}
function addOuter(grad,x,t){const n=t.length;for(let i=0;i<x.length;i++)for(let j=0;j<n;j++)grad[i*n+j]+=x[i]*t[j];}
function backwardWeights(w,t,n){const d=w.length/n,out=vec(d);for(let i=0;i<d;i++)for(let j=0;j<n;j++)out[i]+=w[i*n+j]*t[j];return out;}
function lowerGrad(upper,features){const g=vec(H);for(let j=0;j<H;j++)g[j]=upper[j]*features[j]+upper[j+H]*features[j+H];return g;}
function updateAdam(weights,grad,mom,var0,beta1t,beta2t,lr,batch){for(let i=0;i<weights.length;i++){const g=grad[i]/batch;mom[i]=.9*mom[i]+.1*g;var0[i]=.999*var0[i]+.001*g*g;weights[i]-=lr*(mom[i]/beta1t)/(Math.sqrt(var0[i]/beta2t)+1e-8);}}
function fitBP(train,dev,seed,kind){
  const start=timestamp(),front=[];let win,best;
  for(const lr of [.003,.012]){
    const r=rng(seed+19),m=model(seed,kind),keys=['w1','b1','w2','b2','v','vb'];
    const state=Object.fromEntries(keys.map(k=>[k,[vec(m[k].length),vec(m[k].length),vec(m[k].length)]]));
    for(let step=1;step<=720;step++){const bs=24;for(const k of keys)state[k][0].fill(0);
      for(let j=0;j<bs;j++){const d=train[Math.floor(r()*train.length)],f=forward(d.x,m),err=probs(f.z);err[d.label]--;
        addOuter(state.v[0],f.f,err);for(let k=0;k<C;k++)state.vb[0][k]+=err[k];
        let dv=lowerGrad(backwardWeights(m.v,err,C),unit(f.v,m.kind,true));addOuter(state.w2[0],f.h,dv);
        for(let k=0;k<H;k++)state.b2[0][k]+=dv[k];
        let du=lowerGrad(backwardWeights(m.w2,dv,H),unit(f.u,m.kind,true));addOuter(state.w1[0],d.x,du);for(let k=0;k<H;k++)state.b1[0][k]+=du[k];
      }
      for(const k of keys)updateAdam(m[k],...state[k],1-.9**step,1-.999**step,lr,bs);
      if([60,180,360,720].includes(step)){const val=score(m,dev);front.push({lr,step,...val,elapsed:timestamp()-start});if(bestDev(val,best)){best=val;win=copy(m);}}
    }
  }return {m:win,front,elapsed:timestamp()-start};
}
function parseSplit(raws,first=1){return raws.flatMap((s,j)=>parseWriter(s,first+j));}
function runnerFresh(raws,seed,arm){
  const t=timestamp(),ds=parseSplit(raws),train=ds.filter(d=>d.writer<=5&&d.group==='old'),dev=ds.filter(d=>d.writer>5&&d.group==='old');
  const prep=timestamp()-t;let ans;
  if(arm==='physicalBP'||arm==='smoothBP')ans=fitBP(train,dev,seed,arm==='physicalBP'?'physical':'smooth');
  else ans=trainConstruct(train,dev,seed,arm==='smoothConstruct'?'smooth':'physical',({physicalConstruct:'construct',smoothConstruct:'construct',shuffle:'shuffle',random:'random',ridge:'ridge'})[arm]);
  return {seed,arm,split:{train:train.length,dev:dev.length,prep},law:{anchor:law.anchor,B0:law.B0,lutMax321:law.maxerr},model:jsonModel(ans.m),front:ans.front,seconds:ans.elapsed};
}

function shortEval(m,old,newd){const a=score(m,old),b=score(m,newd);return {old:a.accuracy,new:b.accuracy,oldLoss:a.loss,newLoss:b.loss};}
function chooseEdit(record,best,base){if(record.old+1e-12<base.old-.02)return false;
  if(record.new>best.new+1e-12)return true;
  return Math.abs(record.new-best.new)<1e-12&&record.newLoss+record.oldLoss<best.newLoss+best.oldLoss-1e-8;}
function prepareEdit(m,train){return train.map(d=>{const ff=forward(d.x,m);return {...d,h:ff.h,teacher:ff.z};});}
function upperOnly(d,m){const v=linear(d.h,m.w2,m.b2,H),f=unit(v,m.kind),z=linear(f,m.v,m.vb,C);return {v,f,z};}
function finiteSecants(m,data){
  const len=data.length,dim=F*H,eps=.03,A=vec(len*dim),B=vec(len*dim),target=vec(len*C),oldFlag=new Uint8Array(len);let maxRecompose=0,probes=0;
  for(let i=0;i<len;i++){
    const d=data[i],s=upperOnly(d,m),p=probs(s.z),isOld=d.group==='old';oldFlag[i]=Number(isOld);
    // Supervised new residual is a bounded logit displacement; the old target
    // is the exact corresponding parent output. Both preserve irrelevant common logits.
    let avg=0;for(let c=0;c<C;c++){const zz=isOld?d.teacher[c]-s.z[c]:4*((c===d.label?1:0)-p[c]);target[i*C+c]=zz;avg+=zz/C;}
    for(let c=0;c<C;c++)target[i*C+c]-=avg;
    for(let k=0;k<F;k++){
      const positive=vec(H),negative=vec(H);for(let j=0;j<H;j++){positive[j]=s.v[j]+eps*d.h[k];negative[j]=s.v[j]-eps*d.h[k];}
      const up=unit(positive,m.kind),down=unit(negative,m.kind);probes+=2;
      for(let j=0;j<H;j++){const ix=i*dim+k*H+j;A[ix]=(up[j]-down[j])/(2*eps);B[ix]=(up[H+j]-down[H+j])/(2*eps);}
      if(i<2&&k<3){
        // Materialize perturbed weights independently and compare the sum of
        // recovered neuron contributions with full-network logits.
        const full=copy(m);for(let j=0;j<H;j++)full.w2[k*H+j]+=eps;
        const alt=forward(d.x,full).z;for(let c=0;c<C;c++){let val=s.z[c];for(let j=0;j<H;j++)val+=(up[j]-s.f[j])*m.v[j*C+c]+(up[H+j]-s.f[H+j])*m.v[(H+j)*C+c];maxRecompose=Math.max(maxRecompose,Math.abs(val-alt[c]));}
      }
    }
  }return {A,B,target,oldFlag,len,dim,v:m.v,probes,maxRecompose};
}
function jacApply(J,theta,transpose=false){
  const {A,B,v,len,dim}=J;if(!transpose){const out=vec(len*C),h=vec(F);for(let i=0;i<len;i++){h.fill(0);for(let k=0;k<F;k++)for(let j=0;j<H;j++){let q=k*H+j,g=theta[q],p=i*dim+q;h[j]+=A[p]*g;h[j+H]+=B[p]*g;}
    let mean=0;for(let c=0;c<C;c++){let val=0;for(let j=0;j<F;j++)val+=h[j]*v[j*C+c];out[i*C+c]=val;mean+=val/C;}
    for(let c=0;c<C;c++)out[i*C+c]-=mean;}return out;
  }const out=vec(dim),ht=vec(F);for(let i=0;i<len;i++){let avg=0;for(let c=0;c<C;c++)avg+=theta[i*C+c]/C;
    for(let j=0;j<F;j++){let val=0;for(let c=0;c<C;c++)val+=(theta[i*C+c]-avg)*v[j*C+c];ht[j]=val;}
    for(let k=0;k<F;k++)for(let j=0;j<H;j++){let q=k*H+j,p=i*dim+q;out[q]+=A[p]*ht[j]+B[p]*ht[j+H];}}
  return out;
}
function secantSolve(J,protect){
  const weight=q=>{for(let i=0;i<J.len;i++)if(J.oldFlag[i])for(let c=0;c<C;c++)q[i*C+c]*=protect;return q;};
  const b=jacApply(J,weight(Float64Array.from(J.target)),true),x=vec(J.dim),r=Float64Array.from(b);let p=Float64Array.from(b),rr=dot(r,r),initial=rr,count=0;
  const ridge=.04*J.len;
  for(let it=0;it<20&&rr>1e-10*Math.max(1,initial);it++){
    const ap=jacApply(J,weight(jacApply(J,p)),true);for(let j=0;j<J.dim;j++)ap[j]+=ridge*p[j];
    const alpha=rr/(dot(p,ap)+1e-24);for(let j=0;j<J.dim;j++){x[j]+=alpha*p[j];r[j]-=alpha*ap[j];}
    const nr=dot(r,r),beta=nr/(rr+1e-24);for(let j=0;j<J.dim;j++)p[j]=r[j]+beta*p[j];rr=nr;count++;
  }return {x,count,relative:Math.sqrt(rr/(initial+1e-24))};
}
function editDirect(parent,train,od,nd,seed,arm){
  const start=timestamp(),base=shortEval(parent,od,nd),front=[{tag:'KEEP',...base,elapsed:0}],logs=[];
  let best=front[0],win=copy(parent),rows=prepareEdit(parent,train);
  if(arm==='shuffledSecant'){const random=rng(seed+1091);let old=rows.filter(d=>d.group==='old'),nu=[];for(let w=1;w<=5;w++){const s=rows.filter(d=>d.group==='new'&&d.writer===w),y=shuffled(s.map(d=>d.label),random);nu.push(...s.map((d,i)=>({...d,label:y[i]})));}rows=[...old,...nu];}
  let current=copy(parent);
  for(let refresh=1;refresh<=2;refresh++){
    const J=finiteSecants(current,rows);logs.push({refresh,groupedPositiveNegativeSampleEvaluations:J.probes,fullEquivalentPerSignSeparate:rows.length*F*H*2,maxRecompose:J.maxRecompose});
    let stepBest=null,next=null;
    for(const protect of [.5,2,8]){const ans=secantSolve(J,protect);
      for(const scale of [.4,1,2]){const m=copy(current);for(let j=0;j<m.w2.length;j++)m.w2[j]+=scale*ans.x[j];
        const met={tag:'secant',refresh,protect,scale,iterations:ans.count,relative:ans.relative,...shortEval(m,od,nd),elapsed:timestamp()-start};front.push(met);
        if(chooseEdit(met,best,base)){best=met;win=copy(m);}
        if(met.old>=base.old-.02-1e-12&&(!stepBest||chooseEdit(met,stepBest,base))){stepBest=met;next=m;}
      }
    }if(next)current=next;else break;
  }return {m:win,front,selected:best,logs,elapsed:timestamp()-start};
}
function rankMatrix(left,right){const rank=4,out=vec(F*H);for(let k=0;k<F;k++)for(let j=0;j<H;j++)for(let q=0;q<rank;q++)out[k*H+j]+=left[k*rank+q]*right[q*H+j];return out;}
function editBP(parent,data,od,nd,seed,arm){
  const start=timestamp(),base=shortEval(parent,od,nd),front=[{tag:'KEEP',...base,elapsed:0}];
  const cached=prepareEdit(parent,data),old=cached.filter(r=>r.group==='old'),nu=cached.filter(r=>r.group==='new');
  let best=front[0],win=copy(parent),totalForwards=0,totalBackwards=0;
  for(const protect of [.5,2,8])for(const lr of [.003,.015,.05]){
    const m=copy(parent),rand=rng(seed+41),rank=4,lora=arm==='LoRA',left=Float64Array.from({length:F*rank},()=>(rand()-.5)*.2),right=vec(rank*H);
    const tensors=lora?[left,right]:[m.w2],states=tensors.map(t=>[vec(t.length),vec(t.length),vec(t.length)]);
    for(let step=1;step<=192;step++){
      const G=vec(F*H),bs=24;
      for(let row=0;row<bs;row++){const isOld=row%2===0,pool=isOld?old:nu,d=pool[Math.floor(rand()*pool.length)],out=upperOnly(d,m);
        const error=probs(out.z);if(isOld){let mean=0;for(let c=0;c<C;c++){error[c]=out.z[c]-d.teacher[c];mean+=error[c]/C;}for(let c=0;c<C;c++)error[c]=(error[c]-mean)*protect*.25;}
        else error[d.label]--;const g=lowerGrad(backwardWeights(m.v,error,C),unit(out.v,m.kind,true));addOuter(G,d.h,g);}
      totalForwards+=bs;totalBackwards+=bs;
      if(lora){const [gl,gr]=states.map(s=>s[0]);gl.fill(0);gr.fill(0);
        for(let k=0;k<F;k++)for(let j=0;j<H;j++)for(let t=0;t<rank;t++){gl[k*rank+t]+=G[k*H+j]*right[t*H+j];gr[t*H+j]+=left[k*rank+t]*G[k*H+j];}
      }else states[0][0]=G;
      tensors.forEach((t,i)=>updateAdam(t,...states[i],1-.9**step,1-.999**step,lr,bs));
      if(lora){const delta=rankMatrix(left,right);for(let j=0;j<delta.length;j++)m.w2[j]=parent.w2[j]+delta[j];}
      if([12,48,96,192].includes(step)){const met={tag:arm,step,lr,protect,...shortEval(m,od,nd),elapsed:timestamp()-start};front.push(met);
        if(chooseEdit(met,best,base)){best=met;win=copy(m);}}
    }
  }return {m:win,front,selected:best,logs:[{tuningTrainingForwardExamples:totalForwards,tuningBackwardExamples:totalBackwards}],elapsed:timestamp()-start};
}
function runnerEdit(raws,parentData,seed,arm){
  const t=timestamp(),ds=parseSplit(raws),train=ds.filter(d=>d.writer<=5),dev=ds.filter(d=>d.writer>5),od=dev.filter(d=>d.group==='old'),nd=dev.filter(d=>d.group==='new');
  const prep=timestamp()-t,parent=copy(parentData.model);let out;
  if(arm==='secant'||arm==='shuffledSecant')out=editDirect(parent,train,od,nd,seed,arm);
  else out=editBP(parent,train,od,nd,seed,arm);
  const nonzero=Array.from(out.m.w2).reduce((n,v,j)=>n+(v!==parent.w2[j]),0);
  for(const k of ['w1','b1','b2','v','vb'])if(!out.m[k].every((v,j)=>v===parent[k][j]))throw Error('out of site '+k);
  return {seed,arm,split:{train:train.length,dev:dev.length,prep},model:jsonModel(out.m),deltaCount:nonzero,front:out.front,selected:out.selected,logs:out.logs,seconds:out.elapsed};
}

if(typeof require==='function'&&typeof module!=='undefined'&&require.main===module){
  const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
  const [mode,rawRoot,outRoot,argSeed,argArm]=process.argv.slice(2);fs.mkdirSync(outRoot,{recursive:true});
  function readRows(start,end){return Array.from({length:end-start+1},(_,i)=>fs.readFileSync(path.join(rawRoot,'UJIpenchars-w'+String(i+start).padStart(2,'0')),'utf8'));}
  if(mode==='fit'){
    const seed=Number(argSeed),arm=argArm,raws=readRows(1,7);
    const q=['secant','shuffledSecant','Adam','LoRA'].includes(arm)?runnerEdit(raws,JSON.parse(fs.readFileSync(path.join(outRoot,seed+'-physicalBP.json'))),seed,arm):runnerFresh(raws,seed,arm);
    fs.writeFileSync(path.join(outRoot,seed+'-'+arm+'.json'),JSON.stringify(q)+'\n');
  }else if(mode==='score'){
    const raws=readRows(8,11),hold=parseSplit(raws,8);
    const dir=fs.readdirSync(outRoot).filter(f=>/^\d+-.+\.json$/.test(f)).sort();
    if(dir.length!==33)throw Error('Expected 33 sealed fits, found '+dir.length);
    const table={};for(const n of dir){const q=JSON.parse(fs.readFileSync(path.join(outRoot,n)));const m=copy(q.model),a=score(m,hold.filter(d=>d.group==='old'),true),b=score(m,hold.filter(d=>d.group==='new'),true);table[n]={old:a,new:b};}
    fs.writeFileSync(path.join(outRoot,'cold.json'),JSON.stringify(table)+'\n');
  }else if(mode==='check'){
    console.log(JSON.stringify({anchor:law.anchor,bc:law.bc,bp:law.bp,B0:law.B0,tableError:law.maxerr}));
  }else throw Error('Mode must be fit, score or check.');
}
