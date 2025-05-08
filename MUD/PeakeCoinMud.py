from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Store multiple players' states
game_state = {}

@app.route("/")
def home():
    return "PeakeCoin MUD backend (multiplayer ready) is running!"

@app.route("/save", methods=["POST"])
def save():
    data = request.json
    player = data.get("player")
    if not player:
        return jsonify({"error": "Missing 'player' key"}), 400

    game_state[player] = {
        "x": data.get("x", 0),
        "y": data.get("y", 0),
        "inventory": data.get("inventory", []),
    }
    return jsonify({"status": "saved", "data": game_state[player]})

@app.route("/load/<player>", methods=["GET"])
def load(player):
    if player in game_state:
        return jsonify(game_state[player])
    else:
        # return a new default state
        game_state[player] = {"x": 0, "y": 0, "inventory": []}
        return jsonify(game_state[player])

@app.route("/players", methods=["GET"])
def list_players():
    return jsonify(list(game_state.keys()))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
