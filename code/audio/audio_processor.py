"""
Audio processing with proper mixing - agent + background
"""
import audioop
import numpy as np
import logging
import array
from livekit import rtc
from config import TELEPHONY_SAMPLE_RATE, LIVEKIT_SAMPLE_RATE
from audio.noise_manager import NoiseManager

logger = logging.getLogger(__name__)


class AudioProcessor:
    """Handles audio conversion and mixing"""
    
    def __init__(self):
        self.return_resampler = rtc.AudioResampler(
            input_rate=LIVEKIT_SAMPLE_RATE,
            output_rate=TELEPHONY_SAMPLE_RATE,
            num_channels=1,
            quality=rtc.AudioResamplerQuality.HIGH
        )
        self.noise_manager = NoiseManager()
        self.is_active = True
        
        # Log status
        status = self.noise_manager.get_status()
        logger.info(f"🔊 AudioProcessor: noise enabled={status['enabled']}, "
                   f"type={status.get('noise_type', 'N/A')}, "
                   f"volume={status.get('volume', 'N/A')}")
        
    def convert_livekit_to_telephony(self, audio_frame):
        """Convert LiveKit audio to telephony μ-law"""
        if not self.is_active:
            return []
            
        try:
            resampled_frames = self.return_resampler.push(audio_frame)
            
            telephony_audio_data = []
            
            for resampled_frame in resampled_frames:
                if not self.is_active:
                    break
                    
                # Convert to PCM bytes
                pcm_bytes = bytes(resampled_frame.data[:resampled_frame.samples_per_channel * 2])
                
                # Convert to μ-law
                mulaw_bytes = audioop.lin2ulaw(pcm_bytes, 2)
                
                telephony_audio_data.append(mulaw_bytes)
                
            return telephony_audio_data
            
        except Exception as e:
            logger.error(f"❌ Error converting audio: {e}")
            return []
    
    def mix_audio_chunks(self, agent_mulaw, background_mulaw):
        """Mix agent audio with background audio (both in μ-law format)"""
        if not agent_mulaw:
            return background_mulaw
        if not background_mulaw:
            return agent_mulaw
        
        try:
            # Convert both to PCM
            agent_pcm = audioop.ulaw2lin(agent_mulaw, 2)
            bg_pcm = audioop.ulaw2lin(background_mulaw, 2)
            
            # Ensure same length
            agent_len = len(agent_pcm)
            bg_len = len(bg_pcm)
            
            if bg_len < agent_len:
                # Repeat background if too short
                repetitions = (agent_len // bg_len) + 1
                bg_pcm = (bg_pcm * repetitions)[:agent_len]
            elif bg_len > agent_len:
                # Truncate background if too long
                bg_pcm = bg_pcm[:agent_len]
            
            # Convert to sample arrays
            agent_samples = array.array('h')
            bg_samples = array.array('h')
            
            agent_samples.frombytes(agent_pcm)
            bg_samples.frombytes(bg_pcm)
            
            # Mix samples - agent at full volume, background at configured volume
            mixed_samples = array.array('h')
            bg_volume = self.noise_manager.volume if self.noise_manager else 0.15
            
            for i in range(len(agent_samples)):
                agent_sample = agent_samples[i]
                bg_sample = int(bg_samples[i] * bg_volume)
                
                # Simple addition
                mixed_sample = agent_sample + bg_sample
                
                # Clamp to prevent clipping
                if mixed_sample > 32767:
                    mixed_sample = 32767
                elif mixed_sample < -32768:
                    mixed_sample = -32768
                
                mixed_samples.append(mixed_sample)
            
            # Convert back to μ-law
            mixed_pcm = mixed_samples.tobytes()
            mixed_mulaw = audioop.lin2ulaw(mixed_pcm, 2)
            
            return mixed_mulaw
            
        except Exception as e:
            logger.error(f"❌ Error mixing audio: {e}")
            return agent_mulaw
    
    def validate_audio_data(self, audio_data):
        """Validate audio data"""
        if not self.is_active:
            return False
            
        if not audio_data or len(audio_data) == 0:
            return False
            
        return True
    
    def stop(self):
        """Stop audio processor"""
        logger.info("🛑 Stopping audio processor...")
        self.is_active = False
        
        if self.noise_manager:
            self.noise_manager.stop()
        
        logger.info("✅ Audio processor stopped")
    
    async def cleanup(self):
        """Cleanup resources"""
        try:
            self.stop()
            
            if hasattr(self.return_resampler, 'aclose'):
                await self.return_resampler.aclose()
            elif hasattr(self.return_resampler, 'close'):
                self.return_resampler.close()
                
            logger.info("✅ Audio processor cleanup complete")
        except Exception as e:
            logger.error(f"❌ Error cleaning up: {e}")

    def update_noise_settings(self, **kwargs):
        """Update background noise settings"""
        if self.noise_manager:
            self.noise_manager.update_settings(**kwargs)
            
            status = self.noise_manager.get_status()
            logger.info(f"🔊 Noise settings updated: enabled={status['enabled']}, "
                       f"type={status.get('noise_type', 'N/A')}, "
                       f"volume={status.get('volume', 'N/A')}")

    def get_background_audio_chunk(self, chunk_size):
        """Get background audio chunk for mixing"""
        if not self.is_active or not self.noise_manager or not self.noise_manager.enabled:
            return None
            
        # Get raw background chunk (volume will be applied during mixing)
        chunk = self.noise_manager.get_background_chunk_raw(chunk_size)
        
        return chunk

    def start_background_audio(self):
        """Start background audio"""
        if self.noise_manager:
            self.noise_manager.start()
            status = self.noise_manager.get_status()
            logger.info(f"🎵 Background audio started: {status}")
    
    def get_noise_status(self):
        """Get noise manager status"""
        if self.noise_manager:
            status = self.noise_manager.get_status()
            status["processor_active"] = self.is_active
            return status
        return {
            "enabled": False,
            "processor_active": self.is_active
        }