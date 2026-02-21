"""
peakecoin_payout.py
- Flask API for secure PeakeCoin payouts signed by the house account.
- Uses Beem to broadcast Hive Engine `custom_json` transfers.
"""

import os
import time
import json as jsonlib
from threading import Thread
from decimal import Decimal, ROUND_DOWN

from beem import Hive
from beem.account import Account
from beem.instance import set_shared_blockchain_instance
from beemgraphenebase.account import PrivateKey
import re
import urllib.request
import urllib.error
from flask import Flask, request, jsonify, Blueprint
from flask_cors import CORS

# Configuration
HOUSE_ACCOUNT = os.getenv('HOUSE_ACCOUNT', 'peakecoin.matic')
KEY_ENV_ACTIVE = os.getenv('PEK_ACTIVE_KEY')
KEY_ENV_POSTING = os.getenv('PEK_POSTING_KEY')
KEY_FILE_ACTIVE = os.getenv('PEK_ACTIVE_KEY_FILE')  # optional: path to file containing active WIF
KEY_FILE_POSTING = os.getenv('PEK_POSTING_KEY_FILE')  # optional: path to file containing posting WIF
QUEUE_FILE = 'payout_queue.json'


def _sanitize_key_string(s: str) -> str:
    # strip, remove common accidental characters
    return (s or '').strip().replace('\r', '').replace('"', '').replace("'", '')


def _read_key_file(path: str):
    try:
        if path and os.path.exists(path):
            with open(path, 'r') as f:
                text = f.read()
                text = _sanitize_key_string(text)
                # Try to extract a likely WIF token even if the file has comments
                candidate = _extract_wif_candidate(text)
                return candidate or text
    except Exception:
        pass
    return None


def validate_wif(wif: str) -> bool:
    try:
        PrivateKey(_sanitize_key_string(wif))
        return True
    except Exception:
        return False


def _extract_wif_candidate(text: str) -> str | None:
    """Extract the first plausible Base58 private key token starting with '5'.
    Accept tokens length >= 50 comprised of Base58 characters.
    """
    if not text:
        return None
    # Find all Base58 tokens
    for token in re.findall(r"[123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz]+", text):
        if token.startswith('5') and len(token) >= 50:
            return token
    # Also check line-by-line for a token that looks like WIF
    for line in text.splitlines():
        line = _sanitize_key_string(line)
        if line.startswith('5') and len(line) >= 50 and re.fullmatch(r"[123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz]+", line):
            return line
    return None


def get_wif_and_auth():
    """Resolve WIF and authority type ('active' or 'posting').
    Priority:
      1) `PEK_ACTIVE_KEY` env → active
      2) `PEK_POSTING_KEY` env → posting
      3) `pek_key_wif.txt` file (assumed active unless `PEK_KEY_AUTH=posting`)
    """
    if KEY_ENV_ACTIVE and KEY_ENV_ACTIVE.strip() and KEY_ENV_ACTIVE.strip().upper() != 'YOUR_ACTIVE_KEY':
        candidate = _sanitize_key_string(KEY_ENV_ACTIVE)
        if validate_wif(candidate):
            return candidate, 'active'
        # try file override if provided
        file_candidate = _read_key_file(KEY_FILE_ACTIVE)
        if file_candidate and validate_wif(file_candidate):
            return file_candidate, 'active'
        raise RuntimeError('PEK_ACTIVE_KEY provided but is not a valid WIF. Check for whitespace or copy errors.')
    if KEY_ENV_POSTING and KEY_ENV_POSTING.strip() and KEY_ENV_POSTING.strip().upper() != 'YOUR_POSTING_KEY':
        candidate = _sanitize_key_string(KEY_ENV_POSTING)
        if validate_wif(candidate):
            return candidate, 'posting'
        file_candidate = _read_key_file(KEY_FILE_POSTING)
        if file_candidate and validate_wif(file_candidate):
            return file_candidate, 'posting'
        raise RuntimeError('PEK_POSTING_KEY provided but is not a valid WIF. Check for whitespace or copy errors.')
    # File fallback
    file_path = os.path.join(os.path.dirname(__file__), 'pek_key_wif.txt')
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            raw = f.read()
            key = _extract_wif_candidate(raw) or _sanitize_key_string(raw)
            if key:
                auth = os.getenv('PEK_KEY_AUTH', 'active').lower()
                if auth not in ('active', 'posting'):
                    auth = 'active'
                if validate_wif(key):
                    return key, auth
                raise RuntimeError('pek_key_wif.txt found but WIF is invalid. Ensure the file contains only the private key.')
    raise RuntimeError('Key not found. Set PEK_ACTIVE_KEY (preferred), PEK_POSTING_KEY, or create pek_key_wif.txt containing the WIF.')


def init_beem():
    wif, auth = get_wif_and_auth()
    try:
        pub = str(PrivateKey(wif).pubkey)
        hive = Hive(
            node=['https://api.hive.blog', 'https://anyx.io', 'https://api.hivekings.com'],
            keys=[wif]
        )
        set_shared_blockchain_instance(hive)
        acct = Account(HOUSE_ACCOUNT, blockchain_instance=hive)
        return acct, auth, pub
    except Exception as e:
        raise RuntimeError(f'Failed to initialize Beem. Ensure WIF is valid. Error: {e}')


house, authority, pubkey = init_beem()

app = Flask(__name__)
CORS(app)

# Mirror endpoints under /peksino
bp = Blueprint('peksino', __name__)


def load_queue():
    if not os.path.exists(QUEUE_FILE):
        return []
    try:
        with open(QUEUE_FILE, 'r') as f:
            return jsonlib.load(f)
    except Exception:
        return []


def save_queue(queue):
    with open(QUEUE_FILE, 'w') as f:
        jsonlib.dump(queue, f, indent=2)


def process_payouts():
    queue = load_queue()
    new_queue = []
    for payout in queue:
        try:
            # Ensure amount is formatted to 8 decimal places (Hive Engine tokens commonly use 8)
            amt = payout.get('amount', 0)
            # Accept number or string; convert safely via Decimal
            try:
                d = Decimal(str(amt))
            except Exception:
                d = Decimal('0')
            d = d.quantize(Decimal('0.00000001'), rounding=ROUND_DOWN)
            quantity = format(d, 'f')
            payload = {
                'contractName': 'tokens',
                'contractAction': 'transfer',
                'contractPayload': {
                    'symbol': 'PEK',
                    'to': payout['to'],
                    'quantity': quantity,
                    'memo': payout.get('memo', '')
                }
            }
            # Sign with appropriate authority
            if authority == 'active':
                tx = house.custom_json(
                    id='ssc-mainnet-hive',
                    json_data=jsonlib.dumps(payload),
                    required_auths=[HOUSE_ACCOUNT],
                    required_posting_auths=[]
                )
            else:
                tx = house.custom_json(
                    id='ssc-mainnet-hive',
                    json_data=jsonlib.dumps(payload),
                    required_auths=[],
                    required_posting_auths=[HOUSE_ACCOUNT]
                )
            txid = tx.get('trx_id') or tx.get('id', '')
            print(f"Payout to {payout['to']} of {payout['amount']} PEK: {txid}")
        except Exception as e:
            print(f"Failed payout to {payout['to']}: {e}")
            new_queue.append(payout)
    save_queue(new_queue)


@app.route('/health', methods=['GET'])
def health():
    try:
        # Check if derived pubkey matches on-chain keys for the selected authority
        try:
            acct = Account(HOUSE_ACCOUNT, blockchain_instance=house.blockchain)
            keys = acct['active']['key_auths'] if authority == 'active' else acct['posting']['key_auths']
            match = any(pubkey == k for k, _ in keys)
            onchain_keys = [k for k, _ in keys]
        except Exception:
            match = None
            onchain_keys = []
        return jsonify({'status': 'ok', 'account': HOUSE_ACCOUNT, 'authority': authority, 'pubkey': pubkey, 'onchain_keys': onchain_keys, 'match': match})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@bp.route('/health', methods=['GET'])
def health_bp():
    try:
        try:
            acct = Account(HOUSE_ACCOUNT, blockchain_instance=house.blockchain)
            keys = acct['active']['key_auths'] if authority == 'active' else acct['posting']['key_auths']
            match = any(pubkey == k for k, _ in keys)
            onchain_keys = [k for k, _ in keys]
        except Exception:
            match = None
            onchain_keys = []
        return jsonify({'status': 'ok', 'account': HOUSE_ACCOUNT, 'authority': authority, 'pubkey': pubkey, 'onchain_keys': onchain_keys, 'match': match})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/enqueue_payout', methods=['POST'])
def enqueue_payout():
    data = request.json
    if not data or 'to' not in data or 'amount' not in data:
        return jsonify({'error': 'Missing required fields'}), 400
    queue = load_queue()
    queue.append({'to': data['to'], 'amount': data['amount'], 'memo': data.get('memo', '')})
    save_queue(queue)
    return jsonify({'status': 'queued'})


@bp.route('/enqueue_payout', methods=['POST'])
def enqueue_payout_bp():
    data = request.json
    if not data or 'to' not in data or 'amount' not in data:
        return jsonify({'error': 'Missing required fields'}), 400
    queue = load_queue()
    queue.append({'to': data['to'], 'amount': data['amount'], 'memo': data.get('memo', '')})
    save_queue(queue)
    return jsonify({'status': 'queued'})


@app.route('/log_bet', methods=['POST'])
def log_bet():
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    print(f"Bet logged: {data.get('from','')} -> {data.get('to','')} | {data.get('amount','')} PEK | {data.get('memo','')} | TXID: {data.get('txid','')}")
    return jsonify({'status': 'logged'})


@bp.route('/log_bet', methods=['POST'])
def log_bet_bp():
    return log_bet()


@app.route('/balance/<username>', methods=['GET'])
def get_balance(username):
    try:
        return jsonify({'username': username, 'balance': '100.00000000', 'symbol': 'PEK'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/balance/<username>', methods=['GET'])
def get_balance_bp(username):
    return get_balance(username)


@bp.route('/test_enqueue', methods=['POST'])
def test_enqueue_bp():
    data = request.json or {}
    to = data.get('to')
    amount = float(data.get('amount', 0.001))
    memo = data.get('memo', 'Test payout')
    if not to:
        return jsonify({'error': 'Missing field: to'}), 400
    q = load_queue()
    q.append({'to': to, 'amount': amount, 'memo': memo})
    save_queue(q)
    return jsonify({'status': 'queued', 'to': to, 'amount': amount})


# Queue viewer and clear endpoints for debugging
@bp.route('/queue', methods=['GET'])
def view_queue_bp():
    q = load_queue()
    return jsonify({'size': len(q), 'queue': q})


@bp.route('/clear_queue', methods=['POST'])
def clear_queue_bp():
    save_queue([])
    return jsonify({'status': 'cleared'})


app.register_blueprint(bp, url_prefix='/peksino')


if __name__ == '__main__':
    def payout_loop():
        while True:
            process_payouts()
            time.sleep(30)
    Thread(target=payout_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=5000)

