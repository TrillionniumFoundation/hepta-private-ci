#include <algorithm>
#include <cmath>

// Only the exponential clock differs in corrected mode. Passing 2 recovers
// the existing, externally archived LIF coefficients and score vectors.
extern "C" void lif(int steps,int width,double dt,const double* drive,double* outputs) {
    for(int neuron=0;neuron<width;++neuron) {
        double membrane=0,previous_hit=0,adaptation=0;
        const double leak=std::exp(-dt/(4.+4.*(neuron%6)));
        const double adapt_leak=std::exp(-dt/(25.+15.*(neuron%4)));
        for(int t=0;t<steps;++t) {
            const double input=drive[t*width+neuron];
            const double potential=leak*membrane+(1-leak)*input-.3*adaptation;
            const double escape=1/(1+std::exp(std::clamp((.8-potential)/.22,-40.,40.)));
            const double flow=(1-previous_hit)*escape;
            membrane=(1-flow)*potential;
            adaptation=adapt_leak*adaptation+flow;
            double* out=outputs+(t*width+neuron)*4;
            out[0]=potential;out[1]=flow;out[2]=membrane;out[3]=adaptation;
            previous_hit=flow;
        }
    }
}
