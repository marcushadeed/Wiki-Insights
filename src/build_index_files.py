from libzim.reader import Archive
from pathlib import Path
from tqdm import tqdm
from multiprocessing import Pool
import os
import re
import struct
from urllib.parse import quote, unquote

ZIM_PATH = "wikipedia_dump/wikipedia_en_all_nopic_2026-03.zim"
WIKI_ARCHIVE = Archive(ZIM_PATH)

N_WORKERS = min(8, os.cpu_count() or 4)
CHUNK_SIZE = 1000

TITLE_FILE = Path(__file__).resolve().parent.parent / "data/wiki_titles.txt"
INDEX_FILE = Path(__file__).resolve().parent.parent / "data/titles_index.idx"
REFERENCE_FILE = Path(__file__).resolve().parent.parent / "data/references.idx"

BAR_FORMAT = "{bar:10} | {n_fmt}/{total_fmt} | {percentage:3.1f}% {postfix}"


def step_tqdm(iterable, *, step: int, total_steps: int, desc: str, unit: str, **kwargs):
    return tqdm(
        iterable,
        ncols=100,
        unit=unit,
        bar_format=BAR_FORMAT,
        desc=desc,
        postfix=f"{step}/{total_steps}",
        leave=False,
        **kwargs,
    )


def title_line_count() -> int:
    with TITLE_FILE.open("rb") as f:
        return sum(1 for _ in f)


def create_title_list() -> bool:
    titles = []
    for i in step_tqdm(
        range(WIKI_ARCHIVE.all_entry_count),
        step=1,
        total_steps=2,
        desc="Reading ZIM entries",
        unit="entries",
    ):
        entry = WIKI_ARCHIVE._get_entry_by_id(i)

        if entry.is_redirect:
            continue
        item = entry.get_item()
        if "text/html" not in item.mimetype:
            continue
        if is_html_redirect(item):
            continue

        if entry.title is not None:
            titles.append(entry.title)

    titles.sort()

    with open(TITLE_FILE, "w") as f:
        for title in step_tqdm(
            titles,
            step=2,
            total_steps=2,
            desc="Writing titles",
            unit="titles",
        ):
            f.write(title + "\n")

    return True


def index_titles() -> bool:
    try:
        title_count = title_line_count()
        with TITLE_FILE.open("rb") as f, INDEX_FILE.open("wb") as idx:
            offset = 0
            for _ in step_tqdm(
                range(title_count),
                step=1,
                total_steps=1,
                desc="Indexing titles",
                unit="titles",
            ):
                idx.write(struct.pack("<q", offset))
                line = f.readline()
                if not line:
                    break
                offset = f.tell()
    except OSError as e:
        print(f"Could not build index file: {e}")
        return False

    return True


def remove_old_data() -> bool:
    try:
        for file in step_tqdm(
            [TITLE_FILE, INDEX_FILE],
            step=1,
            total_steps=1,
            desc="Removing files",
            unit="files",
        ):
            if file.exists():
                file.unlink()
    except OSError as e:
        print(f"Could not remove old data: {e}")
        return False

    return True


def get_index(title: str) -> int | None:
    target = title.encode("utf-8")
    try:
        with INDEX_FILE.open("rb") as idx, TITLE_FILE.open("rb") as f:
            idx.seek(0, 2)
            n_lines = idx.tell() // 8
            lo, hi = 0, n_lines - 1

            while lo <= hi:
                mid = (lo + hi) // 2
                idx.seek(mid * 8)
                raw = idx.read(8)
                if len(raw) != 8:
                    return None
                offset = struct.unpack("<q", raw)[0]
                f.seek(offset)
                line = f.readline().rstrip(b"\n")

                if line == target:
                    return mid
                if line < target:
                    lo = mid + 1
                else:
                    hi = mid - 1
    except OSError as e:
        print(f"get_index: I/O error: {e}")
        return None
    except (struct.error, UnicodeDecodeError) as e:
        print(f"get_index: corrupt data: {e}")
        return None

    return None


def get_title(index: int) -> str | None:
    if index is None:
        return None

    try:
        with INDEX_FILE.open("rb") as idx, TITLE_FILE.open("rb") as f:
            idx.seek(index * 8)
            raw = idx.read(8)
            if len(raw) != 8:
                return None
            offset = struct.unpack("<q", raw)[0]
            f.seek(offset)
            return f.readline().decode().strip()
    except OSError as e:
        print(f"get_title: I/O error: {e}")
        return None
    except (struct.error, UnicodeDecodeError) as e:
        print(f"get_title: corrupt data: {e}")
        return None


# Redirects to anchored sections (e.g. "#Discography") can't be expressed as
# native ZIM redirects, so they're stored as tiny HTML pages with a
# <meta http-equiv="refresh"> tag.  The size gap between these pages
# (≤514 B, empirically) and the smallest real article (≥4109 B) lets us
# use a cheap size pre-filter to skip the content fetch for real articles.
_HTML_REDIRECT_MAX_SIZE = 2048
_HTML_REDIRECT_PATTERN = b"http-equiv"


def is_html_redirect(item) -> bool:
    if item.size > _HTML_REDIRECT_MAX_SIZE:
        return False
    return _HTML_REDIRECT_PATTERN in bytes(item.content[:512])


def path_from_title(title: str) -> str:
    slug = title.replace(' ', '_')
    # Wikipedia keeps these chars unencoded in article paths
    encoded = quote(slug, safe="(),-._~!*':@")
    return f"A/{encoded}"


def title_from_path(path: str) -> str:
    # Inverse of path_from_title: undo URL-encoding and the space->underscore
    # substitution so an href slug can be matched against the stored title.
    return unquote(path).replace("_", " ")


_HREF_PATTERN = re.compile(rb'<a href="([^"]*)"')


def _parse_reference_paths(content) -> set[str]:
    # Accepts bytes (hot path, skips a full-page decode) or str (legacy caller).
    raw = content if isinstance(content, bytes) else content.encode("utf-8")
    paths = set()
    for m in _HREF_PATTERN.finditer(raw):
        href = m.group(1).split(b"?", 1)[0].split(b"#", 1)[0]
        if href.startswith(b"./"):
            href = href[2:]
        if href:
            paths.add(title_from_path(href.decode("utf-8")))
    return paths


def get_reference_indices(index: int) -> list[int]:
    if index is None:
        return []

    entry = WIKI_ARCHIVE.get_entry_by_title(get_title(index))
    content = bytes(entry.get_item().content)
    references = {
        ref_index
        for title in _parse_reference_paths(content)
        if (ref_index := get_index(title)) is not None
    }
    return list(references)


def _load_title_index_map() -> dict[str, int]:
    # Load to memory to avoid binary search over the on-disk index.
    title_to_index = {}
    with TITLE_FILE.open("rb") as f:
        for i, line in enumerate(f):
            title_to_index[line.rstrip(b"\n").decode("utf-8")] = i
    return title_to_index


# Set by the parent before the worker Pool is forked so each worker inherits
# the (large) title->index map via copy-on-write instead of pickling it.
_PARENT_MAP: dict[str, int] | None = None
_WORKER_ARCHIVE = None
_WORKER_MAP: dict[str, int] | None = None


def _worker_init() -> None:
    global _WORKER_ARCHIVE, _WORKER_MAP
    _WORKER_ARCHIVE = Archive(ZIM_PATH)
    _WORKER_MAP = _PARENT_MAP


def _refs_for(archive, title: str, title_to_index: dict[str, int]) -> set[int]:
    raw = bytes(archive.get_entry_by_title(title).get_item().content)
    return {
        idx
        for p in _parse_reference_paths(raw)
        if (idx := title_to_index.get(p)) is not None
    }


def _pack_record(source: int, refs: set[int]) -> bytes:
    return struct.pack(f"<{len(refs) + 2}I", source, len(refs), *refs)


def _process_chunk(args: tuple[int, list[str]]) -> bytes:
    start_i, titles = args
    out = bytearray()
    for offset, title in enumerate(titles):
        refs = _refs_for(_WORKER_ARCHIVE, title, _WORKER_MAP)
        out += _pack_record(start_i + offset, refs)
    return bytes(out)


def build_reference_map(limit: int | None = None, workers: int = N_WORKERS) -> bool:
    global _PARENT_MAP
    try:
        title_to_index = _load_title_index_map()
        n = len(title_to_index) if limit is None else min(limit, len(title_to_index))

        with TITLE_FILE.open("rb") as f:
            titles = [f.readline().rstrip(b"\n").decode("utf-8") for _ in range(n)]
        chunks = [
            (start, titles[start:start + CHUNK_SIZE])
            for start in range(0, n, CHUNK_SIZE)
        ]

        _PARENT_MAP = title_to_index
        with REFERENCE_FILE.open("wb") as idx:
            bar = step_tqdm(
                range(n),
                step=1,
                total_steps=1,
                desc="Building reference map",
                unit="titles",
            )
            with bar:
                if workers <= 1:
                    # In-process path (testable, no fork): use the module archive.
                    for start, chunk_titles in chunks:
                        for offset, title in enumerate(chunk_titles):
                            refs = _refs_for(WIKI_ARCHIVE, title, title_to_index)
                            idx.write(_pack_record(start + offset, refs))
                            bar.update(1)
                else:
                    with Pool(workers, initializer=_worker_init) as pool:
                        for (_, chunk_titles), packed in zip(
                            chunks, pool.imap(_process_chunk, chunks)
                        ):
                            idx.write(packed)
                            bar.update(len(chunk_titles))
    except OSError as e:
        print(f"Could not build reference map: {e}")
        return False

    return True


def index_all_data(force: bool = False) -> bool:
    if not force:
        confirm = input("Are you sure you want to re-index all data? (y/n): ")
        if not confirm or confirm[0].lower() != "y":
            return False

    steps = [
        ("remove_old_data", remove_old_data),
        ("create_title_list", create_title_list),
        ("index_titles", index_titles),
        ("build_reference_map", build_reference_map),
    ]

    with tqdm(
        total=len(steps),
        desc="Pipeline",
        unit="fn",
        ncols=100,
        bar_format="{n_fmt}/{total_fmt} total steps completed",
    ) as pipeline:
        for name, fn in steps:
            pipeline.set_postfix_str(name)
            if not fn():
                return False
            pipeline.update(1)

    return True


if __name__ == "__main__":
    build_reference_map()