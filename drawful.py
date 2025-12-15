import logging
import secrets
import threading
import time
from io import BytesIO

import qrcode
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit

# Suppress socket connection errors from logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)

app = Flask(__name__)
app.config["SECRET_KEY"] = secrets.token_hex(16)
socketio = SocketIO(
    app, 
    cors_allowed_origins="*",
    async_mode='threading',
    logger=False,
    engineio_logger=False,
    ping_timeout=60,
    ping_interval=25
)
HOSTNAME = 'mac.lan'

# Timer state
timer_state = {"active": False, "time_remaining": 60, "thread": None}
guess_timer_state = {"active": False, "time_remaining": 15, "thread": None}

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

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Drawful</title>
    <link rel="stylesheet" href="https://use.typekit.net/hbi1lzm.css">
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'futura-pt', serif;
            background: white;
            min-height: 100vh;
            padding: 20px;
            padding-top: 70px;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }
        .container {
            max-width: 900px;
            margin: 0 auto;
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            padding: 30px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.15);
        }
        h1 {
            color: #ff4f00;
            text-align: center;
            margin-bottom: 30px;
            font-size: 2.5em;
            font-family: 'futura-pt', sans-serif;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: -0.5px;
        }
        .screen { display: none; }
        .screen.active { display: block; }
        input[type="text"] {
            width: 100%;
            padding: 15px;
            border: 1px solid rgba(0,0,0,0.1);
            font-size: 16px;
            font-family: 'futura-pt', serif;
            margin-bottom: 15px;
            background: rgba(255,255,255,0.8);
            transition: all 0.2s;
        }
        input[type="text"]:focus {
            outline: none;
            border-color: #ff4f00;
            background: white;
            box-shadow: 0 0 0 3px rgba(255, 79, 0, 0.1);
        }
        button {
            width: 100%;
            padding: 15px;
            background: #ff4f00;
            color: white;
            border: none;
            font-size: 17px;
            font-family: 'futura-pt', sans-serif;
            font-weight: 700;
            text-transform: uppercase;
            cursor: pointer;
            margin-bottom: 10px;
            transition: all 0.2s;
            letter-spacing: 0.5px;
        }
        button:hover { 
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(255, 79, 0, 0.4);
        }
        button:active {
            transform: translateY(0);
        }
        button:disabled {
            background: #d1d5db;
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
        }
        .tool-btn {
            background: white;
            color: #1f2937;
            border: 2px solid rgba(0,0,0,0.1);
            font-size: 28px;
            padding: 12px;
            min-width: 60px;
            width: auto;
        }
        .tool-btn:hover {
            border-color: #ff4f00;
            background: rgba(255, 79, 0, 0.05);
        }
        .tool-btn.active { 
            background: #ff4f00;
            color: white;
            border-color: #ff4f00;
            box-shadow: 0 0 0 3px rgba(255, 79, 0, 0.2);
        }
        .players-list {
            background: rgba(255, 79, 0, 0.05);
            padding: 20px;
            margin-bottom: 20px;
            border: 1px solid rgba(255, 79, 0, 0.1);
        }
        .player-item {
            background: white;
            padding: 12px 18px;
            margin: 8px 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border: 1px solid rgba(0,0,0,0.06);
            transition: all 0.2s;
        }
        .player-item:hover {
            transform: translateX(4px);
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        canvas {
            border: 2px solid rgba(255, 79, 0, 0.3);
            background: white;
            display: block;
            margin: 20px auto;
            touch-action: none;
            max-width: 100%;
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        }
        .drawing-tools {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-bottom: 20px;
            align-items: center;
        }
        .color-btn {
            width: 50px;
            height: 50px;
            border-radius: 50%;
            border: 3px solid rgba(0,0,0,0.1);
            cursor: pointer;
            transition: all 0.2s;
            padding: 0;
            min-width: unset;
        }
        .color-btn.active {
            border: 4px solid #ff4f00;
            box-shadow: 0 0 0 4px rgba(255, 79, 0, 0.2);
            transform: scale(1.1);
        }
        .prompt-display {
            background: rgba(255, 79, 0, 0.1);
            padding: 20px;
            text-align: center;
            margin-bottom: 20px;
            font-size: 24px;
            font-weight: 700;
            color: #ff4f00;
            border: 2px solid rgba(255, 79, 0, 0.2);
            letter-spacing: -0.5px;
        }
        .drawing-display {
            max-width: 100%;
            border: 2px solid rgba(255, 79, 0, 0.3);
            margin: 20px 0;
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        }
        .answer-btn {
            background: white;
            color: #1f2937;
            margin: 5px 0;
            border: 1px solid rgba(0,0,0,0.1);
        }
        .answer-btn:hover { 
            background: rgba(255, 79, 0, 0.05);
            border-color: rgba(255, 79, 0, 0.3);
        }
        .vote-option {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 15px;
            margin: 10px 0;
            background: white;
            border: 2px solid rgba(0,0,0,0.1);
            cursor: pointer;
            transition: all 0.2s;
        }
        .vote-option:hover {
            border-color: rgba(255, 79, 0, 0.3);
            background: rgba(255, 79, 0, 0.05);
        }
        .vote-option.selected {
            background: rgba(255, 79, 0, 0.1);
            border-color: #ff4f00;
            border-width: 3px;
        }
        .vote-option-text {
            flex: 1;
            font-size: 16px;
            font-weight: 500;
        }
        .like-btn {
            font-size: 24px;
            background: none;
            border: 2px solid rgba(0,0,0,0.15);
            border-radius: 50%;
            cursor: pointer;
            padding: 8px 12px;
            transition: all 0.2s;
            width: auto;
            min-width: unset;
            color: #e63946;
        }
        .like-btn:hover {
            transform: scale(1.2);
            border-color: #e63946;
            background: rgba(230, 57, 70, 0.05);
        }
        .like-btn.liked {
            transform: scale(1.3);
            background: rgba(230, 57, 70, 0.1);
            border-color: #e63946;
        }
        .scores {
            background: rgba(255, 79, 0, 0.05);
            padding: 20px;
            border: 1px solid rgba(255, 79, 0, 0.1);
        }
        .score-item {
            padding: 15px 20px;
            margin: 10px 0;
            background: white;
            display: flex;
            justify-content: space-between;
            font-size: 18px;
            border: 1px solid rgba(0,0,0,0.06);
            transition: all 0.2s;
            font-weight: 500;
            letter-spacing: -0.3px;
        }
        .score-item:hover {
            transform: translateX(4px);
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .winner { 
            background: rgba(255, 79, 0, 0.1);
            border: 2px solid #ff4f00;
            font-weight: 700;
        }
        .status-text {
            text-align: center;
            padding: 15px;
            background: rgba(255, 79, 0, 0.1);
            margin-bottom: 20px;
            color: #ff4f00;
            font-weight: 600;
            border: 2px solid rgba(255, 79, 0, 0.2);
            letter-spacing: -0.3px;
        }
        .waiting {
            text-align: center;
            padding: 30px;
            color: #6b7280;
        }
        .waiting .owl {
            font-size: 120px;
            margin: 20px 0;
            animation: float 3s ease-in-out infinite;
        }
        @keyframes float {
            0%, 100% { transform: translateY(0px); }
            50% { transform: translateY(-20px); }
        }
        .qr-code {
            text-align: center;
            margin: 20px 0;
            padding: 20px;
            background: white;
            border: 1px solid rgba(0,0,0,0.08);
            box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        }
        .qr-code img {
            max-width: 200px;
            height: auto;
            border: 2px solid rgba(255, 79, 0, 0.3);
        }
        .color-shade {
            width: 50px;
            height: 50px;
            border: 2px solid #333;
            cursor: pointer;
            transition: transform 0.2s;
        }
        .color-shade:hover {
            transform: scale(1.1);
        }
        .color-shade.active {
            border: 4px solid #000;
            transform: scale(1.15);
        }
        .timer-display {
            font-size: 32px;
            font-weight: 700;
            text-align: center;
            padding: 15px;
            background: rgba(255, 79, 0, 0.1);
            margin-bottom: 10px;
            color: #ff4f00;
            border: 2px solid rgba(255, 79, 0, 0.2);
            letter-spacing: -0.5px;
        }
        .timer-display.warning {
            animation: pulse 1s infinite;
        }
        @keyframes pulse {
            0%, 100% { background: rgba(239, 68, 68, 0.15); border-color: #ef4444; color: #dc2626; }
            50% { background: rgba(239, 68, 68, 0.25); border-color: #dc2626; }
        }
        .correct-answer-reveal {
            background: #ff4f00;
            color: white;
            padding: 20px 30px;
            margin: 20px auto;
            font-size: 28px;
            font-family: 'futura-pt', serif;
            font-weight: 700;
            text-align: center;
            box-shadow: 0 8px 24px rgba(255, 79, 0, 0.4);
            animation: revealFlash 0.8s ease-out;
            border: 3px solid rgba(255, 255, 255, 0.3);
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.2);
        }
        @keyframes revealFlash {
            0% { transform: scale(0.8); opacity: 0; }
            50% { transform: scale(1.05); }
            100% { transform: scale(1); opacity: 1; }
        }
        .reveal-drawing {
            max-width: 400px;
            margin: 20px auto;
            display: block;
            border: 3px solid rgba(255, 79, 0, 0.3);
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        }
        .user-name-box {
            position: fixed;
            top: 10px;
            right: 10px;
            background: #ff4f00;
            color: white;
            padding: 10px 20px;
            font-family: 'futura-pt', sans-serif;
            font-weight: 700;
            text-transform: uppercase;
            font-size: 14px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            z-index: 1000;
        }
        .title-card {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: #ff4f00;
            display: none;
            justify-content: center;
            align-items: center;
            z-index: 9999;
            animation: fadeOut 0.5s ease-out 2.5s forwards;
        }
        .title-card.active {
            display: flex;
        }
        .title-card h2 {
            color: white;
            font-family: 'futura-pt', sans-serif;
            font-weight: 700;
            text-transform: uppercase;
            font-size: 4em;
            text-align: center;
            animation: titlePulse 0.6s ease-out;
        }
        @keyframes titlePulse {
            0% { transform: scale(0.8); opacity: 0; }
            50% { transform: scale(1.1); }
            100% { transform: scale(1); opacity: 1; }
        }
        @keyframes fadeOut {
            to { opacity: 0; }
        }

    </style>
</head>
<body>
    <!-- User Name Display -->
    <div id="user-name-box" class="user-name-box" style="display: none;"></div>
    
    <!-- Title Card -->
    <div id="title-card" class="title-card">
        <h2 id="title-card-text"></h2>
    </div>
    
    <div class="container">
        <h1>🦉 Drawful!</h1>
        
        <!-- Join Screen -->
        <div id="join-screen" class="screen active">
            <input type="text" id="player-name" placeholder="Enter your name" maxlength="20">
            <button onclick="joinGame()">Join Game</button>
            <div class="waiting">Waiting to join...</div>
        </div>

        <!-- Lobby Screen -->
        <div id="lobby-screen" class="screen">
            <div class="status-text">Lobby - Waiting for players</div>
            <div class="players-list">
                <h3 style="margin-bottom: 15px;">Players:</h3>
                <div id="lobby-players"></div>
            </div>
            <button id="start-btn" onclick="startGame()" disabled>Start Game (Need 3+ players)</button>
            <div class="qr-code">
                <p style="margin-bottom: 10px; color: #6b7280;">Scan to join:</p>
                <img id="qr-code-img" src="/qr_code" alt="QR Code">
                <p style="font-weight: bold; font-size: 14px; margin-top: 10px; color: #ff4f00;" id="game-url"></p>
            </div>
        </div>

        <!-- Drawing Screen -->
        <div id="drawing-screen" class="screen">
            <div class="status-text">Round <span id="round-num">1</span>/3 - Drawing Phase</div>
            <div class="prompt-display" id="draw-prompt"></div>
            <div class="timer-display" id="timer-display">1:00</div>
            <canvas id="draw-canvas" width="600" height="600"></canvas>
            <div class="drawing-tools">
                <button class="color-btn" onclick="setTool('light')" id="light-btn" style="background: white; border-color: #ddd;" title="Light Color"></button>
                <button class="color-btn active" onclick="setTool('dark')" id="dark-btn" style="background: #1f2937;" title="Dark Color"></button>
                <button class="tool-btn active" onclick="setTool('pen')" id="pen-btn" title="Pen">🖊️</button>
                <button class="tool-btn" onclick="setTool('fill')" title="Fill">🪣</button>
                <button class="tool-btn" onclick="setTool('eraser')" title="Eraser">🧹</button>
                <button class="tool-btn" onclick="undoCanvas()" title="Undo">↩️</button>
                <input type="range" id="size-slider" min="1" max="20" value="12" style="flex: 1; min-width: 60px;" title="Brush Size">
            </div>
            <div style="display: flex; gap: 10px; margin-top: 10px;">
                <button class="tool-btn" onclick="clearCanvas()" style="flex: 1; margin: 0;">🗑️ Clear All</button>
                <button class="tool-btn" onclick="addTime()" style="flex: 1; margin: 0;">⏱️ +30s</button>
            </div>
            <button onclick="submitDrawing()" style="margin-top: 15px;">Submit Drawing</button>
        </div>

        <!-- Waiting Screen -->
        <div id="waiting-screen" class="screen">
            <div class="waiting">
                <div class="owl">🦉</div>
                <h2>Waiting for other players...</h2>
                <p style="margin-top: 20px;" id="waiting-message"></p>
            </div>
        </div>

        <!-- Guessing Screen -->
        <div id="guessing-screen" class="screen">
            <div class="status-text">Round <span id="guess-round-num">1</span>/3 - Guessing Phase</div>
            <div class="timer-display" id="guess-timer-display">0:15</div>
            <img id="guess-image" class="drawing-display">
            <input type="text" id="guess-input" placeholder="What is this drawing?" maxlength="50">
            <button onclick="submitGuess()">Submit Guess</button>
        </div>

        <!-- Voting Screen -->
        <div id="voting-screen" class="screen">
            <div class="status-text">Round <span id="vote-round-num">1</span>/3 - Vote for the REAL caption & like your favorites! 👍</div>
            <img id="vote-image" class="drawing-display">
            <div id="vote-options"></div>
            <button onclick="submitVoteWithLikes()" id="submit-vote-btn" disabled>Submit Vote</button>
        </div>

        <!-- Results Screen -->
        <div id="results-screen" class="screen">
            <div class="status-text">Round <span id="results-round-num">1</span>/3 - Results</div>
            <div id="answer-reveal-container" style="display: none;">
                <div class="correct-answer-reveal" id="correct-answer-text">THE REAL PROMPT </div>
                <img id="reveal-drawing" class="reveal-drawing">
            </div>
            <div class="scores" id="round-scores"></div>
            <button onclick="continueToNext()">Continue</button>
        </div>

        <!-- Final Screen -->
        <div id="final-screen" class="screen">
            <div class="status-text">🏆 Final Results 🏆</div>
            <div class="scores" id="final-scores"></div>
            <div style="margin-top: 30px; padding-top: 30px; border-top: 2px solid rgba(255, 79, 0, 0.2);">
                <h2 style="color: #ff4f00; margin-bottom: 15px;">❤️ Most Liked ❤️</h2>
                <div class="scores" id="final-likes"></div>
            </div>
            <button onclick="playAgain()">Play Again</button>
        </div>
    </div>

    <script>
        const socket = io();
        let playerId = null;
        let playerName = '';
        let currentTool = 'pen';
        let lastDrawingTool = 'dark'; // Track last drawing tool for fill color
        let isDrawing = false;
        let ctx = null;
        let playerColors = { light: '#000000', dark: '#000000' };
        let drawingTimer = null;
        let timeRemaining = 60;
        let selectedVote = null;
        let likedOptions = new Set();
        let isCurrentArtist = false; // Track if player is artist for current voting
        let undoStack = []; // Stack to store canvas states for undo

        document.getElementById('game-url').textContent = window.location.href;

        function showScreen(screenId) {
            document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
            document.getElementById(screenId).classList.add('active');
        }

        function joinGame() {
            playerName = document.getElementById('player-name').value.trim();
            if (playerName) {
                socket.emit('join', { name: playerName });
            }
        }

        function startGame() {
            socket.emit('start_game');
        }

        function setTool(tool) {
            currentTool = tool;
            if (tool === 'light' || tool === 'dark') {
                lastDrawingTool = tool; // Remember last drawing color for fill
                // Update color button active states
                document.querySelectorAll('.color-btn').forEach(b => b.classList.remove('active'));
                document.getElementById(tool + '-btn').classList.add('active');
                // Activate pen tool when selecting a color
                document.querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
                document.getElementById('pen-btn').classList.add('active');
                currentTool = 'pen'; // Switch to pen when selecting color
            } else if (tool === 'pen') {
                // Use last selected drawing color
                currentTool = lastDrawingTool;
                document.querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
                document.getElementById('pen-btn').classList.add('active');
            } else {
                // Tool buttons (fill, eraser)
                document.querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
                event.target.classList.add('active');
            }
        }

        function startTimer() {
            timeRemaining = 60;
            updateTimerDisplay();
            // Timer is now controlled by server
        }

        function updateTimerDisplay() {
            const minutes = Math.floor(timeRemaining / 60);
            const seconds = timeRemaining % 60;
            const display = document.getElementById('timer-display');
            display.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
            if (timeRemaining <= 10) {
                display.classList.add('warning');
            } else {
                display.classList.remove('warning');
            }
        }

        function updateGuessTimerDisplay() {
            const seconds = timeRemaining;
            const display = document.getElementById('guess-timer-display');
            display.textContent = `0:${seconds.toString().padStart(2, '0')}`;
            if (timeRemaining <= 5) {
                display.classList.add('warning');
            } else {
                display.classList.remove('warning');
            }
        }

        function addTime() {
            socket.emit('add_time');
        }

        function stopTimer() {
            // Timer is controlled by server
        }

        function saveCanvasState() {
            const canvas = document.getElementById('draw-canvas');
            const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
            undoStack.push(imageData);
            // Limit undo stack to 20 states to prevent memory issues
            if (undoStack.length > 20) {
                undoStack.shift();
            }
        }

        function undoCanvas() {
            if (undoStack.length > 0) {
                const canvas = document.getElementById('draw-canvas');
                const previousState = undoStack.pop();
                ctx.putImageData(previousState, 0, 0);
            }
        }

        function clearCanvas() {
            // Save state before clearing
            saveCanvasState();
            const canvas = document.getElementById('draw-canvas');
            ctx = canvas.getContext('2d');
            ctx.fillStyle = 'white';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
        }

        function initCanvas() {
            const canvas = document.getElementById('draw-canvas');
            ctx = canvas.getContext('2d');
            ctx.fillStyle = 'white';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            undoStack = []; // Clear undo stack for new drawing

            function getPos(e) {
                const rect = canvas.getBoundingClientRect();
                const touch = e.touches ? e.touches[0] : e;
                return {
                    x: (touch.clientX - rect.left) * (canvas.width / rect.width),
                    y: (touch.clientY - rect.top) * (canvas.height / rect.height)
                };
            }

            function startDraw(e) {
                e.preventDefault();
                const pos = getPos(e);
                
                if (currentTool === 'fill') {
                    // Save current state for undo
                    saveCanvasState();
                    
                    // Flood fill algorithm using last selected drawing color
                    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
                    const targetColor = getPixelColor(imageData, Math.floor(pos.x), Math.floor(pos.y));
                    
                    // Use last selected drawing tool color for fill
                    let fillColor;
                    if (lastDrawingTool === 'light') {
                        fillColor = hexToRgb(playerColors.light);
                    } else {
                        fillColor = hexToRgb(playerColors.dark);
                    }
                    
                    if (colorsMatch(targetColor, fillColor, 0)) {
                        return; // Don't fill if same color (exact match)
                    }
                    
                    floodFill(imageData, Math.floor(pos.x), Math.floor(pos.y), targetColor, fillColor);
                    ctx.putImageData(imageData, 0, 0);
                } else {
                    // Save current state for undo
                    saveCanvasState();
                    isDrawing = true;
                    ctx.beginPath();
                    ctx.moveTo(pos.x, pos.y);
                }
            }

            function draw(e) {
                if (!isDrawing) return;
                e.preventDefault();
                const pos = getPos(e);
                const size = document.getElementById('size-slider').value;
                
                let color;
                if (currentTool === 'eraser') {
                    color = 'white';
                } else if (currentTool === 'light' || lastDrawingTool === 'light') {
                    color = playerColors.light;
                } else {
                    color = playerColors.dark;
                }
                
                ctx.lineWidth = size;
                ctx.lineCap = 'round';
                ctx.strokeStyle = color;
                ctx.lineTo(pos.x, pos.y);
                ctx.stroke();
                ctx.beginPath();
                ctx.moveTo(pos.x, pos.y);
            }

            function stopDraw() {
                isDrawing = false;
                ctx.beginPath();
            }

            canvas.addEventListener('mousedown', startDraw);
            canvas.addEventListener('mousemove', draw);
            canvas.addEventListener('mouseup', stopDraw);
            canvas.addEventListener('touchstart', startDraw);
            canvas.addEventListener('touchmove', draw);
            canvas.addEventListener('touchend', stopDraw);
        }

        // Flood fill helper functions
        function hexToRgb(hex) {
            const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
            return result ? {
                r: parseInt(result[1], 16),
                g: parseInt(result[2], 16),
                b: parseInt(result[3], 16),
                a: 255
            } : null;
        }

        function getPixelColor(imageData, x, y) {
            const index = (Math.floor(y) * imageData.width + Math.floor(x)) * 4;
            return {
                r: imageData.data[index],
                g: imageData.data[index + 1],
                b: imageData.data[index + 2],
                a: imageData.data[index + 3]
            };
        }

        function colorsMatch(a, b, tolerance = 50) {
            // Use tolerance to handle anti-aliasing at edges
            return Math.abs(a.r - b.r) <= tolerance && 
                   Math.abs(a.g - b.g) <= tolerance && 
                   Math.abs(a.b - b.b) <= tolerance && 
                   Math.abs(a.a - b.a) <= tolerance;
        }

        function floodFill(imageData, x, y, targetColor, fillColor) {
            const width = imageData.width;
            const height = imageData.height;
            const stack = [[Math.floor(x), Math.floor(y)]];
            const visited = new Set();
            
            while (stack.length > 0) {
                const [cx, cy] = stack.pop();
                const key = `${cx},${cy}`;
                
                if (visited.has(key) || cx < 0 || cx >= width || cy < 0 || cy >= height) {
                    continue;
                }
                
                visited.add(key);
                const currentColor = getPixelColor(imageData, cx, cy);
                
                if (!colorsMatch(currentColor, targetColor)) {
                    continue;
                }
                
                const index = (cy * width + cx) * 4;
                imageData.data[index] = fillColor.r;
                imageData.data[index + 1] = fillColor.g;
                imageData.data[index + 2] = fillColor.b;
                imageData.data[index + 3] = fillColor.a;
                
                // Fill in 4 cardinal directions
                stack.push([cx + 1, cy]);
                stack.push([cx - 1, cy]);
                stack.push([cx, cy + 1]);
                stack.push([cx, cy - 1]);
                
                // Fill in 4 diagonal directions to expand reach
                stack.push([cx + 1, cy + 1]);
                stack.push([cx + 1, cy - 1]);
                stack.push([cx - 1, cy + 1]);
                stack.push([cx - 1, cy - 1]);
                
                // Expand reach by 2 more pixels in cardinal directions
                stack.push([cx + 2, cy]);
                stack.push([cx - 2, cy]);
                stack.push([cx, cy + 2]);
                stack.push([cx, cy - 2]);
                
                // Expand reach by 3 pixels in cardinal directions
                stack.push([cx + 3, cy]);
                stack.push([cx - 3, cy]);
                stack.push([cx, cy + 3]);
                stack.push([cx, cy - 3]);
            }
        }

        function submitDrawing() {
            stopTimer();
            const canvas = document.getElementById('draw-canvas');
            const imageData = canvas.toDataURL();
            socket.emit('submit_drawing', { image: imageData });
            showScreen('waiting-screen');
            document.getElementById('waiting-message').textContent = 'Waiting for others to finish drawing...';
        }

        function submitGuess() {
            const guess = document.getElementById('guess-input').value.trim();
            if (guess) {
                socket.emit('submit_guess', { guess: guess });
                document.getElementById('guess-input').value = '';
                showScreen('waiting-screen');
                document.getElementById('waiting-message').textContent = 'Waiting for others to guess...';
            }
        }

        socket.on('duplicate_guess', (data) => {
            alert(data.message);
            showScreen('guessing-screen');
        });

        function nextRound() {
            socket.emit('next_round');
        }

        function continueToNext() {
            socket.emit('continue_to_next');
        }

        function playAgain() {
            socket.emit('play_again');
        }

        function showTitleCard(text) {
            const titleCard = document.getElementById('title-card');
            const titleText = document.getElementById('title-card-text');
            titleText.textContent = text;
            titleCard.classList.add('active');
            setTimeout(() => {
                titleCard.classList.remove('active');
            }, 3000);
        }

        // Socket events
        socket.on('game_in_progress', () => {
            alert('Sorry, you cannot join because the game has already started. Please wait for the next round!');
            document.getElementById('join-name').value = '';
        });

        socket.on('joined', (data) => {
            playerId = data.player_id;
            playerColors = data.colors;
            playerName = document.getElementById('player-name').value.trim();
            // Update color button backgrounds with actual player colors
            document.getElementById('light-btn').style.background = playerColors.light;
            document.getElementById('dark-btn').style.background = playerColors.dark;
            // Show user name box
            document.getElementById('user-name-box').textContent = playerName;
            document.getElementById('user-name-box').style.display = 'block';
            showScreen('lobby-screen');
        });

        socket.on('update_lobby', (data) => {
            const playersList = document.getElementById('lobby-players');
            playersList.innerHTML = '';
            Object.values(data.players).forEach(player => {
                const div = document.createElement('div');
                div.className = 'player-item';
                div.innerHTML = `<span>${player.name}</span>`;
                playersList.appendChild(div);
            });
            
            const startBtn = document.getElementById('start-btn');
            startBtn.disabled = Object.keys(data.players).length < 2;
        });

        socket.on('game_started', (data) => {
            const roundNum = data.round + 1;
            document.getElementById('round-num').textContent = roundNum;
            document.getElementById('guess-round-num').textContent = roundNum;
            document.getElementById('vote-round-num').textContent = roundNum;
            document.getElementById('results-round-num').textContent = roundNum;
            showTitleCard('Drawing Phase');
        });

        socket.on('your_turn_draw', (data) => {
            setTimeout(() => {
                showScreen('drawing-screen');
                document.getElementById('draw-prompt').textContent = `"${data.prompt}"`;
                const roundNum = data.round + 1;
                document.getElementById('round-num').textContent = roundNum;
                document.getElementById('guess-round-num').textContent = roundNum;
                document.getElementById('vote-round-num').textContent = roundNum;
                document.getElementById('results-round-num').textContent = roundNum;
                initCanvas();
                startTimer();
            }, 3000);
        });

        socket.on('timer_tick', (data) => {
            timeRemaining = data.time;
            updateTimerDisplay();
        });

        socket.on('timer_expired', () => {
            stopTimer();
            submitDrawing();
        });

        socket.on('show_guessing_phase', () => {
            showTitleCard('Guessing Phase');
        });

        socket.on('show_voting_phase', () => {
            showTitleCard('Voting Phase');
        });

        socket.on('your_turn_guess', (data) => {
            setTimeout(() => {
                showScreen('guessing-screen');
                document.getElementById('guess-image').src = data.image;
                timeRemaining = 15;
                updateGuessTimerDisplay();
            }, 3000);
        });

        socket.on('guess_timer_tick', (data) => {
            timeRemaining = data.time;
            updateGuessTimerDisplay();
        });

        socket.on('guess_timer_expired', () => {
            const guess = document.getElementById('guess-input').value.trim();
            if (guess) {
                socket.emit('submit_guess', { guess: guess });
                document.getElementById('guess-input').value = '';
            } else {
                // Submit empty guess to trigger progression
                socket.emit('guess_time_up');
            }
            showScreen('waiting-screen');
            document.getElementById('waiting-message').textContent = 'Waiting for others...';
        });

        socket.on('your_turn_vote', (data) => {
            // Check if this player is the artist
            isCurrentArtist = playerId === data.artist_id;
            
            // After 3 seconds (title card time), show voting screen
            setTimeout(() => {
                showScreen('voting-screen');
                document.getElementById('vote-image').src = data.image;
                const optionsDiv = document.getElementById('vote-options');
                optionsDiv.innerHTML = '';
                selectedVote = null;
                likedOptions = new Set();
                
                // Grey out submit button for artists
                const submitBtn = document.getElementById('submit-vote-btn');
                if (isCurrentArtist) {
                    submitBtn.disabled = true;
                    submitBtn.style.opacity = '0.3';
                    submitBtn.style.cursor = 'not-allowed';
                } else {
                    submitBtn.disabled = true; // Still disabled until selection
                    submitBtn.style.opacity = '';
                    submitBtn.style.cursor = '';
                }
                
                data.options.forEach((option, index) => {
                    const optionDiv = document.createElement('div');
                    optionDiv.className = 'vote-option';
                    optionDiv.dataset.text = option.text;
                    
                    const textSpan = document.createElement('span');
                    textSpan.className = 'vote-option-text';
                    textSpan.textContent = option.text;
                    
                    const likeBtn = document.createElement('button');
                    likeBtn.className = 'like-btn';
                    likeBtn.innerHTML = '♡'; // Empty heart
                    likeBtn.onclick = (e) => {
                        e.stopPropagation();
                        toggleLike(option.text, likeBtn);
                    };
                    
                    // Only allow non-artists to vote
                    if (!isCurrentArtist) {
                        optionDiv.onclick = () => selectVote(option.text, optionDiv);
                    }
                    
                    optionDiv.appendChild(textSpan);
                    optionDiv.appendChild(likeBtn);
                    optionsDiv.appendChild(optionDiv);
                });
            }, 3000);
        });

        function selectVote(text, element) {
            // Prevent artists from voting
            if (isCurrentArtist) return;
            
            selectedVote = text;
            document.querySelectorAll('.vote-option').forEach(opt => opt.classList.remove('selected'));
            element.classList.add('selected');
            document.getElementById('submit-vote-btn').disabled = false;
        }

        function toggleLike(text, button) {
            if (likedOptions.has(text)) {
                likedOptions.delete(text);
                button.innerHTML = '♡'; // Empty heart
                button.classList.remove('liked');
            } else {
                likedOptions.add(text);
                button.innerHTML = '♥'; // Filled heart
                button.classList.add('liked');
            }
        }

        function submitVoteWithLikes() {
            if (selectedVote) {
                // Auto-collect any current likes when submitting vote
                socket.emit('submit_vote', { 
                    vote: selectedVote,
                    likes: Array.from(likedOptions)
                });
                showScreen('waiting-screen');
                document.getElementById('waiting-message').textContent = 'Waiting for others to vote...';
            }
        }

        // When voting phase ends, auto-submit any likes the player has selected
        socket.on('auto_submit_likes', () => {
            if (likedOptions.size > 0) {
                socket.emit('submit_likes_only', {
                    likes: Array.from(likedOptions)
                });
            }
        });

        socket.on('show_results', (data) => {
            showScreen('results-screen');
            const scoresDiv = document.getElementById('round-scores');
            scoresDiv.innerHTML = '<h3 style="margin-bottom: 15px;">Scores:</h3>';
            
            const sorted = Object.entries(data.scores).sort((a, b) => b[1] - a[1]);
            sorted.forEach(([pid, score]) => {
                const player = data.players[pid];
                const likes = data.likes[pid] || 0;
                const div = document.createElement('div');
                div.className = 'score-item';
                div.innerHTML = `<span>${player.name}</span><span>${score} pts | ❤️ ${likes}</span>`;
                scoresDiv.appendChild(div);
            });
        });

        socket.on('wait', (data) => {
            showScreen('waiting-screen');
            document.getElementById('waiting-message').textContent = data.message;
        });

        socket.on('show_current_scores', (data) => {
            // Show dramatic white fade first
            const whiteScreen = document.createElement('div');
            whiteScreen.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: white;
                z-index: 99999;
                animation: fadeOut 0.5s ease-in 2.5s forwards;
            `;
            document.body.appendChild(whiteScreen);
            
            // Wait for fade to complete before showing results
            setTimeout(() => {
                document.body.removeChild(whiteScreen);
                
                showScreen('results-screen');
                
                // Show the correct answer reveal
                const revealContainer = document.getElementById('answer-reveal-container');
                revealContainer.style.display = 'block';
                document.getElementById('correct-answer-text').textContent = `${data.correct_answer}`;
                document.getElementById('reveal-drawing').src = data.drawing_image;
            
            // Show who wrote what and who voted for what
            const votingDetails = document.createElement('div');
            votingDetails.style.cssText = 'margin: 20px 0; padding: 15px; background: rgba(255, 79, 0, 0.15);';
            votingDetails.innerHTML = '<h4 style="margin-bottom: 10px; color: #ff4f00;">Voting Details:</h4>';
            
            // Show the correct answer with artist
            const artist = data.players[data.artist_id];
            const correctDiv = document.createElement('div');
            correctDiv.style.cssText = 'margin: 8px 0; padding: 8px; background: rgba(64, 249, 155, 0.15);';
            correctDiv.innerHTML = `<strong>✓ "${data.correct_answer}"</strong> - by ${artist.name} (correct answer)`;
            votingDetails.appendChild(correctDiv);
            
            // Count votes for each option
            const voteCount = {};
            const votersPerOption = {};
            
            // Count votes for correct answer
            voteCount[data.correct_answer] = 0;
            votersPerOption[data.correct_answer] = [];
            
            data.votes.forEach(v => {
                if (!voteCount[v.vote]) {
                    voteCount[v.vote] = 0;
                    votersPerOption[v.vote] = [];
                }
                voteCount[v.vote]++;
                votersPerOption[v.vote].push(data.players[v.player_id].name);
            });
            
            // Show each guess with author and voters
            data.guesses.forEach(g => {
                const guessDiv = document.createElement('div');
                guessDiv.style.cssText = 'margin: 8px 0; padding: 8px; background: rgba(255, 255, 255, 0.5);';
                const guesser = data.players[g.player_id];
                const votes = voteCount[g.guess] || 0;
                const voters = votersPerOption[g.guess] || [];
                const votersList = voters.length > 0 ? ` - fooled: ${voters.join(', ')}` : '';
                guessDiv.innerHTML = `"${g.guess}" - by ${guesser.name} (${votes} vote${votes !== 1 ? 's' : ''}${votersList})`;
                votingDetails.appendChild(guessDiv);
            });
            
            // Show votes for correct answer
            const correctVotes = voteCount[data.correct_answer] || 0;
            const correctVoters = votersPerOption[data.correct_answer] || [];
            if (correctVoters.length > 0) {
                const correctVotersDiv = document.createElement('div');
                correctVotersDiv.style.cssText = 'margin: 8px 0; padding: 8px; background: rgba(64, 249, 155, 0.1); font-style: italic;';
                correctVotersDiv.innerHTML = `Guessed correctly: ${correctVoters.join(', ')}`;
                votingDetails.appendChild(correctVotersDiv);
            }
            
            // Insert voting details before scores
            const scoresDiv = document.getElementById('round-scores');
            scoresDiv.innerHTML = '';
            scoresDiv.appendChild(votingDetails);
            
            const scoresHeader = document.createElement('h3');
            scoresHeader.style.cssText = 'margin-bottom: 15px; margin-top: 20px;';
            scoresHeader.textContent = 'Current Scores:';
            scoresDiv.appendChild(scoresHeader);
            
            const sorted = Object.entries(data.scores).sort((a, b) => b[1] - a[1]);
            sorted.forEach(([pid, score]) => {
                const player = data.players[pid];
                const div = document.createElement('div');
                div.className = 'score-item';
                div.innerHTML = `<span>${player.name}</span><span>${score} pts</span>`;
                scoresDiv.appendChild(div);
            });
            }, 3000); // End of setTimeout for white fade
        });

        socket.on('show_final', (data) => {
            showScreen('final-screen');
            
            // Display score winners
            const scoresDiv = document.getElementById('final-scores');
            scoresDiv.innerHTML = '';
            const sorted = Object.entries(data.scores).sort((a, b) => b[1] - a[1]);
            sorted.forEach(([pid, score], idx) => {
                const player = data.players[pid];
                const div = document.createElement('div');
                div.className = idx === 0 ? 'score-item winner' : 'score-item';
                const medal = idx === 0 ? '🥇 ' : idx === 1 ? '🥈 ' : idx === 2 ? '🥉 ' : '';
                div.innerHTML = `<span>${medal}${player.name}</span><span>${score} pts</span>`;
                scoresDiv.appendChild(div);
            });
            
            // Display likes winners
            const likesDiv = document.getElementById('final-likes');
            likesDiv.innerHTML = '';
            const sortedLikes = Object.entries(data.likes).sort((a, b) => b[1] - a[1]);
            sortedLikes.forEach(([pid, likes], idx) => {
                const player = data.players[pid];
                const div = document.createElement('div');
                div.className = idx === 0 ? 'score-item winner' : 'score-item';
                const medal = idx === 0 ? '🥇 ' : idx === 1 ? '🥈 ' : idx === 2 ? '🥉 ' : '';
                div.innerHTML = `<span>${medal}${player.name}</span><span>❤️ ${likes} likes</span>`;
                likesDiv.appendChild(div);
            });
        });

        socket.on('wait', (data) => {
            showScreen('waiting-screen');
            document.getElementById('waiting-message').textContent = data.message;
        });

        socket.on('reset', () => {
            showScreen('lobby-screen');
        });
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/qr_code")
def qr_code():
    """Generate QR code for the game URL"""

    # Get the server's network address
    import socket as sock

    local_ip = sock.gethostbyname(HOSTNAME)
    url = f"http://{local_ip}:5001"

    # Generate QR code
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    # Convert to bytes
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    from flask import send_file

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
            socketio.emit("guess_timer_tick", {"time": guess_timer_state["time_remaining"]})
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
    guess_timer_state["time_remaining"] = 15
    guess_timer_state["active"] = True
    if guess_timer_state["thread"] is None or not guess_timer_state["thread"].is_alive():
        guess_timer_state["thread"] = threading.Thread(target=guess_timer_thread, daemon=True)
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
            
            emit("joined", {"player_id": player_id, "colors": PLAYER_COLORS[pdata["color_index"]]})
            
            # Restore player to current game state if game is in progress
            if game_state["phase"] != "lobby":
                current_idx = game_state.get("current_drawing_index", 0)
                
                if game_state["phase"] == "drawing":
                    # Check if player has already submitted drawing
                    has_submitted = any(d["player_id"] == player_id for d in game_state["drawings"])
                    if not has_submitted and player_id in game_state["players"]:
                        prompt = game_state["players"][player_id].get("prompt", "Draw something!")
                        emit("your_turn_draw", {"prompt": prompt, "round": game_state.get("round", 0)})
                    else:
                        emit("wait", {"message": "Waiting for others to finish drawing..."})
                
                elif game_state["phase"] == "guessing":
                    if current_idx < len(game_state["drawings"]):
                        current_drawing = game_state["drawings"][current_idx]
                        # Check if player is the artist or has already guessed
                        is_artist = current_drawing["player_id"] == player_id
                        has_guessed = any(g["player_id"] == player_id for g in game_state["guesses"].get(current_idx, []))
                        
                        if is_artist:
                            emit("wait", {"message": "Waiting for others to guess your drawing..."})
                        elif not has_guessed:
                            emit("your_turn_guess", {"image": current_drawing["image"], "drawing_index": current_idx})
                        else:
                            emit("wait", {"message": "Waiting for others to guess..."})
                
                elif game_state["phase"] == "voting":
                    if current_idx < len(game_state["drawings"]):
                        current_drawing = game_state["drawings"][current_idx]
                        artist_id = current_drawing["player_id"]
                        is_artist = artist_id == player_id
                        has_voted = any(v["player_id"] == player_id for v in game_state["votes"].get(current_idx, []))
                        
                        if not has_voted and not is_artist:
                            # Recreate voting options
                            options = [{"text": current_drawing["prompt"], "is_correct": True}]
                            for guess in game_state["guesses"].get(current_idx, []):
                                options.append({"text": guess["guess"], "is_correct": False})
                            import random
                            random.shuffle(options)
                            emit("your_turn_vote", {"image": current_drawing["image"], "options": options, "drawing_index": current_idx, "artist_id": artist_id})
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

        # Reload prompts from file to get current unused list
        import random
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
            socketio.emit("your_turn_guess", {"image": current["image"], "drawing_index": current_idx}, room=pid)
        else:
            socketio.emit(
                "wait", {"message": "Waiting for others to guess your drawing..."}, room=pid
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
        emit("duplicate_guess", {"message": "That's the real prompt! Try guessing something different."})
        return
    
    # Check if guess matches any existing guess
    for existing_guess in game_state["guesses"][current_idx]:
        if guess.lower() == existing_guess["guess"].lower():
            emit("duplicate_guess", {"message": "That prompt has already been submitted! Try something different."})
            return
    
    # Prevent duplicate guesses from same player for this drawing
    if not any(g["player_id"] == player_id for g in game_state["guesses"][current_idx]):
        if guess:  # Only add non-empty guesses
            game_state["guesses"][current_idx].append({"player_id": player_id, "guess": guess})

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
        print(f"Error: current_drawing_index {current_idx} out of range (only {len(game_state['drawings'])} drawings)")
        return
    
    # Initialize votes for this drawing if not exists
    if current_idx not in game_state["votes"]:
        game_state["votes"][current_idx] = []
    
    current = game_state["drawings"][current_idx]
    artist_id = current["player_id"]
    options = [{"text": current["prompt"], "is_correct": True}]

    for guess in game_state["guesses"][current_idx]:
        options.append({"text": guess["guess"], "is_correct": False})

    import random
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
        
        import random
        random.shuffle(player_options)
        
        socketio.emit(
            "your_turn_vote",
            {"image": current["image"], "options": player_options, "drawing_index": current_idx, "artist_id": artist_id},
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
        game_state["votes"][current_idx].append({"player_id": player_id, "vote": vote, "likes": likes})

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
            "votes": game_state["votes"].get(idx, [])
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
            room=player_id
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

        # Reload prompts from file to get current unused list
        import random
        available_prompts = load_prompts("unused_prompts.txt")
        random.shuffle(available_prompts)

        for idx, pid in enumerate(game_state["players"].keys()):
            prompt = available_prompts[idx % len(available_prompts)]
            game_state["players"][pid]["prompt"] = prompt
            # Move prompt to used file
            move_prompt_to_used(prompt)
            # Send drawing prompt to each player
            socketio.emit("your_turn_draw", {"prompt": prompt, "round": game_state["round"]}, room=pid)

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
    import socket
    import sys

    # Suppress broken pipe and socket errors
    import warnings
    warnings.filterwarnings("ignore", category=ResourceWarning)
    
    # Custom exception handler to suppress socket errors
    def handle_exception(exc_type, exc_value, exc_traceback):
        # Ignore socket errors (broken pipe, connection reset, etc.)
        if exc_type == OSError and exc_value.errno in (32, 54, 57, 104):
            return
        # Call default handler for other exceptions
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
    
    sys.excepthook = handle_exception

    local_ip = socket.gethostbyname(HOSTNAME)

    print("\n" + "=" * 50)
    print("🎨 DRAWFUL PARTY GAME SERVER 🎨")
    print("=" * 50)
    print("\nServer starting on:")
    print("  Local:   http://localhost:5001")
    print(f"  Network: http://{local_ip}:5001")
    print("\nShare the Network address with players on your WiFi!")
    print("=" * 50 + "\n")

    socketio.run(
        app, 
        host="0.0.0.0", 
        port=5001, 
        debug=False, 
        allow_unsafe_werkzeug=True,
        use_reloader=False
    )
