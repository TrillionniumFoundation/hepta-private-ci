"""Research-only adversarial tests for asynchronous Erlang refractory phases."""
import math
import random
import unittest
import numpy as np

from .stopping import Stop
from .coupled_qvi import TwoCell, Rectangle
from .asynchronous_qvi import solve_asynchronous_policy
from .erlang_async_qvi import (solve_erlang_policy,solve_erlang_jacobi,
                               erlang_discount)

P=TwoCell(Stop(.035,.45,.16,1.,0.,.4),Stop(-.02,.42,.16,1.1,-.1,.6))
R=Rectangle(-2.,4.5,13,-2.,4.5,13)


def rate_pair(c,x):
    h=x[1]-x[0];d=c.diffusion*c.diffusion/(2*h*h)
    down=d-c.drift/(2*h);up=d+c.drift/(2*h)
    if min(down,up)<0:
        down=d+max(-c.drift,0.)/h
        up=d+max(c.drift,0.)/h
    return down,up


def scalar_deterministic_value(stop,x):
    """Independent *fixed-delay* one-dimensional discounted obstacle oracle."""
    n=len(x);pdown,pup=rate_pair(stop,x)
    v=np.zeros(n,dtype=float)
    d=math.exp(-stop.discount*stop.refractory)
    for _ in range(50000):
        reset_val=float(np.interp(stop.reset,x,v))
        nxt=np.empty_like(v)
        for i in range(n):
            a=pdown if i>0 else 0.
            b=pup if i<n-1 else 0.
            cont=((a*v[i-1] if i>0 else 0.)+(b*v[i+1] if i<n-1 else 0.))/(stop.discount+a+b)
            nxt[i]=max(cont,x[i]-stop.cost+d*reset_val)
        if np.max(np.abs(nxt-v))<1e-13:
            return nxt
        v=nxt
    raise RuntimeError('deterministic scalar oracle exhausted budget')


def independent_erlang_residual(p,result):
    """Check residual from scalar loops, not solver's graph/matrix/value code."""
    n1,n2=len(result.x1),len(result.x2)
    k1,k2=result.phases;v=result.values
    pairs=(rate_pair(p.first,result.x1),rate_pair(p.second,result.x2))
    maximum=0.;chosen_max=0.
    for i in range(n1+k1):
        for j in range(n2+k2):
            neighbors=[]
            for axis,(c,x,n,k,idx,downup) in enumerate(zip((p.first,p.second),
                    (result.x1,result.x2),(n1,n2),(k1,k2),(i,j),pairs)):
                if idx<n:
                    if idx>0:
                        dest=(idx-1,j) if axis==0 else (i,idx-1)
                        neighbors.append((downup[0],v[dest]))
                    if idx<n-1:
                        dest=(idx+1,j) if axis==0 else (i,idx+1)
                        neighbors.append((downup[1],v[dest]))
                elif idx==n:
                    interp=float(np.interp(c.reset,x,v[:n,j] if axis==0 else v[i,:n]))
                    neighbors.append((k/c.refractory,interp))
                else:
                    dest=(idx-1,j) if axis==0 else (i,idx-1)
                    neighbors.append((k/c.refractory,v[dest]))
            q=sum(rate*(nxt-v[i,j]) for rate,nxt in neighbors)-p.first.discount*v[i,j]
            a1=result.x1[i]-p.first.cost+v[n1+k1-1,j]-v[i,j] if i<n1 else -math.inf
            a2=result.x2[j]-p.second.cost+v[i,n2+k2-1]-v[i,j] if j<n2 else -math.inf
            errs=(q,a1,a2)
            maximum=max(maximum,abs(max(errs)))
            chosen_max=max(chosen_max,abs(errs[int(result.policy[i,j])]))
    return maximum,chosen_max


def sample_policy(p,result,start,seed,episodes=800):
    """Independent continuous-time stage-by-stage event sampler."""
    rng=random.Random(seed)
    x1,x2=result.x1,result.x2
    n1,n2=len(x1),len(x2)
    k1,k2=result.phases
    out=[]
    for _ in range(episodes):
        i,j=start;total=0.;weight=1.
        for step in range(20000):
            if weight<1e-10:break
            action=int(result.policy[i,j])
            if action:
                if action==1:
                    total+=weight*(x1[i]-p.first.cost)
                    i=n1+k1-1
                else:
                    total+=weight*(x2[j]-p.second.cost)
                    j=n2+k2-1
                continue
            moves=[]
            for axis,(c,x,n,k,idx) in enumerate(((p.first,x1,n1,k1,i),
                                                   (p.second,x2,n2,k2,j))):
                if idx<n:
                    down,up=rate_pair(c,x)
                    if idx>0:
                        moves.append((down,(idx-1,j) if axis==0 else (i,idx-1)))
                    if idx<n-1:
                        moves.append((up,(idx+1,j) if axis==0 else (i,idx+1)))
                elif idx>n:
                    moves.append((k/c.refractory,(idx-1,j) if axis==0 else (i,idx-1)))
                else:
                    left=min(int(np.searchsorted(x,c.reset,side='right'))-1,n-2)
                    f=(c.reset-x[left])/(x[left+1]-x[left])
                    moves.append(((k/c.refractory)*(1-f),(left,j) if axis==0 else (i,left)))
                    moves.append(((k/c.refractory)*f,(left+1,j) if axis==0 else (i,left+1)))
            q=sum(z for z,_ in moves)
            if q<=0:break
            weight*=math.exp(-p.first.discount*rng.expovariate(q))
            coin=rng.random()*q
            for qij,next_state in moves:
                coin-=qij
                if coin<=0:
                    i,j=next_state
                    break
            else:
                i,j=moves[-1][1]
        else:
            raise RuntimeError('simulator did not terminate')
        out.append(total)
    return float(np.mean(out)),float(np.std(out,ddof=1)/math.sqrt(episodes))


class ErlangAsynchronousTests(unittest.TestCase):
    def test_one_stage_exactly_reduces_to_exponential_parent(self):
        a=solve_asynchronous_policy(P,R)
        b=solve_erlang_policy(P,R,(1,1))
        np.testing.assert_array_equal(a.values,b.values)
        np.testing.assert_array_equal(a.policy,b.policy)
        self.assertEqual(b.stage_rates,(1/P.first.refractory,1/P.second.refractory))

    def test_two_solver_families_and_independent_residual(self):
        cfgs=[(P,R,(2,3)),(P,Rectangle(-2.,4.,9,-3.,4.,11),(4,2)),
              (TwoCell(Stop(.7,.2,.3,1.,-.5,.45),Stop(-.5,.18,.3,1.,-.4,1.1)),
               Rectangle(-2.5,4.5,9,-2.5,4.5,9),(3,4))]
        for p,r,k in cfgs:
            with self.subTest(k=k):
                a=solve_erlang_policy(p,r,k)
                b=solve_erlang_jacobi(p,r,k)
                self.assertLess(float(np.max(np.abs(a.values-b.values))),2e-8)
                self.assertLess(a.qvi_residual,3e-8)
                self.assertLess(b.qvi_residual,3e-8)
                resid,chosen=independent_erlang_residual(p,a)
                self.assertLess(resid,3e-8)
                self.assertLess(chosen,3e-8)

    def test_deterministic_discount_analytic_limit(self):
        c=P.first
        target=math.exp(-c.discount*c.refractory)
        discounts=[erlang_discount(c.discount,c.refractory,k) for k in (1,2,4,8,16,32,1000)]
        self.assertTrue(all(d>target for d in discounts))
        self.assertTrue(all(discounts[k]>discounts[k+1] for k in range(len(discounts)-1)))
        self.assertLess(abs(discounts[-1]-target),2e-6)

    def test_scalar_fixed_delay_grid_limit(self):
        p=TwoCell(P.first,Stop(0.,.4,.16,1e6,-.1,.6))
        x=np.linspace(R.x1min,R.x1max,R.n1)
        ref=scalar_deterministic_value(p.first,x)
        differences=[]
        for k in (1,2,4,8,16,32):
            got=solve_erlang_policy(p,R,(k,1))
            self.assertFalse(np.any(got.policy==2))
            delta=float(np.max(np.abs(got.values[:len(x),:len(got.x2)]-ref[:,None])))
            differences.append(delta)
        self.assertTrue(all(differences[i+1]<differences[i] for i in range(len(differences)-1)))
        self.assertLess(differences[-1],1e-5)
        self.assertGreater(differences[0],2e-4)

    def test_refractory_stage_value_contract_when_other_cell_inert(self):
        p=TwoCell(P.first,Stop(0.,.4,.16,1e6,-.1,.6))
        k=6
        out=solve_erlang_policy(p,R,(k,1))
        reset_v=np.interp(p.first.reset,out.x1,out.values[:len(out.x1),0])
        q=(k/p.first.refractory)/(k/p.first.refractory+p.first.discount)
        for stage in range(k):
            self.assertAlmostEqual(out.values[len(out.x1)+stage,0],
                                   (q**(stage+1))*reset_v,delta=2e-10)

    def test_asynchronous_other_cell_can_fire_across_stages(self):
        out=solve_erlang_policy(P,R,(5,7))
        n,m=len(out.x1),len(out.x2)
        self.assertTrue(np.any(out.policy[n:n+5,:m]==2))
        self.assertTrue(np.any(out.policy[:n,m:m+7]==1))
        self.assertFalse(np.any(out.policy[n:,:]==1))
        self.assertFalse(np.any(out.policy[:,m:]==2))
        self.assertGreater(out.values[-1,-1],0.)

    def test_swapping_cells_preserves_value(self):
        other=TwoCell(P.second,P.first)
        r=Rectangle(R.x2min,R.x2max,R.n2,R.x1min,R.x1max,R.n1)
        a=solve_erlang_policy(P,R,(2,5))
        b=solve_erlang_policy(other,r,(5,2))
        np.testing.assert_allclose(a.values,b.values.T,rtol=0.,atol=2e-9)

    def test_event_simulation_with_staged_recovery(self):
        r=Rectangle(-2.,4.,9,-2.,4.,9)
        out=solve_erlang_policy(P,r,(3,4))
        for s,start in enumerate(((8,8),(len(out.x1)+2,5),(len(out.x1)+2,len(out.x2)+3))):
            with self.subTest(start=start):
                mean,se=sample_policy(P,out,start,seed=6001+s,episodes=800)
                self.assertLess(abs(mean-out.values[start]),6.*se+.04)

    def test_seeded_policy_residual_sweep(self):
        rng=random.Random(630)
        for _ in range(20):
            rho=rng.uniform(.1,.5)
            p=TwoCell(Stop(rng.uniform(-.5,.5),rng.uniform(.2,.9),rho,1.,-.2,
                           rng.uniform(.1,2.)),
                      Stop(rng.uniform(-.5,.5),rng.uniform(.2,.9),rho,.9,-.4,
                           rng.uniform(.1,2.)))
            r=Rectangle(-2.5,4.5,9,-2.5,4.5,9)
            k=(rng.randint(2,5),rng.randint(2,5))
            got=solve_erlang_policy(p,r,k)
            resid,chosen=independent_erlang_residual(p,got)
            self.assertLess(resid,2e-8)
            self.assertLess(chosen,2e-8)

    def test_invalid_inputs_and_precision_fail_closed(self):
        for phases in ((0,1),(1,0),(1,33),(1,1.5),[1,2],(True,2),(1,),()):
            with self.subTest(phases=phases),self.assertRaises(ValueError):
                solve_erlang_policy(P,R,phases)
        c=TwoCell(Stop(0.,1e14,.16,1.,0.,.4),P.second)
        with self.assertRaises(ArithmeticError):
            solve_erlang_policy(c,R,(2,3))
        with self.assertRaises(RuntimeError):
            solve_erlang_policy(P,R,(2,3),max_iterations=1)
        with self.assertRaises(RuntimeError):
            solve_erlang_jacobi(P,R,(2,3),max_iterations=1)
        with self.assertRaises(ValueError):
            solve_erlang_policy(P,R,(2,3),decision_tolerance=-1.)
        with self.assertRaises(ValueError):
            solve_erlang_jacobi(P,R,(2,3),tolerance=0.)
        with self.assertRaises(ValueError):
            erlang_discount(.16,-1.,3)
        out=solve_erlang_policy(P,R,(2,3))
        for x,y in ((math.nan,0.),(-99.,0.),(0.,math.inf)):
            with self.assertRaises(ValueError):
                out.at_active(x,y)


if __name__=='__main__':
    unittest.main()
