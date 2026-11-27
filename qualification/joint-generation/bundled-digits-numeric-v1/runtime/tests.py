import hashlib,json,math,struct
import numpy as np
import kernel as k
import reference as ref
STATE={}

def check(ok,code):
    STATE['last_check']={'code':code,'status':'pending'}
    STATE['last_check']['status']='pass' if bool(ok) else 'fail'
    if not bool(ok):raise AssertionError(code)
def witness_check(record,ok,code):
    record['status']='pass' if bool(ok) else 'fail'
    record['check']=code
    check(ok,code)
def finite_witness(arm,phase,values):
    record={'arm':arm,'phase':phase,'status':'pending','arrays':[]}
    STATE.setdefault('finite_records',[]).append(record)
    for name,value in values:
        a=np.asarray(value);bad=~np.isfinite(a);count=int(np.count_nonzero(bad))
        item={'name':name,'size':int(a.size),'nonfinite_count':count}
        if count:
            idx=int(np.flatnonzero(bad)[0]);item.update(first_bad_index=idx,first_bad_value=float(a.flat[idx]))
        record['arrays'].append(item)
    witness_check(record,all(v['nonfinite_count']==0 for v in record['arrays']),'finite_'+phase)

def finite(values):return all(np.isfinite(x).all() for x in values)
def close(x,y,atol,rtol):return bool(np.all(np.abs(x-y)<=atol+rtol*np.abs(y)))

def run(fixtures):
    STATE.update(counts=k.COUNTS)
    # Exactly two handcrafted 64-pixel inputs. No dataset and no file input.
    clean=np.array([[((i*3+1)%17)/16 for i in range(64)], [((i*7+5)%17)/16 for i in range(64)]],dtype=np.float32)
    labels=np.array([2,7]);names=['0'*64,'1'*64]
    x=np.stack([k.noise(clean[i],names[i]) for i in range(2)])
    check(x.tobytes().hex()==fixtures['noise_hex'],'noise_KAT')
    check(k.order(names+['2'*64,'3'*64],0)==fixtures['order'],'order_KAT')
    check([k.uniform('init','W1',i).hex() for i in range(4)]==fixtures['uniform_hex'],'uniform_KAT')
    models={a:k.initialize(a) for a in 'ABCL'}
    check(all(models['A'][n].tobytes()==models['B'][n].tobytes() for n in models['A']),'AB_identity')
    check(models['A']['W1'].tobytes()==models['C']['W1'].tobytes(),'AC_W1_identity')
    check(models['A']['b1'].tobytes()==models['C']['b1'].tobytes(),'AC_b1_identity')
    check(models['A']['W1'].ravel()[:4].tobytes().hex()==fixtures['init_hex'],'init_KAT')
    diagnostics={};fd_checks=0;adam_checks=0;interventions={};fd_records=[];adam_records=[]
    STATE.update(FD_records=fd_records,Adam_records=adam_records,models=diagnostics,interventions=interventions,counts=k.COUNTS)
    for arm in 'ABCL':
        p=models[arm];check(sum(v.size for v in p.values())=={'A':35658,'B':35658,'C':36408,'L':4810}[arm],'parameter_count')
        z,y,cache=k.forward(arm,p,x);loss,g,dx=k.backward(arm,p,cache,clean,labels)
        finite_witness(arm,'backward',[('loss',loss),('dx',dx)]+[('parameter_'+n,v) for n,v in p.items()]+[('gradient_'+n,v) for n,v in g.items()])
        if arm=='B':check(np.count_nonzero(g['Wr'][128:])==0,'B_condition_gradient')
        q={n:v.astype(np.float64) for n,v in p.items()};xx=x.astype(np.float64);tt=clean.astype(np.float64)
        baseline=ref.loss(arm,q,xx,tt,labels)
        loss_record={'arm':arm,'actual32':float(loss),'reference64':baseline,'atol':2e-6,'rtol':3e-4,'status':'pending'}
        STATE.setdefault('loss_records',[]).append(loss_record)
        witness_check(loss_record,close(float(loss),baseline,2e-6,3e-4),'loss_reference')
        worst=0.
        for name in p:
            n=p[name].size
            for probe in range(3):
                direction=np.zeros(n,dtype=np.float64)
                if probe<2:direction[(0,n//2)[probe]]=1.
                else:direction=np.array([(-1. if i%2 else 1.)/math.sqrt(n) for i in range(n)],dtype=np.float64)
                direction=direction.reshape(p[name].shape);original=q[name];derivatives=[]
                analytic=float(np.sum(g[name].astype(np.float64)*direction))
                record={'arm':arm,'tensor':name,'tensor_size':n,'probe':probe,'identity':('coordinate0','coordinate_midpoint','alternating_normalized')[probe],'analytic32':analytic,'FD':derivatives,'raw_losses':[],'stability_atol':2e-8,'stability_rtol':2e-5,'gradient_atol':2e-6,'gradient_rtol':3e-4,'status':'pending'}
                fd_records.append(record)
                for epsilon in (1e-5,5e-6):
                    raw={'epsilon':epsilon,'plus':None,'minus':None,'status':'pending'};record['raw_losses'].append(raw)
                    q[name]=original+epsilon*direction;plus=ref.loss(arm,q,xx,tt,labels);raw['plus']=plus
                    q[name]=original-epsilon*direction;minus=ref.loss(arm,q,xx,tt,labels);raw['minus']=minus;raw['status']='complete'
                    derivatives.append((plus-minus)/(2*epsilon))
                q[name]=original
                record.update(error=abs(analytic-derivatives[1]),tolerance=2e-6+3e-4*abs(derivatives[1]))
                witness_check(record,close(derivatives[0],derivatives[1],2e-8,2e-5),'FD_stability')
                record['stability_status']='pass';record['status']='pending'
                witness_check(record,close(analytic,derivatives[1],2e-6,3e-4),'gradient_reference')
                worst=max(worst,abs(analytic-derivatives[1]));fd_checks+=1
        old={n:v.copy() for n,v in p.items()};m={n:np.zeros_like(v) for n,v in p.items()};v={n:np.zeros_like(v) for n,v in p.items()}
        k.adam(p,g,m,v,1)
        # Three preregistered scalar coordinates per tensor check updates and moments.
        for name in p:
            for idx in (0,p[name].size//2,p[name].size-1):
                record={'arm':arm,'tensor':name,'index':idx,'step':1,'before':[float(old[name].flat[idx]),0.,0.],'gradient':float(g[name].flat[idx]),'after':[float(p[name].flat[idx]),float(m[name].flat[idx]),float(v[name].flat[idx])],'reference':None,'atol':2e-7,'rtol':2e-5,'status':'pending'}
                adam_records.append(record)
                expected=ref.scalar_adam(old[name].flat[idx],g[name].flat[idx],1)
                record['reference']=[float(a) for a in expected]
                witness_check(record,all(close(actual,float(want),2e-7,2e-5) for actual,want in zip(record['after'],expected)),'Adam_reference')
                adam_checks+=1
        finite_witness(arm,'Adam',[(kind+'_'+n,a) for kind,group in (('parameter',p),('moment',m),('variance',v)) for n,a in group.items()])
        wire=x[0].astype('<f4').tobytes();body,c=k.singleton(arm,p,wire);parsed=json.loads(body)
        decoded=np.frombuffer(b''.join(bytes.fromhex(h) for h in parsed['image']),dtype='<f4')
        rz,ry,rc=k.forward(arm,p,x[:1]);check(decoded.tobytes()==ry[0].astype('<f4').tobytes(),'wire_roundtrip')
        check(parsed['digit_word']==('zero','one','two','three','four','five','six','seven','eight','nine')[int(rz.argmax())],'word')
        if arm in 'AB':
            changes=[]
            for replace in (lambda prob:np.full_like(prob,np.float32(.1)),lambda prob:np.roll(prob,-1,axis=1)):
                changed,cc=k.singleton(arm,p,wire,replace);check(cc['h'].tobytes()==c['h'].tobytes(),'fixed_h')
                image=np.frombuffer(b''.join(bytes.fromhex(h) for h in json.loads(changed)['image']),dtype='<f4')
                delta=float(np.max(np.abs(image.astype(float)-decoded.astype(float))));changes.append(delta)
                if arm=='B':check(changed==body,'B_invariance')
            interventions[arm]={'maximum_pixel_changes':changes,'detected':[d>1e-7 for d in changes]}
        # Input rejects invoke no model forward.
        for bad in (b'',struct.pack('<f',float('nan'))+wire[4:],struct.pack('<f',1.1)+wire[4:]):
            try:k.singleton(arm,p,bad)
            except ValueError:pass
            else:raise AssertionError('wire_reject')
        diagnostics[arm]={'loss':float(loss),'gradient_max_error':worst,'parameters':sum(w.size for w in p.values())}
    # Two fixed scalar optimizer steps independently exercise nontrivial bias correction.
    micro={'v':np.array([.125,-.25],dtype=np.float32)};mm={'v':np.zeros(2,dtype=np.float32)};vv={'v':np.zeros(2,dtype=np.float32)};micro_records=[]
    STATE['optimizer_micro_records']=micro_records
    for step,grad in ((1,[.03,-.07]),(2,[-.02,.11])):
        gg={'v':np.array(grad,dtype=np.float32)};before=[micro['v'].copy(),mm['v'].copy(),vv['v'].copy()]
        k.adam(micro,gg,mm,vv,step)
        for i in range(2):
            record={'step':step,'index':i,'before':[float(a[i]) for a in before],'gradient':float(gg['v'][i]),'after':[float(micro['v'][i]),float(mm['v'][i]),float(vv['v'][i])],'reference':None,'atol':2e-7,'rtol':2e-5,'status':'pending'}
            micro_records.append(record)
            wanted=ref.scalar_adam(before[0][i],gg['v'][i],step,before[1][i],before[2][i])
            record['reference']=[float(a) for a in wanted]
            witness_check(record,close(np.array(record['after']),np.array(wanted),2e-7,2e-5),'Adam_micro_reference')
    check(fd_checks==72 and ref.CALLS==292 and adam_checks==72,'reference_counts')
    check(k.COUNTS=={'models':4,'updates':6,'forward_calls':16,'forward_examples':20,'backward_calls':4,'backward_examples':8,'dense_forward_macs':587152,'dense_backward_macs':445840,'forward_matmuls':52,'backward_matmuls':24},'operator_counts')
    return {'finite_records':STATE['finite_records'],'loss_records':STATE['loss_records'],'optimizer_micro_records':micro_records,'fullsize_model_updates':4,'scalar_fixture_updates':2,'FD_records':fd_records,'Adam_records':adam_records,'models':diagnostics,'counts':k.COUNTS,'reference_forward_calls':ref.CALLS,'reference_forward_macs':ref.MACS,'FD_probes':fd_checks,'Adam_parameter_checks':adam_checks,'interventions':interventions,'real_data_access':False,'real_training':False}
