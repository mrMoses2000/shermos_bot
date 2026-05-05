import pytest
from fastapi.testclient import TestClient
from src.api.app import app
from src.api.auth import create_access_token
from tests.helpers import FakePool


def _auth_headers() -> dict:
    token = create_access_token({"sub": "test-manager", "type": "access"})
    return {"Authorization": f"Bearer {token}"}

client = TestClient(app)

PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000b4944415408d7636000020000050001e226059b0000000049454e44"
    "ae426082"
)

@pytest.fixture
def fake_pool():
    pool = FakePool([])
    
    # Wait, we need to override get_pool in the router, not the global dependencies if it's there.
    # Actually it's easier to mock get_pool directly.
    from src.api.deps import get_pool
    app.dependency_overrides[get_pool] = lambda: pool
    yield pool
    app.dependency_overrides.clear()

def test_auth_required():
    res = client.get("/api/gallery/works")
    assert res.status_code == 401

def test_create_work(fake_pool):
    fake_pool.results = [{"id": "w1", "partition_type": "fixed", "title": "Test"}]
    res = client.post(
        "/api/gallery/works",
        headers=_auth_headers(),
        json={"partition_type": "fixed", "title": "Test"}
    )
    assert res.status_code == 200
    assert res.json()["id"] == "w1"

def test_create_work_with_jwt_auth(fake_pool):
    fake_pool.results = [{"id": "w1", "partition_type": "fixed", "title": ""}]
    res = client.post(
        "/api/gallery/works",
        headers=_auth_headers(),
        json={"partition_type": "fixed"},
    )
    assert res.status_code == 200

def test_upload_photos(fake_pool, tmp_path, monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "gallery_dir", str(tmp_path))
    
    fake_pool.results = [
        {"id": "w1", "partition_type": "fixed", "photos": []}, # get_gallery_work fetchrow
        [], # get_gallery_work fetch
        {"id": "p1", "file_path": "w1/p1.png"}, # add_gallery_photo
        {"id": "p2", "file_path": "w1/p2.png"}  # add_gallery_photo
    ]
    
    res = client.post(
        "/api/gallery/works/w1/photos",
        headers=_auth_headers(),
        files=[
            ("files", ("test1.png", PNG_1x1, "image/png")),
            ("files", ("test2.png", PNG_1x1, "image/png"))
        ]
    )
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 2
    assert len(list(tmp_path.glob("w1/*.png"))) == 2

def test_upload_invalid_format(fake_pool):
    fake_pool.results = [{"id": "w1", "partition_type": "fixed", "photos": []}]
    res = client.post(
        "/api/gallery/works/w1/photos",
        headers=_auth_headers(),
        files=[("files", ("test.txt", b"not an image", "text/plain"))]
    )
    assert res.status_code == 400
    assert "Неподдерживаемый формат" in res.json()["detail"]

def test_upload_oversize(fake_pool, monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "gallery_photo_max_bytes", 10)
    fake_pool.results = [{"id": "w1", "partition_type": "fixed", "photos": []}]
    res = client.post(
        "/api/gallery/works/w1/photos",
        headers=_auth_headers(),
        files=[("files", ("test.png", PNG_1x1, "image/png"))]
    )
    assert res.status_code == 413
    assert "слишком большой" in res.json()["detail"]


@pytest.mark.asyncio
async def test_upload_oversize_declared_size(monkeypatch):
    """Reject immediately when UploadFile.size > limit, before streaming body."""
    import io
    from fastapi import UploadFile, HTTPException
    from starlette.datastructures import Headers
    from src.config import settings
    from src.api.routes_gallery import upload_photos
    from tests.helpers import FakePool

    monkeypatch.setattr(settings, "gallery_photo_max_bytes", 10)

    # Craft an UploadFile whose .size is already over the limit.
    # The route should raise 413 before ever calling file.read().
    big_upload = UploadFile(
        file=io.BytesIO(PNG_1x1),
        size=9999,  # declared > limit of 10
        filename="big.png",
        headers=Headers({"content-type": "image/png"}),
    )

    # get_gallery_work does fetchrow + fetch, so provide both results
    fake_pool = FakePool([
        {"id": "w1", "partition_type": "fixed"},  # fetchrow for work
        [],  # fetch for photos
    ])

    try:
        await upload_photos("w1", files=[big_upload], pool=fake_pool)
        assert False, "Expected HTTPException 413"
    except HTTPException as exc:
        assert exc.status_code == 413
        assert "слишком большой" in exc.detail


def test_upload_decompression_bomb(fake_pool, monkeypatch):
    """Upload of a pixel-bomb image returns 400 (decompression bomb)."""
    from PIL import Image as PILImage
    import src.api.routes_gallery as gallery_mod

    fake_pool.results = [{"id": "w1", "partition_type": "fixed", "photos": []}]

    original_open = PILImage.open

    def fake_open(fp, *args, **kwargs):
        raise PILImage.DecompressionBombError("too big")

    monkeypatch.setattr(gallery_mod.Image, "open", fake_open)

    res = client.post(
        "/api/gallery/works/w1/photos",
        headers=_auth_headers(),
        files=[("files", ("test.png", PNG_1x1, "image/png"))]
    )
    assert res.status_code == 400
    assert "decompression bomb" in res.json()["detail"]


def test_upload_mime_not_in_allowlist(fake_pool):
    """Content-Type not in ALLOWED_MIME is rejected with 400 before body is read."""
    fake_pool.results = [{"id": "w1", "partition_type": "fixed", "photos": []}]
    res = client.post(
        "/api/gallery/works/w1/photos",
        headers=_auth_headers(),
        files=[("files", ("shell.sh", b"#!/bin/bash\nrm -rf /", "application/x-sh"))]
    )
    assert res.status_code == 400
    assert "Неподдерживаемый формат" in res.json()["detail"]

def test_get_work(fake_pool):
    fake_pool.results = [
        {"id": "w1", "partition_type": "fixed"},
        [{"file_path": "foo.png"}]
    ]
    res = client.get(
        "/api/gallery/works/w1",
        headers=_auth_headers()
    )
    assert res.status_code == 200
    assert res.json()["id"] == "w1"
    assert res.json()["photos"][0]["url"] == "/gallery/foo.png"

def test_update_work(fake_pool):
    fake_pool.results = [{"id": "w1", "is_published": False}]
    res = client.patch(
        "/api/gallery/works/w1",
        headers=_auth_headers(),
        json={"is_published": False}
    )
    assert res.status_code == 200
    assert res.json()["is_published"] is False

def test_delete_work(fake_pool, tmp_path, monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "gallery_dir", str(tmp_path))
    (tmp_path / "w1").mkdir(parents=True)
    f = tmp_path / "w1/test.png"
    f.write_bytes(PNG_1x1)

    # Call sequence: get_gallery_work (fetchrow + fetch), delete_gallery_work (fetch + fetchrow)
    fake_pool.results = [
        {"id": "w1", "partition_type": "fixed"},   # get_gallery_work fetchrow
        [{"file_path": "w1/test.png"}],            # get_gallery_work fetch (photos)
        [{"file_path": "w1/test.png"}],            # delete_gallery_work list_photos_for_work fetch
        {"id": "w1"},                              # delete_gallery_work DELETE fetchrow
    ]
    res = client.delete(
        "/api/gallery/works/w1",
        headers=_auth_headers()
    )
    assert res.status_code == 200
    assert not f.exists()
    assert not (tmp_path / "w1").exists()


def test_delete_work_file_unlink_fails_returns_500(fake_pool, tmp_path, monkeypatch):
    """If any file unlink fails during delete_work, return 500 and do NOT delete from DB."""
    from src.config import settings
    from pathlib import Path
    monkeypatch.setattr(settings, "gallery_dir", str(tmp_path))
    (tmp_path / "w1").mkdir(parents=True)

    # Two photos; we'll make the first unlink raise OSError
    fake_pool.results = [
        {"id": "w1", "partition_type": "fixed"},          # get_gallery_work fetchrow
        [                                                   # get_gallery_work fetch (photos)
            {"file_path": "w1/a.png"},
            {"file_path": "w1/b.png"},
        ],
        # delete_gallery_work should NOT be called — no further results needed
    ]

    original_unlink = Path.unlink

    def failing_unlink(self, missing_ok=False):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    res = client.delete(
        "/api/gallery/works/w1",
        headers=_auth_headers()
    )
    assert res.status_code == 500
    # No DELETE call should have been made to the DB
    delete_calls = [c for c in fake_pool.calls if "DELETE FROM gallery_works" in c[1]]
    assert len(delete_calls) == 0


def test_delete_photo(fake_pool, tmp_path, monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "gallery_dir", str(tmp_path))
    (tmp_path / "w1").mkdir(parents=True)
    f = tmp_path / "w1/test.png"
    f.write_bytes(PNG_1x1)

    # Call sequence: get_gallery_photo (fetchrow) then delete_gallery_photo (fetchrow)
    fake_pool.results = [
        {"id": "p1", "file_path": "w1/test.png"},  # get_gallery_photo
        {"id": "p1", "file_path": "w1/test.png"},  # delete_gallery_photo
    ]
    res = client.delete(
        "/api/gallery/photos/p1",
        headers=_auth_headers()
    )
    assert res.status_code == 200
    assert not f.exists()

    # Missing photo → 404
    fake_pool.results = [None]
    res = client.delete(
        "/api/gallery/photos/missing",
        headers=_auth_headers()
    )
    assert res.status_code == 404


def test_delete_photo_file_unlink_fails_returns_500(fake_pool, tmp_path, monkeypatch):
    """If file unlink fails, return 500 and do NOT call delete_gallery_photo."""
    from src.config import settings
    from pathlib import Path
    monkeypatch.setattr(settings, "gallery_dir", str(tmp_path))
    (tmp_path / "w1").mkdir(parents=True)
    (tmp_path / "w1" / "test.png").write_bytes(PNG_1x1)

    fake_pool.results = [
        {"id": "p1", "file_path": "w1/test.png"},  # get_gallery_photo
        # delete_gallery_photo should NOT be called
    ]

    original_unlink = Path.unlink

    def failing_unlink(self, missing_ok=False):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    res = client.delete(
        "/api/gallery/photos/p1",
        headers=_auth_headers()
    )
    assert res.status_code == 500
    # Confirm delete_gallery_photo was not called (no DELETE query in pool calls)
    delete_calls = [c for c in fake_pool.calls if "DELETE FROM gallery_photos" in c[1]]
    assert len(delete_calls) == 0