"""Separate high-precision divided differences and differentiated finite law.

This module imports no candidate code and uses no candidate quadrature, dual
arithmetic, or finite differences for its boundary derivative reference.
"""
import mpmath as mp


def boundary(theta):
    r, delta, alpha, tax, coupon, principal, sigma, liquidity, maturity = theta
    variance, rate = sigma ** 2, r + liquidity
    a = (r - delta - variance / 2) / variance
    z = mp.sqrt(a * a + 2 * r / variance)
    zt = mp.sqrt(a * a + 2 * rate / variance)
    eta, gamma = z - a, z + a
    s, c = sigma * mp.sqrt(maturity), coupon / maturity
    q = principal / maturity - c / rate
    discount = mp.exp(-rate * maturity)
    cost = (1 - tax) * coupon - mp.expm1(-rate * maturity) * q

    def divided(y):
        return (mp.erfc(-y * s / mp.sqrt(2)) / 2
                - mp.exp((z * z - y * y) * s * s / 2)
                * mp.erfc(z * s / mp.sqrt(2)) / 2) / (z + y)

    bs = divided(-zt) + divided(zt)
    return ((cost / eta + q * discount * (divided(-a) + divided(a)) + c / rate * bs)
            / (variance * (gamma + 1) / 2 + alpha / maturity * bs))



def law(theta):
    parameters, x = theta[:9], theta[9]
    r, delta, alpha, tax, coupon, principal, sigma, liquidity, maturity = parameters
    b = boundary(parameters)
    variance, rate = sigma*sigma, r+liquidity
    a = (r-delta-variance/2)/variance
    z = mp.sqrt(a*a+2*r/variance)
    zt = mp.sqrt(a*a+2*rate/variance)
    eta, gamma = z-a, z+a
    s, c = sigma*mp.sqrt(maturity), coupon/maturity
    q, discount = principal/maturity-c/rate, mp.exp(-rate*maturity)
    cost = (1-tax)*coupon-mp.expm1(-rate*maturity)*q
    normal = lambda argument: mp.erfc(-argument/mp.sqrt(2))/2
    def a_function(y):
        def numerator(u):
            exponent = (z*z-u*u)*s*s/2
            common = -mp.exp(exponent-gamma*x)*(normal(z*s)-normal(z*s-x/s))
            common += mp.exp(exponent+eta*x)*normal(-x/s-z*s)
            return (mp.exp(-gamma*x)*normal(u*s)+common
                    -mp.exp(-(a+u)*x)*normal(-x/s+u*s)
                    -mp.exp(-(a-u)*x)*normal(-x/s-u*s))
        return numerator(y)/(z-y)+numerator(-y)/(z+y)
    equity = b*mp.exp(x)-delta*b/(z*variance)*mp.exp(-gamma*x)/(gamma+1)
    equity -= cost/(z*variance)*(1/eta-mp.expm1(-gamma*x)/gamma)
    equity += (discount*q*a_function(a)-(alpha*b/maturity-c/rate)*a_function(zt))/(z*variance)
    f = normal(-x/s-a*s)+mp.exp(-2*a*x)*normal(-x/s+a*s)
    g = (mp.exp((-a+zt)*x)*normal(-x/s-zt*s)
         +mp.exp((-a-zt)*x)*normal(-x/s+zt*s))
    debt = c/rate+discount*q*(1-f)+(alpha*b/maturity-c/rate)*g
    return [b,equity,f,g,debt]


def evaluate(theta):
    with mp.workdps(80):
        point=list(map(mp.mpf,map(float,theta)))
        values=law(point)
        jacobian=[]
        for channel in range(5):
            jacobian.append([mp.diff(lambda value,j=j: law(point[:j]+[value]+point[j+1:])[channel],point[j])
                             for j in range(10)])
        return dict(values=list(map(float,values)),jacobian=[list(map(float,row)) for row in jacobian],
                    values_decimal=list(map(str,values)),jacobian_decimal=[list(map(str,row)) for row in jacobian])
