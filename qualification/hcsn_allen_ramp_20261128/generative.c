#include <stddef.h>
#include <math.h>

/* Clock, current, survival and reset conventions are identical to the sealed bin forecasts.
   The sampler's inputs do not include an observed spike train. mode 0/1 is dual/no price,
   2 is the stochastic LIF and 3 is the GLM. */
int sample(int n, int replicates, int mode, const double *current, const double *drive,
           const double *drift, const double *table, const double *grid, const double *reset,
           const double *mid, const double *change, const double *base, const double *coef,
           double tau, const double *uniforms, int *counts, int *first, double *trace) {
    const double decay=exp(-2./tau), dt[3]={exp(-2./5),exp(-2./20),exp(-2./80)};
    double centre=0.;
    for(int j=0;j<4;j++)centre+=grid[j]*reset[j];
    for(int s=0;s<replicates;s++){
        double mass[4]={reset[0],reset[1],reset[2],reset[3]},E=0.,L=0.,mem=0.,past[3]={0.};
        int last=0;
        counts[s]=0;first[s]=n;
        for(int t=0;t<n;t++){
            double moved[5]={0.},eta=base[t];
            if(mode<2){
                double v=drift[t];
                if(mode==0){
                    double mean=0.;for(int j=0;j<4;j++)mean+=mass[j]*grid[j];
                    v+=.65*tanh(fmax(E,0.))*(centre-mean)-.65*tanh(fmax(L,0.));
                }
                if(v<=-5.||v>=5.)return 1;
                double w=(v+5.)*409.6;int low=(int)w;w-=low;
                for(int j=0;j<4;j++)for(int k=0;k<5;k++){
                    int ix=(low*4+j)*5+k;moved[k]+=mass[j]*((1.-w)*table[ix]+w*table[ix+20]);
                }
                double h=fmax(1e-10,fmin(1.-1e-10,moved[4]));
                eta+=coef[0]*log(-log1p(-h));
            }else if(mode==2){
                mem=last?0.:decay*mem+(1.-decay)*current[t]/100.;
                eta+=coef[0]*mem;
            }else{
                for(int j=0;j<3;j++){past[j]=dt[j]*past[j]+(1.-dt[j])*last;eta+=coef[j]*past[j];}
            }
            const double q=exp(fmax(-35.,fmin(9.,eta)));
            double p=last?1e-10:fmax(1e-10,fmin(1.-1e-10,-expm1(-q)));
            int emit=uniforms[(size_t)s*n+t]<p;
            if(s==0)trace[t]=p;
            if(emit){if(!counts[s])first[s]=t;counts[s]++;}
            if(mode<2){
                double live=moved[0]+moved[1]+moved[2]+moved[3];
                if(!emit&&!last&&live<=0.)return 2;
                E=L=0.;
                for(int j=0;j<4;j++){
                    mass[j]=emit||last?reset[j]:moved[j]/live;
                    if(!emit){E+=mass[j]*(mid[2*j]+drive[t]*change[2*j]);L+=mass[j]*(mid[2*j+1]+drive[t]*change[2*j+1]);}
                }
            }
            last=emit;
        }
    }
    return 0;
}
