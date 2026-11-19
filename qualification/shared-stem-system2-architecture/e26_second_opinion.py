"""Independent exact dynamic-programming sign-flip distribution, no brute force.

The separate enumeration algorithm lives in e26_frozen_admission.py. This
second opinion never calls that function. Both are integer / exact-rational.
"""
from collections import Counter
from fractions import Fraction


def independent_signflip(differences):
    if type(differences) not in (tuple,list) or not 1<=len(differences)<=12:
        raise ValueError('bounded source cluster list')
    if any(type(x) is not int or not -16<=x<=16 for x in differences):
        raise ValueError('integer original question or candidate diffs')
    sums=Counter({0:1})
    for difference in differences:
        following=Counter()
        for total,weight in sums.items():
            following[total+difference]+=weight
            following[total-difference]+=weight
        sums=following
    observed=abs(sum(differences))
    count=sum(weight for total,weight in sums.items() if abs(total)>=observed)
    if sum(sums.values())!=2**len(differences):
        raise ValueError('independent distribution mass incomplete')
    return Fraction(count,2**len(differences))
