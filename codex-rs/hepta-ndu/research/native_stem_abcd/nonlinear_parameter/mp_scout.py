"""Independent arbitrary-precision root scout, not used in proof predicates."""
import mpmath as mp
mp.mp.dps=80

def candidate_gradient(a,b,kap=mp.mpf('0.01')):
    values=[]; derivatives=[]
    X=[mp.mpf(v)/2 for v in (-2,-1,0,1,2)]
    for x in X:
        for p0 in (0,1):
            step1=[]; d1s=[]
            phi=[x*x,x**3]
            for e1 in (-1,1):
                p1=p0^(e1==1)
                t1=x*x+x**4/2
                z=x+(a-1)*phi[0]+b*phi[1]+mp.mpf(e1)/5-x**4/2
                gain=1+e1*x/10
                L1=z*z+mp.mpf(p1)/20
                costs2=[]; grads2=[]
                for e2 in (-1,1):
                    p2=p1^(e2==1)
                    gap=gain*z+kap*z*z+mp.mpf(e2)/10-x/8
                    costs2.append(gap*gap+mp.mpf(p2)/25)
                    grads2.append([2*gap*(gain+2*kap*z)*v for v in phi])
                rho=mp.mpf('0.5') if p1==0 else mp.mpf(1)
                logits=[mp.exp(rho*v) for v in costs2]
                weights=[v/sum(logits) for v in logits]
                ce=mp.log(sum(logits)/2)/rho
                step1.append(L1+mp.mpf('.9')*ce)
                d1s.append([2*z*phi[j]+mp.mpf('.9')*sum(weights[i]*grads2[i][j] for i in range(2)) for j in (0,1)])
            rho=mp.mpf('.5') if p0==0 else mp.mpf(1)
            logits=[mp.exp(rho*v) for v in step1]
            w=[v/sum(logits) for v in logits]
            values.append(mp.mpf('.9')*mp.log(sum(logits)/2)/rho)
            derivatives.append([mp.mpf('.9')*sum(w[i]*d1s[i][j] for i in range(2)) for j in (0,1)])
    return mp.fsum(values)/10,tuple(mp.fsum(d[j] for d in derivatives)/10 for j in (0,1))

if __name__=='__main__':
    def f(a,b):return candidate_gradient(a,b)[1]
    a,b=mp.findroot(f,(mp.mpf('1.4778'),mp.mpf('-1.00356')),solver='mdnewton',tol=mp.mpf('1e-70'))
    print('a',mp.nstr(a,78))
    print('b',mp.nstr(b,78))
    print('cost',mp.nstr(candidate_gradient(a,b)[0],70))
    print('rounded16 candidate',mp.nstr(a,17),mp.nstr(b,17))
