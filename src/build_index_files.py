from libzim.reader import Archive
from pathlib import Path
from tqdm import tqdm
import struct
from urllib.parse import quote

WIKI_ARCHIVE = Archive("wikipedia_dump/wikipedia_en_all_nopic_2026-03.zim")

TITLE_FILE = Path(__file__).resolve().parent.parent / "data/wiki_titles.txt"
INDEX_FILE = Path(__file__).resolve().parent.parent / "data/titles_index.idx"
REFERENCE_FILE = Path(__file__).resolve().parent.parent / "data/references.idx"

def create_title_list() -> bool:
    print("Creating title list...")

    # Get the titles from the zim file
    print("Retrieving titles from zim file...")
    titles = []
    for i in tqdm(range(WIKI_ARCHIVE.all_entry_count), ncols=100, unit=" entries", bar_format="{bar:10} | {n_fmt}/{total_fmt} | {percentage:3.1f}%", desc="Processing entries"):
        entry = WIKI_ARCHIVE._get_entry_by_id(i)

        if entry.is_redirect:
            continue
        item = entry.get_item()
        if "text/html" not in item.mimetype:
            continue

        if entry.title is not None:
            titles.append(entry.title)
    
    # Sort the titles
    print("Sorting titles...")
    titles.sort()

    # Write the titles to a file
    print("Writing titles to file...")
    with open(TITLE_FILE, "w") as f:
        for title in titles:
            f.write(title + "\n")

    print("Title list created successfully")
    return True

def index_titles() -> bool:
    print("Indexing titles...")

    # Get title count
    title_count = sum(1 for _ in TITLE_FILE.open("rb"))

    # Build the index
    try:
        with TITLE_FILE.open("rb") as f, INDEX_FILE.open("wb") as idx:
            offset = 0
            progress_bar = tqdm(
                range(title_count),
                ncols=100,
                unit=" titles",
                bar_format="{bar:10} | {n_fmt}/{total_fmt} | {percentage:3.1f}%",
                desc="Indexing titles"
            )
            
            for _ in progress_bar:
                idx.write(struct.pack("<q", offset))
                line = f.readline()
                if not line:
                    break
                offset = f.tell()
    except OSError as e:
        print(f"Could not build index file: {e}")
        return False
    
    print("Titles indexed successfully")
    return True

def remove_old_data() -> bool:
    print("Removing old data...")
    try:
        for file in [TITLE_FILE, INDEX_FILE]:
            if file.exists():
                file.unlink()
    except OSError as e:
        print(f"Could not remove old data: {e}")
        return False

    print("Old data removed successfully")
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

def path_from_title(title: str) -> str:
    slug = title.replace(' ', '_')
    # Wikipedia keeps these chars unencoded in article paths
    encoded = quote(slug, safe="(),-._~!*':@")
    return f"A/{encoded}"

def get_reference_indices(index: int) -> list[int]:
    if index is None:
        return []

    entry = WIKI_ARCHIVE.get_entry_by_path(path_from_title(get_title(index)))
    content = bytes(entry.get_item().content).decode("utf-8")
    lines = content.splitlines()
    references = set()
    for line in lines:
        if "<a href=" in line:
            href = line.split("<a href=\"")[1].split("\"")[0]
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
    print("Building reference map...")

    # Get title count
    title_count = sum(1 for _ in TITLE_FILE.open("rb"))

    try:
        with TITLE_FILE.open("rb") as f, REFERENCE_FILE.open("wb") as idx:
            offset = 0
            progress_bar = tqdm(
                range(title_count),
                ncols=100,
                unit=" titles",
                bar_format="{bar:10} | {n_fmt}/{total_fmt} | {percentage:3.1f}%",
                desc="Building reference map"
            )

            for _ in progress_bar:
                _ = 1
                # mph TODO: Build the reference map
                
    except OSError as e:
        print(f"Could not build reference map: {e}")
        return False

    print("Reference map built successfully")
    return True

def index_all_data(force: bool = False) -> bool:
    if not force:
        confirm = input("Are you sure you want to re-index all data? (y/n): ")
        if not confirm or confirm[0].lower() != "y":
            return False
    
    if not remove_old_data():
        return False

    if not create_title_list():
        return False

    if not index_titles():
        return False

    if not build_reference_map():
        return False

    print("All data indexed successfully!")
    return True

if __name__ == "__main__":
    index_all_data(force=True)
    # print(get_reference_indices(500000))