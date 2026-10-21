from rank_bm25 import BM25Okapi
import json

class BM25Retriever:
    def __init__(self, data_path: str = "data/merged_obd.json"):
        print("Loading BM25 index...")
        with open(data_path, "r") as f:
            all_docs = json.load(f)
        
        # Load only rich P-codes to reduce memory
        self.docs = [
            d for d in all_docs 
            if (d["causes"] or d["symptoms"]) and d["dtc_code"].startswith("P")
        ]
        
        corpus = [doc["text"].lower().split() for doc in self.docs]
        self.bm25 = BM25Okapi(corpus)
        self.docs_by_code = {}
        for doc in self.docs:
            self.docs_by_code.setdefault(doc["dtc_code"].upper(), []).append(doc)
        print(f"BM25 index built with {len(self.docs)} documents.")

    @staticmethod
    def _to_result(doc: dict, source: str, score: float) -> dict:
        """Return documents in the common retriever result format."""
        return {
            "dtc_code": doc["dtc_code"],
            "fault_name": doc["fault_name"],
            "symptoms": doc["symptoms"],
            "causes": doc["causes"],
            "repair_steps": doc["repair_steps"],
            "text": doc["text"],
            "score": score,
            "source": source,
        }

    def exact_matches(self, dtc_code: str) -> list:
        """Return only records for the requested DTC code (case-insensitive)."""
        return [
            self._to_result(doc, "exact_dtc", 1.0)
            for doc in self.docs_by_code.get(dtc_code.strip().upper(), [])
        ]
        
    def search(self, query: str, top_k: int = 5) -> list:
        """Search using BM25 keyword matching"""
        tokenized_query = query.lower().split()
        scores = self.bm25.get_scores(tokenized_query)
        
        top_indices = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True
        )[:top_k]
        
        results = []
        for idx in top_indices:
            doc = self.docs[idx]
            results.append(self._to_result(doc, "bm25", float(scores[idx])))
        
        return results
