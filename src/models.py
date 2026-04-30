"""
All Pydantic models for the system.
"""

from datetime import UTC, datetime
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field


class Job(BaseModel):
    channel: Literal["telegram", "whatsapp"] = "telegram"
    update_id: int
    chat_id: int
    user_id: int
    text: str = ""
    msg_type: str = "text"
    callback_data: str = ""
    external_chat_id: Optional[str] = None
    external_message_id: Optional[str] = None
    phone_e164: Optional[str] = None
    media_path: Optional[str] = None
    media_mime: Optional[str] = None
    raw_update: dict = Field(default_factory=dict)
    attempt: int = 0
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    bot_type: str = "client"


class RenderPartitionAction(BaseModel):
    shape: str
    shape_side: Optional[str] = None
    height: float
    width_a: float
    width_b: Optional[float] = None
    width_c: Optional[float] = None
    glass_type: Union[str, int] = "1"
    frame_color: Union[str, int] = "1"
    partition_type: str = "sliding_2"
    matting: str = "none"
    complex_pattern: bool = False
    rows: int = 1
    cols: int = 2
    frame_thickness: float = 0.04
    add_handle: bool = False
    handle_style: str = "Современный"
    handle_position: str = "Право"
    handle_wall: Optional[str] = None
    handle_sections: Optional[list[int]] = None
    door_wall: Optional[str] = None
    door_sections: Optional[list[int]] = None
    door_section: Optional[int] = None
    rows_front: Optional[int] = None
    cols_front: Optional[int] = None
    rows_side: Optional[int] = None
    cols_side: Optional[int] = None
    rows_left: Optional[int] = None
    cols_left: Optional[int] = None
    rows_right: Optional[int] = None
    cols_right: Optional[int] = None
    mullion_positions: Optional[dict] = None


class ScheduleMeasurementAction(BaseModel):
    date: str
    time: str
    client_name: str
    phone: str
    address: str = Field(min_length=1)


class UpdateClientProfileAction(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None


class StatePatch(BaseModel):
    mode: Optional[str] = None
    step: Optional[str] = None
    collected_params: Optional[dict] = None


class ActionsJson(BaseModel):
    reply_text: str = Field(min_length=1, max_length=4000)
    actions: Optional[dict] = None


class OrderStatusUpdate(BaseModel):
    order_id: str
    new_status: str
    note: str = ""
