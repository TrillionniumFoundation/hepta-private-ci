/* Positive birth–death approximation to absorbing transport, deterministic
   refractory reinjection, and a tracked open upper exit. No upper reentry. */
#include <math.h>
#include <stdint.h>
#include <stdlib.h>

typedef struct {
    int n, reset_i, delay, slot;
    double dx,dt,escape,total_refractory;
    double *mass,*queue,*upper,*rhs;
    const double *e0,*e1,*l0,*l1;
} Cell;

static void init(Cell *s,int n,double dx,double dt,double u,
                 const double *e0,const double *e1,const double *l0,const double *l1) {
    s->n=n;s->dx=dx;s->dt=dt;s->reset_i=lround(.3/dx)-1;s->delay=lround(.25/dt);s->slot=0;s->escape=0;
    s->mass=calloc(n,sizeof(double));s->queue=calloc(s->delay,sizeof(double));
    s->upper=calloc(n,sizeof(double));s->rhs=calloc(n,sizeof(double));
    s->e0=e0;s->e1=e1;s->l0=l0;s->l1=l1;
    double lam=u/(.23*.23/2),norm=.30+.25*u;
    for (int i=0;i<n;i++){
        double x=(i+1)*dx;
        double weight=(x<=.30 ? -expm1(-lam*x) : -expm1(-lam*.30)*exp(-lam*(x-.30)));
        s->mass[i]=weight*dx/norm;
    }
    for(int i=0;i<s->delay;i++)s->queue[i]=u/norm;
    s->total_refractory=.25*u/norm;
}
static void dispose(Cell *s){free(s->mass);free(s->queue);free(s->upper);free(s->rhs);}

static double prop(Cell *s,double v,double wall_velocity,double current) {
    double total=0,moment=0,e=0,l=0;
    int n=s->n;
    for(int i=0;i<n;i++){
        double p=s->mass[i];
        total+=p;moment+=p*(i+1)*s->dx;
        e+=p*(s->e0[i]+(v+.9)*s->e1[i]);l+=p*(s->l0[i]+(v+.9)*s->l1[i]);
    }
    double vel=.03355-.7*v+.6*tanh(fmax(e,0.))*(.30-moment/total)-4.1*tanh(fmax(l,0.))-wall_velocity+current;
    double D=.23*.23/2,pe=vel*s->dx/D;
    double up,down;
    if(fabs(pe)<1e-7){
        up=D/(s->dx*s->dx)*(1+pe/2+pe*pe/12);down=D/(s->dx*s->dx)*(1-pe/2+pe*pe/12);
    }else{
        up=vel/(s->dx*(-expm1(-pe)));down=vel/(s->dx*expm1(pe));
    }
    double diag=1+s->dt*(up+down),sup=-s->dt*down,sub=-s->dt*up;
    double reset=s->queue[s->slot];
    s->mass[s->reset_i]+=s->dt*reset;
    s->upper[0]=sup/diag;s->rhs[0]=s->mass[0]/diag;
    for(int i=1;i<n;i++){
        double piv=diag-sub*s->upper[i-1];
        s->upper[i]=sup/piv;s->rhs[i]=(s->mass[i]-sub*s->rhs[i-1])/piv;
    }
    s->mass[n-1]=s->rhs[n-1];
    for(int i=n-2;i>=0;i--)s->mass[i]=s->rhs[i]-s->upper[i]*s->mass[i+1];
    double flux=down*s->mass[0];
    s->queue[s->slot]=flux;s->slot=(s->slot+1)%s->delay;
    s->total_refractory+=s->dt*(flux-reset);s->escape+=s->dt*up*s->mass[n-1];
    return flux;
}

/* Contiguous output rows contain time, source wall, source flux, receiver flux,
   cumulative open-edge escape for both cells. src and rec share no density. */
void response(int n,int steps,int pulse,double period,double dx,double dt,double eps,double gain,
              double amp,double us,double ur,double bminus,double bprime,
              const double *e0,const double *e1,const double *l0,const double *l1,double *out){
    Cell src,rec;init(&src,n,dx,dt,us,e0,e1,l0,l1);init(&rec,n,dx,dt,ur,e0,e1,l0,l1);
    double z=src.total_refractory,q=0.,h0=atanh(-.8),wb0=bminus+.1*bprime;
    double half=-expm1(-dt/2),full=-expm1(-dt);
    for(int i=0;i<steps;i++){
        double t=(i+.5)*dt, g=1+amp*(pulse?(t>=20 && t<24):cos(2*acos(-1.)*t/period));
        double goal=g*src.total_refractory,zmid=z+half*(goal-z),dz=goal-zmid;
        double vs=tanh(h0+eps*zmid),bs=bminus+(vs+.9)*bprime;
        double wall=log(bs/wb0),svel=(bprime/bs)*(1-vs*vs)*eps*dz;
        double qmid=q+half*(wall-q),dq=wall-qmid;
        double vr=tanh(h0+gain*qmid),br=bminus+(vr+.9)*bprime;
        double rvel=(bprime/br)*(1-vr*vr)*gain*dq;
        double js=prop(&src,vs,svel,0.),jr=prop(&rec,vr,rvel,0.);
        z+=full*(goal-z);q+=full*(wall-q);
        double endv=tanh(h0+eps*z),y=log((bminus+(endv+.9)*bprime)/wb0);
        out[i*6]=(i+1)*dt;out[i*6+1]=y;out[i*6+2]=js;out[i*6+3]=jr;
        out[i*6+4]=src.escape;out[i*6+5]=rec.escape;
    }
    dispose(&src);dispose(&rec);
}

/* Identical hard reset and initially empty refractory history, followed by
   scalar current injection. The independent receiver is enabled only at a
   declared later common read time; before then it is the same unforced cell. */
void condition(int n,int steps,double dx,double dt,double eps,double gain,double amp,double duration,
               double read_time,double ur,double bminus,double bprime,const double *e0,const double *e1,
               const double *l0,const double *l1,double *out){
    Cell src,rec; init(&src,n,dx,dt,.1,e0,e1,l0,l1); init(&rec,n,dx,dt,ur,e0,e1,l0,l1);
    for(int i=0;i<n;i++)src.mass[i]=0.;
    src.mass[src.reset_i]=1.;
    for(int i=0;i<src.delay;i++)src.queue[i]=0.;
    src.total_refractory=0.;
    double z=0.,q=0.,h0=atanh(-.8),wb0=bminus+.1*bprime;
    double half=-expm1(-dt/2),full=-expm1(-dt);
    for(int i=0;i<steps;i++){
        double t=(i+.5)*dt,goal=src.total_refractory,zmid=z+half*(goal-z),dz=goal-zmid;
        double vs=tanh(h0+eps*zmid),bs=bminus+(vs+.9)*bprime;
        double source_wall=log(bs/wb0),svel=(bprime/bs)*(1-vs*vs)*eps*dz;
        double observed=t>=read_time?source_wall:0.;
        double qmid=q+half*(observed-q),dq=observed-qmid;
        double vr=tanh(h0+gain*qmid),br=bminus+(vr+.9)*bprime;
        double rvel=(bprime/br)*(1-vr*vr)*gain*dq;
        double js=prop(&src,vs,svel,t<duration?amp:0.),jr=prop(&rec,vr,rvel,0.);
        z+=full*(goal-z);q+=full*(observed-q);
        double endv=tanh(h0+eps*z),y=log((bminus+(endv+.9)*bprime)/wb0);
        out[i*6]=(i+1)*dt;out[i*6+1]=y;out[i*6+2]=js;out[i*6+3]=jr;
        out[i*6+4]=src.escape;out[i*6+5]=rec.escape;
    }
    dispose(&src);dispose(&rec);
}
