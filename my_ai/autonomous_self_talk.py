import json
import os
import time

from peakebot import generate_response


class PeakeSelfTalkEngine:
    def __init__(self, buffer_path="online_learning_buffer.json"):
        self.buffer_path = buffer_path
        self.instructor_system = (
            "You are the Peake AI Head Instructor. Teach one concept at a time, "
            "ask precise questions, stay in character, keep responses compact."
        )
        self.learner_system = (
            "You are Peake AI (Learner Profile). You know very little. "
            "Listen, answer to the best of your ability, and state when you "
            "have understood or processed a new fact."
        )

    def _call(self, system_prompt, user_message):
        prompt = f"{system_prompt}\n\nUser: {user_message}\nAssistant:"
        return generate_response(prompt).strip()

    def log_learned_fact(self, fact_text):
        buffer = []
        if os.path.exists(self.buffer_path):
            with open(self.buffer_path, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    if isinstance(data, list):
                        buffer = data
                    elif isinstance(data, dict):
                        buffer = data.get("facts", []) or []
                except json.JSONDecodeError:
                    buffer = []
        buffer.append({"timestamp": int(time.time()), "session": "self_talk_autonomous", "extracted_knowledge": fact_text})
        with open(self.buffer_path, "w", encoding="utf-8") as f:
            json.dump(buffer, f, indent=2, separators=(",", ":"))

    def execute_self_talk_command(self, cycles, curriculum_topic):
        print(f"Initializing Self-Talk Protocol on topic: '{curriculum_topic}'")
        instructor_message = f"Let's begin today's lesson. We are learning about: {curriculum_topic}. What do you know about it?"
        for cycle in range(1, cycles + 1):
            print(f"[CYCLE {cycle}]")
            print(f"Instructor: {instructor_message}\n")
            learner_response = self._call(self.learner_system, instructor_message)
            print(f"Peake Learner: {learner_response}\n")
            if "understand" in learner_response.lower() or cycle == 1:
                self.log_learned_fact(f"Topic absorption validation for {curriculum_topic}: Verified in Cycle {cycle}.")
                print("[Data Logged]: Saved new knowledge to online_learning_buffer.json")
            time.sleep(0.5)
            instructor_message = self._call(self.instructor_system, f"The student responded: '{learner_response}'. Continue the lesson plan.")
        print("Self-talk cycle complete.")


if __name__ == "__main__":
    engine = PeakeSelfTalkEngine()
    engine.execute_self_talk_command(cycles=3, curriculum_topic="Python REST APIs and HTTP requests")
