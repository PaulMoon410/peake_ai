import time
import csv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from beem import Hive
from beem.account import Account
from beem.transactionbuilder import TransactionBuilder
from beembase.operations import Custom_json
from beem.instance import set_shared_blockchain_instance

# ---- CONFIG ---- #

HIVE_NODES = ["https://api.hive.blog", "https://anyx.io"]
HIVE_ACCOUNT = "peakecoin.bnb"
ACTIVE_KEY = "5JgXLzFB8fsH64WPWD9fzC4sJQyxSXhn4ykqXrakCnJaSfDjNuL"  # <-- INSERT YOUR ACTIVE KEY HERE
PEK_TOKEN = "PEK"
SWAP_RATE = 0.001

ECENCY_POINTS_URL = "https://ecency.com/@peakecoin.bnb/points"
CHECK_INTERVAL = 60  # seconds between page checks

# ---- SETUP ---- #

# Setup Hive connection
hive = Hive(node=HIVE_NODES, keys=[ACTIVE_KEY])
set_shared_blockchain_instance(hive)
account = Account(HIVE_ACCOUNT, blockchain_instance=hive)

# Setup Headless Chromium on Raspberry Pi
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--window-size=1920x1080")

chromedriver_path = "/usr/bin/chromedriver"
driver = webdriver.Chrome(service=Service(chromedriver_path), options=chrome_options)

# Ensure swap log exists
LOG_FILE = "swap_log.csv"
try:
    with open(LOG_FILE, "x", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "username", "points", "pek_sent"])
except FileExistsError:
    pass  # File already exists

# Load processed usernames to avoid double swaps
processed = set()
with open(LOG_FILE, newline="") as f:
    reader = csv.reader(f)
    next(reader, None)  # skip header
    for row in reader:
        if len(row) > 1:
            processed.add(row[1])

# ---- FUNCTIONS ---- #

def send_pek(to_account, points_amount):
    pek_amount = points_amount * SWAP_RATE
    payload = {
        "contractName": "tokens",
        "contractAction": "transfer",
        "contractPayload": {
            "symbol": PEK_TOKEN,
            "to": to_account,
            "quantity": str(round(pek_amount, 8)),
            "memo": "Ecency Points Swap"
        }
    }

    tx = TransactionBuilder(blockchain_instance=hive, wallet=hive.wallet)
    op = Custom_json(
        required_auths=[HIVE_ACCOUNT],
        required_posting_auths=[],
        id="ssc-mainnet-hive",
        json=payload
    )
    tx.appendOps(op)
    tx.appendSigner(HIVE_ACCOUNT, "active")
    tx.sign()
    tx.broadcast()

    print(f"✅ Sent {pek_amount} {PEK_TOKEN} to {to_account}")
    return pek_amount

def monitor_swaps():
    print("🚀 Starting Ecency Points Swap Bot...")
    while True:
        try:
            driver.get(ECENCY_POINTS_URL)
            time.sleep(5)
            # DEBUG: Save full page HTML for troubleshooting
            with open("debug_page.html", "w") as debug_file:
                debug_file.write(driver.page_source)  # let the page load

            notifications = driver.find_elements(By.CSS_SELECTOR, ".p-transaction-list .cursor-pointer")

            for note in notifications:
                print("📝 Notification text:", note.text)
                text = note.text.lower()
                if "points" in text and "peakecoin transfer" in text:
                    try:
                        parts = text.split(" ")
                        from_index = parts.index("from")
                        username = parts[from_index + 1].lstrip("@").strip()
                        points = int([p for p in parts if p.isdigit()][0])

                        if username not in processed:
                            print(f"🔍 Swap found: {username} sent {points} Points")
                            pek_sent = send_pek(username, points)

                            with open(LOG_FILE, "a", newline="") as f:
                                writer = csv.writer(f)
                                writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), username, points, pek_sent])

                            processed.add(username)

                    except Exception as e:
                        print(f"⚠️ Error parsing notification: {e}")

        except Exception as e:
            print(f"❌ Error during page check: {e}")

        time.sleep(CHECK_INTERVAL)

# ---- RUN ---- #

if __name__ == "__main__":
    monitor_swaps()
