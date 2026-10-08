"""Load a curated graph artifact only when its source chunks still match."""
import gzip
import hashlib
import json
from pathlib import Path


def corpus_fingerprint(chunks_dir):
    digest = hashlib.sha256()
    for path in sorted(Path(chunks_dir).glob("*.jsonl")):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def load_prepared_graph(path, chunks_dir):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        saved = json.load(stream)
    if saved.get("schema_version") != 1 or saved.get("corpus_sha256") != corpus_fingerprint(chunks_dir):
        raise ValueError("Prepared graph does not match the current OpenFDA chunks")
    ids = set()
    for chunk_file in Path(chunks_dir).glob("*.jsonl"):
        for line in chunk_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                chunk = json.loads(line)
                if chunk.get("source") != "openfda":
                    raise ValueError("Unexpected source in curated graph input")
                ids.add(chunk["chunk_id"])
    rows = saved.get("relationships")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Prepared graph has no relationships")
    for row in rows:
        if row.get("relationship") not in {"TREATS", "CONTRAINDICATED_IN", "CAUSES"}:
            raise ValueError("Unsupported relationship type in prepared graph")
        evidence = row.get("source_chunk_ids")
        if not isinstance(evidence, list) or not evidence or not set(evidence).issubset(ids):
            raise ValueError("Prepared graph references non-curated or missing chunks")
        for key in ("chemical", "chemical_normalized", "disease", "disease_normalized"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError("Invalid graph entity")
    return rows
