// Temporal order is strict. The injected-current bank has already shifted the input by one bin.
#include <algorithm>
#include <array>
#include <cmath>
#include <vector>

extern "C" void reservoir(int kind,int steps,int width,int atoms,int table_rows,
    double delta_min,double delta_step,double boundary_ratio,const double* drive,
    const double* transition,const double* reset,const double* prices,double* outputs) {
    const int states=atoms+1;
    for(int neuron=0;neuron<width;++neuron) {
        std::vector<double> mass(reset,reset+states), next(states);
        double last_b=0,e=0,l=0,membrane=0,previous_hit=0,adaptation=0;
        const double leak=std::exp(-2./(4.+4.*(neuron%6)));
        const double adapt_leak=std::exp(-2./(25.+15.*(neuron%4)));
        for(int t=0;t<steps;++t){
            const double input=drive[t*width+neuron];
            double* out=outputs+(t*width+neuron)*4;
            if(kind==3) {
                const double potential=leak*membrane+(1-leak)*input-.3*adaptation;
                const double escape=1/(1+std::exp(std::clamp((.8-potential)/.22,-40.,40.)));
                const double flow=(1-previous_hit)*escape;
                membrane=(1-flow)*potential;
                adaptation=adapt_leak*adaptation+flow;
                out[0]=potential;out[1]=flow;out[2]=membrane;out[3]=adaptation;
                previous_hit=flow;
                continue;
            }
            const double feedback=kind==2?0:.25*std::tanh(e)+.25*std::tanh(l);
            const double rel=.28*std::tanh(input+.25*last_b+feedback);
            const double b=std::log1p(boundary_ratio*rel);
            const double index=std::clamp((last_b-b-delta_min)/delta_step,0.,double(table_rows-1));
            const int ix=std::min(int(index),table_rows-2);
            const double weight=index-ix;
            const double* a=transition+ix*states*states;
            const double* z=a+states*states;
            std::fill(next.begin(),next.end(),0);
            for(int i=0;i<states;++i)for(int j=0;j<states;++j) {
                double m=a[i*states+j]+weight*(z[i*states+j]-a[i*states+j]);
                next[j]+=mass[i]*m;
            }
            mass.swap(next); e=0;l=0;
            for(int i=0;i<atoms;++i) {
                e+=mass[i]*(prices[4*i]+rel*prices[4*i+2]);
                l+=mass[i]*(prices[4*i+1]+rel*prices[4*i+3]);
            }
            out[0]=b;out[1]=mass.back();out[2]=e;out[3]=l;
            last_b=b;
        }
    }
}
