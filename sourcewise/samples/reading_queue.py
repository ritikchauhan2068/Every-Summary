"""A small reading queue with an in-memory list of sources."""

from dataclasses import dataclass


@dataclass
class ReadingItem:
    """One saved source and its reading status."""

    title: str
    minutes: int
    finished: bool = False


def add_item(queue, title, minutes):
    """Save a source after checking that the reading time is positive."""
    if not title.strip():
        raise ValueError("A title is required")
    if minutes <= 0:
        raise ValueError("Reading time must be positive")
    item = ReadingItem(title.strip(), minutes)
    queue.append(item)
    return item


def next_item(queue):
    """Find the shortest unread source, or return None for an empty queue."""
    unread = [item for item in queue if not item.finished]
    return min(unread, key=lambda item: item.minutes, default=None)


def mark_finished(item):
    """Mark a source read so it is excluded from suggestions."""
    item.finished = True
    return item


def main():
    queue = []
    add_item(queue, "HTTP caching", 12)
    add_item(queue, "Database indexes", 6)
    item = next_item(queue)
    if item is not None:
        print(f"Read next: {item.title}")
        mark_finished(item)


if __name__ == "__main__":
    main()
