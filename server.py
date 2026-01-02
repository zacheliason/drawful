"""
Main Flask server for Drawful game.
Coordinates game logic, socket events, and serves the web interface.
"""
import logging
import random
import secrets
import socket as socket_module
import sys
import warnings
from io import BytesIO

import qrcode
from flask import Flask, render_template, request, send_file
from flask_socketio import SocketIO, emit

# Import our modularized components
import config
from game_state import game_state
from prompt_manager import get_random_prompt, load_prompts
from timer import Timer

# Suppress socket connection errors from logging
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# Initialize Flask app
app = Flask(__name__)
app.config["SECRET_KEY"] = secrets.token_hex(16)
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    logger=False,
    engineio_logger=False,
    ping_timeout=config.PING_TIMEOUT,
    ping_interval=config.PING_INTERVAL,
)

# Get local IP for game URL — prefer the active LAN interface IP.
# Binding uses 0.0.0.0 so we need a routable IP for the QR/printed GAME_URL.
LOCAL_IP = "127.0.0.1"
try:
    # If a HOSTNAME is explicitly configured and resolves to a non-loopback
    # address, use it. Otherwise fall back to probing the active interface.
    hostname = getattr(config, "HOSTNAME", None)
    if hostname:
        try:
            resolved = socket_module.gethostbyname(hostname)
            if resolved and not resolved.startswith("127."):
                LOCAL_IP = resolved
            else:
                raise Exception("resolved to loopback, use interface probe")
        except Exception:
            # Probe active interface by creating a UDP socket to a public IP.
            try:
                s = socket_module.socket(socket_module.AF_INET, socket_module.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                LOCAL_IP = s.getsockname()[0]
                s.close()
            except Exception:
                LOCAL_IP = "127.0.0.1"
    else:
        s = socket_module.socket(socket_module.AF_INET, socket_module.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        LOCAL_IP = s.getsockname()[0]
        s.close()
except Exception:
    LOCAL_IP = "127.0.0.1"

GAME_URL = f"https://{LOCAL_IP}:{config.DEFAULT_PORT}"

# Load prompts
PROMPT_BANK = load_prompts()

# Timer instances
drawing_timer = None
guessing_timer = None
voting_timer = None


def on_drawing_timer_tick(time_remaining):
    """Callback for drawing timer ticks."""
    socketio.emit("timer_tick", {"time": time_remaining})


def on_drawing_timer_expire():
    """Callback when drawing timer expires."""
    socketio.emit("timer_expired")


def on_guessing_timer_tick(time_remaining):
    """Callback for guessing timer ticks."""
    socketio.emit("guess_timer_tick", {"time": time_remaining})


def on_guessing_timer_expire():
    """Callback when guessing timer expires."""
    socketio.emit("guess_timer_expired")


def start_timer():
    """Start the drawing timer."""
    global drawing_timer
    drawing_timer = Timer(
        config.DRAWING_TIME,
        on_tick=on_drawing_timer_tick,
        on_expire=on_drawing_timer_expire
    )
    drawing_timer.start()


def stop_timer():
    """Stop the drawing timer."""
    if drawing_timer:
        drawing_timer.stop()


def start_guess_timer():
    """Start the guessing timer."""
    global guessing_timer
    guessing_timer = Timer(
        config.GUESSING_TIME,
        on_tick=on_guessing_timer_tick,
        on_expire=on_guessing_timer_expire
    )
    guessing_timer.start()


def stop_guess_timer():
    """Stop the guessing timer."""
    if guessing_timer:
        guessing_timer.stop()


def start_vote_timer():
    """Start timer for voting phase."""
    global voting_timer
    voting_timer = Timer(
        config.VOTING_TIME,
        on_tick=lambda t: socketio.emit("timer_tick", {"time": t}),
        on_expire=vote_time_up
    )
    voting_timer.start()


def stop_vote_timer():
    """Stop voting timer."""
    global voting_timer
    if voting_timer:
        voting_timer.stop()


def vote_time_up():
    """Called when voting timer expires - auto-submit for missing voters."""
    current_idx = game_state.current_drawing_index
    
    # Add empty votes for players who haven't voted
    for pid in game_state.players.keys():
        if not any(v["player_id"] == pid for v in game_state.votes[current_idx]):
            game_state.votes[current_idx].append({
                "player_id": pid,
                "vote": "",
                "likes": []
            })
    
    # Now all votes should be complete
    show_current_scores()


# Socket event handlers

@socketio.on("join")
def handle_join(data):
    """Handle player joining the game."""
    player_id = request.sid
    name = data["name"].strip()
    emoji = data.get("emoji", "😀")

    # Check if emoji is already taken by another player
    for pid, pdata in game_state.players.items():
        if pid != player_id and pdata.get("emoji") == emoji:
            emit("emoji_taken", {"message": f"Emoji {emoji} is already taken by {pdata['name']}!"})
            return

    # Check for reconnecting players
    for pid, pdata in list(game_state.players.items()):
        if pdata["name"].lower() == name.lower() and pid != player_id:
            # Check if new emoji is taken by someone else
            emoji_conflict = False
            for other_pid, other_pdata in game_state.players.items():
                if other_pid != pid and other_pid != player_id and other_pdata.get("emoji") == emoji:
                    emit("emoji_taken", {"message": f"Emoji {emoji} is already taken by {other_pdata['name']}!"})
                    emoji_conflict = True
                    break
            
            if emoji_conflict:
                return
            
            # Reassign session ID
            game_state.players[player_id] = pdata
            # Update emoji if reconnecting with different emoji
            game_state.players[player_id]["emoji"] = emoji
            del game_state.players[pid]
            
            emit(
                "joined",
                {
                    "player_id": player_id,
                    "colors": config.PLAYER_COLORS[pdata["color_index"]]
                }
            )
            return

    # New player
    player_data = game_state.add_player(player_id, name, emoji)
    
    if player_data is None:
        emit("game_in_progress")
        return
    
    emit(
        "joined",
        {
            "player_id": player_id,
            "colors": config.PLAYER_COLORS[player_data["color_index"]]
        }
    )
    
    # Update lobby for all players
    socketio.emit("update_lobby", {"players": game_state.players})


@socketio.on("disconnect")
def handle_disconnect():
    """Handle player disconnection."""
    player_id = request.sid
    game_state.remove_player(player_id)
    
    if game_state.phase == "lobby":
        socketio.emit("update_lobby", {"players": game_state.players})
    elif game_state.phase == "drawing":
        # Check if all remaining players have submitted
        if game_state.all_drawings_complete():
            stop_timer()
            game_state.current_drawing_index = 0
            start_guessing_for_current_drawing()
    elif game_state.phase == "guessing":
        # Check if all remaining players have submitted
        if game_state.all_guesses_complete():
            stop_guess_timer()
            start_voting_for_current_drawing()
    elif game_state.phase == "voting":
        # Check if all remaining players have submitted
        if game_state.all_votes_complete():
            stop_vote_timer()
            show_current_scores()


@socketio.on("start_game")
def handle_start():
    """Handle game start."""
    if not game_state.can_start_game():
        return
    
    game_state.start_new_round()
    
    # Assign prompts to players
    for pid in game_state.players:
        prompt = get_random_prompt(PROMPT_BANK)
        game_state.players[pid]["prompt"] = prompt
    
    game_state.phase = "drawing"
    
    # Notify all players
    socketio.emit("game_started", {"round": game_state.round - 1})
    
    # Send each player their prompt
    for pid, pdata in game_state.players.items():
        socketio.emit(
            "your_turn_draw",
            {"prompt": pdata["prompt"], "round": game_state.round},
            room=pid
        )
    
    start_timer()


@socketio.on("add_time")
def handle_add_time():
    """Add extra time to drawing timer."""
    if drawing_timer:
        drawing_timer.add_time(30)


@socketio.on("submit_drawing")
def handle_drawing(data):
    """Handle drawing submission."""
    player_id = request.sid
    image_data = data.get("image", "")
    
    # Check if player already submitted a drawing
    if any(d["player_id"] == player_id for d in game_state.drawings):
        return
    
    # Store drawing
    if player_id in game_state.players:
        prompt = game_state.players[player_id]["prompt"]
        game_state.drawings.append({
            "player_id": player_id,
            "prompt": prompt,
            "image": image_data
        })
    
    # Check if all drawings are complete
    if game_state.all_drawings_complete():
        stop_timer()
        game_state.current_drawing_index = 0
        start_guessing_for_current_drawing()


def start_guessing_for_current_drawing():
    """Start guessing phase for current drawing."""
    game_state.phase = "guessing"
    current_idx = game_state.current_drawing_index
    
    # Initialize guesses
    if current_idx not in game_state.guesses:
        game_state.guesses[current_idx] = []
    
    # Show title card
    socketio.emit("show_guessing_phase")
    
    current = game_state.drawings[current_idx]
    
    # Send to each player
    for pid in game_state.players.keys():
        if pid != current["player_id"]:
            socketio.emit(
                "your_turn_guess",
                {"image": current["image"], "drawing_index": current_idx},
                room=pid
            )
        else:
            socketio.emit(
                "wait",
                {"message": "Waiting for others to guess your drawing..."},
                room=pid
            )
    
    start_guess_timer()


@socketio.on("submit_guess")
def handle_guess(data):
    """Handle guess submission."""
    player_id = request.sid
    guess = data.get("guess", "").strip()
    current_idx = game_state.current_drawing_index
    current = game_state.drawings[current_idx]
    
    # Check if guess matches the real prompt (case-insensitive)
    if guess.lower() == current["prompt"].lower():
        emit("duplicate_guess", {
            "message": "That's the real prompt! Try guessing something different."
        })
        return
    
    # Check if guess matches any existing guess (case-insensitive)
    for existing_guess in game_state.guesses[current_idx]:
        if guess.lower() == existing_guess["guess"].lower():
            emit("duplicate_guess", {
                "message": "That prompt has already been submitted! Try something different."
            })
            return
    
    # Add guess (including empty ones)
    if not any(g["player_id"] == player_id for g in game_state.guesses[current_idx]):
        game_state.guesses[current_idx].append({
            "player_id": player_id,
            "guess": guess  # Can be empty string
        })
    
    # Check if all guesses complete
    if game_state.all_guesses_complete():
        stop_guess_timer()
        start_voting_for_current_drawing()



@socketio.on("guess_time_up")
def handle_guess_time_up():
    """Handle guess timer expiration."""
    current_idx = game_state.current_drawing_index
    # Check if current_idx is valid
    if current_idx >= len(game_state.drawings):
        return
    current = game_state.drawings[current_idx]
    # Find all players who have not guessed (excluding artist)
    guessed_pids = {g["player_id"] for g in game_state.guesses[current_idx]}
    missing = [pid for pid in game_state.players if pid != current["player_id"] and pid not in guessed_pids]
    # Auto-submit empty guesses for missing players
    for pid in missing:
        game_state.guesses[current_idx].append({"player_id": pid, "guess": ""})
    stop_guess_timer()
    start_voting_for_current_drawing()


def start_voting_for_current_drawing():
    """Start voting phase for current drawing."""
    game_state.phase = "voting"
    current_idx = game_state.current_drawing_index
    
    # Initialize votes
    if current_idx not in game_state.votes:
        game_state.votes[current_idx] = []
    
    # Show title card
    socketio.emit("show_voting_phase")
    
    current = game_state.drawings[current_idx]
    guesses = game_state.guesses[current_idx]
    
    # Send voting options to each player
    for pid in game_state.players.keys():
        if pid != current["player_id"]:
            # Create options (guesses + real prompt, excluding this player's guess)
            options = [{"text": current["prompt"], "player_id": current["player_id"], "is_correct": True}]
            for g in guesses:
                if g["player_id"] != pid and g["guess"].strip():  # Filter out empty guesses
                    options.append({"text": g["guess"], "player_id": g["player_id"], "is_correct": False})
            
            random.shuffle(options)
            
            socketio.emit(
                "your_turn_vote",
                {
                    "image": current["image"],
                    "options": options,
                    "artist_id": current["player_id"],
                    "players": game_state.players
                },
                room=pid
            )
        else:
            # Artist gets voting screen too, but with all options (to like)
            options = [{"text": current["prompt"], "player_id": current["player_id"], "is_correct": True}]
            for g in guesses:
                if g["guess"].strip():  # Filter out empty guesses
                    options.append({"text": g["guess"], "player_id": g["player_id"], "is_correct": False})
            
            random.shuffle(options)
            
            socketio.emit(
                "your_turn_vote",
                {
                    "image": current["image"],
                    "options": options,
                    "artist_id": current["player_id"],
                    "players": game_state.players
                },
                room=pid
            )
    
    # Start the voting timer
    start_vote_timer()


@socketio.on("submit_vote")
def handle_vote(data):
    """Handle vote submission."""
    player_id = request.sid
    vote = data.get("vote", "").strip()
    likes = data.get("likes", [])
    current_idx = game_state.current_drawing_index
    
    # Add vote (including empty ones to prevent hang)
    if not any(v["player_id"] == player_id for v in game_state.votes[current_idx]):
        game_state.votes[current_idx].append({
            "player_id": player_id,
            "vote": vote,  # Can be empty string
            "likes": likes
        })
    
    # Check if all votes complete
    if game_state.all_votes_complete():
        stop_vote_timer()
        show_current_scores()


@socketio.on("submit_likes_only")
def handle_likes_only(data):
    """Handle likes-only submission from artists."""
    player_id = request.sid
    likes = data.get("likes", [])
    current_idx = game_state.current_drawing_index
    
    # Add likes without vote (for artist)
    if not any(v["player_id"] == player_id for v in game_state.votes[current_idx]):
        game_state.votes[current_idx].append({
            "player_id": player_id,
            "vote": None,  # No vote for artist
            "likes": likes
        })
    
    # Check if all votes complete
    if game_state.all_votes_complete():
        stop_vote_timer()
        show_current_scores()


def show_current_scores():
    """Calculate and show scores for current drawing."""
    current_idx = game_state.current_drawing_index
    
    # Calculate scores
    result = game_state.calculate_scores_for_drawing(current_idx)
    
    if result:
        socketio.emit("show_current_scores", {
            "correct_answer": result["correct_answer"],
            "artist_id": game_state.drawings[current_idx]["player_id"],
            "drawing_image": result["drawing_image"],
            "scores": {pid: pdata["score"] for pid, pdata in game_state.players.items()},
            "players": game_state.players,
            "guesses": game_state.guesses[current_idx],
            "votes": game_state.votes[current_idx]
        })


@socketio.on("continue_to_next")
def handle_continue():
    """Handle continue button click."""
    player_id = request.sid
    game_state.continue_ready.add(player_id)
    
    # Calculate waiting count
    ready_count = len(game_state.continue_ready)
    total_count = len(game_state.players)
    waiting_count = total_count - ready_count
    
    # Broadcast updated waiting count to all players who are already waiting (including this one)
    if waiting_count > 0:
        for ready_pid in game_state.continue_ready:
            socketio.emit("wait", {
                "message": f"Waiting for {waiting_count} player{'s' if waiting_count != 1 else ''} to continue..."
            }, room=ready_pid)
    
    if game_state.all_players_ready_to_continue():
        game_state.continue_ready.clear()
        game_state.current_drawing_index += 1
        
        if game_state.current_drawing_index < len(game_state.drawings):
            # More drawings in this round
            start_guessing_for_current_drawing()
        else:
            # Round complete
            if game_state.round < config.NUM_ROUNDS:
                # Start next round
                handle_next_round()
            else:
                # Game over
                show_final_scores()


def handle_next_round():
    """Start the next round."""
    game_state.start_new_round()
    
    # Assign prompts
    for pid in game_state.players:
        prompt = get_random_prompt(PROMPT_BANK)
        game_state.players[pid]["prompt"] = prompt
    
    game_state.phase = "drawing"
    
    socketio.emit("game_started", {"round": game_state.round - 1})
    
    for pid, pdata in game_state.players.items():
        socketio.emit(
            "your_turn_draw",
            {"prompt": pdata["prompt"], "round": game_state.round},
            room=pid
        )
    
    start_timer()


def show_final_scores():
    """Show final game results."""
    game_state.phase = "final"
    
    # Calculate total likes
    likes = {pid: pdata["likes"] for pid, pdata in game_state.players.items()}
    
    socketio.emit("show_final", {
        "scores": {pid: pdata["score"] for pid, pdata in game_state.players.items()},
        "likes": likes,
        "players": game_state.players
    })


@socketio.on("play_again")
def handle_play_again():
    """Reset game for another round."""
    for pid in game_state.players.keys():
        game_state.players[pid]["score"] = 0
        game_state.players[pid]["likes"] = 0
    
    game_state.phase = "lobby"
    game_state.drawings = []
    game_state.guesses = {}
    game_state.votes = {}
    game_state.round = 0
    game_state.current_drawing_index = 0
    game_state.current_drawer_index = 0
    game_state.player_order = []
    game_state.continue_ready.clear()
    
    socketio.emit("reset")
    socketio.emit("update_lobby", {"players": game_state.players})


@app.route("/qr_code")
def qr_code():
    """Generate QR code for the game URL."""
    # Use the same protocol as the current request to avoid iOS compatibility issues
    protocol = "https" if request.is_secure else "http"
    qr_url = f"{protocol}://{LOCAL_IP}:{config.DEFAULT_PORT}"
    
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(qr_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buf = BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    
    return send_file(buf, mimetype="image/png")

# Ensure the configured port is available; if not, pick the next free port.
def find_available_port(start_port, max_tries=50):
    for p in range(start_port, start_port + max_tries):
        try:
            test_sock = socket_module.socket(socket_module.AF_INET, socket_module.SOCK_STREAM)
            test_sock.setsockopt(socket_module.SOL_SOCKET, socket_module.SO_REUSEADDR, 1)
            test_sock.bind(("", p))
            test_sock.close()
            return p
        except OSError:
            continue
    return start_port





@app.route("/")
def index():
    """Serve the main game page."""
    return render_template("index.html")


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=ResourceWarning)
    
    # Custom exception handler to suppress socket errors
    def handle_exception(exc_type, exc_value, exc_traceback):
        # Ignore socket errors (broken pipe, connection reset, etc.)
        if exc_type == OSError and hasattr(exc_value, 'errno') and exc_value.errno in (32, 54, 57, 104):
            return
        # Call default handler for other exceptions
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
    
    sys.excepthook = handle_exception
    
    print("\n" + "=" * 50)
    print("🎨 DRAWFUL PARTY GAME SERVER 🎨")
    print("=" * 50)
    print("\nGame Configuration:")
    print(f"  Drawing Time: {config.DRAWING_TIME}s")
    print(f"  Guessing Time: {config.GUESSING_TIME}s")
    print(f"  Number of Rounds: {config.NUM_ROUNDS}")
    print(f"  Min Players: {config.MIN_PLAYERS}")
    print(f"  Max Players: {config.MAX_PLAYERS}")
    print("\nServer starting on:")

    port_to_use = find_available_port(config.DEFAULT_PORT)
    # Update GAME_URL to include the actual port we will bind to.
    GAME_URL = f"https://{LOCAL_IP}:{port_to_use}"

    print(f"  Local:   http://localhost:{port_to_use}")
    print(f"  Network: {GAME_URL}")
    print("\nShare the Network address with players on your WiFi!")
    print("=" * 50 + "\n")
    try:
        socketio.run(
            app,
            host="0.0.0.0",
            port=port_to_use,
            debug=False,
            allow_unsafe_werkzeug=True,
            use_reloader=False,
        )
    except OSError as e:
        print(f"Failed to start server: {e}")
        sys.exit(1)
