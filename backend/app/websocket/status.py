"""
WebSocket handler for real-time system status updates.

Provides /ws/status endpoint that streams aggregated system metrics
including scan state, device info, CPU usage, frame timing, noise floor,
AGC gain, and drop rate statistics.
"""

import asyncio
import time
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.dependencies import state
from app.dependencies.helpers import cpu_percent

router = APIRouter()


@router.websocket("/ws/status")
async def ws_status(websocket: WebSocket) -> None:
    """
    Stream real-time system status updates.
    
    Sends aggregated status information every second to connected clients.
    Useful for monitoring dashboard health indicators.
    
    Args:
        websocket: FastAPI WebSocket connection instance
        
    Message Format:
        {
            "status": {
                "state": "running",
                "device": "rtlsdr://0",
                "cpu_pct": 45.2,
                "frame_age_ms": 125,
                "noise_floor_db": -95.5,
                "threshold_db": -89.5,
                "agc_gain_db": 12.8,
                "drop_rate_pct": 0.15,
                "protocol_version": 2,
                "scan": {
                    "running": true,
                    "center_hz": 14100000,
                    "span_hz": 192000,
                    ...
                }
            }
        }
        
    Status Fields:
        - state: Scan state ("idle", "running", "stopping", etc.)
        - device: Current SDR device identifier
        - cpu_pct: CPU utilization percentage (0-100)
        - frame_age_ms: Milliseconds since last spectrum frame
        - noise_floor_db: Current band noise floor estimate
        - threshold_db: Current adaptive detection threshold
        - agc_gain_db: Current AGC gain in dB
        - drop_rate_pct: WebSocket frame drop rate percentage
        - protocol_version: WebSocket protocol version number
        - scan: Full scan engine status dictionary
        
    Authentication:
        - If auth is enabled, verifies 'Authorization' header with Basic Auth
        - Closes connection with code 1008 if authentication fails
        
    Update Rate:
        - 1 second interval
        - Lightweight payload optimized for frequent updates
        
    Example Client Usage:
        ```javascript
        const ws = new WebSocket('ws://localhost:8002/ws/status');
        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            console.log('CPU:', data.status.cpu_pct);
            console.log('Frame age:', data.status.frame_age_ms, 'ms');
        };
        ```
    """
    # Authenticate before accepting connection
    if state.auth_required and not state.verify_auth_transport(
        websocket.headers.get("authorization"),
        websocket.headers.get("cookie"),
    ):
        await websocket.close(code=1008)
        return
    
    await websocket.accept()
    
    try:
        while True:
            now = time.time()
            
            # Calculate frame age
            frame_age_ms = None
            if state.last_frame_ts:
                frame_age_ms = int((now - state.last_frame_ts) * 1000)
            
            # Get current band
            band = (
                state.scan_engine.config.get("band") 
                if state.scan_engine.config 
                else None
            )
            
            # Calculate drop rate
            sent = state.spectrum_send_stats.get("sent", 0)
            dropped = state.spectrum_send_stats.get("dropped", 0)
            total = sent + dropped
            drop_rate_pct = (
                (float(dropped) / float(total) * 100.0) 
                if total > 0 
                else 0.0
            )
            
            # Build status payload
            payload = {
                "status": {
                    "state": state.scan_state.get("state"),
                    "device": state.scan_state.get("device"),
                    "cpu_pct": cpu_percent(),
                    "frame_age_ms": frame_age_ms,
                    "noise_floor_db": state.noise_floor.get(band),
                    "threshold_db": state.threshold_state.get(band),
                    "agc_gain_db": state.last_agc_gain_db,
                    "drop_rate_pct": round(drop_rate_pct, 2),
                    "protocol_version": state.ws_protocol_version,
                    "scan": state.scan_engine.status()
                }
            }

            # Attach rotation status if active
            if state.scan_rotation and state.scan_rotation.running:
                payload["rotation"] = state.scan_rotation.status()

            # Attach and consume the retention notification (fires once per event)
            if state.retention_notification:
                payload["retention_completed"] = state.retention_notification
                state.retention_notification = None
            
            await websocket.send_json(payload)
            await asyncio.sleep(1.0)
            
    except WebSocketDisconnect:
        # Client disconnected, clean exit
        return
