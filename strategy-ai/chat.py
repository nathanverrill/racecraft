import os
from typing import List, Tuple

from google import genai
from google.genai import types
from opensearchpy import OpenSearch


# ------------------------------------------------------------
# Config
# ------------------------------------------------------------

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# Use fully-qualified model names with current SDK
GEMINI_EMBED_MODEL = "models/gemini-embedding-001"   # embeddings
GEMINI_RAG_MODEL   = "models/gemini-2.5-flash"       # chat / answer

OPENSEARCH_HOST  = os.getenv("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT  = int(os.getenv("OPENSEARCH_PORT", "9200"))
OPENSEARCH_USER  = os.getenv("OPENSEARCH_USER", "admin")
OPENSEARCH_PASS  = os.getenv("OPENSEARCH_PASS", "admin")
OPENSEARCH_INDEX = os.getenv("OPENSEARCH_INDEX", "hybrid-search-index")

# Must match your mapping
EMBEDDING_FIELD = "embedding_1024"
TOP_K = 5


# ------------------------------------------------------------
# Clients
# ------------------------------------------------------------

client_genai = genai.Client(api_key=GEMINI_API_KEY)

client_os = OpenSearch(
    hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
    http_auth=(OPENSEARCH_USER, OPENSEARCH_PASS),
    use_ssl=False,
    verify_certs=False,
    ssl_show_warn=False,
)


# ------------------------------------------------------------
# Embedding + hybrid search
# ------------------------------------------------------------

def embed_query(text: str) -> List[float]:
    """Create a 1024-dim query embedding with Gemini."""
    resp = client_genai.models.embed_content(
        model=GEMINI_EMBED_MODEL,
        contents=text,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=1024,  # matches embedding_1024
        ),
    )
    return resp.embeddings[0].values


def hybrid_search(query_text: str, top_k: int = TOP_K) -> Tuple[List[str], list]:
    """
    Hybrid search: lexical on text_representation + KNN on embedding_1024.
    Uses your hybrid-search-pipeline for score normalization.
    """
    vec = embed_query(query_text)

    search_body = {
        "size": top_k,
        "query": {
            "hybrid": {
                "queries": [
                    {
                        "match": {
                            "text_representation": {
                                "query": query_text
                            }
                        }
                    },
                    {
                        "knn": {
                            # short-form syntax; no num_candidates (avoids 400 error)
                            EMBEDDING_FIELD: {
                                "vector": vec,
                                "k": top_k
                            }
                        }
                    }
                ]
            }
        },
        "_source": ["text_representation", "metadata"],
    }

    res = client_os.search(index=OPENSEARCH_INDEX, body=search_body)
    hits = res["hits"]["hits"]
    contexts = [h["_source"]["text_representation"] for h in hits]
    return contexts, hits


# ------------------------------------------------------------
# RAG answer with Gemini
# ------------------------------------------------------------

def build_rag_prompt(question: str, contexts: List[str]) -> str:
    context_block = "\n\n".join(
        f"Document {i+1}:\n{c}" for i, c in enumerate(contexts)
    )
    prompt = (
        "You are an expert F1 assistant. Use ONLY the following documents as context.\n\n"
        f"{context_block}\n\n"
        f"Question: {question}\n\n"
        "If the answer cannot be found in the documents, say you don't know."
    )
    return prompt


def answer_with_rag(question: str) -> str:
    contexts, hits = hybrid_search(question)
    if not contexts:
        return "I couldn't find any relevant documents in the index."

    prompt = build_rag_prompt(question, contexts)

    resp = client_genai.models.generate_content(
        model=GEMINI_RAG_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
        ),
    )
    return resp.text


# ------------------------------------------------------------
# Simple chat loop
# ------------------------------------------------------------

def chat_loop():
    print("F1 RAG Chatbot (type 'exit' to quit)")
    while True:
        q = input("\nYou: ").strip()
        if not q:
            continue
        if q.lower() in {"exit", "quit"}:
            break

        try:
            ans = answer_with_rag(q)
        except Exception as e:
            ans = f"Error while answering: {e}"
        print(f"\nBot: {ans}")


if __name__ == "__main__":
    if not GEMINI_API_KEY:
        raise RuntimeError("Set GEMINI_API_KEY in your environment.")
    chat_loop()
