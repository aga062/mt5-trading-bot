import asyncio
import json
import logging
from typing import Dict, Set

from fastapi import WebSocket

logger = logging.getLogger("websocket.ws_manager")


class ConnectionManager:
    def __init__(self):
        self._connections: Dict[int, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        async with self._lock:
            if user_id not in self._connections:
                self._connections[user_id] = set()
            self._connections[user_id].add(websocket)
        logger.info(f"WebSocket connected for user {user_id}")

    async def disconnect(self, websocket: WebSocket, user_id: int):
        async with self._lock:
            if user_id in self._connections:
                self._connections[user_id].discard(websocket)
                if not self._connections[user_id]:
                    del self._connections[user_id]
        logger.info(f"WebSocket disconnected for user {user_id}")

    async def send_to_user(self, user_id: int, data: dict):
        async with self._lock:
            connections = self._connections.get(user_id, set()).copy()

        dead = []
        for ws in connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)

        for ws in dead:
            await self.disconnect(ws, user_id)

    async def broadcast(self, data: dict):
        async with self._lock:
            all_connections = {uid: conns.copy() for uid, conns in self._connections.items()}

        for user_id, connections in all_connections.items():
            for ws in connections:
                try:
                    await ws.send_json(data)
                except Exception:
                    await self.disconnect(ws, user_id)

    def get_connected_users(self) -> list[int]:
        return list(self._connections.keys())


ws_manager = ConnectionManager()
