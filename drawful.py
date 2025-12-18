import logging
import random
import secrets
import socket
import sys
import threading
import time
import warnings
from io import BytesIO

import qrcode
from flask import Flask, render_template_string, request, send_file
from flask_socketio import SocketIO, emit

# Suppress socket connection errors from logging
logging.getLogger("werkzeug").setLevel(logging.ERROR)

app = Flask(__name__)
app.config["SECRET_KEY"] = secrets.token_hex(16)
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    logger=False,
    engineio_logger=False,
    ping_timeout=60,
    ping_interval=25,
)
HOSTNAME = "mac.lan"

try:
    LOCAL_IP = socket.gethostbyname(HOSTNAME)
except Exception:
    LOCAL_IP = "127.0.0.1"

GAME_URL = f"http://{LOCAL_IP}:5001"
# Timer state
timer_state = {"active": False, "time_remaining": 60, "thread": None}
guess_timer_state = {"active": False, "time_remaining": 20, "thread": None}

# Player colors - each player gets a unique hue with light and dark shades
PLAYER_COLORS = [
    {"light": "#FF6B6B", "dark": "#C92A2A"},  # Red
    {"light": "#4DABF7", "dark": "#1864AB"},  # Blue
    {"light": "#51CF66", "dark": "#046113"},  # Green
    {"light": "#FFD43B", "dark": "#F08C00"},  # Yellow
    {"light": "#FF6BFF", "dark": "#C92AC9"},  # Magenta
    {"light": "#FF9F40", "dark": "#E67700"},  # Orange
    {"light": "#FFA07A", "dark": "#ff4f00"},  # Orange theme
    {"light": "#66D9E8", "dark": "#0B7285"},  # Cyan
]


# Load prompt bank from external file
def load_prompts(filename="unused_prompts.txt"):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            prompts = [line.strip() for line in f if line.strip()]
        return prompts
    except Exception as e:
        print(f"Error loading prompts: {e}")
        return []


def move_prompt_to_used(prompt):
    """Move a prompt from unused_prompts.txt to used_prompts.txt"""
    try:
        # Read all unused prompts
        with open("unused_prompts.txt", "r", encoding="utf-8") as f:
            unused = [line.strip() for line in f if line.strip()]

        # Remove the used prompt
        if prompt in unused:
            unused.remove(prompt)

        # Write back to unused_prompts.txt
        with open("unused_prompts.txt", "w", encoding="utf-8") as f:
            for p in unused:
                f.write(p + "\n")

        # Append to used_prompts.txt
        with open("used_prompts.txt", "a", encoding="utf-8") as f:
            f.write(prompt + "\n")
    except Exception as e:
        print(f"Error moving prompt to used: {e}")


PROMPT_BANK = load_prompts()

# Game state
game_state = {
    "phase": "lobby",  # lobby, drawing, guessing, voting, results, final
    "players": {},  # {session_id: {name, score, likes, ready, color_index, prompt}}
    "drawings": [],  # [{player_id, prompt, image_data}]
    "guesses": {},  # {drawing_index: [{player_id, guess}]}
    "votes": {},  # {drawing_index: [{player_id, vote}]}
    "current_drawing_index": 0,
    "current_drawer_index": 0,  # Track which player is currently drawing
    "player_order": [],  # List of player IDs in drawing order
    "round": 0,
    "continue_ready": set(),  # Track which players have clicked continue
}

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/qr_code")
def qr_code():
    """Generate QR code for the game URL"""

    # Use the globally-resolved GAME_URL
    url = GAME_URL
    url = "http://192.168.86.37:5001/"

    # Generate QR code
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    # Convert to bytes
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return send_file(buf, mimetype="image/png")


def timer_thread():
    """Background thread that manages the drawing timer"""
    while timer_state["active"]:
        if timer_state["time_remaining"] > 0:
            socketio.emit("timer_tick", {"time": timer_state["time_remaining"]})
            time.sleep(1)
            timer_state["time_remaining"] -= 1
        else:
            # Time's up - auto submit all drawings
            timer_state["active"] = False
            socketio.emit("timer_expired")
            break


def guess_timer_thread():
    """Background thread that manages the guessing timer"""
    while guess_timer_state["active"]:
        if guess_timer_state["time_remaining"] > 0:
            socketio.emit(
                "guess_timer_tick", {"time": guess_timer_state["time_remaining"]}
            )
            time.sleep(1)
            guess_timer_state["time_remaining"] -= 1
        else:
            # Time's up - move to next guess
            guess_timer_state["active"] = False
            socketio.emit("guess_timer_expired")
            break


def start_timer():
    """Start the server-side timer"""
    timer_state["time_remaining"] = 60
    timer_state["active"] = True
    if timer_state["thread"] is None or not timer_state["thread"].is_alive():
        timer_state["thread"] = threading.Thread(target=timer_thread, daemon=True)
        timer_state["thread"].start()


def stop_timer():
    """Stop the server-side timer"""
    timer_state["active"] = False


def start_guess_timer():
    """Start the server-side guess timer"""
    guess_timer_state["time_remaining"] = 20
    guess_timer_state["active"] = True
    if (
        guess_timer_state["thread"] is None
        or not guess_timer_state["thread"].is_alive()
    ):
        guess_timer_state["thread"] = threading.Thread(
            target=guess_timer_thread, daemon=True
        )
        guess_timer_state["thread"].start()


def stop_guess_timer():
    """Stop the server-side guess timer"""
    guess_timer_state["active"] = False


@socketio.on("join")
def handle_join(data):
    player_id = request.sid
    name = data["name"].strip()

    # First check if this is an existing player trying to reconnect
    for pid, pdata in game_state["players"].items():
        if pdata["name"].lower() == name.lower():
            # If the same player is reconnecting, reassign their session id
            if pid != player_id:
                # Move player data to new session id
                game_state["players"][player_id] = pdata
                del game_state["players"][pid]

            emit(
                "joined",
                {"player_id": player_id, "colors": PLAYER_COLORS[pdata["color_index"]]},
            )

            # Restore player to current game state if game is in progress
            if game_state["phase"] != "lobby":
                current_idx = game_state.get("current_drawing_index", 0)

                if game_state["phase"] == "drawing":
                    # Check if player has already submitted drawing
                    has_submitted = any(
                        d["player_id"] == player_id for d in game_state["drawings"]
                    )
                    if not has_submitted and player_id in game_state["players"]:
                        prompt = game_state["players"][player_id].get(
                            "prompt", "Draw something!"
                        )
                        emit(
                            "your_turn_draw",
                            {"prompt": prompt, "round": game_state.get("round", 0)},
                        )
                    else:
                        emit(
                            "wait",
                            {"message": "Waiting for others to finish drawing..."},
                        )

                elif game_state["phase"] == "guessing":
                    if current_idx < len(game_state["drawings"]):
                        current_drawing = game_state["drawings"][current_idx]
                        # Check if player is the artist or has already guessed
                        is_artist = current_drawing["player_id"] == player_id
                        has_guessed = any(
                            g["player_id"] == player_id
                            for g in game_state["guesses"].get(current_idx, [])
                        )

                        if is_artist:
                            emit(
                                "wait",
                                {
                                    "message": "Waiting for others to guess your drawing..."
                                },
                            )
                        elif not has_guessed:
                            emit(
                                "your_turn_guess",
                                {
                                    "image": current_drawing["image"],
                                    "drawing_index": current_idx,
                                },
                            )
                        else:
                            emit("wait", {"message": "Waiting for others to guess..."})

                elif game_state["phase"] == "voting":
                    if current_idx < len(game_state["drawings"]):
                        current_drawing = game_state["drawings"][current_idx]
                        artist_id = current_drawing["player_id"]
                        is_artist = artist_id == player_id
                        has_voted = any(
                            v["player_id"] == player_id
                            for v in game_state["votes"].get(current_idx, [])
                        )

                        if not has_voted and not is_artist:
                            # Recreate voting options
                            options = [
                                {"text": current_drawing["prompt"], "is_correct": True}
                            ]
                            for guess in game_state["guesses"].get(current_idx, []):
                                options.append(
                                    {"text": guess["guess"], "is_correct": False}
                                )
                            random.shuffle(options)
                            emit(
                                "your_turn_vote",
                                {
                                    "image": current_drawing["image"],
                                    "options": options,
                                    "drawing_index": current_idx,
                                    "artist_id": artist_id,
                                },
                            )
                        else:
                            emit("wait", {"message": "Waiting for others to vote..."})
            else:
                socketio.emit("update_lobby", {"players": game_state["players"]})
            return

    # Check if game is in progress (not in lobby phase) - only block NEW players
    if game_state["phase"] != "lobby":
        emit("game_in_progress")
        return

    # Assign a color to the player based on their order
    color_index = len(game_state["players"]) % len(PLAYER_COLORS)
    player_colors = PLAYER_COLORS[color_index]

    game_state["players"][player_id] = {
        "name": name,
        "score": 0,
        "likes": 0,
        "color_index": color_index,
    }
    emit("joined", {"player_id": player_id, "colors": player_colors})
    socketio.emit("update_lobby", {"players": game_state["players"]})


@socketio.on("start_game")
def handle_start():
    if len(game_state["players"]) >= 3:
        game_state["phase"] = "drawing"
        game_state["round"] = 0
        game_state["drawings"] = []
        game_state["current_drawing_index"] = 0
        game_state["current_drawer_index"] = 0
        game_state["player_order"] = list(game_state["players"].keys())

        socketio.emit("game_started", {"round": 0})

        available_prompts = load_prompts("unused_prompts.txt")
        random.shuffle(available_prompts)

        for idx, pid in enumerate(game_state["players"].keys()):
            prompt = available_prompts[idx % len(available_prompts)]
            game_state["players"][pid]["prompt"] = prompt
            # Move prompt to used file
            move_prompt_to_used(prompt)
            # Send drawing prompt to each player
            socketio.emit("your_turn_draw", {"prompt": prompt, "round": 0}, room=pid)

        # Start timer for all players to draw simultaneously
        start_timer()


@socketio.on("submit_drawing")
def handle_drawing(data):
    player_id = request.sid
    player_prompt = game_state["players"][player_id].get("prompt", "Unknown")
    game_state["drawings"].append(
        {
            "player_id": player_id,
            "prompt": player_prompt,
            "image": data["image"],
        }
    )

    # Check if all players have submitted their drawings
    if len(game_state["drawings"]) == len(game_state["players"]):
        stop_timer()
        # All drawings complete, start guessing for first drawing
        game_state["current_drawing_index"] = 0
        start_guessing_for_current_drawing()


def start_guessing_for_current_drawing():
    """Start guessing phase for the current drawing"""
    game_state["phase"] = "guessing"
    current_idx = game_state["current_drawing_index"]

    # Initialize guesses for this drawing if not exists
    if current_idx not in game_state["guesses"]:
        game_state["guesses"][current_idx] = []

    # Emit title card event for guessing phase
    socketio.emit("show_guessing_phase")

    current = game_state["drawings"][current_idx]

    # All players (except the artist) guess the current drawing
    for pid in game_state["players"].keys():
        if pid != current["player_id"]:
            socketio.emit(
                "your_turn_guess",
                {"image": current["image"], "drawing_index": current_idx},
                room=pid,
            )
        else:
            socketio.emit(
                "wait",
                {"message": "Waiting for others to guess your drawing..."},
                room=pid,
            )

    # Start guess timer
    start_guess_timer()


@socketio.on("submit_guess")
def handle_guess(data):
    player_id = request.sid
    guess = data.get("guess", "").strip()
    current_idx = game_state["current_drawing_index"]
    current = game_state["drawings"][current_idx]

    # Check if guess matches the real prompt
    if guess.lower() == current["prompt"].lower():
        emit(
            "duplicate_guess",
            {"message": "That's the real prompt! Try guessing something different."},
        )
        return

    # Check if guess matches any existing guess
    for existing_guess in game_state["guesses"][current_idx]:
        if guess.lower() == existing_guess["guess"].lower():
            emit(
                "duplicate_guess",
                {
                    "message": "That prompt has already been submitted! Try something different."
                },
            )
            return

    # Prevent duplicate guesses from same player for this drawing
    if not any(g["player_id"] == player_id for g in game_state["guesses"][current_idx]):
        if guess:  # Only add non-empty guesses
            game_state["guesses"][current_idx].append(
                {"player_id": player_id, "guess": guess}
            )

    # Expected guesses = all players except the artist
    expected_guesses = len(game_state["players"]) - 1
    if len(game_state["guesses"][current_idx]) == expected_guesses:
        stop_guess_timer()
        # Move to voting for this same drawing
        start_voting_for_current_drawing()


@socketio.on("guess_time_up")
def handle_guess_time_up():
    """Handle when guess timer expires - move to voting for current drawing"""
    stop_guess_timer()
    start_voting_for_current_drawing()


def start_voting_for_current_drawing():
    """Start voting phase for the current drawing only"""
    game_state["phase"] = "voting"
    current_idx = game_state["current_drawing_index"]

    # Bounds check to prevent IndexError
    if current_idx >= len(game_state["drawings"]):
        print(
            f"Error: current_drawing_index {current_idx} out of range (only {len(game_state['drawings'])} drawings)"
        )
        return

    # Initialize votes for this drawing if not exists
    if current_idx not in game_state["votes"]:
        game_state["votes"][current_idx] = []

    current = game_state["drawings"][current_idx]
    artist_id = current["player_id"]
    options = [{"text": current["prompt"], "is_correct": True}]

    for guess in game_state["guesses"][current_idx]:
        options.append({"text": guess["guess"], "is_correct": False})

    random.shuffle(options)

    # Emit title card event for voting phase
    socketio.emit("show_voting_phase")

    # All players vote on this drawing
    for pid in game_state["players"].keys():
        # Create options for this specific player (excluding their own guess)
        player_options = [{"text": current["prompt"], "is_correct": True}]

        for guess in game_state["guesses"][current_idx]:
            # Don't show this player their own guess
            if guess["player_id"] != pid:
                player_options.append({"text": guess["guess"], "is_correct": False})

        random.shuffle(player_options)

        socketio.emit(
            "your_turn_vote",
            {
                "image": current["image"],
                "options": player_options,
                "drawing_index": current_idx,
                "artist_id": artist_id,
            },
            room=pid,
        )


@socketio.on("submit_vote")
def handle_vote(data):
    player_id = request.sid
    vote = data.get("vote")  # The prompt the player thinks is real
    likes = data.get("likes", [])  # Array of liked prompts
    current_idx = game_state["current_drawing_index"]

    # Prevent duplicate votes from same player for this drawing
    if not any(v["player_id"] == player_id for v in game_state["votes"][current_idx]):
        game_state["votes"][current_idx].append(
            {"player_id": player_id, "vote": vote, "likes": likes}
        )

    # Check if all non-artist players have voted
    current_drawing = game_state["drawings"][current_idx]
    artist_id = current_drawing["player_id"]
    expected_votes = len(game_state["players"]) - 1  # Exclude the artist

    if len(game_state["votes"][current_idx]) == expected_votes:
        # Calculate scores for this drawing
        calculate_scores_for_current_drawing()

        # Show current scoreboard
        show_current_scores()


def calculate_scores_for_current_drawing():
    """Calculate and award points for the current drawing only"""
    idx = game_state["current_drawing_index"]
    drawing = game_state["drawings"][idx]
    real_prompt = drawing["prompt"]

    for v in game_state["votes"][idx]:
        voter_id = v["player_id"]
        voted_answer = v["vote"]
        likes = v.get("likes", [])

        # Correct guess
        if voted_answer == real_prompt:
            game_state["players"][voter_id]["score"] += 1000
        else:
            # If they voted for a fake prompt, give points to the prompt author
            for g in game_state["guesses"][idx]:
                if g["guess"] == voted_answer:
                    game_state["players"][g["player_id"]]["score"] += 500
                    break

        # Like tracking (tracked separately from score)
        for liked_text in likes:
            # Find the author of each liked prompt
            for g in game_state["guesses"][idx]:
                if g["guess"] == liked_text:
                    game_state["players"][g["player_id"]]["likes"] += 1
                    break


def show_current_scores():
    """Show current scoreboard after each drawing, then move to next"""
    # Clear continue ready for the next continue click
    game_state["continue_ready"].clear()

    idx = game_state["current_drawing_index"]
    drawing = game_state["drawings"][idx]
    scores = {pid: p["score"] for pid, p in game_state["players"].items()}
    likes = {pid: p["likes"] for pid, p in game_state["players"].items()}

    socketio.emit(
        "show_current_scores",
        {
            "scores": scores,
            "likes": likes,
            "players": game_state["players"],
            "correct_answer": drawing["prompt"],
            "drawing_image": drawing["image"],
            "artist_id": drawing["player_id"],
            "guesses": game_state["guesses"].get(idx, []),
            "votes": game_state["votes"].get(idx, []),
        },
    )

    # Move to next drawing after a delay (handled by client clicking continue)


@socketio.on("continue_to_next")
def handle_continue():
    """Track continue clicks and move to next drawing when all players ready"""
    player_id = request.sid

    # Add this player to the ready set
    game_state["continue_ready"].add(player_id)

    # Check if all players have clicked continue
    if len(game_state["continue_ready"]) >= len(game_state["players"]):
        # Reset continue ready for next time
        game_state["continue_ready"].clear()

        # Advance game state
        game_state["current_drawing_index"] += 1

        if game_state["current_drawing_index"] >= len(game_state["drawings"]):
            # All drawings in this round are done
            if game_state["round"] < 2:
                # Start next round
                handle_next_round()
            else:
                # All rounds done, show final results
                show_final_results()
        else:
            # Move to guessing phase for next drawing in this round
            start_guessing_for_current_drawing()
    else:
        # Not everyone ready yet, show waiting message to this player
        ready_count = len(game_state["continue_ready"])
        total_count = len(game_state["players"])
        socketio.emit(
            "wait",
            {"message": f"Waiting for others... ({ready_count}/{total_count} ready)"},
            room=player_id,
        )


def show_final_results():
    """Show final results after all drawings are complete"""
    game_state["phase"] = "results"
    scores = {pid: p["score"] for pid, p in game_state["players"].items()}
    likes = {pid: p["likes"] for pid, p in game_state["players"].items()}
    socketio.emit(
        "show_results",
        {"scores": scores, "likes": likes, "players": game_state["players"]},
    )


@socketio.on("next_round")
def handle_next_round():
    if game_state["round"] < 2:
        # Start next round
        game_state["round"] += 1
        game_state["phase"] = "drawing"
        game_state["drawings"] = []
        game_state["current_drawing_index"] = 0
        game_state["current_drawer_index"] = 0
        game_state["player_order"] = list(game_state["players"].keys())

        available_prompts = load_prompts("unused_prompts.txt")
        random.shuffle(available_prompts)

        for idx, pid in enumerate(game_state["players"].keys()):
            prompt = available_prompts[idx % len(available_prompts)]
            game_state["players"][pid]["prompt"] = prompt
            # Move prompt to used file
            move_prompt_to_used(prompt)
            # Send drawing prompt to each player
            socketio.emit(
                "your_turn_draw",
                {"prompt": prompt, "round": game_state["round"]},
                room=pid,
            )

        # Start timer for all players to draw simultaneously
        start_timer()
    else:
        # Go to final screen
        game_state["phase"] = "final"
        scores = {pid: p["score"] for pid, p in game_state["players"].items()}
        likes = {pid: p["likes"] for pid, p in game_state["players"].items()}
        socketio.emit(
            "show_final",
            {"scores": scores, "likes": likes, "players": game_state["players"]},
        )


@socketio.on("add_time")
def handle_add_time():
    # Add time to the appropriate active timer
    if timer_state["active"]:
        timer_state["time_remaining"] += 30
        socketio.emit("timer_tick", {"time": timer_state["time_remaining"]})
    elif guess_timer_state["active"]:
        guess_timer_state["time_remaining"] += 30
        socketio.emit("guess_timer_tick", {"time": guess_timer_state["time_remaining"]})


@socketio.on("play_again")
def handle_play_again():
    for pid in game_state["players"].keys():
        game_state["players"][pid]["score"] = 0
        game_state["players"][pid]["likes"] = 0

    game_state["phase"] = "lobby"

    game_state["drawings"] = []
    game_state["guesses"] = {}
    game_state["votes"] = {}
    game_state["round"] = 0
    game_state["current_drawing_index"] = 0
    game_state["current_drawer_index"] = 0
    game_state["player_order"] = []

    socketio.emit("reset")
    socketio.emit("update_lobby", {"players": game_state["players"]})


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=ResourceWarning)

    # Custom exception handler to suppress socket errors
    def handle_exception(exc_type, exc_value, exc_traceback):
        # Ignore socket errors (broken pipe, connection reset, etc.)
        if exc_type == OSError and exc_value.errno in (32, 54, 57, 104):
            return
        # Call default handler for other exceptions
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = handle_exception

    print("\n" + "=" * 50)
    print("🎨 DRAWFUL PARTY GAME SERVER 🎨")
    print("=" * 50)
    print("\nServer starting on:")
    print("  Local:   http://localhost:5001")
    print(f"  Network: {GAME_URL}")
    print("\nShare the Network address with players on your WiFi!")
    print("=" * 50 + "\n")

    socketio.run(
        app,
        host="0.0.0.0",
        port=5001,
        debug=False,
        allow_unsafe_werkzeug=True,
        use_reloader=False,
    )
