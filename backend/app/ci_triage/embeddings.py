import hashlib
import math
import re
from typing import Any

import httpx

from app.ci_triage.schemas import SemanticClusterOut, SimilarFailureOut
from app.core.config import Settings
from app.db.models import CiBuildRun

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def build_failure_embedding_text(
    *,
    category: str,
    signature: str,
    raw_log: str,
    job_name: str = "",
) -> str:
    """Build normalized text input for semantic failure embedding."""
    excerpt = " ".join(raw_log.splitlines()[:20])[:1000]
    return f"{category} {job_name} {signature} {excerpt}".strip()


def compute_deterministic_embedding(text: str, dimensions: int = 384) -> list[float]:
    """Generate a deterministic L2-normalized hashed unigram/bigram embedding vector."""
    dims = max(16, dimensions)
    vec = [0.0] * dims
    tokens = _TOKEN_RE.findall(text.lower())
    if not tokens:
        return vec

    features = list(tokens)
    for idx in range(len(tokens) - 1):
        features.append(f"{tokens[idx]}_{tokens[idx + 1]}")

    for feat in features:
        digest = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dims
        sign = 1.0 if (digest[4] & 1) == 0 else -1.0
        vec[bucket] += sign

    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [round(v / norm, 6) for v in vec]


async def generate_embedding(text: str, settings: Settings) -> list[float]:
    """Generate embedding via Ollama when configured, falling back to deterministic vector."""
    if settings.embedding_provider == "ollama":
        try:
            url = f"{settings.ollama_base_url.rstrip('/')}/api/embeddings"
            payload: dict[str, Any] = {
                "model": settings.ollama_default_model,
                "prompt": text,
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                raw_vec = resp.json().get("embedding")
                if isinstance(raw_vec, list) and raw_vec:
                    floats = [float(x) for x in raw_vec]
                    norm = math.sqrt(sum(v * v for v in floats))
                    if norm > 0.0:
                        return [round(v / norm, 6) for v in floats]
        except Exception:
            pass
    return compute_deterministic_embedding(text, dimensions=settings.embedding_dimensions)


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two embedding vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=True))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return round(max(-1.0, min(1.0, dot / (norm_a * norm_b))), 4)


def _ensure_vector(run: CiBuildRun) -> list[float]:
    if run.embedding_json:
        return [float(x) for x in run.embedding_json]
    text = build_failure_embedding_text(
        category=run.root_cause_category,
        signature=run.failure_signature,
        raw_log=run.raw_log,
        job_name=run.job_name,
    )
    return compute_deterministic_embedding(text)


def find_similar_failures(
    target: CiBuildRun,
    candidates: list[CiBuildRun],
    limit: int = 5,
) -> list[SimilarFailureOut]:
    """Return top-K failed CI runs semantically closest to the target run."""
    target_vec = _ensure_vector(target)
    scored: list[SimilarFailureOut] = []
    for cand in candidates:
        if cand.id == target.id or cand.status != "failed":
            continue
        sim = cosine_similarity(target_vec, _ensure_vector(cand))
        scored.append(
            SimilarFailureOut(
                run_id=cand.id,
                pipeline_name=cand.pipeline_name,
                branch=cand.branch,
                commit_sha=cand.commit_sha,
                root_cause_category=cand.root_cause_category,
                failure_signature=cand.failure_signature,
                remediation_summary=cand.remediation_summary,
                similarity_score=sim,
            )
        )
    scored.sort(key=lambda item: -item.similarity_score)
    return scored[: max(1, limit)]


def cluster_semantic_failures(
    runs: list[CiBuildRun],
    threshold: float = 0.45,
) -> list[SemanticClusterOut]:
    """Cluster failed CI runs greedily by embedding cosine similarity."""
    failed_runs = [
        r for r in sorted(runs, key=lambda item: item.created_at, reverse=True)
        if r.status == "failed"
    ]
    if not failed_runs:
        return []

    clusters: list[dict[str, Any]] = []
    for run in failed_runs:
        vec = _ensure_vector(run)
        best_cluster: dict[str, Any] | None = None
        best_sim = -1.0
        for cl in clusters:
            sim = cosine_similarity(vec, cl["centroid"])
            if sim >= threshold and sim > best_sim:
                best_sim = sim
                best_cluster = cl

        if best_cluster is None:
            clusters.append(
                {
                    "cluster_id": f"cluster-{len(clusters) + 1}",
                    "centroid": vec,
                    "representative": run,
                    "runs": [run],
                    "sims": [1.0],
                }
            )
        else:
            best_cluster["runs"].append(run)
            best_cluster["sims"].append(best_sim)

    output: list[SemanticClusterOut] = []
    for cl in clusters:
        rep: CiBuildRun = cl["representative"]
        members: list[CiBuildRun] = cl["runs"]
        sims: list[float] = cl["sims"]
        avg_sim = round(sum(sims) / len(sims), 4)
        output.append(
            SemanticClusterOut(
                cluster_id=str(cl["cluster_id"]),
                root_cause_category=rep.root_cause_category,
                representative_signature=rep.failure_signature or rep.root_cause_category,
                run_count=len(members),
                avg_similarity=avg_sim,
                run_ids=[m.id for m in members],
                branches=sorted({m.branch for m in members}),
                remediation_summary=rep.remediation_summary,
            )
        )
    output.sort(key=lambda c: (-c.run_count, -c.avg_similarity))
    return output
