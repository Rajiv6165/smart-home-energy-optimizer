import logging
from typing import Dict, Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        # Maps room names to a set of active WebSocket connections
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, room: str):
        await websocket.accept()
        if room not in self.active_connections:
            self.active_connections[room] = set()
        self.active_connections[room].add(websocket)
        logger.info("WebSocket connected to room: %s (Total: %s)", room, len(self.active_connections[room]))

    def disconnect(self, websocket: WebSocket, room: str):
        if room in self.active_connections:
            self.active_connections[room].discard(websocket)
            if not self.active_connections[room]:
                del self.active_connections[room]
        logger.info("WebSocket disconnected from room: %s", room)

    async def broadcast(self, message: dict, room: str):
        # Broadcast to both the target room and the default 'all' channel
        rooms_to_send = {room, "all"}
        for r in rooms_to_send:
            if r in self.active_connections:
                for connection in list(self.active_connections[r]):
                    try:
                        await connection.send_json(message)
                    except Exception as e:
                        logger.warning("Failed to send message to socket, disconnecting. Error: %s", e)
                        self.disconnect(connection, r)


# Instantiate a global connection manager
manager = ConnectionManager()
