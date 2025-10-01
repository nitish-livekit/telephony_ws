"""
Real-time noise suppression using noisereduce
Toggleable via NOISE_CANCELLATION_ENABLED environment variable
"""
import numpy as np
import logging
from collections import deque

logger = logging.getLogger(__name__)


class NoiseSuppressionProcessor:
    """Streaming noise suppression with minimal latency"""
    
    def __init__(self, enabled=True, sample_rate=8000, stationary=True, 
                 prop_decrease=0.8, learning_frames=25):
        self.enabled = enabled
        self.sample_rate = sample_rate
        self.stationary = stationary
        self.prop_decrease = prop_decrease
        
        # For noise profile learning
        self.noise_profile_buffer = deque(maxlen=50)  # ~1 second at 20ms chunks
        self.noise_profile = None
        self.frames_processed = 0
        self.learning_frames = learning_frames if stationary else 0
        
        # Stats
        self.total_processed = 0
        self.errors = 0
        
        # noisereduce module
        self.nr = None
        self.nr_loaded = False
        
        if self.enabled:
            self._load_noisereduce()
        else:
            logger.info("🔇 Noise Cancellation: DISABLED (NOISE_CANCELLATION_ENABLED=false)")
    
    def _load_noisereduce(self):
        """Load noisereduce library"""
        try:
            import noisereduce as nr
            self.nr = nr
            self.nr_loaded = True
            
            logger.info(f"✅ Noise suppression loaded: {self.sample_rate}Hz")
            logger.info(f"   Mode: {'Stationary' if self.stationary else 'Adaptive'}")
            logger.info(f"   Aggressiveness: {self.prop_decrease}")
            if self.stationary:
                logger.info(f"   Learning frames: {self.learning_frames}")
                
        except ImportError:
            logger.error("❌ noisereduce not installed! Install with: pip install noisereduce")
            logger.error("❌ Noise cancellation will be disabled")
            self.enabled = False
            self.nr_loaded = False
        except Exception as e:
            logger.error(f"❌ Failed to load noisereduce: {e}")
            logger.error("❌ Noise cancellation will be disabled")
            self.enabled = False
            self.nr_loaded = False
    
    def process_chunk(self, audio_pcm_int16):
        """
        Apply noise reduction to audio chunk
        
        Args:
            audio_pcm_int16: PCM int16 audio (bytes or numpy array)
            
        Returns:
            Processed audio as int16 bytes (or original if disabled/error)
        """
        # If disabled, return original
        if not self.enabled or not self.nr_loaded:
            return audio_pcm_int16
        
        try:
            # Convert to numpy
            if isinstance(audio_pcm_int16, bytes):
                audio_np = np.frombuffer(audio_pcm_int16, dtype=np.int16)
            else:
                audio_np = audio_pcm_int16.copy()
            
            # Normalize to float
            audio_float = audio_np.astype(np.float32) / 32768.0
            
            self.frames_processed += 1
            self.total_processed += 1
            
            # Build noise profile in early frames (stationary mode)
            if self.stationary and self.frames_processed <= self.learning_frames:
                self.noise_profile_buffer.append(audio_float)
                
                # Log learning progress
                if self.frames_processed == 1:
                    logger.info(f"🎯 Learning noise profile for {self.learning_frames} frames...")
                elif self.frames_processed == self.learning_frames:
                    logger.info(f"✅ Noise profile learning complete")
                
                return audio_pcm_int16  # Return original during learning
            
            # Create noise profile if needed
            if self.stationary and self.noise_profile is None and len(self.noise_profile_buffer) > 0:
                self.noise_profile = np.concatenate(list(self.noise_profile_buffer))
                logger.info(f"🎯 Noise profile created from {len(self.noise_profile)} samples")
            
            # Apply noise reduction
            if self.stationary and self.noise_profile is not None:
                reduced = self.nr.reduce_noise(
                    y=audio_float,
                    sr=self.sample_rate,
                    y_noise=self.noise_profile,
                    stationary=True,
                    prop_decrease=self.prop_decrease
                )
            else:
                # Non-stationary mode (adaptive)
                reduced = self.nr.reduce_noise(
                    y=audio_float,
                    sr=self.sample_rate,
                    stationary=False,
                    prop_decrease=self.prop_decrease * 0.75  # Less aggressive for adaptive
                )
            
            # Convert back to int16
            reduced_int16 = (reduced * 32768.0).astype(np.int16)
            
            # Log occasionally
            if self.total_processed % 500 == 0:
                logger.info(f"🔇 Noise suppression: {self.total_processed} frames processed, {self.errors} errors")
            
            return reduced_int16.tobytes()
            
        except Exception as e:
            self.errors += 1
            if self.errors <= 5:  # Only log first few errors
                logger.error(f"❌ Noise suppression error: {e}")
            return audio_pcm_int16  # Return original on error
    
    def reset(self):
        """Reset noise suppression state (e.g., between calls)"""
        self.noise_profile_buffer.clear()
        self.noise_profile = None
        self.frames_processed = 0
        logger.info("🔄 Noise suppression state reset")
    
    def get_status(self):
        """Get noise suppression status"""
        return {
            "enabled": self.enabled,
            "loaded": self.nr_loaded,
            "stationary": self.stationary,
            "prop_decrease": self.prop_decrease,
            "learning_frames": self.learning_frames,
            "frames_processed": self.frames_processed,
            "total_processed": self.total_processed,
            "errors": self.errors,
            "noise_profile_ready": self.noise_profile is not None
        }