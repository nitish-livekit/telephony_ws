
"""
Configuration management - WITH VAD AND NOISE CANCELLATION CONTROLS
"""
import os
import logging
from dotenv import load_dotenv

load_dotenv()

# Environment variables
LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "wss://setupforretell-hk7yl5xf.livekit.cloud")
LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY", "APIoLr2sRCRJWY5")
LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET", "yE3wUkoQxjWjhteMAed9ubm5mYg3iOfPT6qBQfffzgJC")
CALLBACK_WS_URL = os.environ.get("CALLBACK_WS_URL", "ws://0.0.0.0:8765")

# Audio configuration
TELEPHONY_SAMPLE_RATE = 8000
LIVEKIT_SAMPLE_RATE = 48000

# Application configuration
PARTICIPANT_NAME = "Telephony Caller"

# Agent configuration
DEFAULT_AGENT_NAME = os.environ.get("DEFAULT_AGENT_NAME", "Mysyara Agent")
AGENT_NAME = os.environ.get("AGENT_NAME", DEFAULT_AGENT_NAME)

# Call acceptance control
ACCEPT_INCOMING_CALLS = os.environ.get("ACCEPT_INCOMING_CALLS", "true").lower() == "true"
REJECT_CALL_MESSAGE = os.environ.get("REJECT_CALL_MESSAGE", "Service temporarily unavailable")

# Background noise configuration
BG_NOISE_ENABLED = os.environ.get("BG_NOISE_ENABLED", "true").lower() == "true"
NOISE_TYPE = os.environ.get("NOISE_TYPE", "call-center")
NOISE_VOLUME = float(os.environ.get("NOISE_VOLUME", "0.15"))
NOISE_FOLDER = "noise"

# ============================================
# NEW: VAD (Voice Activity Detection) Settings
# ============================================
VAD_ENABLED = os.environ.get("VAD_ENABLED", "true").lower() == "true"
VAD_THRESHOLD = float(os.environ.get("VAD_THRESHOLD", "0.5"))  # 0.0 to 1.0
VAD_SPEECH_FRAMES = int(os.environ.get("VAD_SPEECH_FRAMES", "3"))  # Frames to trigger speech start
VAD_SILENCE_FRAMES = int(os.environ.get("VAD_SILENCE_FRAMES", "10"))  # Frames to trigger speech end

# ============================================
# NEW: Noise Cancellation Settings
# ============================================
NOISE_CANCELLATION_ENABLED = os.environ.get("NOISE_CANCELLATION_ENABLED", "true").lower() == "true"
NC_STATIONARY = os.environ.get("NC_STATIONARY", "true").lower() == "true"  # Stationary vs adaptive
NC_PROP_DECREASE = float(os.environ.get("NC_PROP_DECREASE", "0.8"))  # 0.0 to 1.0 (aggressiveness)
NC_LEARNING_FRAMES = int(os.environ.get("NC_LEARNING_FRAMES", "25"))  # Frames for noise profile

# ============================================
# NEW: Interruption Detection Settings
# ============================================
INTERRUPTION_DETECTION_ENABLED = os.environ.get("INTERRUPTION_DETECTION_ENABLED", "true").lower() == "true"
INTERRUPTION_COOLDOWN_MS = int(os.environ.get("INTERRUPTION_COOLDOWN_MS", "500"))  # Cooldown between detections
INTERRUPTION_SIGNAL_AGENT = os.environ.get("INTERRUPTION_SIGNAL_AGENT", "true").lower() == "true"  # Send to agent?

# Server configuration
WEBSOCKET_HOST = "0.0.0.0"
WEBSOCKET_PORT = 8765
HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8080

# Timeouts and limits
LIVEKIT_CONNECTION_TIMEOUT = 3.0
AGENT_DISPATCH_TIMEOUT = 0.5
CLEANUP_TIMEOUT = 3.0

# Logging configuration
LOG_LEVEL = logging.INFO
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

# Audio processing configuration
AUDIO_LOG_FREQUENCY = 250
MESSAGE_LOG_FREQUENCY = 50


def validate_environment():
    """Validate required environment variables"""
    required_vars = ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"]
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {missing_vars}")
    
    return True


def setup_logging():
    """Setup logging configuration"""
    logging.basicConfig(
        level=LOG_LEVEL,
        format=LOG_FORMAT
    )


def get_agent_name(custom_agent_name=None):
    """Get agent name with priority: custom > env > default"""
    if custom_agent_name:
        return custom_agent_name
    return AGENT_NAME


def should_accept_call():
    """Check if incoming calls should be accepted"""
    return ACCEPT_INCOMING_CALLS


def get_reject_message():
    """Get the rejection message for calls"""
    return REJECT_CALL_MESSAGE


def get_vad_config():
    """Get VAD configuration"""
    return {
        "enabled": VAD_ENABLED,
        "threshold": VAD_THRESHOLD,
        "speech_frames": VAD_SPEECH_FRAMES,
        "silence_frames": VAD_SILENCE_FRAMES
    }


def get_noise_cancellation_config():
    """Get noise cancellation configuration"""
    return {
        "enabled": NOISE_CANCELLATION_ENABLED,
        "stationary": NC_STATIONARY,
        "prop_decrease": NC_PROP_DECREASE,
        "learning_frames": NC_LEARNING_FRAMES
    }


def get_interruption_config():
    """Get interruption detection configuration"""
    return {
        "enabled": INTERRUPTION_DETECTION_ENABLED,
        "cooldown_ms": INTERRUPTION_COOLDOWN_MS,
        "signal_agent": INTERRUPTION_SIGNAL_AGENT
    }


# Log configuration on import
if __name__ != "__main__":
    logger = logging.getLogger(__name__)
    logger.info(f"🔊 Background Noise: enabled={BG_NOISE_ENABLED}, type={NOISE_TYPE}, volume={NOISE_VOLUME}")
    logger.info(f"🎤 VAD: enabled={VAD_ENABLED}, threshold={VAD_THRESHOLD}")
    logger.info(f"🔇 Noise Cancellation: enabled={NOISE_CANCELLATION_ENABLED}, stationary={NC_STATIONARY}")
    logger.info(f"🚨 Interruption Detection: enabled={INTERRUPTION_DETECTION_ENABLED}, cooldown={INTERRUPTION_COOLDOWN_MS}ms")