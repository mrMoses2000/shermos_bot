import pytest
from src.db.postgres import (
    create_gallery_work,
    list_gallery_works,
    get_gallery_work,
    update_gallery_work,
    delete_gallery_work,
    add_gallery_photo,
    list_photos_for_work,
    delete_gallery_photo,
    pick_random_gallery_works,
)
from tests.helpers import FakePool

@pytest.mark.asyncio
async def test_create_gallery_work():
    pool = FakePool([{"id": "w1", "partition_type": "fixed", "is_published": True}])
    res = await create_gallery_work(
        pool, "fixed", "clear", None, "Test", "Notes", 123
    )
    assert res["id"] == "w1"
    assert pool.calls[0][1].strip().startswith("INSERT INTO gallery_works")

@pytest.mark.asyncio
async def test_list_gallery_works():
    pool = FakePool([
        [
            {"id": "w1", "partition_type": "fixed", "photo_count": 2},
            {"id": "w2", "partition_type": "sliding_2", "photo_count": 0}
        ]
    ])
    res = await list_gallery_works(pool, partition_type="fixed", published_only=True)
    assert len(res) == 2
    assert pool.calls[0][1].strip().startswith("SELECT w.*,")
    assert "w.partition_type = $1" in pool.calls[0][1]
    assert "w.is_published = true" in pool.calls[0][1]

@pytest.mark.asyncio
async def test_get_gallery_work():
    pool = FakePool([
        {"id": "w1", "partition_type": "fixed"},
        [
            {"id": "p1", "work_id": "w1", "file_path": "path1", "sort_order": 0}
        ]
    ])
    res = await get_gallery_work(pool, "w1")
    assert res is not None
    assert res["id"] == "w1"
    assert len(res["photos"]) == 1
    assert res["photos"][0]["id"] == "p1"
    
    pool.results = [None]
    assert await get_gallery_work(pool, "missing") is None

@pytest.mark.asyncio
async def test_update_gallery_work():
    pool = FakePool([{"id": "w1", "title": "Updated"}])
    res = await update_gallery_work(pool, "w1", title="Updated")
    assert res["title"] == "Updated"
    
    pool.results = [None]
    with pytest.raises(ValueError):
        await update_gallery_work(pool, "missing", title="Updated")

@pytest.mark.asyncio
async def test_delete_gallery_work():
    pool = FakePool([
        [{"id": "p1", "file_path": "path1", "sort_order": 0}], # list_photos_for_work
        {"id": "w1"} # delete RETURNING id
    ])
    photos = await delete_gallery_work(pool, "w1")
    assert len(photos) == 1
    assert photos[0]["id"] == "p1"
    assert "DELETE FROM gallery_works" in pool.calls[1][1]

@pytest.mark.asyncio
async def test_add_gallery_photo():
    pool = FakePool([{"id": "p1", "file_path": "path"}])
    res = await add_gallery_photo(pool, "w1", "path", 0, 100, 100, 1024)
    assert res["id"] == "p1"

@pytest.mark.asyncio
async def test_list_photos_for_work():
    pool = FakePool([
        [{"id": "p1"}]
    ])
    res = await list_photos_for_work(pool, "w1")
    assert len(res) == 1

@pytest.mark.asyncio
async def test_delete_gallery_photo():
    pool = FakePool([{"id": "p1", "file_path": "path"}])
    res = await delete_gallery_photo(pool, "p1")
    assert res is not None
    assert res["id"] == "p1"
    
    pool.results = [None]
    assert await delete_gallery_photo(pool, "missing") is None

@pytest.mark.asyncio
async def test_pick_random_gallery_works():
    pool = FakePool([
        [{"id": "w1", "partition_type": "fixed"}],
        [{"id": "p1", "work_id": "w1", "sort_order": 0}]
    ])
    res = await pick_random_gallery_works(pool, "fixed", limit=1)
    assert len(res) == 1
    assert res[0]["id"] == "w1"
    assert len(res[0]["photos"]) == 1
    assert "ORDER BY random()" in pool.calls[0][1]
