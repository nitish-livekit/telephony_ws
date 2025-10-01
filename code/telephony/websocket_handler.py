# """
# WebSocket handler - Mix agent + background THEN send as ONE stream
# """
# import asyncio
# import time
# import logging
# import websockets
# from livekit import rtc

# from audio.telephony_audio_source import TelephonyAudioSource
# from audio.audio_processor import AudioProcessor
# from lk_utils.livekit_manager import LiveKitManager
# from agents.agent_manager import AgentManager
# from telephony.plivo_handler import PlivoMessageHandler
# from telephony.agent_monitor import AgentConnectionMonitor

# logger = logging.getLogger(__name__)


# class TelephonyWebSocketHandler:
#     """WebSocket handler - ONE mixed stream to Plivo"""
    
#     def __init__(self, room_name, websocket, agent_name=None, noise_settings=None):
#         self.room_name = room_name
#         self.websocket = websocket
#         self.agent_name = agent_name
#         self.connection_start_time = time.time()
        
#         self.outbound_agent_exists = False
        
#         # Component managers
#         self.livekit_manager = LiveKitManager(room_name)
#         self.agent_manager = AgentManager()
#         self.plivo_handler = PlivoMessageHandler()
#         self.audio_processor = AudioProcessor()
        
#         # Agent monitoring
#         self.agent_monitor = None
        
#         # Apply noise settings
#         if noise_settings:
#             self.audio_processor.update_noise_settings(**noise_settings)
        
#         # Audio components
#         self.audio_source = None
#         self.audio_track = None
#         self.audio_stream_task = None
#         self.agent_is_speaking = False
        
#         # Call state
#         self.cleanup_started = False
#         self.force_stop = False
#         self.call_termination_reason = None
#         self.call_ended = False
        
#         # Participant tracking
#         self.agent_participant = None
#         self.participants = {}
#         self.audio_tracks = {}
        
#         # Statistics
#         self.stats = {
#             "audio_frames_sent_to_livekit": 0,
#             "audio_frames_received_from_agent": 0,
#             "bytes_from_telephony": 0,
#             "bytes_to_telephony": 0,
#             "mixed_frames_sent": 0,
#         }
        
#         logger.info(f"🆕 Handler created for room: {room_name}")
        
#         # Log noise status
#         noise_status = self.audio_processor.get_noise_status()
#         if noise_status["enabled"]:
#             logger.info(f"🔊 Background: {noise_status['noise_type']} at {noise_status['volume']}")
#             logger.info(f"🎯 Mode: Pre-mix agent + background, send ONE stream")
    
#     async def initialize(self):
#         """Initialize handler"""
#         logger.info(f"🚀 Initializing...")
        
#         # Start background audio
#         noise_status = self.audio_processor.get_noise_status()
#         if noise_status["enabled"]:
#             logger.info("🎵 Background noise ready for mixing...")
#             self.audio_processor.start_background_audio()
        
#         if self.outbound_agent_exists:
#             livekit_task = asyncio.create_task(self._setup_livekit())
#             message_task = asyncio.create_task(self._handle_messages())
            
#             try:
#                 await asyncio.wait_for(livekit_task, timeout=8.0)
#             except:
#                 pass
            
#             return message_task
            
#         else:
#             self.agent_monitor = AgentConnectionMonitor(self, timeout_seconds=5)
            
#             livekit_task = asyncio.create_task(self._setup_livekit())
#             agent_task = asyncio.create_task(
#                 self.agent_manager.trigger_agent(self.room_name, self.agent_name)
#             )
#             message_task = asyncio.create_task(self._handle_messages())
#             monitor_task = asyncio.create_task(self.agent_monitor.start_monitoring())
            
#             try:
#                 await asyncio.wait_for(livekit_task, timeout=8.0)
#                 await asyncio.wait_for(agent_task, timeout=2.0)
#             except:
#                 pass
            
#             return message_task

#     async def _setup_livekit(self):
#         event_handlers = {
#             'on_connected': self._on_livekit_connected,
#             'on_disconnected': self._on_livekit_disconnected,
#             'on_participant_connected': self._on_participant_connected,
#             'on_participant_disconnected': self._on_participant_disconnected,
#             'on_track_subscribed': self._on_track_subscribed,
#         }
        
#         success = await self.livekit_manager.connect_to_room(event_handlers)
        
#         if success:
#             await self._setup_audio_track()
        
#         return success
    
#     async def _setup_audio_track(self):
#         self.audio_source = TelephonyAudioSource()
#         self.audio_track = rtc.LocalAudioTrack.create_audio_track(
#             "telephony-audio", 
#             self.audio_source
#         )
        
#         await self.livekit_manager.publish_audio_track(self.audio_track)
    
#     def _on_livekit_connected(self):
#         logger.info(f"✅ LiveKit connected")
        
#         for participant in self.livekit_manager.get_remote_participants().values():
#             self._handle_participant_joined(participant)
    
#     def _on_livekit_disconnected(self):
#         if not self.cleanup_started and not self.call_ended:
#             asyncio.create_task(self._terminate_call_immediately("LiveKit disconnected"))
    
#     def _on_participant_connected(self, participant):
#         self._handle_participant_joined(participant)
    
#     def _on_participant_disconnected(self, participant):
#         if participant.identity in self.participants:
#             del self.participants[participant.identity]
        
#         if participant == self.agent_participant:
#             logger.warning("🤖 Agent disconnected")
#             asyncio.create_task(self._terminate_call_immediately("Agent disconnected"))
    
#     async def _terminate_call_immediately(self, reason):
#         if self.call_ended:
#             return
            
#         self.call_ended = True
#         self.force_stop = True
        
#         logger.warning(f"🔚 Terminating: {reason}")
        
#         if self.audio_stream_task and not self.audio_stream_task.done():
#             self.audio_stream_task.cancel()
        
#         try:
#             if self.websocket and not self.websocket.closed:
#                 await self.websocket.close(code=1000, reason=reason)
#         except:
#             pass
        
#         asyncio.create_task(self.cleanup())
    
#     def _on_track_subscribed(self, track, publication, participant):
#         if self.call_ended or self.cleanup_started:
#             return
        
#         if track.kind == rtc.TrackKind.KIND_AUDIO:
#             if self.agent_manager.is_agent_participant(participant):
#                 logger.info(f"🤖 Agent audio track")
#                 self.agent_participant = participant
#                 self._start_mixed_agent_stream(track)
    
#     def _handle_participant_joined(self, participant):
#         if self.call_ended:
#             return
        
#         self.participants[participant.identity] = participant
        
#         if self.agent_manager.is_agent_participant(participant):
#             self.agent_participant = participant
            
#             if hasattr(self, 'agent_monitor') and self.agent_monitor:
#                 self.agent_monitor.notify_agent_connected()
            
#             for track in self.agent_manager.find_agent_audio_tracks(participant):
#                 self._start_mixed_agent_stream(track)
    
#     def _start_mixed_agent_stream(self, track):
#         if self.cleanup_started or self.force_stop or self.call_ended:
#             return
            
#         if self.audio_stream_task and not self.audio_stream_task.done():
#             self.audio_stream_task.cancel()
        
#         self.agent_is_speaking = True
#         logger.info("🔊 Starting agent stream with background mixing")
        
#         self.audio_stream_task = asyncio.create_task(
#             self._stream_mixed_audio(track)
#         )
    
#     async def _stream_mixed_audio(self, audio_track):
#         """Stream agent audio MIXED with background - ONE stream to Plivo"""
#         logger.info(f"🔊 Starting mixed stream (agent + background)")
        
#         frame_count = 0
#         last_log_time = time.time()
        
#         try:
#             audio_stream = rtc.AudioStream(audio_track)
            
#             async for audio_frame_event in audio_stream:
#                 if self.cleanup_started or self.force_stop or self.call_ended:
#                     break
                
#                 current_time = time.time()
#                 frame_count += 1
                
#                 if current_time - last_log_time >= 2.0:
#                     logger.info(f"🔊 Mixed stream: {frame_count} frames")
#                     last_log_time = current_time
                
#                 try:
#                     # Convert agent audio to telephony
#                     telephony_chunks = self.audio_processor.convert_livekit_to_telephony(
#                         audio_frame_event.frame
#                     )
                    
#                     # Mix each chunk with background BEFORE sending
#                     for agent_chunk in telephony_chunks:
#                         if self.cleanup_started or self.call_ended:
#                             break
                        
#                         # Get matching background chunk
#                         bg_chunk = self.audio_processor.get_background_audio_chunk(len(agent_chunk))
                        
#                         # Mix agent + background
#                         if bg_chunk:
#                             mixed_chunk = self.audio_processor.mix_audio_chunks(
#                                 agent_chunk, bg_chunk
#                             )
#                         else:
#                             mixed_chunk = agent_chunk
                        
#                         # Send ONE mixed stream to Plivo
#                         await self.plivo_handler.send_audio_to_plivo(
#                             self.websocket, mixed_chunk
#                         )
                        
#                         self.stats["mixed_frames_sent"] += 1
                        
#                 except Exception as e:
#                     logger.error(f"❌ Frame error: {e}")
#                     continue
                    
#         except Exception as e:
#             logger.error(f"❌ Stream error: {e}")
#         finally:
#             self.agent_is_speaking = False
#             logger.info(f"🔇 Mixed stream ended: {frame_count} frames")
    
#     async def _handle_messages(self):
#         try:
#             async for message in self.websocket:
#                 if self.cleanup_started or self.call_ended:
#                     break
                    
#                 await self.plivo_handler.handle_message(
#                     message,
#                     audio_callback=self._handle_user_audio,
#                     event_callback=self._handle_plivo_event,
#                     websocket_handler=self
#                 )
                        
#         except websockets.ConnectionClosed:
#             if not self.call_ended:
#                 self.call_ended = True
#         finally:
#             if not self.cleanup_started:
#                 await self.cleanup()
    
#     async def _handle_user_audio(self, audio_data):
#         """User audio to agent (clean, no background)"""
#         if self.cleanup_started or self.call_ended:
#             return
            
#         if self.audio_source and self.livekit_manager.is_connected():
#             try:
#                 await self.audio_source.push_audio_data(audio_data)
#                 self.stats["audio_frames_sent_to_livekit"] += 1
#             except Exception as e:
#                 logger.error(f"❌ Error: {e}")

#     async def _handle_plivo_event(self, event_type):
#         if event_type == "call_ended":
#             await self._terminate_call_immediately("Plivo call ended")
    
#     async def cleanup(self):
#         if self.cleanup_started:
#             return
            
#         self.cleanup_started = True
#         self.force_stop = True
#         self.call_ended = True
        
#         logger.warning(f"🧹 Cleanup...")
        
#         if hasattr(self, 'agent_monitor') and self.agent_monitor:
#             self.agent_monitor.stop_monitoring()
        
#         if self.audio_stream_task and not self.audio_stream_task.done():
#             self.audio_stream_task.cancel()
        
#         if self.audio_processor:
#             self.audio_processor.stop()
        
#         try:
#             await asyncio.wait_for(self.livekit_manager.disconnect(), timeout=3.0)
#         except:
#             pass
        
#         logger.warning(f"✅ Cleanup complete")



"""
WebSocket handler - WITH VAD, NOISE CANCELLATION, AND INTERRUPTION DETECTION
Audio flow:
1. User audio (μ-law) → PCM
2. Noise cancellation (if enabled)
3. VAD processing (if enabled)
4. Interruption detection (if enabled)
5. Clean audio → μ-law → LiveKit (agent)
6. Agent audio → Background mixing → Plivo
"""
import asyncio
import time
import logging
import websockets
import audioop
from livekit import rtc

from audio.telephony_audio_source import TelephonyAudioSource
from audio.audio_processor import AudioProcessor
from audio.vad_processor import SileroVADProcessor
from audio.noise_suppression import NoiseSuppressionProcessor
from audio.interruption_detector import InterruptionDetector
from lk_utils.livekit_manager import LiveKitManager
from agents.agent_manager import AgentManager
from telephony.plivo_handler import PlivoMessageHandler
from telephony.agent_monitor import AgentConnectionMonitor
from config import (
    get_vad_config, get_noise_cancellation_config, get_interruption_config
)

logger = logging.getLogger(__name__)


class TelephonyWebSocketHandler:
    """WebSocket handler with VAD, noise cancellation, and interruption detection"""
    
    def __init__(self, room_name, websocket, agent_name=None, noise_settings=None):
        self.room_name = room_name
        self.websocket = websocket
        self.agent_name = agent_name
        self.connection_start_time = time.time()
        
        self.outbound_agent_exists = False
        
        # Component managers
        self.livekit_manager = LiveKitManager(room_name)
        self.agent_manager = AgentManager()
        self.plivo_handler = PlivoMessageHandler()
        self.audio_processor = AudioProcessor()
        
        # Agent monitoring
        self.agent_monitor = None
        
        # Apply background noise settings
        if noise_settings:
            self.audio_processor.update_noise_settings(**noise_settings)
        
        # ============================================
        # NEW: Initialize VAD, Noise Cancellation, and Interruption Detection
        # ============================================
        vad_config = get_vad_config()
        nc_config = get_noise_cancellation_config()
        int_config = get_interruption_config()
        
        # VAD Processor
        self.vad_processor = SileroVADProcessor(
            enabled=vad_config["enabled"],
            threshold=vad_config["threshold"],
            speech_frames=vad_config["speech_frames"],
            silence_frames=vad_config["silence_frames"],
            sample_rate=8000  # Telephony rate
        )
        
        # Noise Suppression
        self.noise_suppressor = NoiseSuppressionProcessor(
            enabled=nc_config["enabled"],
            sample_rate=8000,
            stationary=nc_config["stationary"],
            prop_decrease=nc_config["prop_decrease"],
            learning_frames=nc_config["learning_frames"]
        )
        
        # Interruption Detector
        self.interruption_detector = InterruptionDetector(
            enabled=int_config["enabled"],
            cooldown_ms=int_config["cooldown_ms"]
        )
        
        self.interruption_signal_agent = int_config["signal_agent"]
        
        # Log configuration
        logger.info(f"🆕 Handler created for room: {room_name}")
        logger.info(f"   🎤 VAD: {vad_config['enabled']}")
        logger.info(f"   🔇 Noise Cancellation: {nc_config['enabled']}")
        logger.info(f"   🚨 Interruption Detection: {int_config['enabled']}")
        
        # Audio components
        self.audio_source = None
        self.audio_track = None
        self.audio_stream_task = None
        self.agent_is_speaking = False
        
        # Call state
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
            "mixed_frames_sent": 0,
            "vad_speech_frames": 0,
            "vad_silence_frames": 0,
            "noise_cancelled_frames": 0,
            "interruptions_detected": 0
        }
        
        # Log noise status
        noise_status = self.audio_processor.get_noise_status()
        if noise_status["enabled"]:
            logger.info(f"🔊 Background: {noise_status['noise_type']} at {noise_status['volume']}")
    
    async def initialize(self):
        """Initialize handler"""
        logger.info(f"🚀 Initializing...")
        
        # Start background audio
        noise_status = self.audio_processor.get_noise_status()
        if noise_status["enabled"]:
            logger.info("🎵 Background noise ready for mixing...")
            self.audio_processor.start_background_audio()
        
        if self.outbound_agent_exists:
            livekit_task = asyncio.create_task(self._setup_livekit())
            message_task = asyncio.create_task(self._handle_messages())
            
            try:
                await asyncio.wait_for(livekit_task, timeout=8.0)
            except:
                pass
            
            return message_task
            
        else:
            self.agent_monitor = AgentConnectionMonitor(self, timeout_seconds=5)
            
            livekit_task = asyncio.create_task(self._setup_livekit())
            agent_task = asyncio.create_task(
                self.agent_manager.trigger_agent(self.room_name, self.agent_name)
            )
            message_task = asyncio.create_task(self._handle_messages())
            monitor_task = asyncio.create_task(self.agent_monitor.start_monitoring())
            
            try:
                await asyncio.wait_for(livekit_task, timeout=8.0)
                await asyncio.wait_for(agent_task, timeout=2.0)
            except:
                pass
            
            return message_task

    async def _setup_livekit(self):
        event_handlers = {
            'on_connected': self._on_livekit_connected,
            'on_disconnected': self._on_livekit_disconnected,
            'on_participant_connected': self._on_participant_connected,
            'on_participant_disconnected': self._on_participant_disconnected,
            'on_track_subscribed': self._on_track_subscribed,
        }
        
        success = await self.livekit_manager.connect_to_room(event_handlers)
        
        if success:
            await self._setup_audio_track()
        
        return success
    
    async def _setup_audio_track(self):
        self.audio_source = TelephonyAudioSource()
        self.audio_track = rtc.LocalAudioTrack.create_audio_track(
            "telephony-audio", 
            self.audio_source
        )
        
        await self.livekit_manager.publish_audio_track(self.audio_track)
    
    def _on_livekit_connected(self):
        logger.info(f"✅ LiveKit connected")
        
        for participant in self.livekit_manager.get_remote_participants().values():
            self._handle_participant_joined(participant)
    
    def _on_livekit_disconnected(self):
        if not self.cleanup_started and not self.call_ended:
            asyncio.create_task(self._terminate_call_immediately("LiveKit disconnected"))
    
    def _on_participant_connected(self, participant):
        self._handle_participant_joined(participant)
    
    def _on_participant_disconnected(self, participant):
        if participant.identity in self.participants:
            del self.participants[participant.identity]
        
        if participant == self.agent_participant:
            logger.warning("🤖 Agent disconnected")
            asyncio.create_task(self._terminate_call_immediately("Agent disconnected"))
    
    async def _terminate_call_immediately(self, reason):
        if self.call_ended:
            return
            
        self.call_ended = True
        self.force_stop = True
        
        logger.warning(f"🔚 Terminating: {reason}")
        
        if self.audio_stream_task and not self.audio_stream_task.done():
            self.audio_stream_task.cancel()
        
        try:
            if self.websocket and not self.websocket.closed:
                await self.websocket.close(code=1000, reason=reason)
        except:
            pass
        
        asyncio.create_task(self.cleanup())
    
    def _on_track_subscribed(self, track, publication, participant):
        if self.call_ended or self.cleanup_started:
            return
        
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            if self.agent_manager.is_agent_participant(participant):
                logger.info(f"🤖 Agent audio track")
                self.agent_participant = participant
                self._start_mixed_agent_stream(track)
    
    def _handle_participant_joined(self, participant):
        if self.call_ended:
            return
        
        self.participants[participant.identity] = participant
        
        if self.agent_manager.is_agent_participant(participant):
            self.agent_participant = participant
            
            if hasattr(self, 'agent_monitor') and self.agent_monitor:
                self.agent_monitor.notify_agent_connected()
            
            for track in self.agent_manager.find_agent_audio_tracks(participant):
                self._start_mixed_agent_stream(track)
    
    def _start_mixed_agent_stream(self, track):
        if self.cleanup_started or self.force_stop or self.call_ended:
            return
            
        if self.audio_stream_task and not self.audio_stream_task.done():
            self.audio_stream_task.cancel()
        
        self.agent_is_speaking = True
        logger.info("🔊 Starting agent stream with background mixing")
        
        self.audio_stream_task = asyncio.create_task(
            self._stream_mixed_audio(track)
        )
    
    async def _stream_mixed_audio(self, audio_track):
        """Stream agent audio MIXED with background - ONE stream to Plivo"""
        logger.info(f"🔊 Starting mixed stream (agent + background)")
        
        frame_count = 0
        last_log_time = time.time()
        
        try:
            audio_stream = rtc.AudioStream(audio_track)
            
            async for audio_frame_event in audio_stream:
                if self.cleanup_started or self.force_stop or self.call_ended:
                    break
                
                current_time = time.time()
                frame_count += 1
                
                if current_time - last_log_time >= 2.0:
                    logger.info(f"🔊 Mixed stream: {frame_count} frames")
                    last_log_time = current_time
                
                try:
                    # Convert agent audio to telephony
                    telephony_chunks = self.audio_processor.convert_livekit_to_telephony(
                        audio_frame_event.frame
                    )
                    
                    # Mix each chunk with background BEFORE sending
                    for agent_chunk in telephony_chunks:
                        if self.cleanup_started or self.call_ended:
                            break
                        
                        # Get matching background chunk
                        bg_chunk = self.audio_processor.get_background_audio_chunk(len(agent_chunk))
                        
                        # Mix agent + background
                        if bg_chunk:
                            mixed_chunk = self.audio_processor.mix_audio_chunks(
                                agent_chunk, bg_chunk
                            )
                        else:
                            mixed_chunk = agent_chunk
                        
                        # Send ONE mixed stream to Plivo
                        await self.plivo_handler.send_audio_to_plivo(
                            self.websocket, mixed_chunk
                        )
                        
                        self.stats["mixed_frames_sent"] += 1
                        
                except Exception as e:
                    logger.error(f"❌ Frame error: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"❌ Stream error: {e}")
        finally:
            self.agent_is_speaking = False
            logger.info(f"🔇 Mixed stream ended: {frame_count} frames")
    
    async def _handle_messages(self):
        try:
            async for message in self.websocket:
                if self.cleanup_started or self.call_ended:
                    break
                    
                await self.plivo_handler.handle_message(
                    message,
                    audio_callback=self._handle_user_audio,
                    event_callback=self._handle_plivo_event,
                    websocket_handler=self
                )
                        
        except websockets.ConnectionClosed:
            if not self.call_ended:
                self.call_ended = True
        finally:
            if not self.cleanup_started:
                await self.cleanup()
    
    async def _handle_user_audio(self, audio_data):
        """
        User audio processing pipeline with VAD and noise cancellation
        Flow: μ-law → PCM → Noise Cancel → VAD → Interruption → μ-law → Agent
        """
        if self.cleanup_started or self.call_ended:
            return
            
        if not self.audio_source or not self.livekit_manager.is_connected():
            return
        
        try:
            # Step 1: Convert μ-law to PCM for processing
            pcm_data = audioop.ulaw2lin(audio_data, 2)
            
            # Step 2: Apply noise cancellation (if enabled)
            if self.noise_suppressor.enabled:
                clean_pcm = self.noise_suppressor.process_chunk(pcm_data)
                self.stats["noise_cancelled_frames"] += 1
            else:
                clean_pcm = pcm_data
            
            # Step 3: Run VAD on clean audio (if enabled)
            vad_result = self.vad_processor.process_chunk(clean_pcm)
            
            if vad_result["is_speech"]:
                self.stats["vad_speech_frames"] += 1
            else:
                self.stats["vad_silence_frames"] += 1
            
            # Step 4: Check for interruptions (if enabled)
            if self.interruption_detector.enabled:
                interruption = self.interruption_detector.check_interruption(
                    vad_result, 
                    self.agent_is_speaking
                )
                
                if interruption:
                    self.stats["interruptions_detected"] += 1
                    
                    # Send interruption signal to agent (if configured)
                    if self.interruption_signal_agent:
                        await self._signal_agent_interruption()
            
            # Step 5: Convert back to μ-law for LiveKit
            clean_mulaw = audioop.lin2ulaw(clean_pcm, 2)
            
            # Step 6: Send clean audio to LiveKit (agent hears clean audio)
            await self.audio_source.push_audio_data(clean_mulaw)
            self.stats["audio_frames_sent_to_livekit"] += 1
            
            # Step 7: Log stats occasionally
            if self.stats["audio_frames_sent_to_livekit"] % 500 == 0:
                self._log_processing_stats()
                
        except Exception as e:
            logger.error(f"❌ Error processing user audio: {e}")

    def _log_processing_stats(self):
        """Log audio processing statistics"""
        total_vad = self.stats["vad_speech_frames"] + self.stats["vad_silence_frames"]
        speech_ratio = (self.stats["vad_speech_frames"] / total_vad * 100) if total_vad > 0 else 0
        
        logger.info(f"📊 Processing stats:")
        logger.info(f"   Frames processed: {self.stats['audio_frames_sent_to_livekit']}")
        logger.info(f"   Noise cancelled: {self.stats['noise_cancelled_frames']}")
        logger.info(f"   VAD speech: {self.stats['vad_speech_frames']} ({speech_ratio:.1f}%)")
        logger.info(f"   Interruptions: {self.stats['interruptions_detected']}")
    
    async def _signal_agent_interruption(self):
        """Send interruption signal to LiveKit agent via data channel"""
        try:
            if self.livekit_manager.is_connected():
                room = self.livekit_manager.get_room()
                if room:
                    # Send data packet to agent
                    await room.local_participant.publish_data(
                        payload=b'{"type":"interruption","timestamp":' + str(time.time()).encode() + b'}',
                        kind=rtc.DataPacketKind.KIND_RELIABLE
                    )
                    logger.info("📨 Interruption signal sent to agent via data channel")
            
        except Exception as e:
            logger.error(f"❌ Error signaling interruption: {e}")

    async def _handle_plivo_event(self, event_type):
        if event_type == "call_ended":
            await self._terminate_call_immediately("Plivo call ended")
    
    async def cleanup(self):
        if self.cleanup_started:
            return
            
        self.cleanup_started = True
        self.force_stop = True
        self.call_ended = True
        
        logger.warning(f"🧹 Cleanup starting...")
        
        # Stop agent monitor
        if hasattr(self, 'agent_monitor') and self.agent_monitor:
            self.agent_monitor.stop_monitoring()
        
        # Cancel audio stream
        if self.audio_stream_task and not self.audio_stream_task.done():
            self.audio_stream_task.cancel()
        
        # Stop audio processor
        if self.audio_processor:
            self.audio_processor.stop()
        
        # Reset VAD/NC/Interruption states
        if self.vad_processor:
            self.vad_processor.reset()
        if self.noise_suppressor:
            self.noise_suppressor.reset()
        if self.interruption_detector:
            self.interruption_detector.reset()
        
        # Disconnect LiveKit
        try:
            await asyncio.wait_for(self.livekit_manager.disconnect(), timeout=3.0)
        except:
            pass
        
        # Log final stats
        self._log_final_stats()
        
        logger.warning(f"✅ Cleanup complete")
    
    def _log_final_stats(self):
        """Log final call statistics"""
        duration = time.time() - self.connection_start_time
        
        logger.info(f"📊 Final Call Statistics:")
        logger.info(f"   Duration: {duration:.1f}s")
        logger.info(f"   Frames to LiveKit: {self.stats['audio_frames_sent_to_livekit']}")
        logger.info(f"   Mixed frames sent: {self.stats['mixed_frames_sent']}")
        
        if self.noise_suppressor.enabled:
            logger.info(f"   Noise cancelled: {self.stats['noise_cancelled_frames']}")
        
        if self.vad_processor.enabled:
            total_vad = self.stats["vad_speech_frames"] + self.stats["vad_silence_frames"]
            speech_ratio = (self.stats["vad_speech_frames"] / total_vad * 100) if total_vad > 0 else 0
            logger.info(f"   VAD speech frames: {self.stats['vad_speech_frames']} ({speech_ratio:.1f}%)")
        
        if self.interruption_detector.enabled:
            logger.info(f"   Interruptions detected: {self.stats['interruptions_detected']}")