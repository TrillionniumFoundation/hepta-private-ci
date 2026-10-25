"""Causal input and exact-preservation boundaries for the future predictor."""

import unittest

import numpy as np
import torch

from ...abc_recovery.runtime import initialize, public_frame, transition
from ...v6.data import Observation
from ...v7.model import SlotPortfolio
from .forecast import HIDDEN, INPUT_DIM, Q, emitted_state, predict, public_input
from .forecast import runtime_predictions


class ForecastBoundaries(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1);torch.manual_seed(701)
        self.generator=SlotPortfolio().eval()
        observation=Observation(torch.rand(2,1,28,56),torch.ones(2,1,28,56),
            torch.tensor([[1,9,12,11,13,11,2,0],[1,10,12,11,13,11,2,0]]))
        self.observation=observation
        self.run=initialize(self.generator,observation,generator=torch.Generator().manual_seed(702))
        self.run=transition(self.generator,self.run,"refine_image",generator=torch.Generator().manual_seed(703))
        rng=np.random.default_rng(704)
        self.weights={"w1":rng.normal(0,.01,(HIDDEN,INPUT_DIM)),"b1":np.zeros(HIDDEN),
            "w2":np.zeros((33,HIDDEN)),"b2":np.zeros(33),
            "token_state":self.generator.token_embedding.weight.detach()[:,:8].tanh().double().numpy()}

    def test_public_projection_reconstructs_actual_past(self):
        x=public_input(self.generator,public_frame(self.run),self.observation,"refine_text")/Q
        forecast,_=predict(self.weights,x)
        actual=emitted_state(self.generator,public_frame(self.run))/Q
        np.testing.assert_allclose(forecast,actual,atol=1/Q,rtol=0)

    def test_future_observation_cannot_change_precommitted_forecast(self):
        x=public_input(self.generator,public_frame(self.run),self.observation,"couple")/Q
        cal={"cuts":[.2,.8],"probabilities":[.8]*8}
        first=runtime_predictions(self.weights,cal,x,np.zeros((2,32)))
        changed=runtime_predictions(self.weights,cal,x,np.ones((2,32)))
        np.testing.assert_array_equal(first[0],changed[0])
        np.testing.assert_array_equal(first[3],changed[3])
        self.assertFalse(np.array_equal(first[4],changed[4]))

    def test_refine_text_forecast_keeps_exact_current_visual_state(self):
        self.weights["b2"][:16]=.5
        x=public_input(self.generator,public_frame(self.run),self.observation,"refine_text")/Q
        forecast,_=predict(self.weights,x)
        actual=emitted_state(self.generator,public_frame(self.run))/Q
        np.testing.assert_array_equal(forecast[:,:16],actual[:,:16])

    def test_actual_stochastic_future_not_available_to_forecast(self):
        x=public_input(self.generator,public_frame(self.run),self.observation,"couple")/Q
        before=predict(self.weights,x)[0].copy()
        futures=[transition(self.generator,self.run,"couple",generator=torch.Generator().manual_seed(seed)) for seed in (705,706)]
        self.assertFalse(torch.equal(futures[0].pixels,futures[1].pixels))
        np.testing.assert_array_equal(before,predict(self.weights,x)[0])


if __name__=="__main__":unittest.main()
