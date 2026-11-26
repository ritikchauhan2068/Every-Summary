import ast
import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote

from sourcewise.domain import Material, Passage, SourceError
from sourcewise.ingest.network import get_public, parse_http_url

DECLARATION = re.compile(
    r"^(?P<indent>[ \t]*)(?:(?:export|default|public|private|protected|static|final|async|pub)\s+)*"
    r"(?P<kind>function|class|interface|struct|trait|enum|fn|func|def|impl)\s+"
    r"(?:\([^)]*\)\s*)?(?P<name>[A-Za-z_$][\w$]*)"
)
ARROW = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([\w$]+)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\([^)]*\)|[\w$]+)\s*=>")
METHOD = re.compile(r"^\s+(?:(?:public|private|protected|static|async|get|set)\s+)*([A-Za-z_$][\w$]*)\s*\([^\n]*\)\s*(?::[^\{]+)?\{\s*$")
MAX_CODE_BYTES = 200_000
CONTROL = {"if", "while", "for", "switch", "catch", "with", "return", "match"}


def load(url, progress):
    progress("Reading the GitHub file")
    parts = parse_http_url(url)
    host = parts.hostname
    segments = [unquote(value) for value in parts.path.strip("/").split("/")]
    if any("/" in value or value in {"", ".", ".."} for value in segments):
        raise SourceError("Enter the URL of an individual GitHub file.")
    if host == "github.com" and len(segments) >= 5 and segments[2] == "blob":
        owner, repo, _, *tail = segments
    elif host == "raw.githubusercontent.com" and len(segments) >= 4:
        owner, repo, *tail = segments
    else:
        raise SourceError("Paste an individual file URL from GitHub. Open the file in its repository and copy the browser URL.")
    if not all(re.fullmatch(r"[\w.-]+", item, flags=re.ASCII) for item in (owner, repo)):
        raise SourceError("The GitHub repository name is invalid.")
    escaped = quote("/".join(tail), safe="/")
    current = f"https://github.com/{owner}/{repo}/blob/{escaped}"
    fetch_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{escaped}"
    raw, _, _ = get_public(
        fetch_url, limit=MAX_CODE_BYTES, allowed_host=lambda name: name == "raw.githubusercontent.com",
    )
    return decode_code(raw, tail[-1], current)


def load_file(path, filename, progress):
    progress("Reading the uploaded code file")
    return decode_code(Path(path).read_bytes(), filename)


def decode_code(raw, filename, url=""):
    if b"\x00" in raw:
        raise SourceError("Choose a source file with readable text.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise SourceError("This source file is not UTF-8 text.") from exc
    return analyze(text, filename, url)


def python_symbols(text):
    try:
        tree = ast.parse(text)
    except (SyntaxError, RecursionError):
        return None, []
    marks = []

    def visit(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + child.name
                kind = "Class" if isinstance(child, ast.ClassDef) else ("Async function" if isinstance(child, ast.AsyncFunctionDef) else "Function")
                start = min([child.lineno, *(item.lineno for item in child.decorator_list)])
                details = {"doc": ast.get_docstring(child) or ""}
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = child.args
                    details["inputs"] = [argument.arg for argument in [
                        *args.posonlyargs, *args.args, *args.kwonlyargs
                    ] if argument.arg not in {"self", "cls"}]
                marks.append((start, name, kind, details))
                visit(child, name + ".")
            elif not isinstance(child, (ast.expr, ast.arguments)):
                visit(child, prefix)

    try:
        visit(tree)
    except RecursionError:
        return None, []
    return tree, marks


def text_symbols(lines, suffix):
    marks = []
    for number, line in enumerate(lines, 1):
        if match := DECLARATION.match(line):
            marks.append((number, match["name"], match["kind"].capitalize(), {}))
        elif match := ARROW.match(line):
            marks.append((number, match[1], "Function", {}))
        elif suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".java", ".cs"} and (match := METHOD.match(line)):
            if match[1] not in CONTROL:
                marks.append((number, match[1], "Method", {}))
    return marks


def called_names(tree, start, end, content):
    if tree is None:
        return set(re.findall(r"\b([A-Za-z_$][\w$]*)\s*\(", "\n".join(content.splitlines()[1:])))
    calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and start <= node.lineno <= end:
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
    return calls


def analyze(text, filename, url=""):
    lines = text.splitlines()
    if not text.strip():
        raise SourceError("This code file is empty.")
    if len(lines) > 2400:
        raise SourceError("Choose a code file with 2,400 lines or fewer.")
    if any(len(line) > 6000 for line in lines):
        raise SourceError("Choose a formatted source file with lines shorter than 6,000 characters.")
    suffix = PurePosixPath(filename).suffix.lower()
    tree, marks = python_symbols(text) if suffix == ".py" else (None, [])
    if tree is None:
        marks = text_symbols(lines, suffix)
    by_line = {start: (name, kind, details) for start, name, kind, details in sorted(marks, key=lambda mark: mark[0])}
    by_line.setdefault(1, ("Module setup" if marks else "File contents", "Module", {}))
    boundaries = sorted(by_line)
    passages, nodes, edges = [], [], []
    targets = {}
    pending_calls = []
    for index, first in enumerate(boundaries):
        stop = boundaries[index + 1] - 1 if index + 1 < len(boundaries) else len(lines)
        name, kind, details = by_line[first]
        start = first
        while start <= stop:
            end, size = start, len(lines[start - 1])
            while end < min(start + 79, stop) and size + len(lines[end]) < 5500:
                size += len(lines[end]) + 1
                end += 1
            content = "\n".join(lines[start - 1:end])
            node_id = f"L{start}"
            label = f"Lines {start}–{end}" if start != end else f"Line {start}"
            linked = f"{url}#L{start}-L{end}" if url else ""
            passages.append(Passage(content, label, linked, start, end))
            nodes.append({
                "id": node_id, "name": name if start == first else f"{name} (continued)",
                "kind": kind if start == first else "Continuation", "label": label,
                "passage": f"S{len(passages)}", "start": start, "end": end,
                "details": details if start == first else {},
            })
            if start == first:
                targets.setdefault(name.split(".")[-1], []).append(node_id)
            else:
                edges.append({"from": f"L{first}", "to": node_id, "kind": "continues"})
            pending_calls.append((node_id, called_names(tree, start, end, content)))
            start = end + 1
    for origin, calls in pending_calls:
        for name in sorted(calls):
            destinations = targets.get(name, [])
            if len(destinations) == 1 and origin != destinations[0]:
                edges.append({"from": origin, "to": destinations[0], "kind": "possible call"})
    return Material(filename, "GitHub file analysis", passages, code={
        "nodes": nodes, "edges": edges, "language": suffix.removeprefix(".") or "text",
        "line_count": len(lines),
    })
