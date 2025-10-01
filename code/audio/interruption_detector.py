"""
Interruption detection combining VAD + agent state
Toggleable via INTERRUPTION_DETECTION_ENABLED environment variable
"""
import logging
import time

logger = logging.getLogger(__name__)


class InterruptionDetector:
    """Detect user interruptions during agent speech"""
    
    def __init__(self, enabled=True, cooldown_ms=500):
        self.enabled = enabled
        self.cooldown_ms = cooldown_ms
        self.last_interruption_time = 0
        self.interruption_count = 0
        
        # Tracking
        self.total_checks = 0
        self.false_positives_prevented = 0  # Cooldown prevented
        
        if self.enabled:
            logger.info(f"✅ Interruption detection: ENABLED (cooldown={cooldown_ms}ms)")
        else:
            logger.info(f"🚫 Interruption detection: DISABLED")
    
    def check_interruption(self, vad_result, agent_is_speaking):
        """
        Check if user is interrupting agent
        
        Args:
            vad_result: Dict from VAD processor
            agent_is_speaking: Bool indicating if agent is currently speaking
            
        Returns:
            bool: True if interruption detected
        """
        self.total_checks += 1
        
        # If disabled, never detect interruptions
        if not self.enabled:
            return False
        
        # If VAD is disabled, can't detect interruptions
        if not vad_result.get("enabled", False):
            return False
        
        current_time = time.time() * 1000  # ms
        time_since_last = current_time - self.last_interruption_time
        
        # Check cooldown first
        in_cooldown = time_since_last < self.cooldown_ms
        
        # Only detect interruption if:
        # 1. Agent is speaking
        # 2. User speech just started (not continuing)
        # 3. Outside cooldown period
        user_speech_started = vad_result.get("speech_started", False)
        
        if agent_is_speaking and user_speech_started:
            if in_cooldown:
                # Cooldown prevented false positive
                self.false_positives_prevented += 1
                if self.false_positives_prevented <= 5:
                    logger.debug(f"🔇 Interruption cooldown active ({time_since_last:.0f}ms < {self.cooldown_ms}ms)")
                return False
            else:
                # Valid interruption detected!
                self.last_interruption_time = current_time
                self.interruption_count += 1
                
                logger.warning(f"🚨 INTERRUPTION #{self.interruption_count} DETECTED")
                logger.warning(f"   Agent was speaking: {agent_is_speaking}")
                logger.warning(f"   User confidence: {vad_result.get('confidence', 0):.3f}")
                logger.warning(f"   Time since last: {time_since_last:.0f}ms")
                
                return True
        
        return False
    
    def get_stats(self):
        """Get interruption statistics"""
        current_time = time.time() * 1000
        time_since_last = current_time - self.last_interruption_time if self.last_interruption_time > 0 else None
        
        return {
            "enabled": self.enabled,
            "total_interruptions": self.interruption_count,
            "total_checks": self.total_checks,
            "false_positives_prevented": self.false_positives_prevented,
            "last_interruption_ms_ago": time_since_last,
            "cooldown_ms": self.cooldown_ms
        }
    
    def reset(self):
        """Reset interruption detection state (e.g., between calls)"""
        self.last_interruption_time = 0
        self.interruption_count = 0
        self.total_checks = 0
        self.false_positives_prevented = 0
        logger.info("🔄 Interruption detection state reset")
    
    def get_status(self):
        """Get current status"""
        return {
            "enabled": self.enabled,
            "cooldown_ms": self.cooldown_ms,
            "interruptions_detected": self.interruption_count
        }