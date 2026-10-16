import os
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE_DIR = os.path.join(ROOT_DIR, "wass_webapp", "workspace")
SEQ_META_PATH = os.path.join(WORKSPACE_DIR, "sequence", "sequence_meta.json")


@pytest.fixture(autouse=True)
def preserve_sequence_meta():
    """Safety fixture: ensures sequence_meta.json remains intact across all test runs."""
    original_meta = None
    if os.path.exists(SEQ_META_PATH):
        try:
            with open(SEQ_META_PATH, "r", encoding="utf-8") as f:
                original_meta = f.read()
        except Exception:
            pass

    yield

    if original_meta is not None:
        try:
            with open(SEQ_META_PATH, "r", encoding="utf-8") as f:
                current_meta = f.read()
            if current_meta != original_meta:
                with open(SEQ_META_PATH, "w", encoding="utf-8") as f:
                    f.write(original_meta)
        except Exception:
            pass
