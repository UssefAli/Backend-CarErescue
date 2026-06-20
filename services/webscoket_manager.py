# websocket_manager.py

from typing import Dict, List
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        # request_id -> list of active websocket connections
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, request_id: int, websocket: WebSocket):
        if request_id not in self.active_connections:
            self.active_connections[request_id] = []
        self.active_connections[request_id].append(websocket)

    def disconnect(self, request_id: int, websocket: WebSocket):
        if request_id in self.active_connections:
            self.active_connections[request_id].remove(websocket)
            if not self.active_connections[request_id]:
                del self.active_connections[request_id]

    async def broadcast(self, request_id: int, data: dict):
        if request_id in self.active_connections:
            for connection in self.active_connections[request_id]:
                await connection.send_json(data)


manager = ConnectionManager()