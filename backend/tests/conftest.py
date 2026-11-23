import os
import sys
import tempfile
from pathlib import Path

# Must be set before the app is imported.
_tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = str(Path(_tmp) / "test.db")
os.environ["DEMO_WORD_DELAY"] = "0"
os.environ["FRONTEND_DIST"] = str(Path(_tmp) / "no-dist")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from app import db  # noqa: E402
from app.auth import COOKIE_NAME, create_session_token, hash_password  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    db.init()
    user = db.get_user_by_username("testuser")
    if not user:
        user = db.create_user("testuser", hash_password("testpassword123"))
    token = create_session_token(user["id"], user["username"])
    for name, mod in list(sys.modules.items()):
        if name.startswith("tests.") or name.startswith("test_") or "test" in name:
            if hasattr(mod, "client") and isinstance(getattr(mod, "client"), TestClient):
                getattr(mod, "client").cookies[COOKIE_NAME] = token
    yield
