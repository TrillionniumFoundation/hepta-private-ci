"""High-precision literal A5/A7 oracle and short-maturity evaluation path.

Requires mpmath>=1.3.0. It intentionally evaluates the paper's K/k formula
directly, separately from the float64 regrouping in hx_model.py.
"""


def precision_boundary_equity(parameters, x_values, digits=60):
    from mpmath import mp

    ctx = mp.clone()
    ctx.dps = digits
    cv = lambda value: ctx.mpf(str(value))
    p = {key: cv(value) for key, value in vars(parameters).items()}
    r, delta, sigma, m = p["r"], p["delta"], p["sigma"], p["maturity"]
    R, alpha, tax = r+p["liquidity"], p["alpha"], p["tax"]
    coupon, principal = p["coupon"], p["principal"]
    c, principal_unit = coupon/m, principal/m
    q = principal_unit-c/R
    a = (r-delta-sigma**2/2)/sigma**2
    z = ctx.sqrt(a*a+2*r/sigma**2)
    zt = ctx.sqrt(a*a+2*R/sigma**2)
    eta, gamma = z-a, z+a
    s = sigma*ctx.sqrt(m)
    phi = lambda t: ctx.exp(-t*t/2)/ctx.sqrt(2*ctx.pi)
    Phi = lambda t: ctx.erfc(-t/ctx.sqrt(2))/2
    discount = ctx.exp(-R*m)
    cost = (1-tax)*coupon+(1-discount)*q

    def B(y):
        if z+y == 0:
            return s*phi(z*s)-z*s*s*Phi(-z*s)
        return (Phi(y*s)-ctx.exp((z*z-y*y)*s*s/2)*Phi(-z*s))/(z+y)

    b = (cost/eta+q*discount*(B(a)+B(-a))+(c/R)*(B(zt)+B(-zt)))
    b /= delta/(eta-1)+alpha/m*(B(zt)+B(-zt))

    def K(v, y, power):
        factor = ctx.exp(((power-a)**2-y*y)*s*s/2)
        return ((Phi(y*s)-factor*Phi((power-a)*s))*ctx.exp(-power*v)
                +factor*ctx.exp(-power*v)*Phi(-v/s+(power-a)*s)
                -ctx.exp(-(a+y)*v)*Phi(-v/s+y*s))

    def little_k(v, y):
        factor = ctx.exp(((-eta-a)**2-y*y)*s*s/2)
        return (factor*ctx.exp(eta*v)*Phi(-v/s+(-eta-a)*s)
                -ctx.exp(-(a+y)*v)*Phi(-v/s+y*s))

    def A(v, y):
        def numerator(u):
            return K(v, u, gamma)+little_k(v, -u)
        terms = []
        for u in [y, -y]:
            terms.append(-ctx.diff(numerator, z) if z-u == 0 else numerator(u)/(z-u))
        return sum(terms)

    values = []
    for value in x_values:
        x = cv(value)
        E = b*ctx.exp(x)-delta*b/(z*sigma**2)*ctx.exp(-gamma*x)/(gamma+1)
        E -= cost/(z*sigma**2)*(1/eta+(1-ctx.exp(-gamma*x))/gamma)
        E += (discount*q*A(x, a)-(alpha*b/m-c/R)*A(x, zt))/(z*sigma**2)
        values.append(float(E))
    return float(b), values
