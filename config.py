"""
Game configuration constants.
Adjust these values to customize game behavior.
"""

# Game Timing (in seconds)
DRAWING_TIME = 10
GUESSING_TIME = 10
VOTING_TIME = 15
TITLE_CARD_DURATION = 1  # Duration for phase transition title cards

# Game Rules
MIN_PLAYERS = 3
MAX_PLAYERS = 80
NUM_ROUNDS = 1

# Server Configuration
DEFAULT_PORT = 5001
HOSTNAME = "mac.lan"

# Socket.IO Configuration
PING_TIMEOUT = 60
PING_INTERVAL = 25

# File Paths
UNUSED_PROMPTS_FILE = "unused_prompts.txt"
USED_PROMPTS_FILE = "used_prompts.txt"

# Player Colors - each player gets a unique hue with light and dark shades
PLAYER_COLORS = [
    {"light": "#FF6B6B", "dark": "#C92A2A"},  # Red
    {"light": "#4DABF7", "dark": "#1864AB"},  # Blue
    {"light": "#51CF66", "dark": "#046113"},  # Green
    {"light": "#FFD43B", "dark": "#F08C00"},  # Yellow
    {"light": "#FF9F40", "dark": "#E67700"},  # Orange
    {"light": "#FF6BFF", "dark": "#C92AC9"},  # Magenta
    {"light": "#FFA07A", "dark": "#ff4f00"},  # Orange theme
    {"light": "#66D9E8", "dark": "#0B7285"},  # Cyan
]

# Canvas Configuration
CANVAS_UNDO_STACK_SIZE = 20
FILL_TOLERANCE = 50
