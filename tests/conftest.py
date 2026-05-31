import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

# Patch libzim.reader.Archive before src.build_index_files is imported so
# the module-level Archive("...zim") call doesn't fail without the real file.
try:
    import libzim.reader as _lzr
    _lzr.Archive = MagicMock(return_value=MagicMock(name="wiki_archive"))
except ImportError:
    _stub = MagicMock()
    sys.modules["libzim"] = _stub
    sys.modules["libzim.reader"] = _stub.reader
