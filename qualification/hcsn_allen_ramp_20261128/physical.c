#include <math.h>
#include <stddef.h>

/* State is conditional on the observed history strictly before this bin. */
int boundary_feature(size_t n, const double *current, const unsigned short *count,
                     const double *kern, const double *grid, const double *reset,
                     const double *p0, const double *p1, const double kappa,
                     const double scale, const int mode, double *output) {
    double m[4], E=0., L=0., last=0., centre=0.;
    int refractory=0;
    for(int j=0;j<4;j++) {m[j]=reset[j];centre+=grid[j]*reset[j];}
    for(size_t t=0;t<n;t++) {
        double u=tanh(current[t]/scale), wall=log1p(kappa*u), mean=0.;
        for(int j=0;j<4;j++) mean+=m[j]*grid[j];
        double drift=.03355-.70*u+(last-wall)/.25;
        if(mode==0 || mode==1) drift+=.65*tanh(fmax(E,0.))*(centre-mean);
        if(mode==0 || mode==2) drift-=.65*tanh(fmax(L,0.));
        if(fabs(drift)>=5.)return 1;
        double a=(drift+5.)*409.6;int i=(int)a;a-=i;
        double sums[5]={0.,0.,0.,0.,0.};
        for(int j=0;j<4;j++)for(int k=0;k<5;k++) {
            const int ix=(i*4+j)*5+k;
            sums[k]+=m[j]*((1.-a)*kern[ix]+a*kern[ix+20]);
        }
        double h=refractory?0.:sums[4];
        if(h < -1e-12 || h>1.+1e-12)return 2;
        h=fmax(1e-10,fmin(1.-1e-10,h));
        output[t]=log(-log1p(-h));
        if(count[t]>0){for(int j=0;j<4;j++)m[j]=reset[j];E=L=0.;refractory=1;}
        else{
            if(refractory){for(int j=0;j<4;j++) m[j]=reset[j];}
            else {
                double live=sums[0]+sums[1]+sums[2]+sums[3];if(live<=0.)return 3;
                for(int j=0;j<4;j++)m[j]=sums[j]/live;
            }
            E=L=0.;
            for(int j=0;j<4;j++){E+=m[j]*(p0[2*j]+u*p1[2*j]);L+=m[j]*(p0[2*j+1]+u*p1[2*j+1]);}
            refractory=0;
        }
        last=wall;
    }
    return 0;
}
void lif_feature(size_t n,const double *x,const unsigned short *ys,double tau_ms,double *out){
    const double decay=exp(-2./tau_ms);double v=0.;int refractory=0;
    for(size_t t=0;t<n;t++){
        if(refractory)v=0.;else v=decay*v+(1.-decay)*(x[t]/100.);
        out[t]=v;
        refractory=ys[t]>0;if(refractory)v=0.;
    }
}
