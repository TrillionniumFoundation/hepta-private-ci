"""Separate high-precision divided differences and differentiated finite law.

This module imports no candidate code and uses no candidate quadrature, dual
arithmetic, or finite differences for its boundary derivative reference.
"""
import mpmath as mp
import numpy as np


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


def evaluate(theta):
    with mp.workdps(80):
        point = list(map(mp.mpf, map(float, theta)))
        value = boundary(point)
        derivatives = [mp.diff(lambda x, i=i: boundary(point[:i] + [x] + point[i+1:]), point[i])
                       for i in range(9)]
        reset = mp.log(90 / value)
        centers = [mp.mpf(2 * i + 1) / 20 for i in range(8)]
        lower = sum(x < reset for x in centers) - 1
        if lower < 0 or lower > 6 or any(abs(x - reset) < mp.mpf('1e-30') for x in centers):
            raise ValueError('Reference reset regime inadmissible')
        weights, dweights = [mp.mpf(0)] * 8, [[mp.mpf(0)] * 8 for _ in range(9)]
        weights[lower+1] = (reset - centers[lower]) * 10
        weights[lower] = 1 - weights[lower+1]
        for j, derivative in enumerate(derivatives):
            dweights[j][lower+1] = -10 * derivative / value
            dweights[j][lower] = 10 * derivative / value
        r, delta, _, _, _, _, sigma, _, _ = point
        rates = [sigma * sigma / mp.mpf('.02') + (r-delta-sigma*sigma/2)/mp.mpf('.2'),
                 sigma * sigma / mp.mpf('.02') - (r-delta-sigma*sigma/2)/mp.mpf('.2'),
                 sigma * sigma / mp.mpf('.01')]
        drates = [[mp.mpf(0)] * 3 for _ in range(9)]
        drates[0], drates[1] = [mp.mpf(5), -mp.mpf(5), mp.mpf(0)], [-mp.mpf(5), mp.mpf(5), mp.mpf(0)]
        drates[6] = [95 * sigma, 105 * sigma, 200 * sigma]
        q, dq = [mp.mpf(0)] * 1600, [[mp.mpf(0)] * 1600 for _ in range(9)]

        def edge(source, destination, rate, tangent):
            q[40*source+destination] += rate
            q[40*source+source] -= rate
            for j in range(9):
                dq[j][40*source+destination] += tangent[j]
                dq[j][40*source+source] -= tangent[j]

        for phase in range(8):
            for content in range(4):
                source = 4 * phase + content
                if phase < 7:
                    edge(source, source+4, rates[0], [row[0] for row in drates])
                if phase:
                    edge(source, source-4, rates[1], [row[1] for row in drates])
                else:
                    edge(source, 32+content, rates[2], [row[2] for row in drates])
        recovery = mp.mpf(40) / 7
        for content in range(4):
            edge(32+content, 36+content, recovery, [mp.mpf(0)] * 9)
            for phase in range(8):
                for dest in range(4):
                    retention = mp.mpf(7) / 8 if dest == content else mp.mpf(1) / 24
                    edge(36+content, 4*phase+dest, recovery*weights[phase]*retention,
                         [recovery*row[phase]*retention for row in dweights])
        emissions = []
        for state in range(40):
            emissions.extend([int(obs == 4) if state >= 32 else
                              (0 if obs == 4 else (.7 if obs == state % 4 else .1)) for obs in range(5)])
        emissions.extend(.97 if obs == state % 4 else .01 for state in range(40) for obs in range(4))
        prior = [weights[phase] / 4 for phase in range(8) for _ in range(4)] + [mp.mpf(0)] * 8
        dprior = [[row[phase] / 4 for phase in range(8) for _ in range(4)] + [mp.mpf(0)] * 8
                  for row in dweights]
        values = np.array(list(map(float, [value] + q + emissions + prior)))
        jacobian = np.array([[float(derivatives[j])] + list(map(float, dq[j]))
                             + [0.] * 360 + list(map(float, dprior[j])) for j in range(9)])
        return dict(values=values, jacobian=jacobian, lower=lower,
                    boundary_decimal=str(value), derivatives_decimal=list(map(str, derivatives)))
