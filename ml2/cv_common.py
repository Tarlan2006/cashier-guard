"""Общие функции для CV-части: метки, файлы, md5."""
import hashlib
import re
from pathlib import Path

import openpyxl


def num_of(name: str):
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else None


def parse_ts(s):
    """'22 секунда' -> 22, '1минута 8 секунда' -> 68, None -> None."""
    if s is None:
        return None
    s = str(s).lower()
    mins = re.search(r"(\d+)\s*мин", s)
    secs = re.search(r"(\d+)\s*сек", s)
    if not (mins or secs):
        return None
    return (int(mins.group(1)) * 60 if mins else 0) + (int(secs.group(1)) if secs else 0)


def md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_dataset(root):
    """Возвращает список dict: num, path, violation(bool), t(sec|None), md5."""
    root = Path(root)
    ws = openpyxl.load_workbook(root / "open_labels.xlsx").active
    labels = {}
    for name, ts, verdict in list(ws.iter_rows(values_only=True))[1:]:
        if name is None:
            continue
        v = str(verdict).lower()
        labels[num_of(str(name))] = (parse_ts(ts), "нарушение" in v and "без" not in v)
    items = []
    for p in sorted((root / "videos").glob("*.mov")):
        n = num_of(p.stem)
        if n not in labels:
            continue
        t, viol = labels[n]
        items.append(dict(num=n, path=p, violation=viol, t=t, md5=md5(p)))
    return items


def group_dataset_by_md5(items: list[dict]) -> list[dict]:
    """Keep each byte-identical video once and retain all its annotation times."""
    groups: dict[str, list[dict]] = {}
    for item in items:
        groups.setdefault(item["md5"], []).append(item)
    unique = []
    for digest, members in groups.items():
        members = sorted(members, key=lambda item: item["num"])
        if len({item["violation"] for item in members}) != 1:
            raise ValueError(f"Conflicting verdicts for identical MD5: {digest}")
        event_times = sorted({float(item["t"]) for item in members if item["t"] is not None})
        if members[0]["violation"] and not event_times:
            raise ValueError(f"Positive video has no timecode: {digest}")
        unique.append(dict(members[0], nums=[item["num"] for item in members], event_times=event_times))
    return sorted(unique, key=lambda item: item["num"])
