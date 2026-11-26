from pathlib import Path
from time import monotonic, sleep

import pymupdf
import pytest
from fastapi.testclient import TestClient

from sourcewise.agent import Agent, UNKNOWN
from sourcewise.app import create_app
from sourcewise.domain import Material, Passage, SourceError
from sourcewise.ingest import github, website, youtube
from sourcewise.ingest.network import get_public, parse_http_url, public_addresses


@pytest.fixture
def client(tmp_path, monkeypatch):
    for key in ("GEMINI_API_KEY", "OPENAI_API_KEY", "AI_API_KEY", "AI_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    with TestClient(create_app(tmp_path)) as browser:
        browser.get("/")
        yield browser


def finish(client, response):
    assert response.status_code == 202, response.text
    identifier = response.json()["id"]
    deadline = monotonic() + 8
    while monotonic() < deadline:
        row = client.get(f"/api/sources/{identifier}").json()
        if row["status"] in {"ready", "failed"}:
            return row
        sleep(.04)
    raise AssertionError("Background processing timed out")


def test_sample_chat_citations_and_download(client):
    row = finish(client, client.post("/api/samples", json={"demo": "web"}))
    assert row["status"] == "ready"
    assert row["result"]["summary"]["items"]
    endpoint = f"/api/sources/{row['id']}"
    result = client.post(endpoint + "/questions", json={"question": "What are semantic embeddings?"}).json()
    assert "semantic retriever" in result["answer"]
    assert result["citations"] == ["S3"]
    no_answer = client.post(endpoint + "/questions", json={"question": "Who won Wimbledon?"}).json()
    assert no_answer["answer"] == UNKNOWN
    assert len(client.get(endpoint).json()["history"]) == 2
    download = client.get(endpoint + "/summary.txt")
    assert download.headers["content-disposition"] == 'attachment; filename="summary.txt"'
    assert "[Section 1]" in download.text
    assert client.get("/api/sources").json()[0]["id"] == row["id"]
    assert client.delete(endpoint).status_code == 200
    assert client.get(endpoint).status_code == 404


def test_github_graph_has_every_line(client, monkeypatch):
    text = "import math\n\ndef total(x):\n    return round_up(x)\n\ndef round_up(x):\n    return math.ceil(x)\n"
    monkeypatch.setattr(github, "get_public", lambda *args, **kwargs: (text.encode(), "text/plain", ""))
    row = finish(client, client.post("/api/sources", data={
        "kind": "github", "url": "https://github.com/octocat/Hello-World/blob/main/math.py"
    }))
    assert row["status"] == "ready"
    result = row["result"]
    code = result["code"]
    assert [line for node in code["nodes"] for line in range(node["start"], node["end"] + 1)] == list(range(1, 8))
    assert {"from": "L3", "to": "L6", "kind": "possible call"} in code["edges"]
    assert all(node["explanation"] for node in code["nodes"])
    assert code["interview"]
    assert result["passages"][1]["url"].endswith("#L3-L5")


def test_pdf_upload_has_page_citations(client):
    document = pymupdf.open()
    document.new_page().insert_text((70, 70), "The tidal lake supports coastal vegetation and local wildlife.")
    document.new_page().insert_text((70, 70), "Biodiversity habitat is monitored with annual species surveys.")
    data = document.tobytes()
    document.close()
    row = finish(client, client.post("/api/sources", data={"kind": "pdf"},
                                    files={"file": ("report.pdf", data, "application/pdf")}))
    assert row["status"] == "ready"
    assert [p["label"] for p in row["result"]["passages"]] == ["Page 1", "Page 2"]
    result = client.post(f"/api/sources/{row['id']}/questions", json={"question": "How is biodiversity monitored?"}).json()
    assert result["citations"] == ["S2"]
    assert "annual species surveys" in result["answer"]
    page = client.post(f"/api/sources/{row['id']}/questions", json={"question": "What is on page 1?"}).json()
    assert page["citations"] == ["S1"]
    assert "tidal lake" in page["answer"]


def test_video_caption_failure_uses_audio_and_timestamp_links(client, monkeypatch):
    monkeypatch.setattr(youtube, "captions", lambda _: [])
    monkeypatch.setattr(youtube, "title_for", lambda _: "A captionless video")

    def download(_, folder):
        audio = Path(folder) / "test.wav"
        audio.write_bytes(b"audio fixture")
        return audio

    monkeypatch.setattr(youtube, "download", download)
    monkeypatch.setattr(youtube, "duration_for", lambda _: 12)
    monkeypatch.setattr(youtube, "speech_segments", lambda _: [(3, 11, "The lesson explains wireless routing and addresses.")])
    row = finish(client, client.post("/api/sources", data={
        "kind": "youtube", "url": "https://www.youtube.com/watch?v=abcdefghi12"
    }))
    assert row["status"] == "ready"
    assert row["result"]["method"] == "Whisper audio transcription"
    passage = row["result"]["passages"][0]
    assert passage["label"] == "00:03–00:11"
    assert passage["url"].endswith("&t=3s")


def test_site_ingestion_and_retry(client, monkeypatch):
    def temporary(*args, **kwargs):
        raise SourceError("The source is temporarily unavailable.")

    monkeypatch.setattr(website, "get_public", temporary)
    response = client.post("/api/sources", data={"kind": "website", "url": "https://example.com/blog/"})
    row = finish(client, response)
    assert row["status"] == "failed"
    raw = b"<title>Open document</title><main><h1>Habitat study</h1><p>This report tracks the migratory birds that visit wetlands every winter.</p></main>"
    monkeypatch.setattr(website, "get_public", lambda *args, **kwargs: (raw, "text/html", "https://example.com/blog/"))
    row = finish(client, client.post(f"/api/sources/{row['id']}/retry"))
    assert row["status"] == "ready"
    assert "migratory birds" in row["result"]["passages"][0]["text"]


def test_workspaces_are_isolated_and_private_hosts_blocked(client):
    row = finish(client, client.post("/api/samples", json={"demo": "code"}))
    session = client.cookies.get("sourcewise_session")
    client.cookies.clear()
    assert client.get("/api/sources").json() == []
    assert client.get(f"/api/sources/{row['id']}").status_code == 404
    assert client.delete(f"/api/sources/{row['id']}").status_code == 404
    client.cookies.clear()
    client.cookies.set("sourcewise_session", session)
    assert client.get(f"/api/sources/{row['id']}").status_code == 200
    for url in ("file:///etc/passwd", "https://example.com:8080", "http://user@example.com"):
        with pytest.raises(SourceError):
            parse_http_url(url)
    with pytest.raises(SourceError, match="public address"):
        public_addresses("127.0.0.1", 80)
    with pytest.raises(SourceError, match="public address"):
        get_public("http://[::1]/")


def test_provider_workflow_discards_citations_outside_retrieval():
    class FakeProvider:
        enabled = True
        embedding_model = "test"

        def embed(self, texts, *, query=False, title=""):
            return [[1, 0] if "transport" in text else [0, 1] for text in texts]

        def generate(self, instruction, data):
            if instruction.startswith("Plan"):
                return {"query": "transport"}
            if instruction.startswith("Answer"):
                return {"answer": "Invalid citation.", "citations": ["S99"]}
            return {"overview": "A transport guide.", "citations": ["S1", "S100"], "items": []}

    agent = Agent(FakeProvider())
    material = Material("Transport", "Example", [Passage("The transport runs daily.", "One")])
    record = agent.prepare(material, lambda _: None)
    assert record["summary"]["citations"] == ["S1"]
    assert record["vectors"]
    assert agent.answer(record, "How does the transport run?")["answer"] == UNKNOWN


def test_uploaded_code_uses_same_analysis(client):
    source = b"export function double(number) {\n  return number * 2;\n}\n"
    row = finish(client, client.post("/api/sources", data={"kind": "github"},
                                    files={"file": ("math.js", source, "text/javascript")}))
    assert row["status"] == "ready"
    assert row["result"]["code"]["nodes"][0]["name"] == "double"
    assert row["result"]["passages"][0]["label"] == "Lines 1–3"
