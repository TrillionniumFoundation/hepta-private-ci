#include <algorithm>
#include <array>
#include <cmath>
#include <vector>

// Capture only candidate event states; every millisecond of the conditioning stream is stepped.
extern "C" void capture(int steps,int width,int atoms,int rows,double low,double increment,double ratio,
    const double* input,const double* bank,const double* reset,const double* prices,
    const int* indices,int count,double* result) {
    const int states=atoms+1;
    for (int w=0;w<width;++w) {
        std::vector<double> mass(reset,reset+states),next(states);
        double previous=0,e=0,l=0;
        int candidate=0;
        for(int t=0;t<steps;++t) {
            double rel=.28*std::tanh(input[t*width+w]+.25*previous+.25*(std::tanh(e)+std::tanh(l)));
            double boundary=std::log1p(ratio*rel);
            double index=std::clamp((previous-boundary-low)/increment,0.,double(rows-1));
            int lo=std::min(int(index),rows-2);
            const double* left=bank+lo*states*states,*right=left+states*states;
            std::fill(next.begin(),next.end(),0.);
            for(int i=0;i<states;++i)for(int j=0;j<states;++j){
                int off=i*states+j;
                next[j]+=mass[i]*(left[off]+(index-lo)*(right[off]-left[off]));
            }
            mass.swap(next);e=0;l=0;
            for(int i=0;i<atoms;++i){
                e+=mass[i]*(prices[4*i]+rel*prices[4*i+2]);
                l+=mass[i]*(prices[4*i+1]+rel*prices[4*i+3]);
            }
            while(candidate<count && t==indices[candidate]){
                double* out=result+(candidate*width+w)*(4+states);
                out[0]=boundary;out[1]=mass.back();out[2]=e;out[3]=l;
                std::copy(mass.begin(),mass.end(),out+4);++candidate;
            }
            previous=boundary;
        }
    }
}
