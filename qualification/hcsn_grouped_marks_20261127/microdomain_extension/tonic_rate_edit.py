"""Direct local rate edits for a fixed absolute reset and a controllable common boundary."""
import math
from typing import NamedTuple
from tonic_microdomains import zero_drift_dimensionless_moment


class RateEdit(NamedTuple):
    preactivation: float
    initial_distance: float
    boundary: float
    principal: float
    achieved_rate: float


class TonicRatePort:
    """Zero-drift finite-mean models with equal path reset levels and volatility."""
    def __init__(self,copies,volatility,refractory,absolute_reset,base_principal,intercept,slope,drive_fraction,correlation=None):
        numbers=(volatility,refractory,absolute_reset,base_principal,intercept,slope,drive_fraction)
        if not all(math.isfinite(i) for i in numbers) or min(volatility,refractory,absolute_reset,base_principal,slope)<=0:
            raise ValueError('finite parameters and positive physical scales required')
        if not 0<drive_fraction<1:
            raise ValueError('fractional drive scale must be in (0,1)')
        if correlation is None:
            constant=zero_drift_dimensionless_moment(copies,1)
            if not math.isfinite(constant):raise ValueError('positive live tonic rates require a finite mean')
        else:
            if copies!=2 or not -1<correlation<0:
                raise ValueError('the two-path correlated closed mean applies to strictly negative correlation')
            constant=-1/correlation
        self.coefficient=constant/volatility**2
        self.refractory=refractory;self.absolute_reset=absolute_reset;self.base=base_principal
        self.intercept=intercept;self.slope=slope;self.fraction=drive_fraction
        self.minimum_boundary=intercept+slope*base_principal*(1-drive_fraction)
        self.maximum_boundary=intercept+slope*base_principal*(1+drive_fraction)
        if self.minimum_boundary<=0:raise ValueError('all modeled boundaries must stay positive')

    def forward(self,z):
        if not math.isfinite(z):raise ValueError('a finite preactivation is required')
        principal=self.base*(1+self.fraction*math.tanh(z))
        boundary=self.intercept+self.slope*principal
        distance=math.log(self.absolute_reset/boundary)
        rate=1/(self.refractory+self.coefficient*max(distance,0.)**2)
        return RateEdit(z,distance,boundary,principal,rate)

    def invert(self,target,existing_z):
        if not math.isfinite(target) or not 0<target<=1/self.refractory:
            raise ValueError('rate outside the finite positive rate interval')
        current=self.forward(existing_z)
        if target==1/self.refractory:
            if current.initial_distance<=0:return current
            distance=0.
        else:
            distance=math.sqrt((1/target-self.refractory)/self.coefficient)
        boundary=self.absolute_reset*math.exp(-distance)
        if not self.minimum_boundary<boundary<self.maximum_boundary:
            raise ValueError('required boundary lies outside finite drive reach')
        principal=(boundary-self.intercept)/self.slope
        control=(principal/self.base-1)/self.fraction
        if not -1<control<1:raise ValueError('drive inversion reached floating-point saturation')
        return self.forward(math.atanh(control))
