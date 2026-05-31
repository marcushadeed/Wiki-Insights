from unittest.mock import MagicMock, patch

import src.build_index_files as bif


def _make_entry(html: str) -> MagicMock:
    item = MagicMock()
    item.content = html.encode()
    entry = MagicMock()
    entry.get_item.return_value = item
    return entry


class TestGetReferenceIndices:

    def test_none_index_returns_empty(self):
        assert bif.get_reference_indices(None) == []

    def test_no_links_returns_empty(self):
        with (
            patch.object(bif.WIKI_ARCHIVE, "get_entry_by_title", return_value=_make_entry("<p>No links.</p>")),
            patch("src.build_index_files.get_title", return_value="Article"),
            patch("src.build_index_files.get_index", return_value=None),
        ):
            assert bif.get_reference_indices(0) == []

    def test_resolves_relative_link(self):
        with (
            patch.object(bif.WIKI_ARCHIVE, "get_entry_by_title", return_value=_make_entry('<a href="./Target">link</a>')),
            patch("src.build_index_files.get_title", return_value="Source"),
            patch("src.build_index_files.get_index", side_effect=lambda t: 7 if t == "Target" else None),
        ):
            assert bif.get_reference_indices(0) == [7]

    def test_strips_anchor(self):
        with (
            patch.object(bif.WIKI_ARCHIVE, "get_entry_by_title", return_value=_make_entry('<a href="./Target#Section">link</a>')),
            patch("src.build_index_files.get_title", return_value="Source"),
            patch("src.build_index_files.get_index", side_effect=lambda t: 3 if t == "Target" else None),
        ):
            assert bif.get_reference_indices(0) == [3]

    def test_strips_query_params(self):
        with (
            patch.object(bif.WIKI_ARCHIVE, "get_entry_by_title", return_value=_make_entry('<a href="./Target?action=edit">link</a>')),
            patch("src.build_index_files.get_title", return_value="Source"),
            patch("src.build_index_files.get_index", side_effect=lambda t: 5 if t == "Target" else None),
        ):
            assert bif.get_reference_indices(0) == [5]

    def test_strips_query_and_anchor(self):
        with (
            patch.object(bif.WIKI_ARCHIVE, "get_entry_by_title", return_value=_make_entry('<a href="./Target?action=edit#Section">link</a>')),
            patch("src.build_index_files.get_title", return_value="Source"),
            patch("src.build_index_files.get_index", side_effect=lambda t: 9 if t == "Target" else None),
        ):
            assert bif.get_reference_indices(0) == [9]

    def test_deduplicates_repeated_links(self):
        html = '<a href="./Target">a</a> <a href="./Target">b</a>'
        with (
            patch.object(bif.WIKI_ARCHIVE, "get_entry_by_title", return_value=_make_entry(html)),
            patch("src.build_index_files.get_title", return_value="Source"),
            patch("src.build_index_files.get_index", return_value=11),
        ):
            assert bif.get_reference_indices(0) == [11]

    def test_unresolved_link_excluded(self):
        with (
            patch.object(bif.WIKI_ARCHIVE, "get_entry_by_title", return_value=_make_entry('<a href="./Missing">link</a>')),
            patch("src.build_index_files.get_title", return_value="Source"),
            patch("src.build_index_files.get_index", return_value=None),
        ):
            assert bif.get_reference_indices(0) == []

    def test_anchor_only_href_skipped(self):
        with (
            patch.object(bif.WIKI_ARCHIVE, "get_entry_by_title", return_value=_make_entry('<a href="#Section">link</a>')),
            patch("src.build_index_files.get_title", return_value="Source"),
            patch("src.build_index_files.get_index", return_value=None),
        ):
            assert bif.get_reference_indices(0) == []

    def test_multiple_links_same_line_all_resolved(self):
        html = '<p><a href="./A">a</a> and <a href="./B">b</a> and <a href="./C">c</a></p>'
        index_map = {"A": 1, "B": 2, "C": 3}
        with (
            patch.object(bif.WIKI_ARCHIVE, "get_entry_by_title", return_value=_make_entry(html)),
            patch("src.build_index_files.get_title", return_value="Source"),
            patch("src.build_index_files.get_index", side_effect=index_map.get),
        ):
            assert sorted(bif.get_reference_indices(0)) == [1, 2, 3]
