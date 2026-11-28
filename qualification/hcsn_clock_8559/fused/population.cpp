// Fused single-thread update and vector-Jacobian product for the 4-live + 1-refractory HCSN.
#include <algorithm>
#include <cmath>
#include <cstddef>
struct Axis {
    int idx;
    float frac, slope;
};
static inline Axis axis(float x, float first, float step, int n) {
    const float raw=(x-first)/step;
    const float clipped=std::min(float(n-1),std::max(0.f,raw));
    const int ix=std::min(n-2,int(clipped));
    return {ix,clipped-ix,(raw>=0.f && raw<=float(n-1))?1.f/step:0.f};
}
static inline float lerp(float a,float b,float w) {
    return w<.5f ? std::fma(w,b-a,a) : std::fma(-(1.f-w),b-a,b);
}
#ifdef HCSN_REFERENCE_COORDINATES
#define POSITION_ARGUMENT const float* position,
#define POSITION(k) Point(position+9*(k))
#else
#define POSITION_ARGUMENT
#define POSITION(k) Point(u[(k)],prev[(k)],beta,fixed)
#endif
struct Point {
    float bounded,relative,wall;
    Axis shift,drift;
    explicit Point(const float* v) : bounded(v[0]),relative(v[1]),wall(v[2]),
        shift{int(v[3]),v[4],v[5]},drift{int(v[6]),v[7],v[8]} {}
    Point(float u,float prev,float beta,bool fixed) {
        bounded=std::tanh(u);
        relative=fixed?0.f:.21f*bounded;
        wall=std::log1p(beta*relative);
        shift=axis(wall-prev,-.45f,.005f,181);
        drift=axis(std::fma(.25f,bounded,-.10f),-.35f,.0125f,41);
    }
};
static inline void transition(const float* table,const Point& p,int old_atom,int next,float& prob,float& dx,float& dy) {
    const int k=20*(41*p.shift.idx+p.drift.idx)+5*old_atom+next;
    const float a=table[k],b=table[k+20],c=table[k+820],d=table[k+840];
    const float low=lerp(a,b,p.drift.frac),high=lerp(c,d,p.drift.frac);
    prob=lerp(low,high,p.shift.frac);
    dx=(high-low)*p.shift.slope;
    dy=lerp(b-a,d-c,p.shift.frac)*p.drift.slope;
}
static inline void coords(const float* o,const float* probes,const Point& p,float* c) {
    c[0]=o[0];c[1]=o[5];c[2]=o[6];c[3]=o[7];
    for (int h=0;h<3;++h) {
        c[4+h]=0.f;
        for(int a=0;a<4;++a) {
            const int k=(p.drift.idx*4+a)*3+h;
            c[4+h]+=o[1+a]*lerp(probes[k],probes[k+12],p.drift.frac);
        }
    }
}
extern "C" void population_forward(int n,int width,float beta,int fixed,POSITION_ARGUMENT const float* u,const float* prev,const float* mass,const float* refractory,const float* table,const float* prices,const float* probes,const float* emit,float* out) {
    for(int k=0;k<n;++k) {
        const Point p=POSITION(k);float* o=out+9*k;
        o[0]=p.wall;
        for(int b=0;b<5;++b) {
            float arrival=0.f;
            for(int a=0;a<4;++a) {
                float prob,dx,dy;transition(table,p,a,b,prob,dx,dy);
                arrival+=mass[4*k+a]*prob;
            }
            o[1+b]=arrival+(b==2?refractory[k]:0.f);
        }
        for(int j=0;j<2;++j) {
            o[6+j]=0.f;
            for(int a=0;a<4;++a)
                o[6+j]+=o[1+a]*(prices[2*a+j]+p.relative*prices[8+2*a+j]);
        }
        float c[7];coords(o,probes,p,c);
        const float* w=emit+7*(k%width);
        o[8]=0.f;for(int j=0;j<7;++j)o[8]+=c[j]*w[j];
    }
}
extern "C" void population_backward(int n,int width,float beta,int fixed,POSITION_ARGUMENT const float* u,const float* prev,const float* mass,const float* table,const float* prices,const float* probes,const float* emit,const float* out,const float* grad,float* du,float* dprev,float* dmass,float* drefr,float* demit) {
    for(int k=0;k<n;++k) {
        const Point p=POSITION(k);
        const float *o=out+9*k,*g=grad+9*k,*w=emit+(k%width)*7;
        float c[7];coords(o,probes,p,c);
        for(int j=0;j<7;++j)demit[(k%width)*7+j]+=g[8]*c[j];
        float dprice[2]={g[6]+g[8]*w[2],g[7]+g[8]*w[3]};
        float drel=0.f,dmu=0.f,dshift=0.f,darrival[5];
        for(int a=0;a<4;++a) {
            float v=g[1+a];
            for(int j=0;j<2;++j) {
                v+=dprice[j]*(prices[2*a+j]+p.relative*prices[8+2*a+j]);
                drel+=dprice[j]*o[1+a]*prices[8+2*a+j];
            }
            for(int h=0;h<3;++h) {
                const int j=(p.drift.idx*4+a)*3+h;
                const float gh=g[8]*w[4+h];
                v+=gh*lerp(probes[j],probes[j+12],p.drift.frac);
                dmu+=gh*o[1+a]*(probes[j+12]-probes[j])*p.drift.slope;
            }
            darrival[a]=v;
        }
        darrival[4]=g[5]+g[8]*w[1];
        drefr[k]=darrival[2];
        for(int a=0;a<4;++a) {
            float v=0.f;
            for(int b=0;b<5;++b) {
                float prob,dx,dy;transition(table,p,a,b,prob,dx,dy);
                v+=darrival[b]*prob;
                float scale=darrival[b]*mass[4*k+a];
                dshift+=scale*dx;dmu+=scale*dy;
            }
            dmass[4*k+a]=v;
        }
        dprev[k]=-dshift;
        const float dwall=g[0]+g[8]*w[0]+dshift;
        drel+=dwall*beta/(1.f+beta*p.relative);
        du[k]=(1.f-p.bounded*p.bounded)*(.25f*dmu+(fixed?0.f:.21f*drel));
    }
}
