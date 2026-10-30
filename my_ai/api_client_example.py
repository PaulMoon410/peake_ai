#!/usr/bin/env python3
"""
Example client for the AI API wrapper.
This demonstrates how to interact with your AI system through the API.
"""

import requests
import json
import time

# API base URL
API_BASE_URL = "http://localhost:5000/api"

def start_self_talk(topic=""):
    """Start the self-talk process."""
    url = f"{API_BASE_URL}/selftalk/start"
    data = {"topic": topic}
    response = requests.post(url, json=data)
    return response.json()

def stop_self_talk():
    """Stop the self-talk process."""
    url = f"{API_BASE_URL}/selftalk/stop"
    response = requests.post(url)
    return response.json()

def get_status():
    """Get the current status of the self-talk process."""
    url = f"{API_BASE_URL}/selftalk/status"
    response = requests.get(url)
    return response.json()

def next_turn():
    """Execute a single turn of self-talk."""
    url = f"{API_BASE_URL}/selftalk/next_turn"
    response = requests.post(url)
    return response.json()

def execute_turns(cycles=1, topic=""):
    """Execute a specified number of self-talk turns."""
    url = f"{API_BASE_URL}/selftalk/execute"
    data = {"cycles": cycles, "topic": topic}
    response = requests.post(url, json=data)
    return response.json()

def get_dialogue():
    """Get the current dialogue."""
    url = f"{API_BASE_URL}/selftalk/dialogue"
    response = requests.get(url)
    return response.json()

def main():
    print("AI API Client Example")
    print("---------------------")

    # Example 1: Start self-talk with a topic
    print("
1. Starting self-talk with 'programming' topic...")
    response = start_self_talk("programming")
    print(json.dumps(response, indent=2))

    # Wait a bit and check status
    print("
2. Checking status...")
    time.sleep(2)
    response = get_status()
    print(json.dumps(response, indent=2))

    # Example 2: Execute a single turn
    print("
3. Executing a single turn...")
    response = next_turn()
    print(json.dumps(response, indent=2))

    # Example 3: Get dialogue
    print("
4. Getting current dialogue...")
    response = get_dialogue()
    print(json.dumps(response, indent=2))

    # Example 4: Execute multiple turns
    print("
5. Executing 3 turns...")
    response = execute_turns(3)
    print(json.dumps(response, indent=2))

    # Example 5: Get updated dialogue
    print("
6. Getting updated dialogue...")
    response = get_dialogue()
    print(json.dumps(response, indent=2))

    # Example 6: Stop self-talk
    print("
7. Stopping self-talk...")
    response = stop_self_talk()
    print(json.dumps(response, indent=2))

if __name__ == "__main__":
    main()
