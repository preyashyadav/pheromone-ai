from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


SourceType = Literal["openfda", "usda_fsis", "supplier", "retailer_internal"]


class RawRecallNoticeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: SourceType
    external_id: str | None = None
    source_url: str | None = None
    published_at_utc: datetime | None = None
    raw_json: dict[str, Any] = Field(default_factory=dict)
    raw_text: str = ""

