# """
# Configuration management for the Telephony-LiveKit Bridge
# """
# import os
# import logging
# from dotenv import load_dotenv
# import os

# load_dotenv()

# # Environment variables
# LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "wss://setupforretell-hk7yl5xf.livekit.cloud")
# LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY", "APIoLr2sRCRJWY5")
# LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET", "yE3wUkoQxjWjhteMAed9ubm5mYg3iOfPT6qBQfffzgJC")
# CALLBACK_WS_URL = os.environ.get("CALLBACK_WS_URL", "ws://0.0.0.0:8765")

# # Audio configuration
# TELEPHONY_SAMPLE_RATE = 8000
# LIVEKIT_SAMPLE_RATE = 48000

# # Application configuration
# PARTICIPANT_NAME = "Telephony Caller"
# AGENT_NAME = "Mysyara Agent"  # outbound-caller / Mysyara Agent


# # Background noise configuration
# BG_NOISE_ENABLED = os.environ.get("BG_NOISE_ENABLED", "false").lower() == "true"
# NOISE_TYPE = os.environ.get("NOISE_TYPE", "call-center")  # call-center, ambience
# NOISE_VOLUME = float(os.environ.get("NOISE_VOLUME", "0.1"))  # 0.0 to 1.0
# NOISE_FOLDER = "noise"

# # Server configuration
# WEBSOCKET_HOST = "0.0.0.0"
# WEBSOCKET_PORT = 8765
# HTTP_HOST = "0.0.0.0"
# HTTP_PORT = 8080

# # Timeouts and limits
# LIVEKIT_CONNECTION_TIMEOUT = 3.0
# AGENT_DISPATCH_TIMEOUT = 0.5
# CLEANUP_TIMEOUT = 3.0

# # Logging configuration
# LOG_LEVEL = logging.INFO
# LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

# # Audio processing configuration
# AUDIO_LOG_FREQUENCY = 250  # Log every N frames
# MESSAGE_LOG_FREQUENCY = 50  # Log every N messages

# def validate_environment():
#     """Validate required environment variables"""
#     required_vars = ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"]
#     missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
#     if missing_vars:
#         raise ValueError(f"Missing required environment variables: {missing_vars}")
    
#     return True

# def setup_logging():
#     """Setup logging configuration"""
#     logging.basicConfig(
#         level=LOG_LEVEL,
#         format=LOG_FORMAT
#     )


"""
Configuration management for the Telephony-LiveKit Bridge
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

# NEW: Agent configuration from environment
DEFAULT_AGENT_NAME = os.environ.get("DEFAULT_AGENT_NAME", "Mysyara Agent")
# Support for backward compatibility
AGENT_NAME = os.environ.get("AGENT_NAME", DEFAULT_AGENT_NAME)

# NEW: Call acceptance control
ACCEPT_INCOMING_CALLS = os.environ.get("ACCEPT_INCOMING_CALLS", "true").lower() == "true"
REJECT_CALL_MESSAGE = os.environ.get("REJECT_CALL_MESSAGE", "Service temporarily unavailable")

# Background noise configuration
BG_NOISE_ENABLED = os.environ.get("BG_NOISE_ENABLED", "false").lower() == "true"
NOISE_TYPE = os.environ.get("NOISE_TYPE", "call-center")  # call-center, ambience
NOISE_VOLUME = float(os.environ.get("NOISE_VOLUME", "0.1"))  # 0.0 to 1.0
NOISE_FOLDER = "noise"

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
AUDIO_LOG_FREQUENCY = 250  # Log every N frames
MESSAGE_LOG_FREQUENCY = 50  # Log every N messages

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