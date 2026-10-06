"""Offline inventory and artifact integrity audit. Never calls external APIs."""
import ast
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
EXCLUDED = {".git", "venv", ".venv", "__pycache__", ".pytest_cache", "neo4j_data", "postgres_data", ".ipynb_checkpoints", "medrag.egg-info"}


def audit():
    files, issues, notebooks = [], [], []
    chunks = {}
    image_files = set()
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDED for part in rel.parts) or rel.as_posix().startswith("docs/audit/") or path.name.startswith(".coverage") or not path.is_file():
            continue
        # Do not read credentials or include their contents/hashes in the report.
        if path.name == ".env":
            files.append({"path": str(rel), "review": "credential file excluded"})
            continue
        raw = path.read_bytes()
        entry = {"path": rel.as_posix(), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        files.append(entry)
        try:
            if path.suffix == ".py":
                ast.parse(raw.decode("utf-8-sig"), filename=str(rel))
                entry["review"] = "syntax parsed; semantic review recorded in Phase 21 report"
            elif path.suffix == ".ipynb":
                nb = json.loads(raw)
                code = []
                errors = []
                for i, cell in enumerate(nb.get("cells", [])):
                    source = "".join(cell.get("source", []))
                    if cell["cell_type"] == "code":
                        # IPython magic/shell lines are notebook syntax, not Python.
                        python_source = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith(("%", "!")))
                        ast.parse(python_source, filename=f"{rel}:cell{i}")
                        code.append(f"# CELL {i}\n{source}")
                        for output in cell.get("outputs", []):
                            if output.get("output_type") == "error":
                                errors.append({"cell": i, "type": output.get("ename"), "message": output.get("evalue")})
                notebooks.append({"path": rel.as_posix(), "cells": len(nb["cells"]), "saved_errors": errors})
                entry["review"] = "all Python cells parsed; saved error outputs checked"
            elif path.suffix in {".json", ".jsonl"}:
                records = [json.loads(line) for line in raw.decode("utf-8-sig").splitlines() if line.strip()] if path.suffix == ".jsonl" else [json.loads(raw)]
                entry["records"] = len(records)
                from medrag.ingestion.models import Article, DrugRecord, Guideline, WhoTable, WhoImage
                model = None
                for prefix, candidate in (("data/raw/pubmed/", Article), ("data/raw/openfda/", DrugRecord), ("data/raw/who/", Guideline), ("data/tables/who/", WhoTable)):
                    if rel.as_posix().startswith(prefix):
                        model = candidate
                if path.name.endswith("_metadata.jsonl"):
                    model = WhoImage
                if model:
                    for row in records:
                        model.model_validate(row)
                if "processed/chunks/" in rel.as_posix():
                    from medrag.processing.models import Chunk
                    for row in records:
                        Chunk.model_validate(row)
                        if row["point_id"] != Chunk.make_point_id(row["chunk_id"]):
                            issues.append({"path": str(rel), "error": "invalid point ID", "chunk_id": row["chunk_id"]})
                        prior = chunks.get(row["chunk_id"])
                        if prior and prior != row:
                            issues.append({"path": str(rel), "error": "conflicting duplicate chunk", "chunk_id": row["chunk_id"]})
                        chunks[row["chunk_id"]] = row
                if path.name.endswith("_metadata.jsonl"):
                    for row in records:
                        img = ROOT / "data" / "images" / "who" / row["filename"]
                        image_files.add(row["filename"])
                        if not img.is_file():
                            issues.append({"path": str(rel), "error": "missing image", "image": row["filename"]})
                entry["review"] = "all records parsed"
            elif path.suffix == ".npy":
                vecs = np.load(path, allow_pickle=False)
                entry["shape"] = list(vecs.shape)
                expected_dimension = 512 if "images" in path.name else 1536
                if vecs.ndim == 2 and vecs.shape[1] != expected_dimension:
                    issues.append({"path": str(rel), "error": "unexpected vector dimension"})
                if vecs.ndim != 2 or not np.isfinite(vecs).all():
                    issues.append({"path": str(rel), "error": "invalid vectors"})
                index_path = path.with_name(path.name.replace("_embeddings.npy", "_index.jsonl"))
                rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
                if len(rows) != len(vecs):
                    issues.append({"path": str(rel), "error": "vector/index row mismatch"})
                entry["review"] = "shape, finiteness and index alignment checked"
            elif path.suffix.lower() == ".png":
                with Image.open(path) as img:
                    img.verify()
                entry["review"] = "image integrity checked"
            elif path.suffix.lower() == ".pdf":
                import pymupdf
                with pymupdf.open(path) as pdf:
                    entry["pages"] = len(pdf)
                    entry["text_characters"] = sum(len(page.get_text()) for page in pdf)
                entry["review"] = "all pages parsed and text extracted"
            else:
                entry["review"] = "read and inventoried; semantic review is separate"
        except Exception as exc:
            issues.append({"path": rel.as_posix(), "error": f"{type(exc).__name__}: {exc}"})

    for source in ("pubmed", "openfda", "who"):
        path = ROOT / "data" / "processed" / "embeddings" / f"{source}_index.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for row in rows:
            chunk = chunks.get(row["chunk_id"])
            if not chunk or row["point_id"] != chunk["point_id"]:
                issues.append({"path": str(path.relative_to(ROOT)), "error": "embedding has no matching chunk", "chunk_id": row["chunk_id"]})

    import tiktoken
    encoding = tiktoken.get_encoding("cl100k_base")
    for chunk in chunks.values():
        if not chunk["text"].strip() or len(encoding.encode(chunk["text"])) > 8191:
            issues.append({"chunk_id": chunk["chunk_id"], "error": "empty or oversized embedding input"})

    links_path = ROOT / "data" / "processed" / "embeddings" / "image_chunk_links.jsonl"
    for line in links_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["chunk_id"] not in chunks or row["image_filename"] not in image_files:
            issues.append({"path": str(links_path.relative_to(ROOT)), "error": "dangling image link", "link": row})
    counts = {source: sum(c["source"] == source for c in chunks.values()) for source in ("pubmed", "openfda", "who")}
    report = {"files": files, "notebooks": notebooks, "unique_chunks": counts, "issues": issues}
    out = ROOT / "docs" / "audit" / "inventory.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"file_count": len(files), "unique_chunks": counts, "notebooks": notebooks, "issues": issues}, indent=2))
    return report


if __name__ == "__main__":
    sys.exit(1 if audit()["issues"] else 0)
