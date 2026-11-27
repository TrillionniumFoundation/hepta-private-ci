# cython: language_level=3
"""Private low-level research callback; sticky failures are mandatory to check."""
from libc.math cimport exp, expm1, isfinite
from libc.stdint cimport uintptr_t
from scipy.special.cython_special cimport log_ndtr

cdef struct State:
    double x
    double sigma
    double drift
    double q
    int error
    int inject

cdef class Context:
    cdef State state
    def __init__(self,double x,double sigma,double drift,double q):
        self.state.x=x
        self.state.sigma=sigma
        self.state.drift=drift
        self.state.q=q
        self.state.error=0
        self.state.inject=0
    def address(self):
        return <uintptr_t>&self.state
    def error(self):
        return self.state.error
    def inject_failure(self,int code):
        """Fault-injection hook for private callback transport tests only."""
        self.state.inject=code

cdef api double survival(double s, void* data) noexcept nogil:
    cdef State* st=<State*>data
    cdef double scaled,a,b,first,second,delta,result
    if st.error:
        return 0.
    if st.inject:
        st.error=st.inject
        return 0.
    if s==0.:
        return 0.
    scaled=st.sigma*s
    if not isfinite(scaled) or scaled<=0.:
        st.error=1
        return 0.
    a=st.x/scaled
    b=st.drift*s/st.sigma
    first=log_ndtr(a+b)
    second=-2*(st.drift/st.sigma)*(st.x/st.sigma)+log_ndtr(-a+b)
    delta=second-first
    if not isfinite(delta) or delta>=0.:
        st.error=2
        return 0.
    result=2*s*exp(-st.q*s*s)*(exp(first)*(-expm1(delta)))
    if not isfinite(result):
        st.error=3
        return 0.
    return result
