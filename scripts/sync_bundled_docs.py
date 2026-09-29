"""Copy the docs `zook guide` prints into the package (src/zook/data/guide/).

The repository copies are the ones people edit; a wheel only carries what is
inside the package, so each is mirrored byte-for-byte (tests/test_bundled_data.py
fails when a copy is stale). Run after editing any of them:

    python scripts/sync_bundled_docs.py
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from zook.guide import BUNDLED_DOCS  # noqa: E402

for bundled, source in BUNDLED_DOCS.items():
    shutil.copyfile(ROOT / source, ROOT / "src" / "zook" / "data" / "guide" / bundled)
    print(f"{source} -> src/zook/data/guide/{bundled}")
