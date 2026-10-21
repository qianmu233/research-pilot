# Third-Party Design References

This independently authored ResearchPilot prototype takes inspiration from the
research planning and reporting architecture of:

- LangChain AI, **Open Deep Research**
- URL: https://github.com/langchain-ai/open_deep_research
- License: MIT, Copyright (c) 2025 LangChain
- Public archive (read-only) since 2026-08-21.

The independent ResearchPilot implementation does **not** copy the whole
upstream repository or claim the upstream project's benchmark results.

MIT license of the referenced project:

Copyright (c) 2025 LangChain

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Optional local embedding model

ResearchPilot's optional vector backend runs the pretrained English model
BAAI/bge-small-en-v1.5 (MIT) locally through FastEmbed and ONNXRuntime.
The model weights are downloaded separately, are not authored by ResearchPilot,
and are excluded from the Docker build context and source distribution.

- Original model and license: https://huggingface.co/BAAI/bge-small-en-v1.5
- Qdrant ONNX conversion: https://huggingface.co/Qdrant/bge-small-en-v1.5-onnx-Q
- FastEmbed: https://github.com/qdrant/fastembed (Apache-2.0)
- pgvector: https://github.com/pgvector/pgvector (PostgreSQL License)
- Python adapter: https://github.com/pgvector/pgvector-python (MIT)

Verified downloaded ONNX snapshot: aa8f8b060edb00e03bfdd08813a2949946c8ba55.
model_optimized.onnx SHA256:
51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431.
Phase 6 now enforces this revision and SHA256 hashes of all five model/tokenizer
artifacts in research_pilot/embedding.lock.json. The download helper requests this
exact revision, and startup verifies local artifacts before loading them.
Changing weights requires rebuilding the collection and rerunning acceptance.
The English test fixtures do not establish Chinese retrieval quality or any
upstream benchmark result for ResearchPilot.

## Official Chinese embedding candidate (Phase 6.1)

The optional Chinese backend uses BAAI/bge-small-zh-v1.5 from the official BAAI
repository (MIT), revision 7999e1d3359715c523056ef9478215996d62a620:
https://huggingface.co/BAAI/bge-small-zh-v1.5/tree/7999e1d3359715c523056ef9478215996d62a620

No official ONNX file was present at that revision. ResearchPilot loads the
original model.safetensors with PyTorch/Transformers, CPU float32 CLS + L2,
512 dimensions, without remote custom code or pickle weights.
SHA256: 354763b9b1357bc9c44f62c6be2276321081ed2567773608c0d0785b61d5a026.
The six official files and their Git/LFS identity are audited in
benchmarks/zh_retrieval_v1/results/official-zh-model-audit.json and fixed in
research_pilot/embedding-zh.lock.json. Weights are downloaded separately and
excluded from the source/Docker context. The earlier English ONNX reference,
MIT source notice and its historical evaluation artifacts remain preserved.

## Local chat model and runtime (Phase 7)

Ollama 0.40.6 is MIT licensed: https://github.com/ollama/ollama/blob/v0.40.6/LICENSE .
Its official portable archive is downloaded separately, never redistributed in
the source or application image. Qwen3:4b-instruct-2507-q4_K_M uses Apache-2.0:
https://ollama.com/library/qwen3:4b-instruct-2507-q4_K_M .
Original manifest SHA256: 0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0.
GGUF SHA256: 85e4a5b7b8ef0e48af0e8658f5aaab9c2324c76c1641493f4d1e25fce54b18b9.
The official tokenizer/config/license uses Qwen/Qwen3-4B-Instruct-2507 revision
cdbee75f17c01a7cc42f958dc650907174af0554 and is fixed by chat-tokenizer.lock.json.
The GGUF license and all local layers were hash-verified. chat-model.lock.json
records identity, not a claim that generated reports are factually correct.
Phase7 source notes paraphrase linked public technical facts; synthetic noise
and attack fixtures are labelled explicitly, not represented as company data.
