from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/health", tags=["health"])


class LiveStatus(BaseModel):
    status: Literal["ok"]


@router.get("/live")
async def live() -> LiveStatus:
    """The API process is running. Says nothing about the database or the embedding model."""
    return LiveStatus(status="ok")
