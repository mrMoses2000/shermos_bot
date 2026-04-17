"""Gallery API routes."""

import io
from pathlib import Path
from typing import Literal
from uuid import uuid4

from PIL import Image
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from src.api.auth import require_telegram_auth
from src.api.deps import get_pool
from src.config import settings
from src.db import postgres
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(
    prefix="/api/gallery",
    tags=["gallery"],
    dependencies=[Depends(require_telegram_auth)],
)

PartitionType = Literal["fixed", "sliding_2", "sliding_3", "sliding_4"]

class WorkCreate(BaseModel):
    partition_type: PartitionType
    glass_type: str | None = None
    matting: str | None = None
    title: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=2000)

class WorkPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    partition_type: PartitionType | None = None
    glass_type: str | None = None
    matting: str | None = None
    is_published: bool | None = None

FORMAT_EXT = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}

@router.get("/works")
async def list_works(
    partition_type: PartitionType | None = None,
    published_only: bool = False,
    pool=Depends(get_pool),
):
    works = await postgres.list_gallery_works(
        pool, partition_type=partition_type, published_only=published_only
    )
    return {"items": works}

@router.post("/works")
async def create_work(
    data: WorkCreate,
    auth: dict = Depends(require_telegram_auth),
    pool=Depends(get_pool),
):
    work = await postgres.create_gallery_work(
        pool,
        partition_type=data.partition_type,
        glass_type=data.glass_type,
        matting=data.matting,
        title=data.title,
        notes=data.notes,
        created_by_chat_id=(auth.get("user_json") or {}).get("id"),
    )
    return work

@router.get("/works/{work_id}")
async def get_work(work_id: str, pool=Depends(get_pool)):
    work = await postgres.get_gallery_work(pool, work_id)
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")
    
    for photo in work.get("photos", []):
        photo["url"] = f"/gallery/{photo['file_path']}"
        
    return work

@router.patch("/works/{work_id}")
async def update_work(work_id: str, data: WorkPatch, pool=Depends(get_pool)):
    try:
        work = await postgres.update_gallery_work(
            pool, work_id, **data.model_dump(exclude_none=True)
        )
        return work
    except ValueError:
        raise HTTPException(status_code=404, detail="Work not found")

@router.delete("/works/{work_id}")
async def delete_work(work_id: str, pool=Depends(get_pool)):
    try:
        photos = await postgres.delete_gallery_work(pool, work_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Work not found")
        
    # Unlink files
    base_dir = Path(settings.gallery_dir)
    for photo in photos:
        file_path = base_dir / photo["file_path"]
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass
            
    # Try removing empty directory
    try:
        (base_dir / work_id).rmdir()
    except OSError:
        pass
        
    return {"deleted_photos": len(photos)}

@router.post("/works/{work_id}/photos")
async def upload_photos(
    work_id: str,
    files: list[UploadFile] = File(..., description="Image files"),
    pool=Depends(get_pool),
) -> dict:
    work = await postgres.get_gallery_work(pool, work_id)
    if not work:
        raise HTTPException(status_code=404, detail="Work not found")
        
    added_photos = []
    base_dir = Path(settings.gallery_dir)
    
    # get current max sort order
    current_photos = work.get("photos", [])
    next_order = max([p["sort_order"] for p in current_photos], default=-1) + 1
    
    for i, file in enumerate(files):
        data = await file.read()
        if len(data) > settings.gallery_photo_max_bytes:
            raise HTTPException(400, "Файл слишком большой")
            
        try:
            img = Image.open(io.BytesIO(data))
            img.verify()
        except Exception:
            raise HTTPException(400, "Неподдерживаемый формат")
            
        img2 = Image.open(io.BytesIO(data))
        if img2.format not in FORMAT_EXT:
            raise HTTPException(400, "Неподдерживаемый формат")
            
        photo_id = uuid4().hex
        ext = FORMAT_EXT[img2.format]
        rel_path = f"{work_id}/{photo_id}.{ext}"
        abs_path = base_dir / rel_path
        
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(data)
        
        width, height = img2.size
        photo = await postgres.add_gallery_photo(
            pool,
            work_id,
            rel_path,
            sort_order=next_order + i,
            width=width,
            height=height,
            size_bytes=len(data),
        )
        photo["url"] = f"/gallery/{photo['file_path']}"
        added_photos.append(photo)
        
    return {"items": added_photos}

@router.delete("/photos/{photo_id}")
async def delete_photo(photo_id: str, pool=Depends(get_pool)):
    photo = await postgres.delete_gallery_photo(pool, photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
        
    abs_path = Path(settings.gallery_dir) / photo["file_path"]
    try:
        abs_path.unlink(missing_ok=True)
    except OSError:
        pass
        
    return {"ok": True}
