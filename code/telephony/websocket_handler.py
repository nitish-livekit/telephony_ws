"""
Enhanced WebSocket handler with FIXED outbound call logic
"""
import asyncio
import time
import logging
import websockets
from livekit import rtc

from audio.telephony_audio_source import TelephonyAudioSource
from audio.audio_processor import AudioProcessor
from lk_utils.livekit_manager import LiveKitManager
from agents.agent_manager import AgentManager
from telephony.plivo_handler import PlivoMessageHandler
from telephony.agent_monitor import AgentConnectionMonitor

logger = logging.getLogger(__name__)


class TelephonyWebSocketHandler:
    """Enhanced WebSocket handler with FIXED outbound call detection"""
    
    def __init__(self, room_name, websocket, agent_name=None, noise_settings=None):
        self.room_name = room_name
        self.websocket = websocket
        self.agent_name = agent_name
        self.connection_start_time = time.time()
        
        # CRITICAL: Initialize outbound flag to False
        self.outbound_agent_exists = False
        
        # Component managers
        self.livekit_manager = LiveKitManager(room_name)
        self.agent_manager = AgentManager()
        self.plivo_handler = PlivoMessageHandler()
        self.audio_processor = AudioProcessor()
        
        # Agent monitoring (only for inbound calls)
        self.agent_monitor = None
        
        # Apply noise settings if provided
        if noise_settings:
            self.audio_processor.update_noise_settings(**noise_settings)
        
        # Start background audio immediately
        if self.audio_processor.get_noise_status()["enabled"]:
            self.audio_processor.start_background_audio()
            self.background_stream_task = asyncio.create_task(self._stream_background_audio_continuously())
        
        # Audio components
        self.audio_source = None
        self.audio_track = None
        self.audio_stream_task = None
        self.background_stream_task = None
        self.agent_is_speaking = False
        
        # Call termination state
        self.cleanup_started = False
        self.force_stop = False
        self.call_termination_reason = None
        self.call_ended = False
        
        # Participant tracking
        self.agent_participant = None
        self.participants = {}
        self.audio_tracks = {}
        
        # Statistics
        self.stats = {
            "audio_frames_sent_to_livekit": 0,
            "audio_frames_received_from_agent": 0,
            "bytes_from_telephony": 0,
            "bytes_to_telephony": 0,
        }
        
        logger.info(f"🆕 Created telephony WebSocket handler for room: {room_name}")
        if agent_name:
            logger.info(f"🤖 Using custom agent: {agent_name}")
        
        # Log noise status
        noise_status = self.audio_processor.get_noise_status()
        if noise_status["enabled"]:
            logger.info(f"🔊 Background noise enabled: {noise_status['noise_type']} at volume {noise_status['volume']}")
        else:
            logger.info("🔇 Background noise disabled")
    
    async def initialize(self):
        """Enhanced initialization with FIXED outbound detection"""
        logger.info(f"🚀 Starting WebSocket handler initialization...")
        logger.info(f"🔍 Outbound agent exists flag: {self.outbound_agent_exists}")
        
        # Check if this is an outbound call (agent already exists)
        if self.outbound_agent_exists:
            logger.info(f"🔄 OUTBOUND CALL CONFIRMED - Agent '{self.agent_name}' already running in room '{self.room_name}'")
            logger.info(f"🚫 SKIPPING agent dispatch - will only connect to existing session")
            
            # For outbound calls: Only setup LiveKit connection, NO agent dispatch
            livekit_task = asyncio.create_task(self._setup_livekit())
            message_task = asyncio.create_task(self._handle_messages())
            
            # Wait for LiveKit connection
            try:
                success = await asyncio.wait_for(livekit_task, timeout=8.0)
                if success:
                    logger.info(f"✅ LiveKit connected for OUTBOUND call: {self.room_name}")
                    logger.info(f"🎯 Ready to bridge existing agent audio to telephony")
                else:
                    logger.error("❌ LiveKit connection failed for outbound call")
            except asyncio.TimeoutError:
                logger.error("❌ LiveKit connection timeout (8s) for outbound call")
            
            logger.info("✅ Outbound WebSocket setup complete - connecting to existing agent")
            return message_task
            
        else:
            # INBOUND CALL - Create new agent
            logger.info(f"📞 INBOUND CALL CONFIRMED - Will create NEW agent '{self.agent_name}' in room '{self.room_name}'")
            logger.info(f"🚀 Starting concurrent setup with 5-second agent timeout...")
            
            # Create agent connection monitor for inbound calls
            self.agent_monitor = AgentConnectionMonitor(self, timeout_seconds=5)
            
            # Start all tasks concurrently
            livekit_task = asyncio.create_task(self._setup_livekit())
            agent_task = asyncio.create_task(self.agent_manager.trigger_agent(self.room_name, self.agent_name))
            message_task = asyncio.create_task(self._handle_messages())
            
            # Start agent connection monitoring
            monitor_task = asyncio.create_task(self.agent_monitor.start_monitoring())
            
            # Wait for LiveKit connection
            try:
                success = await asyncio.wait_for(livekit_task, timeout=8.0)
                if success:
                    logger.info(f"✅ LiveKit connected for INBOUND call: {self.room_name}")
                else:
                    logger.error("❌ LiveKit connection failed for inbound call")
            except asyncio.TimeoutError:
                logger.error("❌ LiveKit connection timeout (8s) for inbound call")
            
            # Wait for agent dispatch to complete
            try:
                await asyncio.wait_for(agent_task, timeout=2.0)
                logger.info("✅ Agent dispatch completed for inbound call")
            except asyncio.TimeoutError:
                logger.warning("⚠️ Agent dispatch took longer than expected for inbound call")
            
            logger.info("✅ Inbound setup complete - monitoring for new agent connection...")
            
            return message_task

    async def _setup_livekit(self):
        """Setup LiveKit connection and audio components"""
        event_handlers = {
            'on_connected': self._on_livekit_connected,
            'on_disconnected': self._on_livekit_disconnected,
            'on_participant_connected': self._on_participant_connected,
            'on_participant_disconnected': self._on_participant_disconnected,
            'on_track_published': self._on_track_published,
            'on_track_subscribed': self._on_track_subscribed,
            'on_track_unsubscribed': self._on_track_unsubscribed
        }
        
        success = await self.livekit_manager.connect_to_room(event_handlers)
        
        if success:
            await self._setup_audio_track()
            logger.info(f"🎯 LiveKit connection complete - ready for audio!")
            logger.info(f"🎯 LiveKit ready in {time.time() - self.connection_start_time:.2f}s")
        
        return success
    
    async def _setup_audio_track(self):
        """Create and publish audio track"""
        self.audio_source = TelephonyAudioSource()
        self.audio_track = rtc.LocalAudioTrack.create_audio_track(
            "telephony-audio", 
            self.audio_source
        )
        
        publication = await self.livekit_manager.publish_audio_track(self.audio_track)
        if publication:
            logger.info(f"✅ Telephony audio track published: {publication.sid}")
    
    # LiveKit Event Handlers
    def _on_livekit_connected(self):
        """Handle LiveKit connection"""
        call_type = "OUTBOUND" if self.outbound_agent_exists else "INBOUND"
        logger.info(f"✅ LiveKit connection established for {call_type} call in room: {self.room_name}")
        
        room = self.livekit_manager.get_room()
        remote_participants = self.livekit_manager.get_remote_participants()
        logger.info(f"👥 Current participants in room: {len(remote_participants)}")
        
        for participant in remote_participants.values():
            logger.info(f"🔍 Found existing participant: {participant.identity}")
            self._handle_participant_joined(participant)
    
    def _on_livekit_disconnected(self):
        """Handle LiveKit disconnection"""
        logger.warning(f"❌ LiveKit connection lost for room: {self.room_name}")
        
        # If we lose LiveKit connection unexpectedly, end the call
        if not self.cleanup_started and not self.call_ended:
            logger.warning("🔌 Unexpected LiveKit disconnection - ending telephony call")
            self.call_termination_reason = "livekit_disconnected"
            asyncio.create_task(self._terminate_call_immediately("LiveKit disconnected"))
    
    def _on_participant_connected(self, participant):
        """Handle participant connection"""
        logger.info(f"👤 NEW participant joined: {participant.identity}")
        self._handle_participant_joined(participant)
    
    def _on_participant_disconnected(self, participant):
        """Handle participant disconnection"""
        logger.info(f"👋 Participant left: {participant.identity}")
        
        # Clean up tracking
        if participant.identity in self.participants:
            del self.participants[participant.identity]
        if participant.identity in self.audio_tracks:
            del self.audio_tracks[participant.identity]
        
        # CRITICAL: Check if this was the agent
        if participant == self.agent_participant:
            logger.warning("🤖 AGENT PARTICIPANT DISCONNECTED!")
            self.agent_participant = None
            self.call_termination_reason = "agent_disconnected"
            
            # End user's call IMMEDIATELY when agent disconnects
            logger.warning("📞 Agent disconnected - terminating telephony call immediately")
            asyncio.create_task(self._terminate_call_immediately("Agent disconnected"))
            
        # ENHANCED: Also check if ALL participants left (empty room scenario)
        elif len(self.participants) == 0:
            logger.warning("🏠 All participants left - room is empty")
            self.call_termination_reason = "room_empty"
            asyncio.create_task(self._terminate_call_immediately("Room empty"))
    
    async def _terminate_call_immediately(self, reason):
        """ENHANCED: Immediately terminate the telephony call"""
        if self.call_ended:
            logger.info(f"🔄 Call already terminated, skipping...")
            return
            
        self.call_ended = True
        logger.warning(f"🔚 TERMINATING CALL IMMEDIATELY: {reason}")
        
        try:
            # Step 1: Set force stop flags FIRST
            self.force_stop = True
            self.agent_is_speaking = False
            
            # Step 2: Cancel ALL audio streaming tasks immediately
            await self._cancel_all_audio_tasks()
            
            # Step 3: Close WebSocket to Plivo (this ends user's call)
            await self._close_websocket_connection(reason)
            
            # Step 4: Trigger full cleanup after a brief delay
            logger.info("⏰ Scheduling full cleanup after call termination...")
            asyncio.create_task(self._delayed_cleanup())
            
        except Exception as e:
            logger.error(f"❌ Error terminating call: {e}")
            # Force cleanup anyway
            await self.cleanup()
    

    async def _cancel_all_audio_tasks(self):
        """Cancel agent audio tasks but PRESERVE background audio"""
        logger.info("Cancelling agent audio tasks (preserving background)")
        
        # Cancel agent audio stream only
        if self.audio_stream_task and not self.audio_stream_task.done():
            try:
                self.audio_stream_task.cancel()
                await asyncio.wait_for(self.audio_stream_task, timeout=0.5)
                logger.info("Agent audio task cancelled")
            except (asyncio.CancelledError, asyncio.TimeoutError):
                logger.info("Agent audio task force cancelled")
        
        # DON'T cancel background_stream_task here - let it run until cleanup


    async def _close_websocket_connection(self, reason):
        """Close WebSocket connection to end user's call"""
        logger.warning(f"🔌 Closing WebSocket connection: {reason}")
        
        try:
            if hasattr(self, 'websocket') and self.websocket:
                if not self.websocket.closed:
                    # Close with specific code and reason
                    await asyncio.wait_for(
                        self.websocket.close(code=1000, reason=f"Call ended: {reason}"),
                        timeout=2.0
                    )
                    logger.warning("✅ WebSocket closed successfully - user call ended")
                else:
                    logger.info("ℹ️ WebSocket already closed")
            else:
                logger.warning("⚠️ No WebSocket to close")
                
        except asyncio.TimeoutError:
            logger.error("⏰ WebSocket close timeout - but call should still end")
        except Exception as e:
            logger.error(f"❌ Error closing WebSocket: {e}")
    
    async def _delayed_cleanup(self):
        """Perform full cleanup after a short delay"""
        await asyncio.sleep(0.5)  # Brief delay to ensure WebSocket close is processed
        if not self.cleanup_started:
            logger.info("🧹 Starting delayed cleanup after call termination")
            await self.cleanup()
    
    def _on_track_published(self, publication, participant):
        """Handle track publication"""
        logger.info(f"📡 Track PUBLISHED by {participant.identity}: {publication.kind}")
        
        if self.agent_manager.is_agent_participant(participant):
            logger.info(f"🤖 AGENT published {publication.kind} track")
    
    def _on_track_subscribed(self, track, publication, participant):
        """Handle track subscription"""
        logger.info(f"🎵 Track SUBSCRIBED from {participant.identity}: {track.kind}")
        
        # Don't start new streams if call is ending
        if self.call_ended or self.cleanup_started:
            logger.info("🛑 Call ended - not processing new track subscription")
            return
        
        # Store the track
        if participant.identity not in self.audio_tracks:
            self.audio_tracks[participant.identity] = []
        
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            self.audio_tracks[participant.identity].append(track)
            logger.info(f"🔊 AUDIO TRACK STORED for {participant.identity}")
            
            # Check if this participant is the agent
            if self.agent_manager.is_agent_participant(participant):
                logger.info(f"🤖 AGENT AUDIO TRACK CONFIRMED! Starting stream to telephony...")
                self._start_agent_audio_stream(participant, track)
    
    def _on_track_unsubscribed(self, track, publication, participant):
        """Handle track unsubscription"""
        logger.info(f"🔇 Track unsubscribed from {participant.identity}: {track.kind}")
        
        # Remove from tracking
        if participant.identity in self.audio_tracks:
            if track in self.audio_tracks[participant.identity]:
                self.audio_tracks[participant.identity].remove(track)
        
        # If agent's audio track unsubscribed, this might indicate agent issues
        if (self.agent_manager.is_agent_participant(participant) and 
            track.kind == rtc.TrackKind.KIND_AUDIO):
            logger.warning("🤖 Agent audio track unsubscribed - potential issue")
    
    def _handle_participant_joined(self, participant):
        """Handle when a participant joins - ENHANCED with outbound detection"""
        logger.info(f"🔍 Analyzing participant: {participant.identity}")
        
        # Don't process if call is ending
        if self.call_ended or self.cleanup_started:
            logger.info("🛑 Call ended - not processing new participant")
            return
        
        # Store participant
        self.participants[participant.identity] = participant
        
        # Check if this is an agent
        is_agent = self.agent_manager.log_agent_detection(participant)
        
        if is_agent:
            self.agent_participant = participant
            
            # ENHANCED: Different handling for inbound vs outbound
            if self.outbound_agent_exists:
                logger.info(f"🔄 Found EXISTING agent '{participant.identity}' for outbound call")
                logger.info(f"✅ Outbound call bridge established - agent already running")
            else:
                logger.info(f"🆕 Found NEW agent '{participant.identity}' for inbound call")
                
                # Only notify monitor for inbound calls
                if hasattr(self, 'agent_monitor') and self.agent_monitor:
                    self.agent_monitor.notify_agent_connected()
                    logger.info("📢 Notified monitor: New agent connected for inbound call!")
            
            # Check if agent already has published audio tracks (both inbound and outbound)
            self._check_existing_agent_tracks(participant)
    
    def _check_existing_agent_tracks(self, participant):
        """Check if agent already has published tracks"""
        logger.info(f"🔍 Checking existing tracks for agent: {participant.identity}")
        
        agent_tracks = self.agent_manager.find_agent_audio_tracks(participant)
        for track in agent_tracks:
            self._start_agent_audio_stream(participant, track)
    
    def _start_agent_audio_stream(self, participant, track):
        """Start streaming agent audio to telephony"""
        # Don't start if cleanup has begun or call ended
        if self.cleanup_started or self.force_stop or self.call_ended:
            logger.info("🛑 Not starting agent stream - call ended or cleanup in progress")
            return
            
        # Cancel existing stream task if any
        if self.audio_stream_task and not self.audio_stream_task.done():
            logger.info("🔄 Cancelling existing audio stream task")
            self.audio_stream_task.cancel()
        
        # Mark agent as speaking
        self.agent_is_speaking = True
        
        # Start new audio streaming task
        call_type = "OUTBOUND" if self.outbound_agent_exists else "INBOUND"
        logger.info(f"🚀 Creating audio stream task for {call_type} call")
        self.audio_stream_task = asyncio.create_task(
            self._stream_agent_audio_to_telephony(track, participant.identity)
        )
    
    async def _stream_agent_audio_to_telephony(self, audio_track, participant_identity):
        """Stream agent's audio back to telephony system with background mixing"""
        call_type = "OUTBOUND" if self.outbound_agent_exists else "INBOUND"
        logger.info(f"🔊 Starting {call_type} agent audio stream to telephony from {participant_identity}")
        
        frame_count = 0
        last_log_time = time.time()
        bytes_sent = 0
        
        try:
            # Create audio stream
            audio_stream = rtc.AudioStream(audio_track)
            logger.info("✅ AudioStream created successfully")
            
            async for audio_frame_event in audio_stream:
                # CRITICAL: Check all stop conditions first
                if self.cleanup_started or self.force_stop or self.call_ended:
                    logger.info("🛑 Stopping agent audio stream - call ended")
                    break
                    
                current_time = time.time()
                
                # Check if still connected
                if not self._is_connection_active():
                    logger.warning("❌ Connection lost, stopping audio stream")
                    break
                
                frame_count += 1
                
                # Log every second
                if current_time - last_log_time >= 1.0:
                    logger.info(f"🔊 [OUTGOING] {call_type} agent audio: {frame_count} frames, {bytes_sent} bytes sent")
                    last_log_time = current_time
                
                try:
                    # Convert audio frame to clean telephony format
                    telephony_audio_data = self.audio_processor.convert_livekit_to_telephony(
                        audio_frame_event.frame
                    )
                    
                    # Send each audio chunk to telephony WITH background mixing
                    for clean_audio_chunk in telephony_audio_data:
                        # Check again before sending
                        if self.cleanup_started or self.force_stop or self.call_ended:
                            logger.info("🛑 Stopping mid-frame - call ended")
                            break
                            
                        # Mix clean agent audio with background for user
                        mixed_audio_chunk = self.audio_processor.mix_agent_audio_with_background(
                            clean_audio_chunk
                        )
                        
                        success = await self.plivo_handler.send_audio_to_plivo(
                            self.websocket, mixed_audio_chunk
                        )
                        
                        if success:
                            bytes_sent += len(mixed_audio_chunk)
                            self.stats["audio_frames_received_from_agent"] += 1
                            self.stats["bytes_to_telephony"] += len(mixed_audio_chunk)
                        
                except Exception as e:
                    logger.error(f"❌ Error processing audio frame {frame_count}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"❌ Error in agent audio stream: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Mark agent as no longer speaking
            self.agent_is_speaking = False
            logger.info(f"🔇 {call_type} agent audio stream ended. Frames: {frame_count}, Bytes: {bytes_sent}")
    
    def _is_connection_active(self):
        """Check if connection is still active"""
        # If cleanup started or call ended, connection is not active
        if self.cleanup_started or self.force_stop or self.call_ended:
            return False
            
        try:
            websocket_closed = (not hasattr(self.websocket, 'open') or 
                              not self.websocket.open if hasattr(self.websocket, 'open') else
                              getattr(self.websocket, 'closed', False))
        except:
            websocket_closed = True
        
        # Check all connection states
        livekit_connected = self.livekit_manager.is_connected()
        call_active = self.plivo_handler.is_call_active()
        
        is_active = livekit_connected and not websocket_closed and call_active
        
        return is_active
    
    async def _handle_messages(self):
        """Handle incoming WebSocket messages from Plivo"""
        call_type = "OUTBOUND" if self.outbound_agent_exists else "INBOUND"
        logger.info(f"👂 Starting to listen for {call_type} Plivo WebSocket messages...")
        
        try:
            async for message in self.websocket:
                # Don't process if call ended
                if self.cleanup_started or self.force_stop or self.call_ended:
                    logger.info("🛑 Stopping message handling - call ended")
                    break
                    
                # Pass self to the handler
                await self.plivo_handler.handle_message(
                    message,
                    audio_callback=self._handle_audio_from_plivo,
                    event_callback=self._handle_plivo_event,
                    websocket_handler=self
                )
                        
        except websockets.ConnectionClosed:
            logger.info(f"📞 {call_type} Plivo WebSocket connection closed normally")
            if not self.call_ended:
                self.call_termination_reason = "websocket_closed"
                self.call_ended = True
        except Exception as e:
            logger.error(f"❌ Error handling {call_type} Plivo messages: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if not self.cleanup_started:
                logger.info(f"🔄 {call_type} message loop ended - starting cleanup")
                await self.cleanup()
    
    async def _handle_audio_from_plivo(self, audio_data):
        """Handle audio data from Plivo"""
        # Don't process if call ended
        if self.cleanup_started or self.force_stop or self.call_ended:
            return
            
        if self.audio_source and self.livekit_manager.is_connected():
            if not self.audio_processor.validate_audio_data(audio_data):
                return
                
            try:
                await self.audio_source.push_audio_data(audio_data)
                self.stats["audio_frames_sent_to_livekit"] += 1
                self.stats["bytes_from_telephony"] += len(audio_data)
                
                # Log progress occasionally
                if self.stats["audio_frames_sent_to_livekit"] % 250 == 0:
                    call_type = "OUTBOUND" if self.outbound_agent_exists else "INBOUND"
                    logger.info(f"🎵 Processed {self.stats['audio_frames_sent_to_livekit']} {call_type} audio frames from Plivo")
            except Exception as e:
                logger.error(f"❌ Error processing audio from Plivo: {e}")
        else:
            # Count dropped frames
            if not hasattr(self, 'dropped_frames'):
                self.dropped_frames = 0
            self.dropped_frames += 1
    
    
    async def _stream_background_audio_continuously(self):
        """Stream background audio continuously throughout the entire call - ROBUST VERSION"""
        if not self.audio_processor.get_noise_status()["enabled"]:
            logger.info("Background audio disabled, not starting continuous stream")
            return
        
        call_type = "OUTBOUND" if self.outbound_agent_exists else "INBOUND"
        noise_status = self.audio_processor.get_noise_status()
        logger.info(f"Starting PERSISTENT background audio stream for {call_type} call")
        logger.info(f"Noise settings: type={noise_status['noise_type']}, volume={noise_status['volume']}")
        
        frame_count = 0
        audio_frame_size = 160  # 20ms at 8kHz μ-law
        last_log_time = time.time()
        consecutive_failures = 0
        max_consecutive_failures = 50
        
        try:
            # Continue until explicitly stopped
            while True:
                current_time = time.time()
                
                # Primary exit conditions - only stop for these
                if self.cleanup_started:
                    logger.info("Background audio stopping - cleanup started")
                    break
                    
                if self.force_stop:
                    logger.info("Background audio stopping - force stop")
                    break
                    
                if self.call_ended:
                    logger.info("Background audio stopping - call ended")
                    break
                
                # Check WebSocket connection less aggressively
                try:
                    websocket_closed = getattr(self.websocket, 'closed', False)
                    if websocket_closed:
                        logger.warning("Background audio stopping - WebSocket closed")
                        break
                except:
                    # If we can't check WebSocket state, continue anyway
                    pass
                
                # ALWAYS attempt to send background audio
                try:
                    # Get background audio chunk
                    bg_chunk = self.audio_processor.get_background_audio_chunk(audio_frame_size)
                    
                    if bg_chunk:
                        # Attempt to send to telephony
                        success = await self.plivo_handler.send_audio_to_plivo(
                            self.websocket, bg_chunk
                        )
                        
                        if success:
                            frame_count += 1
                            consecutive_failures = 0  # Reset failure counter
                            self.stats["bytes_to_telephony"] += len(bg_chunk)
                            
                            # Log progress every 10 seconds
                            if current_time - last_log_time >= 10.0:
                                logger.info(f"Background audio active: {frame_count} frames sent, "
                                        f"agent_speaking={self.agent_is_speaking}")
                                last_log_time = current_time
                        else:
                            consecutive_failures += 1
                            if consecutive_failures <= 10:
                                logger.warning(f"Background audio send failed #{consecutive_failures}")
                            
                            if consecutive_failures >= max_consecutive_failures:
                                logger.error(f"Background audio stopping - {consecutive_failures} consecutive failures")
                                break
                                
                            await asyncio.sleep(0.1)
                            continue
                    else:
                        consecutive_failures += 1
                        if consecutive_failures % 10 == 0:
                            logger.warning(f"No background chunk available #{consecutive_failures}")
                        
                        if consecutive_failures >= max_consecutive_failures:
                            logger.error("Background audio stopping - no chunks available")
                            break
                
                except Exception as e:
                    consecutive_failures += 1
                    if consecutive_failures <= 5:
                        logger.error(f"Background audio error #{consecutive_failures}: {e}")
                    
                    if consecutive_failures >= max_consecutive_failures:
                        logger.error(f"Background audio stopping - too many errors: {e}")
                        break
                    
                    await asyncio.sleep(0.1)
                    continue
                
                # Send frames every 20ms for smooth audio
                await asyncio.sleep(0.02)
                
        except asyncio.CancelledError:
            logger.info("Background audio task cancelled")
        except Exception as e:
            logger.error(f"Fatal error in background audio stream: {e}")
            import traceback
            traceback.print_exc()
        finally:
            elapsed = time.time() - (last_log_time if last_log_time else time.time())
            logger.info(f"{call_type} background audio stream ended. "
                    f"Frames sent: {frame_count}, Failures: {consecutive_failures}")

    
    def _is_connection_active(self):
        """Check if connection is still active - SIMPLIFIED VERSION"""
        # Simplified check - don't be too aggressive about stopping background audio
        if self.cleanup_started or self.force_stop or self.call_ended:
            return False
            
        # Don't check WebSocket state here as it can be unreliable
        # Let the background audio continue and handle failures gracefully
        return True



    def _is_connection_active(self):
        """Check if connection is still active - SIMPLIFIED VERSION"""
        # Simplified check - don't be too aggressive about stopping background audio
        if self.cleanup_started or self.force_stop or self.call_ended:
            return False
            
        # Don't check WebSocket state here as it can be unreliable
        # Let the background audio continue and handle failures gracefully
        return True

    async def _handle_plivo_event(self, event_type):
        """Handle Plivo events"""
        call_type = "OUTBOUND" if self.outbound_agent_exists else "INBOUND"
        logger.info(f"📱 {call_type} Plivo event: {event_type}")
        
        if event_type == "call_ended":
            logger.warning(f"🔴 Received call_ended event from Plivo for {call_type} call")
            self.call_termination_reason = "plivo_call_ended"
            await self._terminate_call_immediately("Plivo call ended")
    
    async def cleanup(self):
        """Enhanced cleanup with improved call termination"""
        if self.cleanup_started:
            logger.info("🔄 Cleanup already in progress, skipping...")
            return
            
        self.cleanup_started = True
        self.force_stop = True
        self.call_ended = True
        
        call_type = "OUTBOUND" if self.outbound_agent_exists else "INBOUND"
        logger.warning(f"🧹 Starting ENHANCED cleanup for {call_type} call...")
        
        # STEP 1: Stop agent monitoring (only for inbound calls)
        if hasattr(self, 'agent_monitor') and self.agent_monitor:
            logger.info("🔄 Stopping agent connection monitor...")
            self.agent_monitor.stop_monitoring()
        
        # STEP 2: Cancel all audio tasks immediately
        await self._cancel_all_audio_tasks()
        
        # STEP 3: Stop audio processor
        logger.info("🔇 Stopping audio processor...")
        if self.audio_processor:
            pass
            # self.audio_processor.stop()
        
        # STEP 4: Disconnect from LiveKit (signals agent)
        logger.info("🔗 Disconnecting from LiveKit...")
        try:
            await asyncio.wait_for(self.livekit_manager.disconnect(), timeout=3.0)
            logger.info("✅ LiveKit disconnected")
        except asyncio.TimeoutError:
            logger.warning("⏰ LiveKit disconnect timed out")
        except Exception as e:
            logger.error(f"❌ Error disconnecting from LiveKit: {e}")

        self.cleanup_started = True

        if self.background_stream_task and not self.background_stream_task.done():
            try:
                await asyncio.wait_for(self.background_stream_task, timeout=3.0)
                logger.info("Background audio ended gracefully")
            except asyncio.TimeoutError:
                self.background_stream_task.cancel()
                logger.info("Background audio cancelled after timeout")

        # STEP 6: Final audio processor cleanup
        if self.audio_processor:
            self.audio_processor.stop()
        
        # STEP 5: Cleanup audio components
        cleanup_tasks = []
        
        if self.audio_source:
            cleanup_tasks.append(self.audio_source.cleanup())
        if self.audio_processor:
            cleanup_tasks.append(self.audio_processor.cleanup())
        
        if cleanup_tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*cleanup_tasks, return_exceptions=True), timeout=2.0)
                logger.info("✅ Audio components cleaned up")
            except asyncio.TimeoutError:
                logger.warning("⏰ Audio cleanup timed out")
        
        # STEP 6: Log final statistics
        await self._log_session_summary()
        
        logger.warning(f"✅ ENHANCED cleanup complete for {call_type} call - terminated properly")
    
    async def _log_session_summary(self):
        """Log session summary statistics"""
        elapsed = time.time() - self.connection_start_time
        dropped_frames = getattr(self, 'dropped_frames', 0)
        plivo_stats = self.plivo_handler.get_call_stats()
        call_type = "OUTBOUND" if self.outbound_agent_exists else "INBOUND"
        
        logger.info(f"📊 {call_type} Call Session Summary:")
        logger.info(f"   Duration: {elapsed:.1f}s")
        logger.info(f"   Call Type: {call_type}")
        logger.info(f"   Termination reason: {self.call_termination_reason}")
        logger.info(f"   Messages: {plivo_stats['messages_received']} received, {plivo_stats['messages_sent']} sent")
        logger.info(f"   Audio to LiveKit: {self.stats['audio_frames_sent_to_livekit']} frames, {self.stats['bytes_from_telephony']} bytes")
        logger.info(f"   Audio from Agent: {self.stats['audio_frames_received_from_agent']} frames, {self.stats['bytes_to_telephony']} bytes")
        logger.info(f"   Dropped frames: {dropped_frames}")
        logger.info(f"   Agent: {'Found' if self.agent_participant else 'Not found'}")
        if self.outbound_agent_exists:
            logger.info(f"   Agent Status: Connected to existing agent '{self.agent_name}'")