from sentence_transformers import SentenceTransformer
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class EvidenceEmbeddingModel:
    """
    M3 - Semantic Evidence Similarity / Clustering

    Converts evidence descriptions into embeddings and groups
    semantically similar exhibits.
    """

    def __init__(self):
        print("Loading MiniLM model...")
        self.model = SentenceTransformer(MODEL_NAME)
        print("MiniLM loaded successfully.")

    def encode(self, descriptions):
        """Convert evidence descriptions into embeddings."""

        if not descriptions:
            return np.array([])

        return self.model.encode(
            descriptions,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

    def similarity_matrix(self, descriptions):
        """Return cosine similarity between every pair of exhibits."""

        embeddings = self.encode(descriptions)

        if len(embeddings) == 0:
            return np.array([])

        return cosine_similarity(embeddings)

    def find_similar(self, descriptions, threshold=0.65):
        """
        Find evidence pairs with similarity >= threshold.
        """

        matrix = self.similarity_matrix(descriptions)

        results = []

        for i in range(len(descriptions)):
            for j in range(i + 1, len(descriptions)):

                score = float(matrix[i][j])

                if score >= threshold:
                    results.append({
                        "item_1": descriptions[i],
                        "item_2": descriptions[j],
                        "similarity": round(score, 4),
                    })

        return sorted(
            results,
            key=lambda x: x["similarity"],
            reverse=True,
        )

    def cluster(self, descriptions, threshold=0.65):
        """
        Automatically group semantically similar evidence.

        threshold:
            Higher = stricter grouping
            Lower  = broader grouping
        """

        if not descriptions:
            return []

        if len(descriptions) == 1:
            return [{
                "cluster_id": 0,
                "items": [descriptions[0]],
            }]

        embeddings = self.encode(descriptions)

        # cosine distance = 1 - cosine similarity
        distance_threshold = 1 - threshold

        clustering = AgglomerativeClustering(
            n_clusters=None,
            metric="cosine",
            linkage="average",
            distance_threshold=distance_threshold,
        )

        labels = clustering.fit_predict(embeddings)

        clusters = {}

        for description, label in zip(descriptions, labels):
            label = int(label)

            clusters.setdefault(label, []).append(description)

        result = []

        for cluster_id, items in clusters.items():
            result.append({
                "cluster_id": cluster_id,
                "count": len(items),
                "items": items,
            })

        return result