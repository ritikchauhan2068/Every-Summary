"""Bounded workflow for indexing, summarizing, code explanation and source-scoped Q&A."""

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from sourcewise.ai import ProviderError
from sourcewise.rag import Retriever, tokens

UNKNOWN = "I couldn't find enough evidence in this source to answer that question."


def text_field(value, limit=1800):
    return value.strip()[:limit] if isinstance(value, str) else ""


def citations(ids, evidence):
    allowed = {p["id"] for p in evidence}
    return list(dict.fromkeys(item for item in ids if isinstance(item, str) and item in allowed))[:8] if isinstance(ids, list) else []


def batch_by_size(items, size=14_000):
    batch, current = [], 0
    for item in items:
        length = len(item["text"])
        if batch and current + length > size:
            yield batch
            batch, current = [], 0
        batch.append(item)
        current += length
    if batch:
        yield batch


def sentence(text, limit=340):
    fragments = re.split(r"(?<=[.!?])\s+", " ".join(text.split()), maxsplit=1)
    excerpt = fragments[0]
    return excerpt if len(excerpt) <= limit else excerpt[:limit].rsplit(" ", 1)[0] + "…"


def spans_evidence(passages, query):
    if not query:
        return []
    ranked = []
    for passage in passages:
        fragments = re.split(r"(?<=[.!?])\s+|\n+", passage["text"])
        fragments = [fragment.strip() for fragment in fragments if len(fragment.strip()) > 18]
        best = max(fragments, key=lambda fragment: len(query.intersection(tokens(fragment))), default="")
        matches = len(query.intersection(tokens(best)))
        if matches:
            ranked.append((matches, best[:650], passage["id"]))
    ranked.sort(key=lambda row: row[0], reverse=True)
    unique = {}
    for _, quote, identifier in ranked:
        unique.setdefault(quote, identifier)
    return list(unique.items())[:3]


class Agent:
    def __init__(self, provider):
        self.provider = provider

    def prepare(self, material, progress):
        passages = []
        for index, passage in enumerate(material.passages, 1):
            passage.id = f"S{index}"
            passages.append(asdict(passage))
        progress("Indexing source passages")
        vectors = self.provider.embed([p["text"] for p in passages], title=material.title)
        progress("Writing the source summary")
        summary = self.summarize(material, passages)
        code = material.code
        if code:
            progress("Building the code map and interview guide")
            code = self.explain_code(code, passages, summary)
        return {
            "title": material.title, "method": material.method, "passages": passages, "notes": material.notes,
            "summary": summary, "code": code, "vectors": vectors,
            "embedding_model": self.provider.embedding_model if vectors else "",
        }

    def summarize(self, material, passages):
        if self.provider.enabled:
            try:
                batches = list(batch_by_size(passages))
                if len(batches) == 1:
                    evidence = [{"id": p["id"], "text": p["text"]} for p in batches[0]]
                else:
                    def condense(batch):
                        result = self.provider.generate(
                            'Extract the main facts and relationships as {"items":[{"text":"sentence","citations":["S1"]}]}. '
                            "Include up to six concrete items that represent the distinct ideas across this group.",
                            [{"id": p["id"], "text": p["text"]} for p in batch],
                        )
                        facts = self.items(result.get("items"), batch, 6)
                        return facts or [{"text": sentence(batch[0]["text"]), "citations": [batch[0]["id"]]}]

                    with ThreadPoolExecutor(max_workers=4) as executor:
                        evidence = [item for facts in executor.map(condense, batches) for item in facts]
                result = self.provider.generate(
                    'Return {"overview":"2-4 clear sentences","citations":["S1"],'
                    '"items":[{"text":"a distinct takeaway in plain language","citations":["S1"]}]}. '
                    "Explain the main idea and cover important parts found throughout the evidence. "
                    "For code, explain its purpose and how it fits together. Include 3–6 takeaways when available.",
                    {"title": material.title, "evidence": evidence},
                )
                overview, ids = text_field(result.get("overview")), citations(result.get("citations"), passages)
                items = self.items(result.get("items"), passages, 6)
                if overview and ids:
                    return {"overview": overview, "citations": ids, "items": items, "mode": "AI synthesis"}
            except ProviderError:
                pass
        if material.code:
            names = [node["name"] for node in material.code["nodes"] if node["kind"] not in {"Module", "Continuation"}]
            code = material.code
            count = code["line_count"]
            overview = f"{material.title} has {count} lines across {len(code['nodes'])} readable sections."
            if names:
                overview += f" The file defines {', '.join(names[:6])}."
            items = [{"text": self.structural_explanation(node, code["edges"], code["nodes"]), "citations": [node["passage"]]}
                     for node in code["nodes"][:6]]
        else:
            count = min(5, len(passages))
            indexes = sorted({round(i * (len(passages) - 1) / max(1, count - 1)) for i in range(count)})
            overview = sentence(passages[0]["text"], 500)
            items = [{"text": sentence(passages[index]["text"]), "citations": [passages[index]["id"]]} for index in indexes]
        return {"overview": overview, "citations": [passages[0]["id"]], "items": items, "mode": "Extractive"}

    @staticmethod
    def items(raw, passages, limit):
        if not isinstance(raw, list):
            return []
        items = []
        for entry in raw:
            if isinstance(entry, dict) and (text := text_field(entry.get("text"))) and (ids := citations(entry.get("citations"), passages)):
                items.append({"text": text, "citations": ids})
            if len(items) == limit:
                break
        return items

    @staticmethod
    def structural_explanation(node, edges, nodes):
        names = {item["id"]: item["name"] for item in nodes}
        calls = [names[edge["to"]] for edge in edges if edge["from"] == node["id"] and edge["kind"] == "possible call"]
        if node["kind"] == "Module":
            description = "Read this block for setup such as imports, configuration, or top-level statements."
        elif node["kind"] == "Continuation":
            description = f"This block continues {node['name'].removesuffix(' (continued)')}. Follow the statements in order."
        elif node["kind"].lower() in {"class", "interface", "struct", "trait", "enum"}:
            description = f"{node['name']} defines a {node['kind'].lower()}. Look at its fields and related methods to see what it represents."
        else:
            description = f"{node['name']} is a {node['kind'].lower()}. Start with its inputs, then follow its decisions and return values."
        details = node["details"]
        if details.get("doc"):
            description = sentence(details["doc"])
        if details.get("inputs"):
            description += f" It takes {', '.join(details['inputs'])} as input."
        if calls:
            description += f" This block appears to call {', '.join(calls[:6])}."
        return description

    def explain_code(self, code, passages, summary):
        nodes, edges = code["nodes"], code["edges"]
        evidence = [{"id": p["id"], "text": p["text"], "section": node["name"]} for p, node in zip(passages, nodes)]
        explained = {}
        if self.provider.enabled:
            def explain_group(batch):
                try:
                    result = self.provider.generate(
                        'Return {"sections":[{"id":"S1","explanation":"2–4 sentences"}]}. '
                        "Explain every supplied section separately in beginner-friendly language. "
                        "Describe its concrete inputs, decisions, outputs or side effects where present.",
                        batch,
                    )
                    raw = result.get("sections")
                    allowed = {part["id"] for part in batch}
                    return {item["id"]: text_field(item.get("explanation"), 900) for item in raw
                            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"] in allowed} if isinstance(raw, list) else {}
                except ProviderError:
                    return {}

            with ThreadPoolExecutor(max_workers=4) as executor:
                for batch in executor.map(explain_group, batch_by_size(evidence, 9500)):
                    explained.update(batch)

        for node in nodes:
            node["explanation"] = explained.get(node["passage"]) or self.structural_explanation(node, edges, nodes)
            node["mode"] = "AI walkthrough" if explained.get(node["passage"]) else "Structural guide"

        interview = []
        if self.provider.enabled:
            try:
                output = self.provider.generate(
                    'Return {"questions":[{"question":"interview question","answer":"plain-language answer","citations":["S1"]}]}. '
                    "Write five distinct likely interview questions about this exact file. Cover purpose, how data flows, "
                    "a concrete implementation choice, an edge case, and a trade-off when the evidence supports it.",
                    {"overview": summary, "sections": [
                        {"id": n["passage"], "name": n["name"], "explanation": n["explanation"][:350]} for n in nodes[:65]
                    ]},
                )
                raw = output.get("questions")
                if isinstance(raw, list):
                    for item in raw[:6]:
                        if isinstance(item, dict):
                            question, answer = text_field(item.get("question"), 250), text_field(item.get("answer"), 700)
                            ids = citations(item.get("citations"), passages)
                            if question and answer and ids:
                                interview.append({"question": question, "answer": answer, "citations": ids})
            except ProviderError:
                pass
        if not interview:
            interview.append({
                "question": "How would you introduce this file in an interview?",
                "answer": summary["overview"] + " Then walk through the sections in order and describe their roles.",
                "citations": summary["citations"],
            })
            for node in [n for n in nodes if n["kind"] != "Continuation"][:5]:
                interview.append({
                    "question": f"What role does {node['name']} play?",
                    "answer": node["explanation"], "citations": [node["passage"]],
                })
        return {**code, "interview": interview}

    @staticmethod
    def location_filter(passages, question):
        page = re.search(r"\bpage\s+(\d+)\b", question, re.I)
        line = re.search(r"\bline(?:s)?\s+(\d+)\b", question, re.I)
        time = re.search(r"(?<![\d:])(?:(\d{1,2}):)?(\d{1,3}):(\d{2})(?![\d:])", question)
        if page and any(p["label"].startswith("Page ") for p in passages):
            return [p for p in passages if p["label"] == f"Page {int(page[1])}"]
        if line and any(p["label"].startswith("Line") for p in passages):
            return [p for p in passages if p["start"] <= int(line[1]) <= p["end"]]
        timed = [p for p in passages if re.match(r"^\d+:\d{2}", p["label"])]
        if time and timed:
            second = int(time[1] or 0) * 3600 + int(time[2]) * 60 + int(time[3])
            return [p for p in timed if p["start"] <= second <= p["end"]]
        return None

    def answer(self, record, question, history=None):
        passages = record["passages"]
        located = self.location_filter(passages, question)
        if located == []:
            return {"answer": UNKNOWN, "citations": [], "mode": "Source references"}
        vectors = record["vectors"] if record.get("embedding_model") == self.provider.embedding_model else []
        if located:
            indexes = {p["id"] for p in located}
            vectors = [v for p, v in zip(passages, vectors) if p["id"] in indexes]
            passages = located
        retriever = Retriever(passages, vectors)
        signals = [part["question"] for part in (history or [])[-2:]]
        if self.provider.enabled:
            try:
                plan = self.provider.generate(
                    'Plan source retrieval. Return {"query":"standalone keyword-rich search query"}. '
                    "Resolve follow-up references using recent questions. Do not answer or request any external action.",
                    {"question": question, "recent_questions": signals, "source_title": record["title"]},
                )
                query = text_field(plan.get("query"), 350) or question
                embedding = self.provider.embed([query], query=True) if vectors else []
                relevant = retriever.search(query, embedding[0] if embedding else None)
                if not relevant:
                    relevant = retriever.search(question + " " + " ".join(signals))
                if not relevant and located:
                    relevant = located[:5]
                if not relevant and re.search(r"\b(overview|summari[sz]e|main idea|about|purpose)\b", question, re.I):
                    relevant = passages[:5]
                if relevant:
                    result = self.provider.generate(
                        'Answer only if the retrieved source evidence supports the answer. Return '
                        '{"answer":"plain-language answer","citations":["S1"]}. Use an empty citations list when unsupported.',
                        {"question": question, "recent_questions": signals, "evidence": [
                            {"id": p["id"], "label": p["label"], "text": p["text"]} for p in relevant
                        ]},
                    )
                    answer, ids = text_field(result.get("answer"), 3200), citations(result.get("citations"), relevant)
                    if answer and ids:
                        return {"answer": answer, "citations": ids, "mode": "AI answer"}
                    return {"answer": UNKNOWN, "citations": [], "mode": "AI answer"}
            except ProviderError:
                pass
        if re.search(r"\b(overview|summari[sz]e|main idea|about|purpose|takeaways?)\b", question, re.I) and len(tokens(question)) <= 3:
            result = record["summary"]
            if "takeaway" in question.lower() and result["items"]:
                evidence = list(dict.fromkeys(id for item in result["items"] for id in item["citations"]))
                return {"answer": "\n".join("• " + item["text"] for item in result["items"]),
                        "citations": evidence[:8], "mode": result["mode"]}
            return {"answer": result["overview"], "citations": result["citations"], "mode": result["mode"]}
        terms = set(tokens(question))
        relevant = retriever.search(question)
        excerpts = spans_evidence(relevant, terms)
        if not excerpts and located:
            excerpts = [(sentence(p["text"], 500), p["id"]) for p in located[:3]]
        if excerpts:
            return {
                "answer": "Relevant passages from this source:\n\n" + "\n\n".join(f"“{quote}”" for quote, _ in excerpts),
                "citations": list(dict.fromkeys(identifier for _, identifier in excerpts)), "mode": "Extractive",
            }
        return {"answer": UNKNOWN, "citations": [], "mode": "Extractive"}
