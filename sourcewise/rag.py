import math
import re
from collections import Counter

STOP = set(("a an and are as at be but by can did do does for from had has have how i in is it its me more "
            "of on or please s so t tell than that the their them then there these they this to use was "
            "were what when where which who why will with would you your explain give according about "
            "source document video page code say says describe happen something main overview key "
            "discussed purpose work").split())


def tokens(text):
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text).replace("_", " ")
    terms = re.findall(r"[^\W_]+", text.casefold(), re.UNICODE)
    result = []
    for term in terms:
        if term in STOP or len(term) < 2:
            continue
        if len(term) > 4 and term.endswith("s") and not term.endswith(("ss", "us", "is")):
            term = term[:-1]
        result.append(term)
    return result


def cosine(left, right):
    if len(left) != len(right):
        return 0
    denominator = math.sqrt(sum(item * item for item in left) * sum(item * item for item in right))
    return sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0


class Retriever:
    def __init__(self, passages, vectors=None):
        self.passages = passages
        self.vectors = vectors or []
        self.docs = [Counter(tokens(item["text"] + " " + item["label"])) for item in passages]
        self.frequency = Counter(term for doc in self.docs for term in doc)
        self.lengths = [sum(doc.values()) for doc in self.docs]
        self.average = max(1, sum(self.lengths) / max(1, len(self.lengths)))

    def search(self, query, vector=None, limit=6):
        terms = set(tokens(query))
        scores = []
        for i, doc in enumerate(self.docs):
            lexical = 0
            for term in terms & doc.keys():
                freq = doc[term]
                count = self.frequency[term]
                idf = math.log(1 + (len(self.docs) - count + .5) / (count + .5))
                lexical += idf * freq * 2.2 / (freq + 1.2 * (.25 + .75 * self.lengths[i] / self.average))
            semantic = cosine(vector, self.vectors[i]) if vector and len(self.vectors) == len(self.docs) else 0
            if lexical or semantic >= .24:
                scores.append((i, lexical, semantic))
        if not scores:
            return []
        ranks = {}
        for key, weight in ((1, 1), (2, .85)):
            for rank, row in enumerate(sorted(scores, key=lambda item: item[key], reverse=True)):
                if row[key] > 0 and (key == 1 or row[key] >= .24):
                    ranks[row[0]] = ranks.get(row[0], 0) + weight / (12 + rank)
        return [self.passages[i] for i in sorted(ranks, key=ranks.get, reverse=True)[:limit]]
