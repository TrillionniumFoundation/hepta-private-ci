#include <math.h>
#include <stddef.h>
void deterministic_lif(size_t n,const double *x,double tau,double theta,unsigned char *events){
    double v=0.,d=exp(-2./tau);int ref=0;
    for(size_t i=0;i<n;i++){
        if(ref){v=0.;ref=0;events[i]=0;continue;}
        v=d*v+(1.-d)*x[i];
        if(v>=theta){events[i]=1;v=0.;ref=1;}else events[i]=0;
    }
}
