"""
WebSocket handler for real-time application logs streaming.

Provides /ws/logs endpoint that streams application log entries
to connected clients in real-time batches.
"""

import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.dependencies import state

router = APIRouter()


@router.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket) -> None:
    """
    Stream application logs in real-time.
    
    Sends batches of new log entries every second to connected clients.
    Supports optional HTTP Basic authentication via headers.
    
    Args:
        websocket: FastAPI WebSocket connection instance
        
    Message Format:
        {
            "logs": ["log entry 1", "log entry 2", ...]
        }
        
    Authentication:
        - If auth is enabled, verifies 'Authorization' header with Basic Auth
        - Closes connection with code 1008 if authentication fails
        
    Example Client Usage:
        ```javascript
        const ws = new WebSocket('ws://localhost:8002/ws/logs');
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            console.log('New logs:', data.logs);
        };
        ```
    """
    # Authenticate before accepting connection
    if state.auth_required and not state.verify_basic_auth_header(
        websocket.headers.get("authorization")
    ):
        await websocket.close(code=1008)
        return
    
    await websocket.accept()
    last_idx = 0

    try:
        while True:
            # Snapshot deque to a list — required for slicing (deque has no slice)
            logs_snap = list(state.logs)
            if last_idx < len(logs_snap):
                batch = logs_snap[last_idx:]
                last_idx = len(logs_snap)
                await websocket.send_json({"logs": batch})

            # Poll every second
            await asyncio.sleep(1.0)

    except WebSocketDisconnect:
        # Client disconnected, clean exit
        return
