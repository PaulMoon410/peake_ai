#!/usr/bin/env python3
"""
Simple API wrapper for the autonomous AI system.
This creates a REST API endpoint that can be used to interact with your AI.
"""

from flask import Flask, request, jsonify
from autonomous_self_talk import PeakeSelfTalkEngine, SelfTalkRunner
import threading
import time
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Global variables to store the AI engine and runner
engine = None
runner = None

# Configure paths based on environment
DATA_DIR = os.getenv("DATA_DIR", "/data")
DIALOGUE_FILE = os.path.join(DATA_DIR, "self_talk_dialogue.json")
BUFFER_FILE = os.path.join(DATA_DIR, "online_learning_buffer.json")

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

@app.route('/api/selftalk/start', methods=['POST'])
def start_self_talk():
    """Start the self-talk process with an optional topic."""
    global runner

    data = request.get_json() or {}
    topic = data.get('topic', '')

    try:
        if runner is None:
            # Initialize with custom paths for Render deployment
            runner = SelfTalkRunner(
                engine_factory=lambda: PeakeSelfTalkEngine(
                    dialogue_path=DIALOGUE_FILE,
                    buffer_path=BUFFER_FILE
                )
            )

        if runner.running:
            return jsonify({"status": "error", "message": "Self-talk is already running"}), 400

        runner.start(topic)
        logger.info(f"Self-talk started with topic: {topic}")
        return jsonify({
            "status": "success", 
            "message": f"Self-talk started with topic: {topic}",
            "status": runner.status()
        })
    except Exception as e:
        logger.error(f"Error starting self-talk: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/selftalk/stop', methods=['POST'])
def stop_self_talk():
    """Stop the self-talk process."""
    global runner

    try:
        if runner is None or not runner.running:
            return jsonify({"status": "error", "message": "Self-talk is not running"}), 400

        runner.stop("API stop request")
        return jsonify({"status": "success", "message": "Self-talk stopped"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/selftalk/status', methods=['GET'])
def self_talk_status():
    """Get the current status of the self-talk process."""
    global runner

    try:
        if runner is None:
            return jsonify({"status": "stopped"})

        status = runner.status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/selftalk/next_turn', methods=['POST'])
def next_turn():
    """Execute a single turn of self-talk."""
    global engine

    try:
        if engine is None:
            engine = PeakeSelfTalkEngine(
                dialogue_path=DIALOGUE_FILE,
                buffer_path=BUFFER_FILE
            )

        turn = engine.next_turn()
        logger.info(f"Executed turn on topic: {turn.get('topic', 'unknown')}")
        return jsonify({
            "status": "success",
            "turn": turn
        })
    except Exception as e:
        logger.error(f"Error executing turn: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/selftalk/execute', methods=['POST'])
def execute_self_talk():
    """Execute a specified number of self-talk turns."""
    global engine

    data = request.get_json() or {}
    cycles = data.get('cycles', 1)
    topic = data.get('topic', '')

    try:
        if engine is None:
            engine = PeakeSelfTalkEngine(
                dialogue_path=DIALOGUE_FILE,
                buffer_path=BUFFER_FILE
            )

        results = engine.execute_self_talk_command(cycles, topic)
        logger.info(f"Executed {cycles} turns on topic: {topic or 'default'}")
        return jsonify({
            "status": "success",
            "results": results
        })
    except Exception as e:
        logger.error(f"Error executing self-talk: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/selftalk/dialogue', methods=['GET'])
def get_dialogue():
    """Get the current dialogue."""
    global engine

    try:
        if engine is None:
            engine = PeakeSelfTalkEngine(
                dialogue_path=DIALOGUE_FILE,
                buffer_path=BUFFER_FILE
            )

        turns = engine.dialogue.recent()
        logger.info(f"Retrieved {len(turns)} dialogue turns")
        return jsonify({
            "status": "success",
            "turns": turns,
            "count": len(turns)
        })
    except Exception as e:
        logger.error(f"Error retrieving dialogue: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    # Start the Flask development server
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("DEBUG", "false").lower() == "true"

    logger.info(f"Starting AI API server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=debug)
