# Sourcewise

Sourcewise is a FastAPI research workspace for websites, YouTube videos, PDFs, and individual public GitHub files. It gives each source a summary, searchable passages, and a question history. It also produces an interactive code map, a section-by-section walkthrough, and interview practice for GitHub files.

## Run with Docker

Docker Compose installs the media tooling, OCR, JavaScript runtime for yt-dlp, and Python dependencies.

```bash
cp .env.example .env
docker compose up --build
```

Open [http://localhost:8000](http://localhost:8000). Use **Try an example** to exercise the code map or ask questions about retrieval. The OpenAPI reference is at [http://localhost:8000/docs](http://localhost:8000/docs). Compose persists your workspace and Whisper model cache in its named volume.

## Run with Python

Use Python 3.12. For media and scanned documents, install **FFmpeg** and **Tesseract** on your system. Install **Node.js 22 or newer** for the YouTube download fallback. The first local transcription may download the selected Whisper model.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-media.txt
cp .env.example .env
python -m uvicorn sourcewise.app:app
```

On Windows PowerShell, activate the environment with ` .venv\Scripts\Activate.ps1 ` and use `Copy-Item .env.example .env`. For CPU-only machines, `WHISPER_MODEL=base` trades accuracy for faster transcription. Install the matching Tesseract language pack and set `OCR_LANGUAGE` for OCR in other languages.

## Use the Gemini free tier

1. Create a Gemini Developer API key for a Free tier project in [Google AI Studio](https://aistudio.google.com/apikey). Leave billing disabled if you want to stay on the free tier.
2. Set `AI_PROVIDER=gemini` and `GEMINI_API_KEY` in your project's `.env` file.
3. Run `docker compose up --build`, or restart the FastAPI process if you run it directly with Python.

Sourcewise defaults to Gemini 3.5 Flash-Lite for summaries, search planning, answers, and code walkthroughs. Gemini Embedding 2 enables semantic retrieval over source passages. Both models have a standard free tier subject to project eligibility and quota. Check Google's current model pricing and the quota for your project. Google may use free-tier inputs and outputs to improve its products. [Gemini pricing](https://aistudio.google.com/docs/pricing) · [Gemini rate limits](https://aistudio.google.com/docs/rate-limits) · [Gemini terms](https://aistudio.google.com/docs/terms)

The app runs in extractive mode without a configured provider. If Gemini rejects a request, Sourcewise can still give cited excerpts and use keyword retrieval. Set `GEMINI_EMBEDDING_MODEL=` to use keyword retrieval with Gemini generation. If you switch embedding models, re-add existing sources to index them with the new model. Keep the key in `.env` on the server.

To use an OpenAI-compatible provider, set `AI_PROVIDER=openai` and configure `OPENAI_API_KEY` or `AI_BASE_URL` and `AI_API_KEY`. Use `AI_MODEL` and `EMBEDDING_MODEL` to override that provider's models.

## What each input supports

| Input | Processing | Reference locations |
| --- | --- | --- |
| Public website | Article extraction and a simpler HTML fallback. Submit a URL that serves its text directly. | Sections and original page link |
| YouTube | Caption tracks, then yt-dlp and local Whisper if captions are absent. On-screen OCR can recover text from sampled frames when speech is unavailable. Upload a local audio or video copy when YouTube restricts downloads. | Clickable timestamps for linked videos |
| PDF | Text per page, with OCR for scanned pages. Up to 25 MB or 200 pages. | PDF page numbers |
| Public GitHub code file | Static source inspection, line coverage, possible call relationships, code explanation, and interview prep. Paste a file link or a raw file URL, or upload a UTF-8 code file up to 200 KB. | GitHub line ranges |

Media uploads are limited to 100 MB and two hours. Webpages, PDFs, and transcripts are capped at 200,000 extracted characters. Code files support up to 2,400 lines. Some YouTube videos require sign-in, are geographically restricted, or have no recoverable audio or on-screen text. Timestamps for on-screen OCR are approximate. Websites requiring client-side rendering or credentials may fail extraction. Dynamic dispatch, external dependencies, and runtime side effects can require reading more files or running tests separately.

## Follow the code

```text
sourcewise/
├── app.py                     FastAPI routes, workspace cookie, upload and job lifecycle
├── store.py                   SQLite data, durable queue and conversation history
├── ingest/
│   ├── website.py             Article extraction
│   ├── youtube.py             Captions, audio transcription and frame OCR
│   ├── pdf.py                 PDF text and scanned pages
│   ├── github.py              Remote or uploaded files, sections and call relationships
│   └── network.py             Public-only network fetch and redirect handling
├── rag.py                     BM25 and semantic retrieval with rank fusion
├── agent.py                   Index, summarize, plan a search, retrieve, answer and cite
├── ai.py                      Gemini and OpenAI-compatible generation and embeddings
├── samples/                   Built-in reading and code examples
└── static/                    HTML, CSS, and vanilla JavaScript
```

A source enters a persistent SQLite queue, where a worker chooses the corresponding adapter. The adapter returns passages with location metadata. The agent indexes those passages, summarizes batches for long inputs, and adds code explanations where applicable. When the user asks a question, the agent can rewrite it using recent turns, retrieve passages from that source, and generate an answer with citations that reference the retrieved passages. Source files and passages are read as data. GitHub code is analyzed statically.

## Verify

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The tests use an isolated temporary database. They exercise source ingestion, workspace isolation, citation validation, source-scoped chat, summary export, retry, and private-address blocking.

## Deployment

Run one application process per SQLite data volume. It resumes pending jobs after a restart and supports multiple ingestion threads inside the process. The supplied Compose configuration binds to localhost and keeps browser workspaces separate via high-entropy cookies. For a team or public service, use HTTPS with `COOKIE_SECURE=true`, put the app behind authentication and request limits, restrict outbound connections, and apply your data retention and backup policies. Multiple replicas require a shared database, shared object storage, and a shared worker queue. If you configure `TRUSTED_FETCH_PROXY`, enforce public-only DNS resolution and destination policy at that proxy.


### Railway

Deploy this directory as a Dockerfile service. The included `railway.toml` configures a single replica and gates deployment on `/api/health`. Attach a persistent volume at `/app/data`. Set `RAILWAY_RUN_UID=0` so the container can initialize the mounted data directory. The entrypoint then drops privileges to the `sourcewise` user before starting FastAPI.

Set `AI_PROVIDER=gemini`, store `GEMINI_API_KEY` as a service secret, and set `COOKIE_SECURE=true` for the HTTPS domain. The container listens on Railway's assigned `PORT`. Configure access control before sharing a service that uses your model quota.

Railway's free plan has limited memory, storage, and monthly usage. The Whisper model cache shares the volume with the database. Choose a hosting plan with enough memory for your selected Whisper model and video workload. [Railway hosting limits](https://docs.railway.com/pricing/free-plan) · [Railway volume permissions](https://docs.railway.com/volumes#permissions)
