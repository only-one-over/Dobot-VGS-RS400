"""Remote REST API bridge for external tablet/MES clients."""

from .app import main, RemoteApiServer

__all__ = ["main", "RemoteApiServer"]
