---
library_name: transformers
license: apache-2.0
language:
- en
---


# SmolLM2

![image/png](https://cdn-uploads.huggingface.co/production/uploads/61c141342aac764ce1654e43/XlT5TM3HWpfoZk_HSubrH.png)

##  Table of Contents

1. [Model Summary](#model-summary)
2. [Evaluation](#evaluation)
3. [Limitations](#limitations)
4. [Training](#training)
5. [License](#license)
6. [Citation](#citation)

## Model Summary

SmolLM2 is a family of compact language models available in three size: 135M, 360M, and 1.7B parameters. They are capable of solving a wide range of tasks while being lightweight enough to run on-device. More details in our paper: https://arxiv.org/abs/2502.02737v1

The 1.7B variant demonstrates significant advances over its predecessor SmolLM1-1.7B, particularly in instruction following, knowledge, reasoning, and mathematics. It was trained on 11 trillion tokens using a diverse dataset combination: FineWeb-Edu, DCLM, The Stack, along with new mathematics and coding datasets that we curated and will release soon. We developed the instruct version through supervised fine-tuning (SFT) using a combination of public datasets and our own curated datasets. We then applied Direct Preference Optimization (DPO) using [UltraFeedback](https://huggingface.co/datasets/HuggingFaceH4/ultrafeedback_binarized).

The instruct model additionally supports tasks such as text rewriting, summarization and function calling thanks to datasets developed by [Argilla](https://huggingface.co/argilla) such as [Synth-APIGen-v0.1](https://huggingface.co/datasets/argilla/Synth-APIGen-v0.1).
You can find the SFT dataset here: https://huggingface.co/datasets/HuggingFaceTB/smoltalk and finetuning code in the [alignement handbook](https://github.com/huggingface/alignment-handbook/tree/main/recipes/smollm2).

For more details refer to: https://github.com/huggingface/smollm. You will find pre-training, post-training, evaluation and local inference code.

### How to use

```bash
pip install transformers
```

#### Running the model on CPU/GPU/multi GPU
* _Using full precision_
```python
# pip install transformers
from transformers import AutoModelForCausalLM, AutoTokenizer
checkpoint = "HuggingFaceTB/SmolLM2-1.7B"
device = "cuda" # for GPU usage or "cpu" for CPU usage
tokenizer = AutoTokenizer.from_pretrained(checkpoint)
# for multiple GPUs install accelerate and do `model = AutoModelForCausalLM.from_pretrained(checkpoint, device_map="auto")`
model = AutoModelForCausalLM.from_pretrained(checkpoint).to(device)
inputs = tokenizer.encode("Gravity is", return_tensors="pt").to(device)
outputs = model.generate(inputs)
print(tokenizer.decode(outputs[0]))
```

* _Using `torch.bfloat16`_
```python
# pip install accelerate
# for fp16 use `torch_dtype=torch.float16` instead
model = AutoModelForCausalLM.from_pretrained(checkpoint, device_map="auto", torch_dtype=torch.bfloat16)
inputs = tokenizer.encode("Gravity is", return_tensors="pt").to("cuda")
outputs = model.generate(inputs)
print(tokenizer.decode(outputs[0]))
```
```bash
>>> print(f"Memory footprint: {model.get_memory_footprint() / 1e6:.2f} MB")
Memory footprint: 3422.76 MB
```

## Evaluation

In this section, we report the evaluation results of SmolLM2. All evaluations are zero-shot unless stated otherwise, and we use [lighteval](https://github.com/huggingface/lighteval) to run them.

## Base Pre-Trained Model

| Metric           | SmolLM2-1.7B | Llama-1B    | Qwen2.5-1.5B | SmolLM1-1.7B |
|------------------|--------------|-------------|---------------|--------------|
| HellaSwag        | **68.7**     | 61.2        | 66.4          | 62.9         |
| ARC (Average)    | **60.5**     | 49.2        | 58.5          | 59.9         |
| PIQA             | **77.6**     | 74.8        | 76.1          | 76.0         |
| MMLU-Pro (MCF)   | **19.4**     | 11.7        | 13.7          | 10.8         |
| CommonsenseQA    | **43.6**     | 41.2        | 34.1          | 38.0         |
| TriviaQA         | **36.7**     | 28.1        | 20.9          | 22.5         |
| Winogrande       | **59.4**     | 57.8        | 59.3          | 54.7         |
| OpenBookQA       | 42.2         | 38.4        | 40.0          | **42.4**     |
| GSM8K (5-shot)   | 31.0         | 7.2         | **61.3**      | 5.5          |

## Instruction Model

| Metric                       | SmolLM2-1.7B-Instruct | Llama-1B-Instruct | Qwen2.5-1.5B-Instruct | SmolLM1-1.7B-Instruct |
|:-----------------------------|:---------------------:|:-----------------:|:----------------------:|:----------------------:|
| IFEval (Average prompt/inst) | **56.7**             | 53.5             | 47.4                  | 23.1                  |
| MT-Bench                     | 6.13                | 5.48             | **6.52**              | 4.33                  |
| OpenRewrite-Eval (micro_avg RougeL) | 44.9           | 39.2             | **46.9**              | NaN                   |
| HellaSwag                    | **66.1**            | 56.1             | 60.9                  | 55.5                  |
| ARC (Average)                | **51.7**            | 41.6             | 46.2                  | 43.7                  |
| PIQA                         | **74.4**            | 72.3             | 73.2                  | 71.6                  |
| MMLU-Pro (MCF)               | 19.3               | 12.7             | **24.2**              | 11.7                  |
| BBH (3-shot)                 | 32.2               | 27.6             | **35.3**              | 25.7                  |
| GSM8K (5-shot)               | **48.2**           | 26.8             | 42.8                  | 4.62                  |


## Limitations

SmolLM2 models primarily understand and generate content in English. They can produce text on a variety of topics, but the generated content may not always be factually accurate, logically consistent, or free from biases present in the training data. These models should be used as assistive tools rather than definitive sources of information. Users should always verify important information and critically evaluate any generated content.

## Training

### Model

- **Architecture:** Transformer decoder
- **Pretraining tokens:** 11T
- **Precision:** bfloat16

### Hardware

- **GPUs:** 256 H100

### Software

- **Training Framework:** [nanotron](https://github.com/huggingface/nanotron/tree/main)

## License

[Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0)

## Citation
```bash
@misc{allal2025smollm2smolgoesbig,
      title={SmolLM2: When Smol Goes Big -- Data-Centric Training of a Small Language Model}, 
      author={Loubna Ben Allal and Anton Lozhkov and Elie Bakouch and Gabriel Martín Blázquez and Guilherme Penedo and Lewis Tunstall and Andrés Marafioti and Hynek Kydlíček and Agustín Piqueres Lajarín and Vaibhav Srivastav and Joshua Lochner and Caleb Fahlgren and Xuan-Son Nguyen and Clémentine Fourrier and Ben Burtenshaw and Hugo Larcher and Haojun Zhao and Cyril Zakka and Mathieu Morlon and Colin Raffel and Leandro von Werra and Thomas Wolf},
      year={2025},
      eprint={2502.02737},
      archivePrefix={arXiv},
      primaryClass={cs.CL},
      url={https://arxiv.org/abs/2502.02737}, 
}
```