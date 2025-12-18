# Drawful Party Game

A multiplayer drawing and guessing party game built with Flask and Socket.IO.

## Project Structure

The project has been refactored into a modular architecture for better maintainability:

```
drawful/
├── config.py              # Game configuration constants
├── game_state.py          # Game state management and logic
├── prompt_manager.py      # Prompt loading and rotation
├── timer.py              # Timer utilities for game phases
├── server.py             # Main Flask server (NEW - recommended)
├── drawful.py            # Original monolithic file (still works)
├── unused_prompts.txt    # Available prompts
├── used_prompts.txt      # Already used prompts
└── prompts.txt           # Original prompts backup
```

## Game Configuration

All game settings can be easily adjusted in `config.py`:

### Timing Settings
```python
DRAWING_TIME = 60        # Seconds for drawing phase
GUESSING_TIME = 20       # Seconds for guessing phase
TITLE_CARD_DURATION = 3  # Duration for phase transitions
```

### Game Rules
```python
MIN_PLAYERS = 3          # Minimum players to start
MAX_PLAYERS = 80         # Maximum players allowed
NUM_ROUNDS = 1           # Number of rounds per game
```

### Server Settings
```python
DEFAULT_PORT = 5001      # Server port
HOSTNAME = "mac.lan"     # Your hostname for network URL
```

## Running the Game

### Option 1: New Modular Server (Recommended)
```bash
python server.py
```

### Option 2: Original Monolithic File
```bash
python drawful.py
```

Both options will start the server and display:
- Game configuration
- Local URL (for testing)
- Network URL (for other players to join)

## How to Play

1. **Start the server** on one computer
2. **Join the game** - Other players scan the QR code or visit the network URL
3. **Drawing Phase** - All players simultaneously draw their assigned prompts
4. **Guessing Phase** - Players guess what each drawing represents
5. **Voting Phase** - Vote for the real prompt and like your favorites
6. **Results** - See scores and who fooled who
7. **Repeat** for 3 rounds, then see final winners!

## Scoring

- **1000 points** - Correctly guessing the real prompt
- **500 points** - Someone votes for your fake answer
- **500 points** - (Artist) For each player who correctly guesses your drawing
- **Likes** - Separate leaderboard for most creative/funny answers

## Features

### Drawing Tools
- **Player-specific colors** - Each player has unique light and dark shades
- **Pen tool** for freehand drawing
- **Fill tool** with smart tolerance
- **Eraser** for corrections
- **Undo button** (up to 20 states)
- **Adjustable brush size**
- **Clear canvas** option
- **Add time** button (+30 seconds)

### Game Mechanics
- **Simultaneous drawing** - All players draw at once
- **Consecutive guessing** - One drawing at a time
- **Artist can like** prompts on their own drawing (but can't vote)
- **Duplicate prevention** - Can't submit same prompt as existing guess or real answer
- **Case-insensitive** comparison for all prompts
- **Auto-submit** - Empty submissions handled gracefully when timers expire
- **Voting timer** - 15 seconds to vote, auto-submits for missing players
- **Unanimous continue** - All players must click continue to proceed
- **Dramatic reveals** - White fade animation before showing correct answers
- **Disconnect handling** - Game progresses when players disconnect
- **Duplicate prevention** - Players can't submit multiple drawings/guesses/votes

### UI/UX
- **Player-specific theming** - All UI elements use each player's assigned colors
- **Typography** - Adobe Typekit fonts (Mrs Eaves, Futura PT)
- **Title cards** - 1-second transitions between game phases
- **Round display** - Always shows current round number
- **Player name** - Displayed in top-right corner with player's color
- **QR code** - Easy joining for mobile devices
- **Mobile optimized** - Double-tap zoom disabled, centered canvas at 70vh
- **Responsive design** - Works on desktop and mobile
- **Voting details** - Shows who wrote what and who voted for what
- **Final results** - All players ranked with tie handling
- **Dynamic waiting screens** - Shows how many players still need to submit

## Module Descriptions

### `config.py`
Central configuration file. Modify values here to change game behavior without touching code logic.

### `game_state.py`
Encapsulates all game state and provides clean methods for:
- Adding/removing players
- Starting new rounds
- Checking completion status
- Calculating scores
- Managing player order

### `prompt_manager.py`
Handles prompt file operations:
- Loading prompts from files
- Moving prompts from unused to used
- Getting random prompts
- Case-insensitive prompt management

### `timer.py`
Reusable timer class with:
- Start/stop functionality
- Tick callbacks for UI updates
- Expiration callbacks for phase transitions
- Add time support

### `server.py`
Main Flask application that:
- Coordinates all modules
- Handles Socket.IO events
- Manages game flow
- Serves web interface

## Development

### Adding New Prompts
Add prompts to `unused_prompts.txt`, one per line. The game will automatically move them to `used_prompts.txt` as they're used.

### Changing Game Duration
Edit `config.py`:
```python
DRAWING_TIME = 90  # Longer drawing time
GUESSING_TIME = 30 # More time to guess
NUM_ROUNDS = 5     # More rounds
```

### Adjusting Player Limits
Edit `config.py`:
```python
MIN_PLAYERS = 2  # Allow 2 player games
MAX_PLAYERS = 12 # Support more players
```

### Adding More Colors
Edit `config.py` `PLAYER_COLORS` list:
```python
PLAYER_COLORS = [
    {"light": "#COLOR1", "dark": "#COLOR2"},
    # Add more color pairs...
]
```

## Dependencies

```
flask>=3.0.0
flask-socketio>=5.3.0
qrcode>=7.4.0
pillow>=10.0.0
```

Install with:
```bash
pip install flask flask-socketio qrcode pillow
```

Or:
```bash
uv pip install .
```

## Technical Details

- **Backend**: Flask + Flask-SocketIO
- **Frontend**: Vanilla JavaScript + Socket.IO client
- **Real-time**: WebSocket communication
- **Canvas**: HTML5 Canvas API for drawing
- **State Management**: Server-side authoritative game state
- **Timer Sync**: Server-controlled timers with client display

## Troubleshooting

### Players can't join
- Check firewall settings
- Ensure all devices are on same WiFi network
- Verify the network URL is accessible

### Timer doesn't work
- Check that timers are server-controlled
- Verify Socket.IO connection is stable

### Prompts not loading
- Ensure `unused_prompts.txt` exists and has content
- Check file encoding is UTF-8
- Verify file permissions

## Future Enhancements

Potential improvements:
- Save/load game state
- Player avatars
- Chat system
- Custom prompt packs
- Drawing replay animations
- More drawing tools (shapes, stamps)
- Theming support
- Localization

## License

Party game for educational and entertainment purposes.
