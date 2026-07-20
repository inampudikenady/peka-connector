import os
import tempfile
from pathlib import Path

os.environ.setdefault("PEKA_JWT_SECRET", "test-secret-that-is-at-least-thirty-two-characters")
os.environ.setdefault(
    "PEKA_ENCRYPTION_KEY", "test-encryption-key-that-is-at-least-thirty-two-characters"
)
test_root = Path(tempfile.mkdtemp(prefix="peka-connector-tests-"))
(test_root / "sources").mkdir()
os.environ.setdefault("PEKA_DATA_ROOT", str(test_root / "data"))
os.environ.setdefault("PEKA_SOURCES_ROOT", str(test_root / "sources"))
os.environ.setdefault(
    "PEKA_DATABASE_URL", f"sqlite+aiosqlite:///{test_root / 'data' / 'state' / 'peka.db'}"
)
os.environ.setdefault("PEKA_BOOTSTRAP_ADMIN_USERNAME", "")
os.environ.setdefault("PEKA_BOOTSTRAP_ADMIN_PASSWORD", "")
