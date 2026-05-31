from libzim.reader import Archive
from pathlib import Path
from tqdm import tqdm
import struct
from urllib.parse import quote

WIKI_ARCHIVE = Archive("wikipedia_dump/wikipedia_en_all_nopic_2026-03.zim")

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


def get_reference_indices(index: int) -> list[int]:
    if index is None:
        return []

    entry = WIKI_ARCHIVE.get_entry_by_title(get_title(index))
    content = bytes(entry.get_item().content).decode("utf-8")
    references = set()
    rest = content
    while '<a href="' in rest:
        _, after = rest.split('<a href="', 1)
        href, rest = after.split('"', 1)
        raw = href.split("?", 1)[0].split("#", 1)[0]
        if raw.startswith("./"):
            raw = raw[2:]
        if not raw:
            continue
        ref_index = get_index(raw)
        if ref_index is not None:
            references.add(ref_index)
    return list(references)


def build_reference_map() -> bool:
    try:
        title_count = title_line_count()
        with TITLE_FILE.open("rb") as f, REFERENCE_FILE.open("wb") as idx:
            for _ in step_tqdm(
                range(title_count),
                step=1,
                total_steps=1,
                desc="Building reference map",
                unit="titles",
            ):
                line = f.readline()
                if not line:
                    break
                # TODO: Build the reference map
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
