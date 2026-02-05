"""
Hybrid Knowledge Base with BM25 + Vector Embeddings
Combines keyword-based search (BM25) with semantic search (OpenAI embeddings)
"""
import os
import json
import math
import re
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter
from datetime import datetime

try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

SUPPRESS_OPTIONAL_WARNINGS = os.getenv("OPTIONAL_DEP_WARNINGS", "0") != "1"

try:
    from sentence_transformers import CrossEncoder
    HAS_CROSS_ENCODER = True
except (ImportError, UnicodeDecodeError, Exception) as e:
    # Catch all errors including Python 3.14 compatibility issues
    HAS_CROSS_ENCODER = False
    if not SUPPRESS_OPTIONAL_WARNINGS:
        print(f"[RERANKER] Warning: Could not load sentence-transformers: {e}")
        print(f"[RERANKER] Re-ranking will be disabled, but hybrid KB will still work")


# Slovenian stop words for BM25 tokenization
SLOVENIAN_STOP_WORDS = {
    "in", "je", "na", "v", "da", "za", "z", "s", "so", "se", "ki", "pa", "od", "po",
    "pri", "kot", "ali", "tudi", "če", "ko", "do", "o", "iz", "ter", "k", "le", "bo",
    "bi", "bil", "bila", "bilo", "bili", "imajo", "ima", "ste", "smo", "si", "sem",
    "to", "ta", "te", "ti", "vse", "vsi", "vse", "njegov", "njegova", "njegovo",
    "njihov", "njihova", "njihovo", "naš", "naša", "naše", "vaš", "vaša", "vaše"
}


def tokenize_slovenian(text: str) -> List[str]:
    """
    Tokenize Slovenian text for BM25
    - Lowercase
    - Remove punctuation
    - Split on whitespace
    - Remove stop words
    - Keep only words with 2+ characters
    """
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    tokens = text.split()
    tokens = [t for t in tokens if len(t) >= 2 and t not in SLOVENIAN_STOP_WORDS]
    return tokens


class BM25:
    """
    BM25 ranking algorithm for keyword-based search
    Implementation optimized for small document collections
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        """
        Args:
            k1: Term frequency saturation parameter (default 1.5)
            b: Length normalization parameter (default 0.75)
        """
        self.k1 = k1
        self.b = b
        self.documents: List[str] = []
        self.doc_tokens: List[List[str]] = []
        self.doc_freqs: List[Counter] = []
        self.idf_scores: Dict[str, float] = {}
        self.avg_doc_len: float = 0.0

    def index(self, documents: List[str]) -> None:
        """Index documents for BM25 search"""
        self.documents = documents
        self.doc_tokens = [tokenize_slovenian(doc) for doc in documents]
        self.doc_freqs = [Counter(tokens) for tokens in self.doc_tokens]

        # Calculate average document length
        total_len = sum(len(tokens) for tokens in self.doc_tokens)
        self.avg_doc_len = total_len / len(documents) if documents else 0

        # Calculate IDF scores for all terms
        num_docs = len(documents)
        df = Counter()  # Document frequency
        for tokens in self.doc_tokens:
            df.update(set(tokens))

        for term, doc_count in df.items():
            # IDF formula: log((N - df + 0.5) / (df + 0.5) + 1)
            self.idf_scores[term] = math.log(
                (num_docs - doc_count + 0.5) / (doc_count + 0.5) + 1.0
            )

    def search(self, query: str, top_k: int = 5) -> List[Tuple[int, float]]:
        """
        Search documents using BM25

        Args:
            query: Search query
            top_k: Number of top results to return

        Returns:
            List of (doc_index, score) tuples sorted by score descending
        """
        query_tokens = tokenize_slovenian(query)
        scores = []

        for doc_idx, (doc_len, doc_freq) in enumerate(
            zip([len(t) for t in self.doc_tokens], self.doc_freqs)
        ):
            score = 0.0
            for term in query_tokens:
                if term not in doc_freq:
                    continue

                # Term frequency in document
                tf = doc_freq[term]

                # IDF score
                idf = self.idf_scores.get(term, 0.0)

                # Length normalization
                norm = 1 - self.b + self.b * (doc_len / self.avg_doc_len)

                # BM25 score for this term
                term_score = idf * (tf * (self.k1 + 1)) / (tf + self.k1 * norm)
                score += term_score

            scores.append((doc_idx, score))

        # Sort by score descending and return top_k
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


class VectorStore:
    """
    Vector store using OpenAI embeddings for semantic search
    Stores embeddings in memory (suitable for small collections)
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
        """
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key required. Set OPENAI_API_KEY env var.")

        if not HAS_OPENAI:
            raise ImportError("openai package required. Run: pip install openai")

        openai.api_key = self.api_key
        self.documents: List[str] = []
        self.embeddings: List[List[float]] = []
        self.model = "text-embedding-ada-002"

    def _get_embedding(self, text: str) -> List[float]:
        """Get embedding for text using OpenAI API"""
        response = openai.embeddings.create(
            input=text,
            model=self.model
        )
        return response.data[0].embedding

    def index(self, documents: List[str]) -> None:
        """Index documents by computing embeddings"""
        print(f"[KB] Computing embeddings for {len(documents)} documents...")
        self.documents = documents
        self.embeddings = []

        for i, doc in enumerate(documents):
            embedding = self._get_embedding(doc)
            self.embeddings.append(embedding)
            if (i + 1) % 5 == 0:
                print(f"[KB] Embedded {i + 1}/{len(documents)} documents")

        print(f"[KB] Embedding complete!")

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors"""
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        return dot_product / (norm1 * norm2) if norm1 > 0 and norm2 > 0 else 0.0

    def search(self, query: str, top_k: int = 5) -> List[Tuple[int, float]]:
        """
        Search documents using vector similarity

        Args:
            query: Search query
            top_k: Number of top results to return

        Returns:
            List of (doc_index, similarity_score) tuples sorted by score descending
        """
        query_embedding = self._get_embedding(query)

        scores = []
        for doc_idx, doc_embedding in enumerate(self.embeddings):
            similarity = self._cosine_similarity(query_embedding, doc_embedding)
            scores.append((doc_idx, similarity))

        # Sort by similarity descending and return top_k
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


class CrossEncoderReranker:
    """
    Cross-encoder re-ranker for improving search result quality

    Uses a cross-encoder model that jointly encodes query and document
    for more accurate relevance scoring than bi-encoders.
    """

    def __init__(self, model_name: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"):
        """
        Args:
            model_name: HuggingFace cross-encoder model name
                       Default: multilingual Marco model supporting Slovenian
        """
        if not HAS_CROSS_ENCODER:
            raise ImportError(
                "sentence-transformers package required. Run: pip install sentence-transformers"
            )

        print(f"[RERANKER] Loading cross-encoder model: {model_name}")
        self.model = CrossEncoder(model_name, max_length=512)
        print(f"[RERANKER] Model loaded successfully!")

    def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: Optional[int] = None
    ) -> List[Tuple[int, float]]:
        """
        Re-rank documents using cross-encoder

        Args:
            query: Search query
            documents: List of document texts
            top_k: Number of top results to return (None = return all)

        Returns:
            List of (doc_index, rerank_score) tuples sorted by score descending
        """
        if not documents:
            return []

        # Prepare query-document pairs
        pairs = [[query, doc] for doc in documents]

        # Compute relevance scores
        scores = self.model.predict(pairs)

        # Create (index, score) tuples
        results = list(enumerate(scores))

        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)

        if top_k is not None:
            results = results[:top_k]

        return results


class HybridKnowledgeBase:
    """
    Hybrid knowledge base combining BM25 (keyword) and vector (semantic) search

    Uses weighted combination of both methods for improved retrieval accuracy,
    with optional cross-encoder re-ranking for enhanced result quality.
    """

    def __init__(
        self,
        documents: Dict[str, str],
        alpha: float = 0.5,
        openai_api_key: Optional[str] = None,
        use_reranker: bool = True,
        reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    ):
        """
        Args:
            documents: Dictionary mapping doc_id -> document_text
            alpha: Weight for BM25 vs vector search (0=all BM25, 1=all vector, 0.5=equal)
            openai_api_key: OpenAI API key for embeddings
            use_reranker: Whether to use cross-encoder re-ranking (default True)
            reranker_model: Cross-encoder model name for re-ranking
        """
        self.doc_ids = list(documents.keys())
        self.doc_texts = list(documents.values())
        self.alpha = alpha
        self.use_reranker = use_reranker and HAS_CROSS_ENCODER

        print(f"[KB] Initializing hybrid knowledge base with {len(documents)} documents")
        print(f"[KB] Alpha={alpha} (BM25 weight={1-alpha:.2f}, Vector weight={alpha:.2f})")

        # Initialize BM25
        self.bm25 = BM25()
        self.bm25.index(self.doc_texts)
        print(f"[KB] BM25 indexing complete")

        # Initialize Vector Store
        self.vector_store = VectorStore(api_key=openai_api_key)
        self.vector_store.index(self.doc_texts)
        print(f"[KB] Vector indexing complete")

        # Initialize Re-ranker (optional)
        self.reranker: Optional[CrossEncoderReranker] = None
        if self.use_reranker:
            try:
                self.reranker = CrossEncoderReranker(model_name=reranker_model)
                print(f"[KB] Re-ranker enabled")
            except Exception as e:
                print(f"[KB] Failed to load re-ranker: {e}")
                print(f"[KB] Continuing without re-ranking")
                self.use_reranker = False

        print(f"[KB] Hybrid knowledge base ready!")

    def search(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search combining BM25 and vector similarity

        Args:
            query: Search query
            top_k: Number of results to return
            min_score: Minimum score threshold (0-1)

        Returns:
            List of result dictionaries with keys:
            - doc_id: Document identifier
            - text: Document text
            - score: Combined score (0-1 normalized)
            - bm25_score: BM25 component score
            - vector_score: Vector similarity component score
        """
        # Get BM25 results
        bm25_results = self.bm25.search(query, top_k=top_k * 2)

        # Get vector results
        vector_results = self.vector_store.search(query, top_k=top_k * 2)

        # Normalize scores to 0-1 range
        def normalize_scores(results: List[Tuple[int, float]]) -> Dict[int, float]:
            if not results or results[0][1] == 0:
                return {}
            max_score = max(score for _, score in results)
            return {idx: score / max_score for idx, score in results}

        bm25_normalized = normalize_scores(bm25_results)
        vector_normalized = normalize_scores(vector_results)

        # Combine scores
        combined_scores: Dict[int, Dict[str, float]] = {}
        all_indices = set(bm25_normalized.keys()) | set(vector_normalized.keys())

        for idx in all_indices:
            bm25_score = bm25_normalized.get(idx, 0.0)
            vector_score = vector_normalized.get(idx, 0.0)

            # Weighted combination
            combined_score = (1 - self.alpha) * bm25_score + self.alpha * vector_score

            combined_scores[idx] = {
                "combined": combined_score,
                "bm25": bm25_score,
                "vector": vector_score
            }

        # Sort by combined score
        sorted_indices = sorted(
            combined_scores.keys(),
            key=lambda idx: combined_scores[idx]["combined"],
            reverse=True
        )

        # ===== OPTIONAL RE-RANKING =====
        # If re-ranker is enabled, apply it to top candidates for better accuracy
        if self.use_reranker and self.reranker is not None:
            # Get top candidates for re-ranking (more than top_k to give re-ranker options)
            rerank_candidates_count = min(top_k * 3, len(sorted_indices))
            candidate_indices = sorted_indices[:rerank_candidates_count]

            # Prepare documents for re-ranking
            candidate_docs = [self.doc_texts[idx] for idx in candidate_indices]

            # Re-rank using cross-encoder
            reranked = self.reranker.rerank(query, candidate_docs, top_k=None)

            # Map re-ranked positions back to original indices
            reranked_indices = [candidate_indices[local_idx] for local_idx, _ in reranked]

            # Update sorted_indices with re-ranked order
            sorted_indices = reranked_indices + [
                idx for idx in sorted_indices if idx not in reranked_indices
            ]

            print(f"[KB] Re-ranked top {len(reranked)} candidates")

        # Build final results with confidence metadata
        results = []
        for rank, idx in enumerate(sorted_indices[:top_k]):
            scores = combined_scores[idx]
            if scores["combined"] < min_score:
                continue

            results.append({
                "doc_id": self.doc_ids[idx],
                "text": self.doc_texts[idx],
                "score": scores["combined"],
                "bm25_score": scores["bm25"],
                "vector_score": scores["vector"],
                "rank": rank + 1  # 1-indexed rank
            })

        # ===== CONFIDENCE GATING METADATA =====
        # Add multi-signal confidence metadata to help downstream decision making
        if results:
            # Calculate confidence signals
            top_score = results[0]["score"]
            score_gap = (top_score - results[1]["score"]) if len(results) > 1 else top_score

            # Score gap ratio (higher = more confident in top result)
            score_gap_ratio = score_gap / top_score if top_score > 0 else 0

            # Agreement between BM25 and vector (higher = both methods agree)
            top_bm25 = results[0]["bm25_score"]
            top_vector = results[0]["vector_score"]
            agreement = min(top_bm25, top_vector) / max(top_bm25, top_vector) if max(top_bm25, top_vector) > 0 else 0

            # Overall confidence score (0-1)
            # Combines: top score, score gap, and agreement
            confidence = (
                0.5 * top_score +           # 50% weight to top score
                0.3 * score_gap_ratio +     # 30% weight to score gap
                0.2 * agreement             # 20% weight to method agreement
            )

            # Add metadata to first result
            results[0]["confidence_metadata"] = {
                "confidence": confidence,
                "top_score": top_score,
                "score_gap": score_gap,
                "score_gap_ratio": score_gap_ratio,
                "bm25_vector_agreement": agreement,
                "num_results": len(results),
                "reranker_used": self.use_reranker and self.reranker is not None
            }

        return results


# Singleton instance
_knowledge_base: Optional[HybridKnowledgeBase] = None


def initialize_knowledge_base(
    documents: Dict[str, str],
    alpha: float = 0.5,
    use_reranker: bool = True
) -> None:
    """
    Initialize the global knowledge base

    Args:
        documents: Dictionary mapping doc_id -> document_text
        alpha: Weight for BM25 vs vector search (default 0.5 = equal weight)
        use_reranker: Whether to enable cross-encoder re-ranking (default True)
    """
    global _knowledge_base
    _knowledge_base = HybridKnowledgeBase(
        documents,
        alpha=alpha,
        use_reranker=use_reranker
    )


def get_knowledge_base() -> HybridKnowledgeBase:
    """Get the singleton knowledge base instance"""
    if _knowledge_base is None:
        raise RuntimeError(
            "Knowledge base not initialized. Call initialize_knowledge_base() first."
        )
    return _knowledge_base


def search_knowledge_base(
    query: str,
    top_k: int = 3,
    min_score: float = 0.0
) -> List[Dict[str, Any]]:
    """
    Convenience function to search the knowledge base

    Args:
        query: Search query
        top_k: Number of results to return
        min_score: Minimum score threshold

    Returns:
        List of result dictionaries
    """
    kb = get_knowledge_base()
    return kb.search(query, top_k=top_k, min_score=min_score)
