import subprocess
import json
import os
import time
from datetime import datetime
from beem import Hive
from beem.account import Account
from beem.nodelist import NodeList
from ftplib import FTP
import re

MODEL_PATH = "/home/piminer2/llama.cpp/models/tinyllama-1.1b-chat.q4_K_M.gguf"
LLAMA_BIN = "/home/piminer2/llama.cpp/build/bin/llama-cli"
HISTORY_FILE = "peakebot_memory.json"
KEY_FILE = "hive_keys.json"
FTP_HOST = "ftp.geocities.ws"
FTP_USER = "peakecoin"
FTP_PASS = "Peake410"
FTP_BASE_DIR = "/peakebot"

# Initialize Hive with posting key
def init_hive():
    if not os.path.exists(KEY_FILE):
        raise Exception("Missing hive_keys.json with posting key.")
    with open(KEY_FILE) as f:
        keys = json.load(f)
    return Hive(keys=[keys["posting_key"]])

# Create a safe category directory path
def categorize_prompt(prompt):
    keywords = re.findall(r"\b\w+\b", prompt.lower())
    important = keywords[:3] if keywords else ["general"]
    return "_".join(important)

# Fetch all previous entries from GeoCities FTP
def fetch_all_ftp_memory():
    try:
        ftp = FTP(FTP_HOST)
        ftp.login(FTP_USER, FTP_PASS)
        ftp.set_pasv(True)
        ftp.cwd(FTP_BASE_DIR)
        entries = []
        for category in ftp.nlst():
            try:
                ftp.cwd(f"{FTP_BASE_DIR}/{category}")
                files = ftp.nlst()
                for fname in sorted(files):
                    if fname.endswith(".json"):
                        local_path = f"/tmp/{fname}"
                        with open(local_path, "wb") as f:
                            ftp.retrbinary(f"RETR {fname}", f.write)
                        with open(local_path, "r") as f:
                            entries.append(json.load(f))
            except:
                continue
        ftp.quit()
        return entries
    except Exception as e:
        print("❌ Could not fetch memory from GeoCities:", str(e))
        return []

# Ensure memory file exists
if not os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, "w") as f:
        json.dump([], f)

def load_memory(n=5):
    ftp_memory = fetch_all_ftp_memory()
    return ftp_memory[-n:]

def search_memory(query):
    matches = []
    for entry in fetch_all_ftp_memory():
        if query.lower() in entry["prompt"].lower() or query.lower() in entry["response"].lower():
            matches.append(entry)
    return matches

def remember(prompt, response):
    entry = {
        "timestamp": datetime.now().isoformat(),
        "prompt": prompt,
        "response": response
    }
    with open(HISTORY_FILE, "r") as f:
        memory = json.load(f)
    memory.append(entry)
    with open(HISTORY_FILE, "w") as f:
        json.dump(memory[-50:], f, indent=2)
    save_to_geocities(entry)
    generate_webpage(memory[-50:])

def generate_response(prompt):
    memory_snippets = fetch_all_ftp_memory()
    relevant = [m for m in memory_snippets if any(w in prompt.lower() for w in m["prompt"].lower().split() + m["response"].lower().split())]
    context = "\n".join([f"[You said]: {m['prompt']}\n[Bot said]: {m['response']}" for m in relevant[-5:]])
    full_prompt = context + f"\nUser: {prompt}\nAI:"

    result = subprocess.run([
        LLAMA_BIN,
        "-m", MODEL_PATH,
        "-p", full_prompt,
        "-n", "200"
    ], capture_output=True, text=True)

    output = result.stdout
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    response = lines[-1] if lines else "⚠️ No response generated."
    remember(prompt, response)
    return response

def post_to_hive(title, body):
    hive = init_hive()
    account = Account("peake.matic", blockchain_instance=hive)
    tags = ["peakecoin", "ai", "bot"]
    permlink = "peakebot-" + datetime.now().strftime("%Y%m%d%H%M%S")
    try:
        account.post(title, body, author="peake.matic", permlink=permlink, tags=tags)
        print(f"✅ Posted to Hive as {permlink}")
    except Exception as e:
        print("❌ Failed to post to Hive:", str(e))

def save_to_geocities(entry):
    category = categorize_prompt(entry["prompt"])
    filename = f"entry-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    local_path = f"/tmp/{filename}"
    with open(local_path, "w") as f:
        json.dump(entry, f, indent=2)

    try:
        ftp = FTP(FTP_HOST)
        ftp.login(FTP_USER, FTP_PASS)
        ftp.set_pasv(True)
        try:
            ftp.cwd(f"{FTP_BASE_DIR}/{category}")
        except:
            ftp.cwd(FTP_BASE_DIR)
            ftp.mkd(category)
            ftp.cwd(f"{FTP_BASE_DIR}/{category}")
        with open(local_path, "rb") as file:
            ftp.storbinary(f"STOR {filename}", file)
        ftp.quit()
        print(f"📁 Uploaded memory to GeoCities under /{category}: {filename}")
    except Exception as e:
        print("❌ FTP Upload failed:", str(e))

def generate_webpage(entries):
    html_content = """
    <html>
    <head><title>PeakeBot Journal</title></head>
    <body>
    <h1>🧠 PeakeBot Public Journal</h1>
    <p>AI entries generated by PeakeBot running on Raspberry Pi and published to GeoCities</p>
    <hr>
    """
    for entry in reversed(entries):
        html_content += f"<div><h3>{entry['timestamp']}</h3><p><b>You:</b> {entry['prompt']}<br><b>PeakeBot:</b> {entry['response']}</p><hr></div>"
    html_content += "</body></html>"

    local_path = "/tmp/index.html"
    with open(local_path, "w") as f:
        f.write(html_content)

    try:
        ftp = FTP(FTP_HOST)
        ftp.login(FTP_USER, FTP_PASS)
        ftp.set_pasv(True)
        ftp.cwd(FTP_BASE_DIR)
        with open(local_path, "rb") as file:
            ftp.storbinary("STOR index.html", file)
        ftp.quit()
        print("🌍 Updated PeakeBot journal webpage on GeoCities.")
    except Exception as e:
        print("❌ FTP Upload (HTML) failed:", str(e))

def interactive_loop():
    print("🧠 PeakeBot ready. Type your message below:")
    while True:
        prompt = input("You: ")
        if prompt.lower() in ["exit", "quit"]:
            break
        response = generate_response(prompt)
        print("PeakeBot:", response)

        if "post this" in prompt.lower():
            post_to_hive("🧠 PeakeBot Insight", response)

if __name__ == "__main__":
    interactive_loop()
