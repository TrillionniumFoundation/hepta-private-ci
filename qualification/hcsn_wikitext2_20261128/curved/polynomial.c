#include <stdint.h>
/* Horner evaluation in double, final float32 state and two exact polynomial partials. */
void polyeval(const int64_t n, const int degree, const double *coef, const float *u,
              const float *t, float *value, float *grad_u, float *grad_t) {
    for(int64_t i=0;i<n;i++){
        double x=t[i],p=coef[2*degree],q=coef[2*degree+1],dp=0.,dq=0.;
        for(int k=degree-1;k>=0;k--){
            dp=dp*x+p;dq=dq*x+q;
            p=p*x+coef[2*k];q=q*x+coef[2*k+1];
        }
        value[i]=p+u[i]*q;grad_u[i]=q;grad_t[i]=dp+u[i]*dq;
    }
}
