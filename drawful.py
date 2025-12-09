import secrets
import threading
import time
from io import BytesIO

import qrcode
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config["SECRET_KEY"] = secrets.token_hex(16)
socketio = SocketIO(app, cors_allowed_origins="*")

# Timer state
timer_state = {"active": False, "time_remaining": 60, "thread": None}

# Player colors - each player gets a unique hue with light and dark shades
PLAYER_COLORS = [
    {"light": "#FF6B6B", "dark": "#C92A2A"},  # Red
    {"light": "#4DABF7", "dark": "#1864AB"},  # Blue
    {"light": "#51CF66", "dark": "#2B8A3E"},  # Green
    {"light": "#FFD43B", "dark": "#F08C00"},  # Yellow
    {"light": "#FF6BFF", "dark": "#C92AC9"},  # Magenta
    {"light": "#FF9F40", "dark": "#E67700"},  # Orange
    {"light": "#B197FC", "dark": "#6741D9"},  # Purple
    {"light": "#66D9E8", "dark": "#0B7285"},  # Cyan
]

# Large prompt bank
PROMPT_BANK = [
    "A superhero's day off",
    "Robot learning to dance",
    "Pizza delivery on Mars",
    "Cat running a business meeting",
    "Dinosaur at a birthday party",
    "Underwater tea party",
    "Dragon doing yoga",
    "Astronaut gardening",
    "Penguin surfing",
    "Wizard cooking breakfast",
    "Vampire at a dentist",
    "Alien trying sushi",
    "Zombie barista",
    "Ghost doing laundry",
    "Mermaid riding a bike",
    "Octopus playing piano",
    "Bear in a hot air balloon",
    "Ninja in a library",
    "Pirate doing taxes",
    "Unicorn stuck in traffic",
    "Sasquatch taking a selfie",
    "Time traveler at a drive-thru",
    "Werewolf at the gym",
    "Robot therapist",
    "Chicken crossing the road",
    "Cow jumping over the moon",
    "Fish out of water",
    "Elephant in a china shop",
    "Monkey business",
    "Dog eating homework",
    "Cat got your tongue",
    "Bull in a china shop",
    "Horse of a different color",
    "Raining cats and dogs",
    "Snake in the grass",
    "Wolf in sheep's clothing",
    "Bird's eye view",
    "Busy as a bee",
    "Eagle eye",
    "Lion's share",
    "Shark tank meeting",
    "Turtle race",
    "Snail mail",
    "Butterfly effect",
    "Ant farm manager",
    "Spider-man's day job",
    "Batman at brunch",
    "Superman's laundry day",
    "Wonder Woman's yoga class",
    "Iron Man at the car wash",
    "Thor's hammer time",
    "Hulk doing needlepoint",
    "Black Panther's catnap",
    "Captain America's diet",
    "Spider-Gwen skateboarding",
    "Scarlet Witch cooking",
    "Doctor Strange grocery shopping",
    "Ant-Man's big problem",
    "Wasp's honey harvest",
    "Groot's family tree",
    "Rocket's rocket ship",
    "Star-Lord's mix tape",
    "Gamora's green smoothie",
    "Drax standing still",
    "Thanos gardening",
    "Loki's mischief",
    "Black Widow's web design",
    "Hawkeye's archery lesson",
    "Vision's vision board",
    "Wanda's magic show",
]

# Game state
game_state = {
    "phase": "lobby",  # lobby, drawing, guessing, voting, results, favorites, final
    "players": {},  # {session_id: {name, score, ready, color_index, prompt}}
    "drawings": [],  # [{player_id, prompt, image_data}]
    "guesses": {},  # {drawing_index: [{player_id, guess}]}
    "votes": {},  # {drawing_index: [{player_id, vote}]}
    "favorite_votes": {},  # {player_id: drawing_index}
    "current_drawing_index": 0,
    "round": 0,
    "used_prompts": set(),  # Track used prompts per round
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Drawful Party</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'SF Pro Text', 'Helvetica Neue', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }
        .container {
            max-width: 900px;
            margin: 0 auto;
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border-radius: 16px;
            padding: 30px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.15);
        }
        h1 {
            color: #667eea;
            text-align: center;
            margin-bottom: 30px;
            font-size: 2.5em;
            font-weight: 700;
            letter-spacing: -0.5px;
        }
        .screen { display: none; }
        .screen.active { display: block; }
        input[type="text"] {
            width: 100%;
            padding: 15px;
            border: 1px solid rgba(0,0,0,0.1);
            border-radius: 12px;
            font-size: 16px;
            margin-bottom: 15px;
            background: rgba(255,255,255,0.8);
            transition: all 0.2s;
        }
        input[type="text"]:focus {
            outline: none;
            border-color: #667eea;
            background: white;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        button {
            width: 100%;
            padding: 15px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 17px;
            font-weight: 600;
            cursor: pointer;
            margin-bottom: 10px;
            transition: all 0.2s;
            letter-spacing: -0.3px;
        }
        button:hover { 
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
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
        .players-list {
            background: rgba(102, 126, 234, 0.05);
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 20px;
            border: 1px solid rgba(102, 126, 234, 0.1);
        }
        .player-item {
            background: white;
            padding: 12px 18px;
            margin: 8px 0;
            border-radius: 10px;
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
            border: 2px solid rgba(102, 126, 234, 0.3);
            border-radius: 12px;
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
        }
        .tool-btn {
            flex: 1;
            min-width: 80px;
            padding: 10px;
        }
        .tool-btn.active { 
            background: linear-gradient(135deg, #764ba2 0%, #667eea 100%);
        }
        .prompt-display {
            background: linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%);
            padding: 20px;
            border-radius: 12px;
            text-align: center;
            margin-bottom: 20px;
            font-size: 24px;
            font-weight: 700;
            color: #667eea;
            border: 2px solid rgba(102, 126, 234, 0.2);
            letter-spacing: -0.5px;
        }
        .drawing-display {
            max-width: 100%;
            border: 2px solid rgba(102, 126, 234, 0.3);
            border-radius: 12px;
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
            background: rgba(102, 126, 234, 0.05);
            border-color: rgba(102, 126, 234, 0.3);
        }
        .scores {
            background: rgba(102, 126, 234, 0.05);
            padding: 20px;
            border-radius: 12px;
            border: 1px solid rgba(102, 126, 234, 0.1);
        }
        .score-item {
            padding: 15px 20px;
            margin: 10px 0;
            background: white;
            border-radius: 10px;
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
            background: linear-gradient(135deg, rgba(102, 126, 234, 0.15) 0%, rgba(118, 75, 162, 0.15) 100%);
            border: 2px solid #667eea;
            font-weight: 700;
        }
        .status-text {
            text-align: center;
            padding: 15px;
            background: linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%);
            border-radius: 12px;
            margin-bottom: 20px;
            color: #667eea;
            font-weight: 600;
            border: 2px solid rgba(102, 126, 234, 0.2);
            letter-spacing: -0.3px;
        }
        .waiting {
            text-align: center;
            padding: 30px;
            color: #6b7280;
        }
        .qr-code {
            text-align: center;
            margin: 20px 0;
            padding: 20px;
            background: white;
            border-radius: 12px;
            border: 1px solid rgba(0,0,0,0.08);
            box-shadow: 0 2px 8px rgba(0,0,0,0.04);
        }
        .qr-code img {
            max-width: 200px;
            height: auto;
            border: 2px solid rgba(102, 126, 234, 0.3);
            border-radius: 12px;
        }
        .color-shade {
            width: 50px;
            height: 50px;
            border: 2px solid #333;
            border-radius: 8px;
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
            background: linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%);
            border-radius: 12px;
            margin-bottom: 10px;
            color: #667eea;
            border: 2px solid rgba(102, 126, 234, 0.2);
            letter-spacing: -0.5px;
        }
        .timer-display.warning {
            animation: pulse 1s infinite;
        }
        @keyframes pulse {
            0%, 100% { background: rgba(239, 68, 68, 0.15); border-color: #ef4444; color: #dc2626; }
            50% { background: rgba(239, 68, 68, 0.25); border-color: #dc2626; }
        }
        .favorite-card {
            background: white;
            border-radius: 12px;
            padding: 15px;
            margin: 10px 0;
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            border: 2px solid rgba(0,0,0,0.06);
        }
        .favorite-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 12px 24px rgba(102, 126, 234, 0.15);
            border-color: rgba(102, 126, 234, 0.3);
        }
        .favorite-card.selected {
            border: 3px solid #667eea;
            background: linear-gradient(135deg, rgba(102, 126, 234, 0.08) 0%, rgba(118, 75, 162, 0.08) 100%);
            box-shadow: 0 8px 16px rgba(102, 126, 234, 0.2);
        }
        .favorite-card img {
            width: 100%;
            border-radius: 8px;
            margin-bottom: 10px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Drawful!</h1>
        
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
            <button id="start-btn" onclick="startGame()" disabled>Start Game (Need 2+ players)</button>
            <div class="qr-code">
                <p style="margin-bottom: 10px; color: #6b7280;">Scan to join:</p>
                <img id="qr-code-img" src="/qr_code" alt="QR Code">
                <p style="font-weight: bold; font-size: 14px; margin-top: 10px; color: #667eea;" id="game-url"></p>
            </div>
        </div>

        <!-- Drawing Screen -->
        <div id="drawing-screen" class="screen">
            <div class="status-text">Round <span id="round-num">1</span>/3 - Drawing Phase</div>
            <div class="timer-display" id="timer-display">1:00</div>
            <button class="tool-btn" onclick="addTime()" style="width: 100%; margin-bottom: 15px;">⏱️ Add 30 Seconds</button>
            <div class="prompt-display" id="draw-prompt"></div>
            <div class="drawing-tools">
                <button class="tool-btn" onclick="setTool('light')">🖌️ Light</button>
                <button class="tool-btn active" onclick="setTool('dark')">✏️ Dark</button>
                <button class="tool-btn" onclick="setTool('eraser')">🧹 Eraser</button>
                <input type="range" id="size-slider" min="1" max="20" value="3" style="flex: 2;">
                <button class="tool-btn" onclick="clearCanvas()">🗑️ Clear</button>
            </div>
            <canvas id="draw-canvas" width="600" height="450"></canvas>
            <button onclick="submitDrawing()">Submit Drawing</button>
        </div>

        <!-- Waiting Screen -->
        <div id="waiting-screen" class="screen">
            <div class="waiting">
                <h2>Waiting for other players...</h2>
                <p style="margin-top: 20px;" id="waiting-message"></p>
            </div>
        </div>

        <!-- Guessing Screen -->
        <div id="guessing-screen" class="screen">
            <div class="status-text">Guessing Phase</div>
            <img id="guess-image" class="drawing-display">
            <input type="text" id="guess-input" placeholder="What is this drawing?" maxlength="50">
            <button onclick="submitGuess()">Submit Guess</button>
        </div>

        <!-- Voting Screen -->
        <div id="voting-screen" class="screen">
            <div class="status-text">Voting Phase - Pick the correct answer!</div>
            <img id="vote-image" class="drawing-display">
            <div id="vote-options"></div>
        </div>

        <!-- Results Screen -->
        <div id="results-screen" class="screen">
            <div class="status-text">Round Results</div>
            <div class="scores" id="round-scores"></div>
            <button onclick="nextRound()">Continue</button>
        </div>

        <!-- Favorites Screen -->
        <div id="favorites-screen" class="screen">
            <div class="status-text">Vote for Your Favorite Drawing! 🌟</div>
            <div id="favorites-gallery"></div>
            <button onclick="submitFavorite()" id="submit-favorite-btn" disabled>Submit Vote</button>
        </div>

        <!-- Final Screen -->
        <div id="final-screen" class="screen">
            <div class="status-text">🏆 Final Scores 🏆</div>
            <div class="scores" id="final-scores"></div>
            <button onclick="playAgain()">Play Again</button>
        </div>
    </div>

    <script>
        const socket = io();
        let playerId = null;
        let playerName = '';
        let currentTool = 'dark';
        let isDrawing = false;
        let ctx = null;
        let playerColors = { light: '#000000', dark: '#000000' };
        let drawingTimer = null;
        let timeRemaining = 60;
        let selectedFavorite = null;

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
            document.querySelectorAll('.drawing-tools .tool-btn').forEach(b => b.classList.remove('active'));
            event.target.classList.add('active');
        }

        function startTimer() {
            timeRemaining = 60;
            updateTimerDisplay();
            if (drawingTimer) clearInterval(drawingTimer);
            drawingTimer = setInterval(() => {
                timeRemaining--;
                updateTimerDisplay();
                if (timeRemaining <= 0) {
                    clearInterval(drawingTimer);
                    submitDrawing();
                }
            }, 1000);
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

        function addTime() {
            timeRemaining += 30;
            updateTimerDisplay();
        }

        function stopTimer() {
            if (drawingTimer) {
                clearInterval(drawingTimer);
                drawingTimer = null;
            }
        }

        function clearCanvas() {
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

            function getPos(e) {
                const rect = canvas.getBoundingClientRect();
                const touch = e.touches ? e.touches[0] : e;
                return {
                    x: (touch.clientX - rect.left) * (canvas.width / rect.width),
                    y: (touch.clientY - rect.top) * (canvas.height / rect.height)
                };
            }

            function startDraw(e) {
                isDrawing = true;
                const pos = getPos(e);
                ctx.beginPath();
                ctx.moveTo(pos.x, pos.y);
            }

            function draw(e) {
                if (!isDrawing) return;
                e.preventDefault();
                const pos = getPos(e);
                const size = document.getElementById('size-slider').value;
                
                let color;
                if (currentTool === 'eraser') {
                    color = 'white';
                } else if (currentTool === 'light') {
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

        function submitVote(answer) {
            socket.emit('submit_vote', { vote: answer });
            showScreen('waiting-screen');
            document.getElementById('waiting-message').textContent = 'Waiting for others to vote...';
        }

        function nextRound() {
            socket.emit('next_round');
        }

        function playAgain() {
            socket.emit('play_again');
        }

        function selectFavorite(index) {
            selectedFavorite = index;
            document.querySelectorAll('.favorite-card').forEach((card, i) => {
                if (i === index) {
                    card.classList.add('selected');
                } else {
                    card.classList.remove('selected');
                }
            });
            document.getElementById('submit-favorite-btn').disabled = false;
        }

        function submitFavorite() {
            if (selectedFavorite !== null) {
                socket.emit('submit_favorite', { drawing_index: selectedFavorite });
                showScreen('waiting-screen');
                document.getElementById('waiting-message').textContent = 'Waiting for others to vote...';
            }
        }

        // Socket events
        socket.on('joined', (data) => {
            playerId = data.player_id;
            playerColors = data.colors;
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
            document.getElementById('round-num').textContent = data.round + 1;
        });

        socket.on('your_turn_draw', (data) => {
            showScreen('drawing-screen');
            document.getElementById('draw-prompt').textContent = `"${data.prompt}"`;
            document.getElementById('round-num').textContent = data.round + 1;
            initCanvas();
            startTimer();
        });

        socket.on('your_turn_guess', (data) => {
            showScreen('guessing-screen');
            document.getElementById('guess-image').src = data.image;
        });

        socket.on('your_turn_vote', (data) => {
            showScreen('voting-screen');
            document.getElementById('vote-image').src = data.image;
            const optionsDiv = document.getElementById('vote-options');
            optionsDiv.innerHTML = '';
            
            data.options.forEach(option => {
                const btn = document.createElement('button');
                btn.className = 'answer-btn';
                btn.textContent = option.text;
                btn.onclick = () => submitVote(option.text);
                optionsDiv.appendChild(btn);
            });
        });

        socket.on('show_results', (data) => {
            showScreen('results-screen');
            const scoresDiv = document.getElementById('round-scores');
            scoresDiv.innerHTML = '<h3 style="margin-bottom: 15px;">Scores:</h3>';
            
            const sorted = Object.entries(data.scores).sort((a, b) => b[1] - a[1]);
            sorted.forEach(([pid, score]) => {
                const player = data.players[pid];
                const div = document.createElement('div');
                div.className = 'score-item';
                div.innerHTML = `<span>${player.name}</span><span>${score} pts</span>`;
                scoresDiv.appendChild(div);
            });
        });

        socket.on('show_favorites', (data) => {
            showScreen('favorites-screen');
            const gallery = document.getElementById('favorites-gallery');
            gallery.innerHTML = '';
            selectedFavorite = null;
            
            data.drawings.forEach((drawing, index) => {
                // Skip if this is the player's own drawing
                if (drawing.player_id === playerId) {
                    return;
                }
                
                const card = document.createElement('div');
                card.className = 'favorite-card';
                card.onclick = () => selectFavorite(index);
                const player = data.players[drawing.player_id];
                card.innerHTML = `
                    <img src="${drawing.image}" alt="Drawing">
                    <p style="text-align: center; font-weight: bold; color: #667eea;">${player ? player.name : 'Unknown'}</p>
                    <p style="text-align: center; color: #6b7280;">"${drawing.prompt}"</p>
                `;
                gallery.appendChild(card);
            });
        });

        socket.on('show_final', (data) => {
            showScreen('final-screen');
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

    hostname = sock.gethostname()
    local_ip = sock.gethostbyname(hostname)
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


@socketio.on("join")
def handle_join(data):
    player_id = request.sid

    # Check if game is in progress (not in lobby phase)
    if game_state["phase"] != "lobby":
        emit("game_in_progress")
        return

    # Assign a color to the player based on their order
    color_index = len(game_state["players"]) % len(PLAYER_COLORS)
    player_colors = PLAYER_COLORS[color_index]

    game_state["players"][player_id] = {
        "name": data["name"],
        "score": 0,
        "color_index": color_index,
    }
    emit("joined", {"player_id": player_id, "colors": player_colors})
    socketio.emit("update_lobby", {"players": game_state["players"]})


@socketio.on("start_game")
def handle_start():
    if len(game_state["players"]) >= 2:
        game_state["phase"] = "drawing"
        game_state["round"] = 0
        game_state["drawings"] = []
        game_state["current_drawing_index"] = 0
        game_state["used_prompts"] = set()

        socketio.emit("game_started", {"round": 0})

        # Assign unique prompts to each player
        import random

        available_prompts = [
            p for p in PROMPT_BANK if p not in game_state["used_prompts"]
        ]
        random.shuffle(available_prompts)

        for idx, pid in enumerate(game_state["players"].keys()):
            prompt = available_prompts[idx % len(available_prompts)]
            game_state["players"][pid]["prompt"] = prompt
            game_state["used_prompts"].add(prompt)
            emit("your_turn_draw", {"prompt": prompt, "round": 0}, room=pid)

        # Start the server-side timer
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

    if len(game_state["drawings"]) == len(game_state["players"]):
        stop_timer()
        start_guessing_phase()


def start_guessing_phase():
    game_state["phase"] = "guessing"
    game_state["guesses"] = {}
    game_state["current_drawing_index"] = 0

    for drawing in game_state["drawings"]:
        game_state["guesses"][drawing["player_id"]] = []

    send_next_guess()


def send_next_guess():
    if game_state["current_drawing_index"] >= len(game_state["drawings"]):
        start_voting_phase()
        return

    current = game_state["drawings"][game_state["current_drawing_index"]]

    for pid in game_state["players"].keys():
        if pid != current["player_id"] and not any(
            g["player_id"] == pid for g in game_state["guesses"][current["player_id"]]
        ):
            socketio.emit("your_turn_guess", {"image": current["image"]}, room=pid)
        else:
            socketio.emit(
                "wait", {"message": "Waiting for others to guess..."}, room=pid
            )


@socketio.on("submit_guess")
def handle_guess(data):
    player_id = request.sid
    current = game_state["drawings"][game_state["current_drawing_index"]]

    game_state["guesses"][current["player_id"]].append(
        {"player_id": player_id, "guess": data["guess"]}
    )

    expected_guesses = len(game_state["players"]) - 1
    if len(game_state["guesses"][current["player_id"]]) == expected_guesses:
        game_state["current_drawing_index"] += 1
        send_next_guess()


def start_voting_phase():
    game_state["phase"] = "voting"
    game_state["votes"] = {}
    game_state["current_drawing_index"] = 0

    for drawing in game_state["drawings"]:
        game_state["votes"][drawing["player_id"]] = []

    send_next_vote()


def send_next_vote():
    if game_state["current_drawing_index"] >= len(game_state["drawings"]):
        calculate_scores()
        return

    current = game_state["drawings"][game_state["current_drawing_index"]]
    options = [{"text": current["prompt"], "is_correct": True}]

    for guess in game_state["guesses"][current["player_id"]]:
        options.append({"text": guess["guess"], "is_correct": False})

    import random

    random.shuffle(options)

    for pid in game_state["players"].keys():
        if pid != current["player_id"] and not any(
            v["player_id"] == pid for v in game_state["votes"][current["player_id"]]
        ):
            socketio.emit(
                "your_turn_vote",
                {"image": current["image"], "options": options},
                room=pid,
            )
        else:
            socketio.emit(
                "wait", {"message": "Waiting for others to vote..."}, room=pid
            )


@socketio.on("submit_vote")
def handle_vote(data):
    player_id = request.sid
    current = game_state["drawings"][game_state["current_drawing_index"]]

    game_state["votes"][current["player_id"]].append(
        {"player_id": player_id, "vote": data["vote"]}
    )

    expected_votes = len(game_state["players"]) - 1
    if len(game_state["votes"][current["player_id"]]) == expected_votes:
        game_state["current_drawing_index"] += 1
        send_next_vote()


def calculate_scores():
    for drawing in game_state["drawings"]:
        for vote in game_state["votes"][drawing["player_id"]]:
            voter_id = vote["player_id"]
            voted_answer = vote["vote"]

            if voted_answer == drawing["prompt"]:
                game_state["players"][voter_id]["score"] += 1000
            else:
                for guess in game_state["guesses"][drawing["player_id"]]:
                    if guess["guess"] == voted_answer:
                        game_state["players"][guess["player_id"]]["score"] += 500
                        break

    game_state["phase"] = "results"
    scores = {pid: p["score"] for pid, p in game_state["players"].items()}
    socketio.emit(
        "show_results",
        {"scores": scores, "players": game_state["players"]},
    )


@socketio.on("next_round")
def handle_next_round():
    if game_state["round"] < 2:
        # Start favorites voting phase
        game_state["phase"] = "favorites"
        game_state["favorite_votes"] = {}
        socketio.emit(
            "show_favorites",
            {"drawings": game_state["drawings"], "players": game_state["players"]},
        )
    else:
        # Start favorites voting before final screen
        game_state["phase"] = "favorites"
        game_state["favorite_votes"] = {}
        socketio.emit(
            "show_favorites",
            {"drawings": game_state["drawings"], "players": game_state["players"]},
        )


@socketio.on("submit_favorite")
def handle_favorite(data):
    player_id = request.sid
    game_state["favorite_votes"][player_id] = data["drawing_index"]

    if len(game_state["favorite_votes"]) == len(game_state["players"]):
        # Award points for favorite votes
        for voter_id, drawing_index in game_state["favorite_votes"].items():
            if drawing_index < len(game_state["drawings"]):
                drawing = game_state["drawings"][drawing_index]
                artist_id = drawing["player_id"]
                game_state["players"][artist_id]["score"] += 250

        # Check if we should go to next round or final
        if game_state["round"] < 2:
            game_state["round"] += 1
            game_state["phase"] = "drawing"
            game_state["drawings"] = []
            game_state["used_prompts"] = set()

            # Assign new unique prompts to each player
            import random

            available_prompts = [
                p for p in PROMPT_BANK if p not in game_state["used_prompts"]
            ]
            random.shuffle(available_prompts)

            for idx, pid in enumerate(game_state["players"].keys()):
                prompt = available_prompts[idx % len(available_prompts)]
                game_state["players"][pid]["prompt"] = prompt
                game_state["used_prompts"].add(prompt)
                socketio.emit(
                    "your_turn_draw",
                    {"prompt": prompt, "round": game_state["round"]},
                    room=pid,
                )

            # Start timer for new round
            start_timer()
        else:
            game_state["phase"] = "final"
            scores = {pid: p["score"] for pid, p in game_state["players"].items()}
            socketio.emit(
                "show_final",
                {"scores": scores, "players": game_state["players"]},
            )


@socketio.on("add_time")
def handle_add_time(data):
    # Add time to the server timer
    timer_state["time_remaining"] += 30
    socketio.emit("timer_tick", {"time": timer_state["time_remaining"]})


@socketio.on("play_again")
def handle_play_again():
    for pid in game_state["players"].keys():
        game_state["players"][pid]["score"] = 0

    game_state["phase"] = "lobby"

    game_state["drawings"] = []
    game_state["guesses"] = {}
    game_state["votes"] = {}
    game_state["round"] = 0

    socketio.emit("reset")
    socketio.emit("update_lobby", {"players": game_state["players"]})


if __name__ == "__main__":
    import socket

    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)

    print("\n" + "=" * 50)
    print("🎨 DRAWFUL PARTY GAME SERVER 🎨")
    print("=" * 50)
    print("\nServer starting on:")
    print("  Local:   http://localhost:5001")
    print(f"  Network: http://{local_ip}:5001")
    print("\nShare the Network address with players on your WiFi!")
    print("=" * 50 + "\n")

    socketio.run(
        app, host="0.0.0.0", port=5001, debug=False, allow_unsafe_werkzeug=True
    )
