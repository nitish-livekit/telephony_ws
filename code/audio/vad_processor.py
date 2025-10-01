"""
Silero VAD with audio buffering for minimum chunk size
FIXED: Buffers small chunks to meet Silero's 256-sample minimum
"""
import logging
import numpy as np
from collections import deque

logger = logging.getLogger(__name__)


class SileroVADProcessor:
    """Streaming VAD processor with audio buffering"""
    
    def __init__(self, enabled=True, threshold=0.5, speech_frames=3, silence_frames=10, sample_rate=8000):
        self.enabled = enabled
        self.sample_rate = sample_rate
        self.threshold = threshold
        
        # Configuration for interruption detection
        self.speech_threshold_frames = speech_frames
        self.silence_threshold_frames = silence_frames
        
        # Speech detection state
        self.is_speaking = False
        self.speech_frames = 0
        self.silence_frames = 0
        
        # Audio buffering for minimum chunk size
        # Silero needs at least 256 samples (32ms at 8kHz)
        self.min_samples = 256
        self.audio_buffer = np.array([], dtype=np.float32)
        
        # Model (only load if enabled)
        self.model = None
        self.model_loaded = False
        
        if self.enabled:
            self._load_model()
        else:
            logger.info("🎤 VAD: DISABLED (VAD_ENABLED=false)")
    
    def _load_model(self):
        """Load Silero VAD model"""
        try:
            import torch
            
            logger.info("🎤 Loading Silero VAD model...")
            
            # Load Silero VAD model
            self.model, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                onnx=False
            )
            
            self.model_loaded = True
            logger.info(f"✅ Silero VAD loaded: {self.sample_rate}Hz, threshold={self.threshold}")
            logger.info(f"   Min chunk size: {self.min_samples} samples ({self.min_samples/self.sample_rate*1000:.1f}ms)")
            logger.info(f"   Speech trigger: {self.speech_threshold_frames} frames")
            logger.info(f"   Silence trigger: {self.silence_threshold_frames} frames")
            
        except ImportError:
            logger.error("❌ PyTorch not installed! Install with: pip install torch")
            logger.error("❌ VAD will be disabled")
            self.enabled = False
            self.model_loaded = False
        except Exception as e:
            logger.error(f"❌ Failed to load Silero VAD: {e}")
            logger.error("❌ VAD will be disabled")
            self.enabled = False
            self.model_loaded = False
    
    def process_chunk(self, audio_pcm_int16):
        """
        Process audio chunk with buffering for minimum size
        
        Args:
            audio_pcm_int16: PCM audio as int16 numpy array or bytes
            
        Returns:
            dict with VAD result (or neutral if buffering)
        """
        # If disabled, return neutral result
        if not self.enabled or not self.model_loaded:
            return self._neutral_result()
        
        try:
            import torch
            
            # Convert to numpy if bytes
            if isinstance(audio_pcm_int16, bytes):
                audio_np = np.frombuffer(audio_pcm_int16, dtype=np.int16)
            else:
                audio_np = audio_pcm_int16
            
            # Normalize to float32 [-1, 1]
            audio_float = audio_np.astype(np.float32) / 32768.0
            
            # Add to buffer
            self.audio_buffer = np.concatenate([self.audio_buffer, audio_float])
            
            # If buffer is still too small, return neutral result
            if len(self.audio_buffer) < self.min_samples:
                return self._neutral_result()
            
            # Process buffered audio in chunks
            result = self._neutral_result()
            
            while len(self.audio_buffer) >= self.min_samples:
                # Take minimum chunk size
                chunk = self.audio_buffer[:self.min_samples]
                self.audio_buffer = self.audio_buffer[self.min_samples:]
                
                # Convert to torch tensor
                audio_tensor = torch.from_numpy(chunk)
                
                # Get VAD probability
                speech_prob = self.model(audio_tensor, self.sample_rate).item()
                
                is_speech = speech_prob >= self.threshold
                
                # Update result with this chunk's analysis
                result = self._update_speech_state(is_speech, speech_prob)
            
            return result
            
        except Exception as e:
            logger.error(f"❌ VAD processing error: {e}")
            return self._neutral_result()
    
    def _update_speech_state(self, is_speech, speech_prob):
        """Update speech state machine"""
        speech_started = False
        speech_ended = False
        
        if is_speech:
            self.speech_frames += 1
            self.silence_frames = 0
            
            # Detect speech start
            if not self.is_speaking and self.speech_frames >= self.speech_threshold_frames:
                self.is_speaking = True
                speech_started = True
                logger.info(f"🎤 USER SPEECH STARTED (confidence: {speech_prob:.3f})")
        else:
            self.silence_frames += 1
            self.speech_frames = 0
            
            # Detect speech end
            if self.is_speaking and self.silence_frames >= self.silence_threshold_frames:
                self.is_speaking = False
                speech_ended = True
                logger.info(f"🔇 USER SPEECH ENDED")
        
        return {
            "enabled": True,
            "is_speech": is_speech,
            "confidence": speech_prob,
            "speech_started": speech_started,
            "speech_ended": speech_ended,
            "user_speaking": self.is_speaking
        }
    
    def _neutral_result(self):
        """Return neutral result when buffering or disabled"""
        return {
            "enabled": self.enabled,
            "is_speech": False,
            "confidence": 0.0,
            "speech_started": False,
            "speech_ended": False,
            "user_speaking": self.is_speaking  # Keep current state
        }
    
    def reset(self):
        """Reset VAD state (e.g., between calls)"""
        if self.model_loaded and self.model:
            self.model.reset_states()
        
        self.is_speaking = False
        self.speech_frames = 0
        self.silence_frames = 0
        self.audio_buffer = np.array([], dtype=np.float32)
        logger.info("🔄 VAD state reset")
    
    def get_status(self):
        """Get VAD status"""
        return {
            "enabled": self.enabled,
            "model_loaded": self.model_loaded,
            "threshold": self.threshold,
            "speech_threshold_frames": self.speech_threshold_frames,
            "silence_threshold_frames": self.silence_threshold_frames,
            "currently_speaking": self.is_speaking,
            "buffer_samples": len(self.audio_buffer),
            "min_samples": self.min_samples
        }