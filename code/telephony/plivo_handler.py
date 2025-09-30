"""
Enhanced Plivo WebSocket message handling with better call state management
"""
import json
import base64
import logging
from config import TELEPHONY_SAMPLE_RATE, MESSAGE_LOG_FREQUENCY
import os
import aiohttp
import time

logger = logging.getLogger(__name__)


class PlivoMessageHandler:
    """Enhanced Plivo handler with better call state management"""
    
    def __init__(self):
        self.stream_sid = None
        self.call_active = False
        self.messages_received = 0
        self.messages_sent = 0
        self.call_db_id = None
        self.api_base_url = os.environ.get("INCOMING_CALL_AGENT_BACKEND_API", None)
        
        # Enhanced call state tracking
        self.call_started = False
        self.call_ended = False
        self.last_message_time = None
    
    async def handle_message(self, message, audio_callback=None, event_callback=None, websocket_handler=None):
        """Handle incoming WebSocket message - Enhanced with call state"""
        
        self.messages_received += 1
        self.last_message_time = time.time()
        
        try:
            if isinstance(message, str):
                event = json.loads(message)
                await self._handle_telephony_event(event, audio_callback, event_callback, websocket_handler)
            else:
                # Handle binary audio only if call is active
                if self.call_active and not self.call_ended and audio_callback:
                    await audio_callback(message)
                    
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON from Plivo: {e}")

    async def _handle_telephony_event(self, event, audio_callback=None, event_callback=None, websocket_handler=None):
        """Handle Plivo WebSocket events - Enhanced"""
        event_type = event.get("event")
        
        if event_type == "start":
            await self._handle_start_event(event, websocket_handler)
        elif event_type == "media":
            await self._handle_media_event(event, audio_callback)
        elif event_type == "stop":
            await self._handle_stop_event(event, event_callback)
        else:
            logger.info(f"❓ Unknown Plivo event: {event_type}")

    async def _handle_start_event(self, event, websocket_handler=None):
        """Handle call start event - Enhanced"""
        logger.info("🟢 CALL STARTED")
        self.call_active = True
        self.call_started = True
        self.call_ended = False
        
        start_data = event.get("start", {})
        self.stream_sid = start_data.get("streamId")
        call_id = start_data.get("callId")
        from_number = start_data.get("from")
        to_number = start_data.get("to")
        
        logger.info(f"📊 From: {from_number} → To: {to_number}")
        logger.info(f"📊 Stream ID: {self.stream_sid}")
        logger.info(f"📊 Call ID: {call_id}")
        logger.info(f"📊 Account ID: {start_data.get('accountId')}")
        
        # Validate critical data
        if not self.stream_sid:
            logger.error(f"❌ CRITICAL: No stream ID found! This will prevent audio return!")
            logger.error(f"❌ Start data: {json.dumps(start_data, indent=2)}")
        else:
            logger.info(f"✅ Stream ID captured: {self.stream_sid}")

        # Create database record if we have the API
        if call_id and websocket_handler:
            await self._create_inbound_call_record(
                call_uuid=call_id,
                from_number=from_number,
                to_number=to_number,
                room_name=websocket_handler.room_name,
                agent_name=websocket_handler.agent_name
            )

    async def _create_inbound_call_record(self, call_uuid, from_number, to_number, room_name, agent_name):
        """Create database record for inbound call"""
        if not self.api_base_url:
            logger.info("📝 No API URL configured - skipping database record")
            return
            
        try:
            logger.info(f"📝 Creating database record for inbound call: {call_uuid}")
            
            call_data = {
                "call_uuid": call_uuid,
                "from_number": from_number,
                "to_number": to_number,
                "room_name": room_name,
                "agent_name": agent_name or "Mysyara Agent",
                "caller_name": f"Caller {from_number[-4:]}"
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_base_url}/api/create-inbound-call/",
                    json=call_data,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    
                    if response.status == 200:
                        result = await response.json()
                        self.call_db_id = result.get("call_db_id")
                        logger.info(f"✅ Call record created: DB ID {self.call_db_id}")
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Failed to create call record: {response.status} - {error_text}")
                        
        except Exception as e:
            logger.error(f"❌ Error creating call record: {e}")
    
    async def _handle_media_event(self, event, audio_callback=None):
        """Handle media/audio event - Enhanced"""
        # Only process media if call is active and not ended
        if not self.call_active or self.call_ended:
            return
            
        # Log sparingly
        if self.messages_received <= 10:
            logger.info(f"📞 Plivo media event")
        
        media_data = event.get("media", {})
        payload = media_data.get("payload")
        
        if payload and audio_callback:
            try:
                decoded_audio = base64.b64decode(payload)
                await audio_callback(decoded_audio)
            except Exception as e:
                logger.error(f"❌ Error processing Plivo media: {e}")
    
    async def _handle_stop_event(self, event, event_callback=None):
        """Handle call stop event - Enhanced"""
        logger.warning("🔴 PLIVO CALL ENDED EVENT")
        self.call_active = False
        self.call_ended = True
        
        # Log stop event details
        stop_data = event.get("stop", {})
        logger.info(f"📊 Stop reason: {stop_data}")
        
        if event_callback:
            await event_callback("call_ended")
    
    async def send_audio_to_plivo(self, websocket, audio_data):
        """Send audio data back to Plivo - Enhanced with better error handling"""
        try:
            # Enhanced connection checking
            if self.call_ended:
                logger.warning("⚠️ Call ended - not sending audio")
                return False
                
            # Check WebSocket state more thoroughly
            websocket_ok = self._check_websocket_state(websocket)
            if not websocket_ok:
                logger.warning("⚠️ WebSocket not ready for sending")
                return False
                
            if not self.stream_sid:
                logger.error(f"❌ CRITICAL: No stream ID! Cannot send {len(audio_data)} bytes to Plivo")
                return False
                
            # Encode and send
            encoded_audio = base64.b64encode(audio_data).decode('utf-8')
            
            media_message = {
                "event": "playAudio",
                "media": {
                    "contentType": "audio/x-mulaw",
                    "sampleRate": TELEPHONY_SAMPLE_RATE,
                    "payload": encoded_audio
                }
            }
            
            await websocket.send(json.dumps(media_message))
            self.messages_sent += 1
            
            # Log success occasionally
            if self.messages_sent <= 5:
                logger.info(f"📤 Sent agent audio #{self.messages_sent} to Plivo ({len(audio_data)} bytes)")
            elif self.messages_sent % MESSAGE_LOG_FREQUENCY == 0:
                logger.info(f"📤 Sent {self.messages_sent} audio messages to Plivo")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error sending audio to Plivo: {e}")
            # Mark call as potentially ended if send fails consistently
            if "closed" in str(e).lower():
                logger.warning("🔌 WebSocket appears closed - marking call as ended")
                self.call_ended = True
            return False
    
    def _check_websocket_state(self, websocket):
        """Enhanced WebSocket state checking"""
        try:
            if not websocket:
                return False
                
            # Check various WebSocket state indicators
            if hasattr(websocket, 'closed') and websocket.closed:
                return False
                
            if hasattr(websocket, 'open') and not websocket.open:
                return False
                
            if hasattr(websocket, 'state'):
                # websockets library state check
                import websockets
                if websocket.state != websockets.protocol.State.OPEN:
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error checking WebSocket state: {e}")
            return False
    
    def get_call_stats(self):
        """Get call statistics - Enhanced"""
        return {
            "messages_received": self.messages_received,
            "messages_sent": self.messages_sent,
            "call_active": self.call_active,
            "call_started": self.call_started,
            "call_ended": self.call_ended,
            "stream_sid": self.stream_sid,
            "last_message_ago": time.time() - self.last_message_time if self.last_message_time else None
        }
    
    def is_call_active(self):
        """Check if call is currently active - Enhanced"""
        return self.call_active and not self.call_ended and self.call_started
    
    def get_stream_id(self):
        """Get the current stream ID"""
        return self.stream_sid
    
    def force_end_call(self):
        """Force mark call as ended"""
        logger.warning("🔴 Forcing call end state")
        self.call_active = False
        self.call_ended = True

