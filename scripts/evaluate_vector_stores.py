"""Comparo Chroma y pgvector con los mismos embeddings antes de decidir una migración.

Mido recall@k frente a búsqueda exacta, latencia por consulta y tiempo de construcción, sobre
un corpus sintético armado con el vocabulario del corpus de evaluación. No mide calidad
semántica: los dos índices reciben exactamente los mismos vectores.

Uso:
    python scripts/evaluate_vector_stores.py --pg-url postgresql+psycopg://... --n 20000
Requiere PostgreSQL con la extensión vector (por ejemplo, la imagen pgvector/pgvector:pg16).
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from app.rag.corpus_files import load_curated_dir
from app.rag.embeddings import HashEmbeddings, normalize_tokens


def synthetic_corpus(n: int, seed: int = 7) -> list[str]:
    docs = load_curated_dir(Path(__file__).resolve().parents[1] / "evals" / "corpus_v1")
    vocab = sorted({t for d in docs for t in normalize_tokens(d.content)})
    rng = random.Random(seed)
    return [" ".join(rng.choices(vocab, k=rng.randint(20, 60))) for _ in range(n)]


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-url", required=True)
    parser.add_argument("--n", type=int, default=20000)
    parser.add_argument("--queries", type=int, default=200)
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()

    emb = HashEmbeddings()
    texts = synthetic_corpus(args.n)
    vectors = np.array(emb.embed_documents(texts), dtype=np.float32)
    rng = random.Random(11)
    query_texts = [" ".join(rng.sample(texts[rng.randrange(len(texts))].split(), 6)) for _ in range(args.queries)]
    queries = np.array(emb.embed_documents(query_texts), dtype=np.float32)
    exact = np.argsort(-(queries @ vectors.T), axis=1)[:, : args.k]
    ids = [f"c{i}" for i in range(args.n)]
    report: dict = {"n": args.n, "queries": args.queries, "k": args.k, "dimension": emb.dimension}

    # Chroma (HNSW coseno, persistente en disco como en la aplicación)
    import chromadb

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        client = chromadb.PersistentClient(path=tmp)
        col = client.create_collection("bench", metadata={"hnsw:space": "cosine"})
        started = time.perf_counter()
        for i in range(0, args.n, 2000):
            col.add(ids=ids[i : i + 2000], embeddings=vectors[i : i + 2000].tolist(), metadatas=[{"corpus": "public"}] * len(ids[i : i + 2000]))
        build = time.perf_counter() - started
        lat, hits = [], 0
        for qi, q in enumerate(queries):
            t0 = time.perf_counter()
            res = col.query(query_embeddings=[q.tolist()], n_results=args.k, where={"corpus": "public"})
            lat.append((time.perf_counter() - t0) * 1000)
            got = {int(x[1:]) for x in res["ids"][0]}
            hits += len(got & set(exact[qi].tolist()))
        report["chroma"] = {
            "build_seconds": round(build, 2),
            "recall_at_k": round(hits / (args.k * len(queries)), 4),
            "p50_ms": round(statistics.median(lat), 2),
            "p95_ms": round(percentile(lat, 0.95), 2),
        }
        del client

    # pgvector (HNSW coseno; filtro dentro de la misma consulta SQL)
    import psycopg
    from sqlalchemy.engine import make_url

    url = make_url(args.pg_url)
    with psycopg.connect(
        host=url.host, port=url.port, user=url.username, password=url.password, dbname=url.database, autocommit=True
    ) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("DROP TABLE IF EXISTS bench_chunks")
        conn.execute(f"CREATE TABLE bench_chunks (id int primary key, corpus text not null, embedding vector({emb.dimension}))")
        started = time.perf_counter()
        with conn.cursor().copy("COPY bench_chunks (id, corpus, embedding) FROM STDIN") as copy:
            for i, v in enumerate(vectors):
                copy.write_row((i, "public", "[" + ",".join(f"{x:.6f}" for x in v) + "]"))
        load = time.perf_counter() - started
        started = time.perf_counter()
        conn.execute("CREATE INDEX ON bench_chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)")
        index_build = time.perf_counter() - started
        conn.execute("ANALYZE bench_chunks")
        conn.execute("SET hnsw.ef_search = 40")
        lat, hits = [], 0
        for qi, q in enumerate(queries):
            literal = "[" + ",".join(f"{x:.6f}" for x in q) + "]"
            t0 = time.perf_counter()
            rows = conn.execute(
                "SELECT id FROM bench_chunks WHERE corpus = 'public' ORDER BY embedding <=> %s::vector LIMIT %s", (literal, args.k)
            ).fetchall()
            lat.append((time.perf_counter() - t0) * 1000)
            hits += len({r[0] for r in rows} & set(exact[qi].tolist()))
        literal = "[" + ",".join(f"{x:.6f}" for x in queries[0]) + "]"
        plan = [r[0] for r in conn.execute(
            "EXPLAIN SELECT id FROM bench_chunks WHERE corpus = 'public' ORDER BY embedding <=> %s::vector LIMIT %s", (literal, args.k)
        ).fetchall()]
        size = conn.execute("SELECT pg_size_pretty(pg_total_relation_size('bench_chunks'))").fetchone()[0]
        conn.execute("DROP TABLE bench_chunks")
        report["pgvector"] = {
            "load_seconds": round(load, 2),
            "index_build_seconds": round(index_build, 2),
            "recall_at_k": round(hits / (args.k * len(queries)), 4),
            "p50_ms": round(statistics.median(lat), 2),
            "p95_ms": round(percentile(lat, 0.95), 2),
            "table_size": size,
            "uses_hnsw_index": any("bench_chunks_embedding_idx" in line for line in plan),
            "plan_head": plan[:3],
        }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
