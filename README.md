# Wiki-Insights

Tools for building searchable indexes from offline English Wikipedia ZIM archives.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Place a Wikipedia ZIM file under `wikipedia_dump/` (see `src/build_index_files.py` for the expected filename), then run the indexing scripts in `src/`.

## Project layout

- `src/build_index_files.py` — extract titles from a ZIM archive and build index files
- `src/indexing.py` — title normalization, sorting, and reference indexing utilities
- `data/` — generated index artifacts (not committed)
- `wikipedia_dump/` — local ZIM archives (not committed)
