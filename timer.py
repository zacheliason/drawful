"""
Timer management for game phases.
"""
import threading
import time
import config


class Timer:
    """Manages a countdown timer for game phases."""
    
    def __init__(self, duration, on_tick=None, on_expire=None):
        """
        Initialize a timer.
        
        Args:
            duration: Timer duration in seconds
            on_tick: Callback function called each second with time_remaining
            on_expire: Callback function called when timer expires
        """
        self.duration = duration
        self.time_remaining = duration
        self.active = False
        self.thread = None
        self.on_tick = on_tick
        self.on_expire = on_expire
    
    def start(self):
        """Start the timer."""
        self.time_remaining = self.duration
        self.active = True
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._countdown, daemon=True)
            self.thread.start()
    
    def stop(self):
        """Stop the timer."""
        self.active = False
    
    def add_time(self, seconds):
        """Add additional time to the timer."""
        if self.active:
            self.time_remaining += seconds
    
    def _countdown(self):
        """Internal countdown loop."""
        while self.active and self.time_remaining > 0:
            if self.on_tick:
                self.on_tick(self.time_remaining)
            time.sleep(1)
            self.time_remaining -= 1
        
        if self.active and self.time_remaining <= 0:
            self.active = False
            if self.on_expire:
                self.on_expire()
