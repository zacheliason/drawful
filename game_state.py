"""
Game state management and core game logic.
"""
import random

import config


class GameState:
    """Manages the state of the game."""
    
    def __init__(self):
        self.reset()
    
    def reset(self):
        """Reset game to initial lobby state."""
        self.phase = "lobby"  # lobby, drawing, guessing, voting, results, final
        self.players = {}  # {session_id: {name, emoji, score, likes, ready, color_index, prompt}}
        self.drawings = []  # [{player_id, prompt, image_data}]
        self.guesses = {}  # {drawing_index: [{player_id, guess}]}
        self.votes = {}  # {drawing_index: [{player_id, vote}]}
        self.current_drawing_index = 0
        self.current_drawer_index = 0
        self.player_order = []  # List of player IDs in drawing order
        self.round = 0
        self.continue_ready = set()  # Track which players have clicked continue
    
    def add_player(self, session_id, name, emoji="😀"):
        """
        Add a new player to the game.
        
        Args:
            session_id: Unique session identifier
            name: Player's display name
            emoji: Player's chosen emoji
        
        Returns:
            dict: Player data or None if game is full/started
        """
        if self.phase != "lobby":
            return None
        
        if len(self.players) >= config.MAX_PLAYERS:
            return None
        
        # Assign color based on player count
        color_index = len(self.players) % len(config.PLAYER_COLORS)
        
        self.players[session_id] = {
            "name": name,
            "emoji": emoji,
            "score": 0,
            "likes": 0,
            "ready": False,
            "color_index": color_index,
            "prompt": None,
        }
        
        return self.players[session_id]
    
    def remove_player(self, session_id):
        """Remove a player from the game."""
        if session_id in self.players:
            del self.players[session_id]
        
        # Remove from continue_ready set if present
        self.continue_ready.discard(session_id)
        
        # Remove from player_order if present
        if session_id in self.player_order:
            self.player_order.remove(session_id)
    
    def can_start_game(self):
        """Check if game has enough players to start."""
        return len(self.players) >= config.MIN_PLAYERS
    
    def start_new_round(self):
        """Initialize a new round."""
        self.round += 1
        self.drawings = []
        self.guesses = {}
        self.votes = {}
        self.current_drawing_index = 0
        self.current_drawer_index = 0
        self.continue_ready = set()
        
        # Randomize player order for this round
        self.player_order = list(self.players.keys())
        random.shuffle(self.player_order)
    
    def all_drawings_complete(self):
        """Check if all players have submitted drawings."""
        return len(self.drawings) == len(self.players)
    
    def all_guesses_complete(self):
        """Check if all players (except artist) have guessed current drawing."""
        current_idx = self.current_drawing_index
        if current_idx not in self.guesses:
            return False
        
        # Expected guesses = all players except the artist
        expected_guesses = len(self.players) - 1
        return len(self.guesses[current_idx]) == expected_guesses
    
    def all_votes_complete(self):
        """Check if all players have submitted votes/likes on current drawing."""
        current_idx = self.current_drawing_index
        if current_idx not in self.votes:
            return False
        
        # Expected votes = all players (including artist who submits likes-only)
        expected_votes = len(self.players)
        return len(self.votes[current_idx]) == expected_votes
    
    def all_players_ready_to_continue(self):
        """Check if all players have clicked continue."""
        return len(self.continue_ready) == len(self.players)
    
    def get_player_scores(self):
        """
        Get sorted list of players by score.
        
        Returns:
            list: Players sorted by score (descending)
        """
        return sorted(
            [{"id": pid, **pdata} for pid, pdata in self.players.items()],
            key=lambda x: x["score"],
            reverse=True
        )
    
    def calculate_scores_for_drawing(self, drawing_index):
        """
        Calculate and update scores for a specific drawing.
        
        Args:
            drawing_index: Index of the drawing to score
        
        Returns:
            dict: Scoring information including correct answer and vote details
        """
        if drawing_index >= len(self.drawings):
            return None
        
        drawing = self.drawings[drawing_index]
        correct_answer = drawing["prompt"]
        artist_id = drawing["player_id"]
        
        # Get all guesses and votes for this drawing
        guesses = self.guesses.get(drawing_index, [])
        votes = self.votes.get(drawing_index, [])
        
        # Track who voted for what
        vote_details = []
        
        # Award points for votes
        for vote_data in votes:
            voter_id = vote_data["player_id"]
            vote = vote_data.get("vote")
            likes = vote_data.get("likes", [])
            
            # Award likes
            for liked_guess in likes:
                for guess_data in guesses:
                    if guess_data["guess"] == liked_guess:
                        liked_player_id = guess_data["player_id"]
                        if liked_player_id in self.players:
                            self.players[liked_player_id]["likes"] += 1
            
            # Skip vote processing if no vote (artist likes-only)
            if not vote:
                continue
            
            # Check if vote is correct
            if vote.lower() == correct_answer.lower():
                # Correct guess - voter gets 1000 points
                if voter_id in self.players:
                    self.players[voter_id]["score"] += 1000
                # Artist gets 500 points for each correct vote
                if artist_id in self.players:
                    self.players[artist_id]["score"] += 500
                vote_details.append({
                    "voter": self.players[voter_id]["name"] if voter_id in self.players else "Unknown",
                    "vote": vote,
                    "correct": True
                })
            else:
                # Wrong guess - check if they voted for someone's fake answer
                for guess_data in guesses:
                    if guess_data["guess"] and guess_data["guess"].lower() == vote.lower():
                        # Found the player who wrote this fake answer
                        fake_answer_player_id = guess_data["player_id"]
                        if fake_answer_player_id in self.players:
                            # Fake answer writer gets 500 points
                            self.players[fake_answer_player_id]["score"] += 500
                        break
                
                vote_details.append({
                    "voter": self.players[voter_id]["name"] if voter_id in self.players else "Unknown",
                    "vote": vote,
                    "correct": False
                })
        
        # Create guess details (who wrote what)
        guess_details = [
            {
                "player": self.players[g["player_id"]]["name"] if g["player_id"] in self.players else "Unknown",
                "guess": g["guess"]
            }
            for g in guesses
        ]
        
        return {
            "correct_answer": correct_answer,
            "artist": self.players[artist_id]["name"] if artist_id in self.players else "Unknown",
            "vote_details": vote_details,
            "guess_details": guess_details,
            "drawing_image": drawing["image"]
        }


# Global game state instance
game_state = GameState()
