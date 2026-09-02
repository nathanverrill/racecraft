# strategy-ai

Hybrid retrieval over Formula 1 knowledge — the substrate for a strategy advisor that
can answer with both the race record and the engineering behind it.

Lexical BM25 and 1024-dimension dense embeddings are combined in a single OpenSearch
query, which matters for this corpus specifically: driver codes, lap numbers and
circuit names are exact-match tokens that embeddings blur, while questions about
downforce or tyre behaviour are semantic and BM25 misses them entirely. Neither
retrieval mode alone covers F1 questions.

The corpus is deliberately two-layered — the 1950–2020 results database for what
happened, and engineering literature (ground-effect aerodynamics, composite materials,
the Cosworth DFV, the 1970 Appendix J regulations) for why. The 94 MB of PDFs stay on
disk; see [`../docs/DATA.md`](../docs/DATA.md).

## Running it

```bash
docker compose up -d
export GEMINI_API_KEY=...
python chat.py
```

Index-building is in `hybrid.ipynb`; `hybrid-2.ipynb` iterates on the retrieval mix.

> A Gemini key was previously hardcoded in `chat.py` and had leaked into `hybrid.ipynb`.
> Both are scrubbed — the key now comes from the environment — but **that key was
> exposed in plaintext and should be rotated.**

## Where this is going

The advisor this feeds is the open thread. The karting side of this repo already
computes the things a strategy model would reason over — sector deltas, tyre-free
degradation, consistency, an ideal lap — and the F1 side has the historical precedent.
Connecting them is the unbuilt part.
