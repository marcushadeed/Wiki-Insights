import functools
import json
import struct
import unicodedata
import os
from pathlib import Path
from urllib.parse import unquote

import anyascii
from libzim.reader import Archive
from mwtp import TitleParser
from mwtp.exceptions import InvalidTitle
from mwtp.namespace import Namespace

BACKUP_FILE = Path(__file__).resolve().parent.parent / "data/backup_titles.txt"
INDEX_FILE = Path(__file__).resolve().parent.parent / "data/index.idx"
SORTED_FILE = Path(__file__).resolve().parent.parent / "data/sorted_titles.txt"
REFERENCES_FILE = Path(__file__).resolve().parent.parent / "data/references.idx"
SITEINFO_JSON = Path(__file__).resolve().parent.parent / "data/enwiki_siteinfo_namespaces.json"


def normalize_title(title: str) -> bytes:
    return unicodedata.normalize("NFC", title).encode("utf-8")


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s.strip())


def _ascii_fold(s: str) -> str:
    return _nfc(anyascii.anyascii(s))


def _canonical_underlined(parsed) -> str:
    page = parsed.name.replace(" ", "_")
    if parsed.namespace == Namespace.MAIN:
        return page
    ns_head = parsed.namespace_data.name.replace(" ", "_")
    return f"{ns_head}:{page}"


def _api_namespaces_to_mwtp_config(
    namespaces: dict, alias_rows: list
) -> tuple[dict[str, dict], list[dict[str, int | str]]]:
    namespace_data: dict[str, dict] = {}
    for _, entry in namespaces.items():
        nid = entry["id"]
        star = entry.get("*", "") or ""
        row = {
            "id": nid,
            "case": entry["case"],
            "name": star,
            "subpages": "subpages" in entry,
            "content": nid == 0 or "content" in entry,
            "nonincludable": bool(entry.get("nonincludable", False)),
        }
        if "canonical" in entry:
            row["canonical"] = entry["canonical"]
        for k in ("namespaceprotection", "defaultcontentmodel"):
            if k in entry:
                row[k] = entry[k]
        namespace_data[str(nid)] = row

    alias_entries = [{"id": a["id"], "alias": a["*"]} for a in alias_rows]
    return namespace_data, alias_entries


@functools.cache
def _title_parser() -> TitleParser:
    data = json.loads(SITEINFO_JSON.read_text(encoding="utf-8"))
    ns, aliases = _api_namespaces_to_mwtp_config(
        data["query"]["namespaces"], data["query"]["namespacealiases"]
    )
    return TitleParser(ns, aliases)


def _lookup_variants(title_fragment: str) -> list[str]:
    base = _nfc(title_fragment)

    canonical: str | None = None
    try:
        canonical = _canonical_underlined(_title_parser().parse(base))
    except InvalidTitle:
        pass

    out: list[str] = []

    def add(s: str | None) -> None:
        if s is None or s == "":
            return
        if s not in out:
            out.append(s)

    add(base)
    add(canonical)

    fb = _ascii_fold(base)
    add(fb)

    if canonical is not None:
        add(_ascii_fold(canonical))

    return out


def re_index():
    confirm = input("Are you sure you want to re-index the wiki titles? (y/n): ")
    if confirm != "y":
        return

    # Remove old index and sorted files
    try:
        if INDEX_FILE.exists():
            INDEX_FILE.unlink()
        if SORTED_FILE.exists():
            SORTED_FILE.unlink()
    except OSError as e:
        print(f"Could not remove old index files: {e}")
        return

    # Read the backup file and sort the titles
    try:
        with BACKUP_FILE.open("rb") as f, SORTED_FILE.open("wb") as srt:
            lines = f.readlines()

            lines.sort(key=lambda x: normalize_title(x.decode().strip()))
            srt.writelines(lines)
    except OSError as e:
        print(f"Could not read backup or write sorted file: {e}")
        return
    except UnicodeError as e:
        print(f"Invalid UTF-8 in backup titles: {e}")
        return

    # Recreate the index
    try:
        with SORTED_FILE.open("rb") as f, INDEX_FILE.open("wb") as idx:
            offset = 0
            while True:
                idx.write(struct.pack("<q", offset))
                line = f.readline()
                if not line:
                    break
                offset = f.tell()
    except OSError as e:
        print(f"Could not build index file: {e}")
        return

    print("Index created successfully")


def get_title(n: int) -> str | None:
    try:
        with INDEX_FILE.open("rb") as idx, SORTED_FILE.open("rb") as srt:
            idx.seek(n * 8)
            raw = idx.read(8)
            if len(raw) != 8:
                return None
            offset = struct.unpack("<q", raw)[0]
            srt.seek(offset)
            return srt.readline().decode().strip()
    except OSError as e:
        print(f"get_title: I/O error: {e}")
        return None
    except (struct.error, UnicodeError) as e:
        print(f"get_title: corrupt data: {e}")
        return None


def _binary_search(target: bytes) -> int | None:
    try:
        with INDEX_FILE.open("rb") as idx, SORTED_FILE.open("rb") as srt:
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
                srt.seek(offset)
                line = srt.readline().rstrip(b"\n")

                if line == target:
                    return mid
                if line < target:
                    lo = mid + 1
                else:
                    hi = mid - 1
    except OSError as e:
        print(f"get_index: I/O error: {e}")
        return None
    except (struct.error, UnicodeError) as e:
        print(f"get_index: corrupt data: {e}")
        return None

    return None


def get_index(title: str) -> int | None:
    for variant in _lookup_variants(title):
        found = _binary_search(normalize_title(variant))
        if found is not None:
            return found
    return None


def get_reference_indices(title_index: int) -> set[int]:
    if title_index is None:
        return set()

    # Grab the html
    zim = Archive("wikipedia_dump/wikipedia_en_all_nopic_2026-03.zim")
    entry = zim.get_entry_by_path(f"A/{get_title(title_index)}")
    content = bytes(entry.get_item().content).decode("utf-8")

    lines = content.splitlines()

    # Find each href and get the index
    references = set()
    for line in lines:
        if "<a href=" in line:
            href = line.split("<a href=\"")[1].split("\"")[0]
            raw = unquote(href.split("?", 1)[0].split("#", 1)[0])
            if raw.startswith("./"):
                raw = raw[2:]

            if not raw:
                continue

            index = get_index(raw)

            if index is not None:
                references.add(index)
            else:
                print(f"No index found for title: {raw}")

    return references


def re_index_references():
    confirm = input("Are you sure you want to re-index the references? (y/n): ")
    if confirm != "y":
        return

    # Remove old references index file
    if REFERENCES_FILE.exists():
        REFERENCES_FILE.unlink()

    # For each title, get the indices for each referenced title and store them
    with (
        SORTED_FILE.open("rb") as f,
        INDEX_FILE.open("r+b") as idx,
        REFERENCES_FILE.open("wb") as references_index,
    ):
        # Store the index list for each reference and save the offset in a table at the front
        idx.seek(0, 2)
        index_bytes = idx.tell()
        # Write zeros to reserve space for offset values (one per line in sorted file) more efficiently
        num_titles = index_bytes // 8
        references_index.write(b"\x00" * (8 * num_titles))

        # Write the index list for each reference
        for i, line in enumerate(f, start=1):
            title = line.decode().strip()
            title_index = get_index(title)

            if title_index is None:
                print(f"Skipping unknown title in sorted file: {title!r}")
                continue

            references = get_reference_indices(title_index)
            reference_list_start = references_index.tell()

            if references:
                for index in references:
                    references_index.write(struct.pack("<q", index))
            references_index.write(struct.pack("<q", -1))

            # Write the offset to the offset table
            idx.seek(title_index * 8)
            idx.write(struct.pack("<q", reference_list_start))
            idx.seek(0, 2)

            if i % 100000 == 0:
                print(f"Processed {i:,} titles ({(i / num_titles) * 100:.2f}%)")


if __name__ == "__main__":
    import time
    import random

    start_time = time.time()

    for _ in range(1000):
        title_index = random.randint(0, 10000000)
        print(f"Title index: {title_index}")
        references = get_reference_indices(title_index)

    print(f"Time taken: {time.time() - start_time:.2f} seconds")