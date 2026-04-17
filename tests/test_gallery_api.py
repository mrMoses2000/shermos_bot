import pytest
from fastapi.testclient import TestClient
from src.api.app import app
from tests.helpers import signed_init_data, FakePool

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
        headers={"X-Telegram-Init-Data": signed_init_data()},
        json={"partition_type": "fixed", "title": "Test"}
    )
    assert res.status_code == 200
    assert res.json()["id"] == "w1"

def test_create_work_captures_chat_id(fake_pool):
    fake_pool.results = [{"id": "w1", "partition_type": "fixed", "title": ""}]
    init_data = signed_init_data(user='{"id": 777, "first_name": "M"}')
    res = client.post(
        "/api/gallery/works",
        headers={"X-Telegram-Init-Data": init_data},
        json={"partition_type": "fixed"},
    )
    assert res.status_code == 200
    insert_call = next(c for c in fake_pool.calls if "INSERT INTO gallery_works" in c[1])
    assert 777 in insert_call[2]

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
        headers={"X-Telegram-Init-Data": signed_init_data()},
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
        headers={"X-Telegram-Init-Data": signed_init_data()},
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
        headers={"X-Telegram-Init-Data": signed_init_data()},
        files=[("files", ("test.png", PNG_1x1, "image/png"))]
    )
    assert res.status_code == 400
    assert "слишком большой" in res.json()["detail"]

def test_get_work(fake_pool):
    fake_pool.results = [
        {"id": "w1", "partition_type": "fixed"},
        [{"file_path": "foo.png"}]
    ]
    res = client.get(
        "/api/gallery/works/w1",
        headers={"X-Telegram-Init-Data": signed_init_data()}
    )
    assert res.status_code == 200
    assert res.json()["id"] == "w1"
    assert res.json()["photos"][0]["url"] == "/gallery/foo.png"

def test_update_work(fake_pool):
    fake_pool.results = [{"id": "w1", "is_published": False}]
    res = client.patch(
        "/api/gallery/works/w1",
        headers={"X-Telegram-Init-Data": signed_init_data()},
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
    
    fake_pool.results = [
        [{"file_path": "w1/test.png"}],
        {"id": "w1"}
    ]
    res = client.delete(
        "/api/gallery/works/w1",
        headers={"X-Telegram-Init-Data": signed_init_data()}
    )
    assert res.status_code == 200
    assert not f.exists()
    assert not (tmp_path / "w1").exists()

def test_delete_photo(fake_pool, tmp_path, monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "gallery_dir", str(tmp_path))
    (tmp_path / "w1").mkdir(parents=True)
    f = tmp_path / "w1/test.png"
    f.write_bytes(PNG_1x1)
    
    fake_pool.results = [{"file_path": "w1/test.png"}]
    res = client.delete(
        "/api/gallery/photos/p1",
        headers={"X-Telegram-Init-Data": signed_init_data()}
    )
    assert res.status_code == 200
    assert not f.exists()
    
    fake_pool.results = [None]
    res = client.delete(
        "/api/gallery/photos/missing",
        headers={"X-Telegram-Init-Data": signed_init_data()}
    )
    assert res.status_code == 404