"""
Background noise manager - provides raw chunks for mixing
"""
import os
import logging
import subprocess
import tempfile
import wave
import audioop
import threading
import array
from pathlib import Path
from config import (
    BG_NOISE_ENABLED, NOISE_TYPE, NOISE_VOLUME, NOISE_FOLDER,
    TELEPHONY_SAMPLE_RATE
)

logger = logging.getLogger(__name__)


class NoiseManager:
    """Manages background noise for mixing"""
    
    def __init__(self):
        self.enabled = BG_NOISE_ENABLED
        self.noise_type = NOISE_TYPE
        self.volume = NOISE_VOLUME
        self.noise_data = None
        self.current_position = 0
        self.is_running = False
        self.lock = threading.Lock()
        
        logger.info(f"🔊 NoiseManager: enabled={self.enabled}, "
                   f"type={self.noise_type}, volume={self.volume}")
        
        if self.enabled:
            self._load_noise_file()
    
    def _load_noise_file(self):
        """Load noise file using FFmpeg"""
        try:
            noise_file = Path(NOISE_FOLDER) / f"{self.noise_type}.mp3"
            
            if not noise_file.exists():
                logger.error(f"❌ Noise file not found: {noise_file}")
                self.enabled = False
                return
            
            logger.info(f"🔊 Loading: {noise_file}")
            
            # Create temp WAV
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                temp_path = temp_file.name
            
            try:
                # Convert with FFmpeg
                result = subprocess.run([
                    'ffmpeg', '-i', str(noise_file),
                    '-ar', str(TELEPHONY_SAMPLE_RATE),
                    '-ac', '1',
                    '-f', 'wav',
                    '-y',
                    temp_path
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode != 0:
                    logger.error(f"❌ FFmpeg failed: {result.stderr}")
                    self.enabled = False
                    return
                
                # Read WAV file
                with wave.open(temp_path, 'rb') as wav_file:
                    if wav_file.getnchannels() != 1:
                        logger.error("❌ Must be mono")
                        self.enabled = False
                        return
                    
                    if wav_file.getframerate() != TELEPHONY_SAMPLE_RATE:
                        logger.error(f"❌ Must be {TELEPHONY_SAMPLE_RATE}Hz")
                        self.enabled = False
                        return
                    
                    # Read PCM data
                    pcm_data = wav_file.readframes(wav_file.getnframes())
                    
                    # Convert to μ-law
                    self.noise_data = audioop.lin2ulaw(pcm_data, 2)
                    
                    duration = len(pcm_data) / (2 * TELEPHONY_SAMPLE_RATE)
                    logger.info(f"✅ Loaded: {len(self.noise_data)} bytes, {duration:.1f}s")
                
            finally:
                try:
                    os.unlink(temp_path)
                except:
                    pass
                    
        except subprocess.TimeoutExpired:
            logger.error("❌ FFmpeg timeout")
            self.enabled = False
        except FileNotFoundError:
            logger.error("❌ FFmpeg not found - install: sudo apt install ffmpeg")
            self.enabled = False
        except Exception as e:
            logger.error(f"❌ Error loading: {e}")
            import traceback
            traceback.print_exc()
            self.enabled = False
    
    def _get_noise_chunk(self, chunk_size):
        """Get noise chunk with looping"""
        if not self.noise_data:
            return None
        
        data_len = len(self.noise_data)
        
        # Loop if reached end
        if self.current_position >= data_len:
            self.current_position = 0
        
        # Get chunk with wrap-around
        if self.current_position + chunk_size <= data_len:
            chunk = self.noise_data[self.current_position:self.current_position + chunk_size]
            self.current_position += chunk_size
        else:
            # Wrap around
            first_part = self.noise_data[self.current_position:]
            remaining = chunk_size - len(first_part)
            second_part = self.noise_data[:remaining]
            chunk = first_part + second_part
            self.current_position = remaining
        
        return chunk
    
    def get_background_chunk_raw(self, chunk_size):
        """Get RAW background chunk (no volume applied - for mixing)"""
        if not self.enabled or not self.noise_data:
            return None
        
        with self.lock:
            return self._get_noise_chunk(chunk_size)
    
    def get_background_chunk(self, chunk_size):
        """Get background chunk with volume applied (for separate streaming)"""
        if not self.enabled or not self.noise_data:
            return None
        
        with self.lock:
            noise_chunk = self._get_noise_chunk(chunk_size)
            
            if noise_chunk and self.volume > 0:
                try:
                    # Convert to PCM
                    pcm_data = audioop.ulaw2lin(noise_chunk, 2)
                    samples = array.array('h')
                    samples.frombytes(pcm_data)
                    
                    # Apply volume
                    volume_adjusted = array.array('h')
                    for sample in samples:
                        adjusted = int(sample * self.volume)
                        adjusted = max(-32768, min(32767, adjusted))
                        volume_adjusted.append(adjusted)
                    
                    # Convert back to μ-law
                    adjusted_pcm = volume_adjusted.tobytes()
                    adjusted_mulaw = audioop.lin2ulaw(adjusted_pcm, 2)
                    return adjusted_mulaw
                    
                except Exception as e:
                    logger.error(f"❌ Error adjusting volume: {e}")
                    return noise_chunk
            
            return noise_chunk
    
    def update_settings(self, noise_type=None, volume=None, enabled=None):
        """Update settings"""
        if enabled is not None:
            self.enabled = enabled
        
        if volume is not None:
            self.volume = max(0.0, min(10.0, volume))
            logger.info(f"🔊 Volume: {self.volume}")
        
        if noise_type is not None and noise_type != self.noise_type:
            self.noise_type = noise_type
            logger.info(f"🔊 Switching to: {noise_type}")
            if self.enabled:
                self._load_noise_file()
    
    def start(self):
        """Start background noise"""
        self.is_running = True
        logger.info(f"🎵 Started at volume {self.volume}")
    
    def stop(self):
        """Stop background noise"""
        self.is_running = False
        logger.info("🔇 Stopped")
    
    def get_status(self):
        """Get status"""
        return {
            "enabled": self.enabled,
            "noise_type": self.noise_type,
            "volume": self.volume,
            "ffmpeg_available": self._check_ffmpeg(),
            "noise_loaded": self.noise_data is not None,
            "noise_samples": len(self.noise_data) if self.noise_data is not None else 0,
            "is_running": self.is_running
        }
    
    def _check_ffmpeg(self):
        """Check FFmpeg"""
        try:
            result = subprocess.run(['ffmpeg', '-version'], 
                                  capture_output=True, timeout=5)
            return result.returncode == 0
        except:
            return False