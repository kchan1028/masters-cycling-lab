from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine

from masters_cycling_lab.config import Settings
from masters_cycling_lab.infrastructure.storage.local_files import LocalFileStorage


# create_app() builds these once per process and keeps them on app.state.
def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def get_storage(request: Request) -> LocalFileStorage:
    storage: LocalFileStorage = request.app.state.storage
    return storage


SettingsDep = Annotated[Settings, Depends(get_settings)]
EngineDep = Annotated[Engine, Depends(get_engine)]
StorageDep = Annotated[LocalFileStorage, Depends(get_storage)]
