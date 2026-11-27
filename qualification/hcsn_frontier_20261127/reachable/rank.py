"""Rigorous local reachability and observability checks for the stopped Gaussian grid."""
import argparse
import json

from flint import arb as R
from flint import arb_mat, ctx

ZERO, ONE = R(0), R(1)


def cdf(x):
    return (-x / R(2).sqrt()).erfc() / 2


def pdf(x):
    return (-x*x/2).exp() / (2*R.pi()).sqrt()


def gaussian_transition(grid):
    sigma, dt = R(".23"), R(".25")
    mu = R(".08") - R(".02") - sigma**2 / 2
    k = 2*mu/sigma**2
    shift, scale = mu*dt, sigma*dt.sqrt()
    cuts = [ZERO] + [(a+b)/2 for a,b in zip(grid, grid[1:])]
    n = len(grid)
    transition = arb_mat(n+1, n+1)
    derivative = arb_mat(n+1, n+1)
    for i,x in enumerate(grid):
        reflection = (-k*x).exp()
        primitive, slope = [], []
        for y in cuts:
            z = (y-x-shift)/scale
            reflected_z = (y+x-shift)/scale
            primitive.append(cdf(z)-reflection*cdf(reflected_z))
            slope.append(-pdf(z)/scale + k*reflection*cdf(reflected_z)
                         - reflection*pdf(reflected_z)/scale)
        primitive.append(ONE-reflection)
        slope.append(k*reflection)
        for j in range(n):
            transition[i,j] = primitive[j+1]-primitive[j]
            derivative[i,j] = slope[j+1]-slope[j]
        transition[i,n] = ONE-(primitive[-1]-primitive[0])
        derivative[i,n] = -(slope[-1]-slope[0])
    reset = R(".30")
    left = next(i for i in range(n-1) if grid[i] < reset < grid[i+1])
    weight = (reset-grid[left])/(grid[left+1]-grid[left])
    transition[n,left], transition[n,left+1] = ONE-weight, weight
    return transition, derivative


def price_rows(grid):
    # Literal Eq. (12), Eq. (A7), and the discounted-shortage readout in the parent.
    r, payout, sigma, recovery = map(R, (".08",".02",".23",".6"))
    coupon, principal, tax, q = map(R, ("6.39","61.68",".27",".09"))
    var = sigma**2
    a = (r-payout-var/2)/var
    z = (a*a+2*r/var).sqrt()
    zbar = (a*a+2*q/var).sqrt()
    eta, gamma = z-a, z+a
    disc = (-q).exp()
    def small(y):
        return disc*(cdf(y*sigma)-r.exp()*cdf(-z*sigma))/(z+y)
    def big(y):
        return (cdf(y*sigma)-((z*z-y*y)*var/2).exp()*cdf(-z*sigma))/(z+y)
    t, u = small(a)+small(-a), big(zbar)+big(-zbar)
    den = payout/(eta-1)+recovery*u
    w = (1-disc)/eta+t
    coefficient = w/den
    barrier = (((1-tax)/eta+(u-w)/q)*coupon+w*principal)/den
    assert coefficient > 0
    equity, loss = [], []
    def hit(x,y,h):
        shift = y*var*h
        scale = sigma*h.sqrt()
        return ((-(a-y)*x).exp()*cdf((-x-shift)/scale)
                + (-(a+y)*x).exp()*cdf((-x+shift)/scale))
    for x in grid:
        def k(y,j):
            return (((((j-a)**2-y*y)*var/2)-j*x).exp()*cdf((-x+(j-a)*var)/sigma)
                    - (-(a+y)*x).exp()*cdf((-x+y*var)/sigma))
        def full(y):
            coeff = cdf(y*sigma)-(((gamma-a)**2-y*y)*var/2).exp()*cdf((gamma-a)*sigma)
            return coeff*(-gamma*x).exp()+k(y,gamma)
        def aux(y):
            return (full(y)+k(-y,-eta))/(z-y)+(full(-y)+k(y,-eta))/(z+y)
        adj = principal-coupon/q
        cash_cost = (1-tax)*coupon+(1-disc)*adj
        decay = (-gamma*x).exp()
        recovered = recovery*barrier-coupon/q
        v = (barrier*x.exp()+(-payout*barrier*decay/(gamma+1)
            -cash_cost*(1/eta+(1-decay)/gamma)
            +disc*adj*aux(a)-recovered*aux(zbar))/(z*var))
        equity.append(v/20)
        loss.append((disc*adj*hit(x,a,ONE)-recovered*hit(x,zbar,ONE))/20)
    probes = [[hit(x,a,R(h)) for x in grid]+[ZERO] for h in (".08",".125",".5","3")]
    return barrier, coefficient, [equity+[ZERO],loss+[ZERO]]+probes


def matrix_columns(columns):
    return arb_mat([list(row) for row in zip(*columns)])


def run(atoms,bits):
    ctx.prec = bits
    grid = [R(".015")+(R("1.30")-R(".015"))*j/(atoms-1) for j in range(atoms)]
    M,D = gaussian_transition(grid)
    n=atoms+1
    for i in range(atoms):
        assert all(M[i,j] > 0 for j in range(n)), "increase precision to resolve positive bins"
        assert sum(M[i,j] for j in range(n)).contains(1)
        assert sum(D[i,j] for j in range(n)).contains(0)
    initial = arb_mat([[M[atoms,j] for j in range(n)]])
    # A level c_j affects x by -c_j on its own step and +c_j on the next.
    # terminal c_{A+1}=0. All later inputs agree in both histories.
    powers = [M**i for i in range(n+1)]
    derivatives = []
    for j in range(1,n):
        row = (initial*powers[j-1]*(M*D-D*M)*powers[atoms-j])
        derivatives.append([row[0,k] for k in range(atoms)])
    reach = arb_mat(derivatives).det()
    assert not reach.contains(0), "reachable tangent rank inconclusive"
    flow = [ZERO]*atoms+[ONE]
    f = arb_mat([[x] for x in flow])
    future = [[(p*f)[i,0] for i in range(n)] for p in powers[:atoms]]
    O = matrix_columns([[ONE]*n]+future)
    obs = O.det()
    assert not obs.contains(0), "observability rank inconclusive"
    barrier,coef,rows = price_rows(grid)
    report = {}
    for label,visible in [('priced', [flow]+rows[:2]),('augmented',[flow]+rows)]:
        # Include the future one-interval firing probability along with the current port and mass.
        mat=matrix_columns([[ONE]*n]+visible+[future[1]])
        gram=(mat.transpose()*mat).det()
        assert gram > 0, "next-flow distinguishing determinant inconclusive"
        report[label]={'terminal_observations':len(visible),'augmented_gram_determinant':gram.str(22)}
    return dict(atoms=atoms,bits=bits,barrier=barrier.str(22),
                barrier_principal_derivative=coef.str(22),reachable_minor=reach.str(22),
                future_bank_determinant=obs.str(22),next_step=report)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bits',type=int,default=768)
    args=parser.parse_args()
    print(json.dumps([run(n,args.bits) for n in (8,12)],indent=2))
