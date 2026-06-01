import struct
from unittest.mock import MagicMock, patch

import src.build_index_files as bif


def _make_entry(html: str) -> MagicMock:
    item = MagicMock()
    item.content = html.encode()
    entry = MagicMock()
    entry.get_item.return_value = item
    return entry


def _decode_records(raw: bytes) -> list[tuple[int, list[int]]]:
    records, pos = [], 0
    while pos < len(raw):
        source, count = struct.unpack_from("<II", raw, pos)
        pos += 8
        refs = list(struct.unpack_from(f"<{count}I", raw, pos)) if count else []
        pos += 4 * count
        records.append((source, refs))
    return records


class TestTitleFromPath:

    def test_underscores_become_spaces(self):
        assert bif.title_from_path("Barack_Obama") == "Barack Obama"

    def test_url_decoded(self):
        assert bif.title_from_path("Rock_%26_roll") == "Rock & roll"

    def test_plain_title_unchanged(self):
        assert bif.title_from_path("Target") == "Target"


class TestParseReferencePaths:

    def test_strips_query_and_anchor_and_dot_prefix(self):
        html = b'<a href="./Foo_Bar?x=1#sec">f</a> <a href="./Baz">b</a>'
        assert bif._parse_reference_paths(html) == {"Foo Bar", "Baz"}

    def test_drops_empty_hrefs(self):
        html = b'<a href="#sec">anchor only</a> <a href="">empty</a>'
        assert bif._parse_reference_paths(html) == set()

    def test_url_decoding(self):
        assert bif._parse_reference_paths(b'<a href="./Rock_%26_roll">r</a>') == {"Rock & roll"}

    def test_accepts_str_input(self):
        assert bif._parse_reference_paths('<a href="./Foo">f</a>') == {"Foo"}


class TestBuildReferenceMap:

    def test_writes_packed_records(self, tmp_path):
        titles = ["Apple", "Banana", "Cherry"]
        title_to_index = {t: i for i, t in enumerate(titles)}
        pages = {
            "Apple": '<a href="./Banana">b</a> <a href="./Cherry">c</a>',
            "Banana": '<a href="./Apple">a</a> <a href="./Missing">m</a>',
            "Cherry": "<p>no links</p>",
        }
        ref_file = tmp_path / "references.idx"

        with (
            patch.object(bif, "REFERENCE_FILE", ref_file),
            patch.object(bif, "title_line_count", return_value=len(titles)),
            patch.object(bif, "_load_title_index_map", return_value=title_to_index),
            patch.object(
                bif.WIKI_ARCHIVE,
                "get_entry_by_title",
                side_effect=lambda t: _make_entry(pages[t]),
            ),
            patch.object(bif, "TITLE_FILE") as title_file,
        ):
            # Sequential line reads of the title file.
            lines = iter(t.encode() + b"\n" for t in titles)
            handle = title_file.open.return_value.__enter__.return_value
            handle.readline.side_effect = lambda: next(lines, b"")

            assert bif.build_reference_map(workers=1) is True

        records = _decode_records(ref_file.read_bytes())
        assert [src for src, _ in records] == [0, 1, 2]
        assert sorted(records[0][1]) == [1, 2]   # Apple -> Banana, Cherry
        assert records[1][1] == [0]              # Banana -> Apple (Missing dropped)
        assert records[2][1] == []               # Cherry -> none
