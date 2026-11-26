import json
from time import monotonic, sleep

import httpx
from fastapi.testclient import TestClient

from sourcewise.app import create_app


def mock_api(monkeypatch, handler):
    client_class = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr("sourcewise.ai.httpx.Client", lambda **args: client_class(transport=transport, **args))


def wait_for_source(client, identifier):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        result = client.get(f"/api/sources/{identifier}").json()
        if result["status"] in {"ready", "failed"}:
            assert result["status"] == "ready", result
            return result["result"]
        sleep(.03)
    raise AssertionError("Source processing timed out")


def reply(data):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(data)}]}}]})


def test_gemini_indexes_and_answers_with_citations(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "local-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "unused-test-key")
    monkeypatch.setenv("AI_MODEL", "old-config")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_EMBEDDING_MODEL", raising=False)
    calls = []

    def handle(request):
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.headers["x-goog-api-key"] == "local-test-key"
        assert "authorization" not in request.headers
        body = json.loads(request.content)
        path = request.url.path
        if path == "/v1beta/models/gemini-embedding-2:batchEmbedContents":
            requests = body["requests"]
            assert all(item["outputDimensionality"] == 768 for item in requests)
            texts = [item["content"]["parts"][0]["text"] for item in requests]
            if len(texts) > 1:
                assert all(text.startswith("title: How retrieval-augmented generation works | text: ") for text in texts)
                calls.append("document embeddings")
            else:
                assert texts == ["task: question answering | query: semantic lexical retrieval"]
                calls.append("query embedding")
            return httpx.Response(200, json={"embeddings": [{"values": [1.0, 0.0]} for _ in texts]})

        assert path == "/v1beta/models/gemini-3.5-flash-lite:generateContent"
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        system = body["systemInstruction"]["parts"][0]["text"]
        content = json.loads(body["contents"][0]["parts"][0]["text"])
        if "Plan source retrieval" in system:
            calls.append("retrieval plan")
            return reply({"query": "semantic lexical retrieval"})
        if "Answer only" in system:
            calls.append("answer")
            assert any(item["id"] == "S3" for item in content["evidence"])
            return reply({"answer": "It finds related meaning through embeddings.", "citations": ["S3", "S999"]})
        calls.append("summary")
        return reply({"overview": "RAG gives the model retrieved evidence.", "citations": ["S1"], "items": []})

    mock_api(monkeypatch, handle)
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/health").json()["ai_mode"] == "Gemini"
        created = client.post("/api/samples", json={"demo": "web"})
        assert created.status_code == 202
        identifier = created.json()["id"]
        source = wait_for_source(client, identifier)
        assert source["summary"]["mode"] == "AI synthesis"
        answer = client.post(f"/api/sources/{identifier}/questions", json={"question": "How does semantic retrieval work?"})
        assert answer.json()["mode"] == "AI answer"
        assert answer.json()["citations"] == ["S3"]
    assert calls == ["document embeddings", "summary", "retrieval plan", "query embedding", "answer"]


def test_gemini_quota_error_falls_back_to_source_excerpts(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "local-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "unused-test-key")
    calls = []

    def handle(request):
        calls.append(request.url.host)
        return httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}})

    mock_api(monkeypatch, handle)
    with TestClient(create_app(tmp_path)) as client:
        client.get("/")
        created = client.post("/api/samples", json={"demo": "web"})
        identifier = created.json()["id"]
        assert wait_for_source(client, identifier)["summary"]["mode"] == "Extractive"
        answer = client.post(f"/api/sources/{identifier}/questions", json={"question": "What are semantic embeddings?"})
        assert answer.json()["mode"] == "Extractive"
        assert answer.json()["citations"] == ["S3"]
    assert calls and set(calls) == {"generativelanguage.googleapis.com"}


def test_gemini_mode_without_a_key_does_not_use_another_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "unused-test-key")
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/health").json()["ai_mode"] == "Extractive"
