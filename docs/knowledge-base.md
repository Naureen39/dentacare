# Knowledge base and embeddings

The chatbot answers from a small knowledge base of short markdown documents. The documents are embedded locally and searched with PostgreSQL and pgvector. No external service is involved.

## Content

68 documents live in `data/kb`, one topic each, 80 to 200 words. Every file starts with front matter and ends with a short answer:

```
---
id: cancellation-policy
title: Cancellation policy
category: policies
updated_at: 2026-09-15
---
Body text ...

## Short answer
One to three sentences used for instant replies without calling a language model.
```

- `id` must equal the file name and uses lower case words joined by hyphens.
- Categories: `practice`, `new-patients`, `policies`, `insurance-payment`, `pricing`, `procedures`, `aftercare`, `pediatric-comfort`, `emergency`, `oral-health`.
- The text is original. Patient education facts follow US government public domain guidance (MedlinePlus and NIDCR) and are phrased in our own words.
- Clinic details are not written into the text. Use `{{clinic_name}}`, `{{clinic_phone}}`, `{{clinic_address}}` and `{{clinic_email}}`; they are filled from configuration when the document is indexed, and changing the configuration re-embeds the affected documents.

`data/intents.yaml` holds 15 example utterances for each of the 13 intents (greeting, hours, location, pricing, insurance, book, reschedule, cancel, faq_procedure, emergency, human_handoff, thanks, out_of_scope) for routing in Phase 9.

## Indexing

```bash
cd backend
uv run python -m scripts.embed_kb --check   # validate the files, no database
uv run python -m scripts.embed_kb           # sync documents and intents
uv run python -m scripts.embed_kb --force   # re-embed everything
uv run python -m scripts.embed_kb --prune   # also remove documents deleted from the folder
```

The sync is incremental. A document is embedded again only when its content hash changes. The hash covers the title, category, rendered body, the embedding model name and the chunking rules version, so changing the model or the rules re-embeds everything. A second run with no changes embeds nothing. In Docker run it inside the API container: `docker compose exec api python -m scripts.embed_kb`.

**Chunking.** Each document is split at headings and then into windows of about 180 tokens with 30 tokens of overlap. Every chunk starts with the document title and its heading path, so it makes sense on its own. Tokens are approximated by counting words and punctuation, which stays close to the model's word piece count for English prose. Most documents become two chunks.

**Embeddings.** `BAAI/bge-small-en-v1.5`, 384 dimensions, run with fastembed on CPU through ONNX. fastembed downloads a quantized ONNX build of the model published on Hugging Face; the first start needs network access and the files are kept in `EMBED_CACHE_DIR` (a Docker volume in Compose). Vectors are normalized to unit length and compared with cosine distance (`<=>`) using HNSW indexes.

## Search

`search_kb(db, embedder, query, k=3, category=None)` returns `SearchHit` objects with the chunk, the cosine similarity score and the document id, best first, one hit per document by default.

- Queries get the BGE instruction prefix `Represent this sentence for searching relevant passages: `. Documents do not.
- The model loads once at API startup in a background task, so startup and health checks never wait for a download. `/ready` reports `embeddings: ready` or `loading` as information; it does not fail readiness. If the model cannot be loaded, searches return 503 `embeddings_unavailable`.
- Encoding runs in a two thread pool so the event loop is never blocked.
- Query vectors are cached in Redis for 24 hours, keyed by the normalized text, so a repeated question costs no model run.
- Index scans use `hnsw.ef_search = 100` and iterative scans, so filtered searches still return `k` rows.

`match_intent` finds the intent whose examples are closest to a message. Messages and examples are both short utterances, so neither side gets the instruction prefix.

## Administration

All endpoints need the administrator role and are audited.

| Endpoint | Purpose |
|---|---|
| `GET /admin/kb/documents` (`category`, `q`, `stale_only`) | List documents with chunk counts and whether they are stale |
| `GET /admin/kb/documents/{slug}` | Full document |
| `POST /admin/kb/documents` | Create; validated and embedded immediately unless `reembed` is false |
| `PUT /admin/kb/documents/{slug}` | Edit title, category or body |
| `POST /admin/kb/documents/{slug}/reembed` | Re-embed one document |
| `POST /admin/kb/reindex` (`force`) | Re-embed stale documents, or all with `force=true` |
| `GET /admin/kb/search?q=` | Preview what the assistant would retrieve, with scores |

A document edited here becomes `managed_by = admin`, and the file sync leaves it alone unless `--force` is given. A document whose chunks no longer match its content is `stale`.

## Quality gates

`backend/tests/knowledge` runs the real model against the real documents:

| Measure | Gate | Result |
|---|---|---|
| Top 3 hit rate on 69 sample questions | at least 90 percent | 100 percent |
| Top 1 hit rate | at least 80 percent | about 93 percent |
| Median query embedding plus vector search | under 80 ms on CPU | about 10 ms |
| Held out intent phrases routed correctly | at least 85 percent | about 90 percent |

The sample questions are in `tests/knowledge/questions.py`. They were written by the same author as the documents, as paraphrases rather than copied titles, so treat the numbers as a regression guard rather than a measure of real traffic. Add real questions that fail to the set as they appear in the chatbot analytics.

The model based tests skip when the model cannot be loaded locally. CI sets `REQUIRE_MODEL=1`, caches `backend/models`, and fails instead of skipping.
