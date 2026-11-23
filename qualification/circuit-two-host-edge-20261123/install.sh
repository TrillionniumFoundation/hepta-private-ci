set -eu
python -m venv "$RUNNER_TEMP/hepta-edge-env"
"$RUNNER_TEMP/hepta-edge-env/bin/pip" install --only-binary=:all: --index-url https://download.pytorch.org/whl/cpu torch==2.9.1+cpu
"$RUNNER_TEMP/hepta-edge-env/bin/pip" install --only-binary=:all: numpy==2.3.5 transformers==4.57.3 peft==0.18.0 tokenizers==0.22.2 accelerate==1.16.0 safetensors==0.7.0 huggingface-hub==0.36.2
