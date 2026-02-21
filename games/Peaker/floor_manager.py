#!/usr/bin/env python3
"""
PeakeCoin Casino Floor Manager
"""

import time
import json
import logging
import requests
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Dict, List, Optional
from beem import Hive
from beem.account import Account
from beem.blockchain import Blockchain
from beem.exceptions import AccountDoesNotExistsException

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('floor_manager.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class GameBet:
    """Represents a game bet transaction"""
    txid: str
    player: str
    amount: float
    game: str
    memo: str
    timestamp: datetime
    processed: bool = False
    result: Optional[str] = None
    payout_amount: Optional[float] = None
    payout_txid: Optional[str] = None

class FloorManager:
    """Main casino floor manager that watches and processes all game activity"""
    
    def __init__(self, config_file='floor_manager_config.json'):
        self.config = self.load_config(config_file)
        
        # Initialize Beem Hive connection
        self.hive = Hive(
            node=['https://api.hive.blog', 'https://api.hivekings.com', 'https://anyx.io'],
            keys=[self.config['active_key']]
        )
        self.account = Account(self.config['casino_account'], blockchain_instance=self.hive)
        self.blockchain = Blockchain(blockchain_instance=self.hive)
        
        self.active_bets: Dict[str, GameBet] = {}
        self.processed_transactions: set = set()
        self.game_odds = self.config.get('game_odds', {})
        self.last_checked_block = self.config.get('last_block', 0)
        
    def load_config(self, config_file: str) -> dict:
        """Load configuration from JSON file"""
        try:
            with open(config_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"Config file {config_file} not found. Creating default config.")
            default_config = {
                "casino_account": "peakecoin.casino",
                "posting_key": "YOUR_POSTING_KEY",
                "active_key": "YOUR_ACTIVE_KEY",
                "watch_interval": 30,
                "last_block": 0,
                "game_odds": {
                    "blackjack": 1.95,
                    "andarbahar": 1.95,
                    "baccarat": 1.95,
                    "poker": 1.95,
                    "teenpatti": 1.95,
                    "liarspoker": 2.0,
                    "default": 1.95
                },
                "min_bet": 1.0,
                "max_bet": 10000.0,
                "house_edge": 0.05
            }
            with open(config_file, 'w') as f:
                json.dump(default_config, f, indent=2)
            return default_config
    
    def save_config(self):
        """Save current configuration"""
        self.config['last_block'] = self.last_checked_block
        with open('floor_manager_config.json', 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def watch_transactions(self):
        """Watch blockchain for incoming bet transactions"""
        try:
            # Get latest transactions to casino account using beem
            history = self.account.history(
                start=self.last_checked_block,
                stop=-1,
                only_ops=['custom_json']
            )
            
            transactions = []
            for tx in history:
                transactions.append(tx)
                if self.is_bet_transaction(tx):
                    self.process_incoming_bet(tx)
                    
            # Update last checked block
            if transactions:
                self.last_checked_block = max(tx.get('block_num', 0) for tx in transactions)
                
        except Exception as e:
            logger.error(f"Error watching transactions: {e}")
    
    def is_bet_transaction(self, tx: dict) -> bool:
        """Check if transaction is a valid bet"""
        try:
            # Beem transaction structure
            if tx.get('type') != 'custom_json':
                return False
                
            if tx.get('id') != 'ssc-mainnet-hive':
                return False
                
            json_data = json.loads(tx.get('json', '{}'))
            if json_data.get('contractName') != 'tokens':
                return False
            if json_data.get('contractAction') != 'transfer':
                return False
                
            payload = json_data.get('contractPayload', {})
            if payload.get('symbol') != 'PEK':
                return False
            if payload.get('to') != self.config['casino_account']:
                return False
                
            # Check if memo indicates a game bet
            memo = payload.get('memo', '').lower()
            game_keywords = ['bet', 'blackjack', 'poker', 'baccarat', 'andarbahar', 'teenpatti', 'liarspoker']
            return any(keyword in memo for keyword in game_keywords)
            
        except Exception as e:
            logger.error(f"Error checking bet transaction: {e}")
            return False
    
    def process_incoming_bet(self, tx: dict):
        """Process a new incoming bet"""
        try:
            txid = tx.get('trx_id', '')
            if txid in self.processed_transactions:
                return
                
            # Beem transaction structure
            json_data = json.loads(tx.get('json', '{}'))
            payload = json_data.get('contractPayload', {})
            
            player = tx.get('required_posting_auths', [None])[0] or tx.get('required_auths', [None])[0]
            amount = float(payload.get('quantity', '0'))
            memo = payload.get('memo', '')
            
            # Extract game type from memo
            game = self.extract_game_type(memo)
            
            # Validate bet
            if not self.validate_bet(player, amount, game):
                logger.warning(f"Invalid bet from {player}: {amount} PEK for {game}")
                return
                
            # Create bet record
            bet = GameBet(
                txid=txid,
                player=player,
                amount=amount,
                game=game,
                memo=memo,
                timestamp=datetime.now()
            )
            
            self.active_bets[txid] = bet
            self.processed_transactions.add(txid)
            
            logger.info(f"New bet: {player} wagered {amount} PEK on {game} (TXID: {txid})")
            
            # For simple games, process immediately
            if game in ['andarbahar', 'liarspoker']:
                self.process_simple_game_result(bet)
                
        except Exception as e:
            logger.error(f"Error processing incoming bet: {e}")
    
    def extract_game_type(self, memo: str) -> str:
        """Extract game type from transaction memo"""
        memo_lower = memo.lower()
        game_map = {
            'blackjack': 'blackjack',
            'poker': 'poker', 
            'baccarat': 'baccarat',
            'andarbahar': 'andarbahar',
            'andar bahar': 'andarbahar',
            'teenpatti': 'teenpatti',
            'teen patti': 'teenpatti',
            'liarspoker': 'liarspoker',
            "liar's poker": 'liarspoker',
            'reddog': 'reddog',
            'casinowar': 'casinowar',
            'caribbean': 'caribbean',
            'threecard': 'threecard',
            'pontoon': 'pontoon',
            'faro': 'faro',
            'chemin': 'chemin',
            'roulette': 'roulette',
            'dice': 'dice'
        }
        
        for keyword, game in game_map.items():
            if keyword in memo_lower:
                return game
        return 'unknown'
    
    def validate_bet(self, player: str, amount: float, game: str) -> bool:
        """Validate bet parameters"""
        if amount < self.config['min_bet']:
            return False
        if amount > self.config['max_bet']:
            return False
        if game == 'unknown':
            return False
        return True
    
    def process_simple_game_result(self, bet: GameBet):
        """Process games that can be resolved immediately (like Andar Bahar)"""
        try:
            import random
            
            if bet.game == 'andarbahar':
                # 50/50 game - house edge built into odds
                player_wins = random.random() > self.config['house_edge']
                if player_wins:
                    odds = self.game_odds.get('andarbahar', 1.95)
                    payout = bet.amount * odds
                    self.process_payout(bet, payout, f"Andar Bahar win")
                else:
                    self.process_loss(bet, "Andar Bahar loss")
                    
            elif bet.game == 'liarspoker':
                # Simple random outcome for demo
                player_wins = random.random() > 0.6  # Slightly harder game
                if player_wins:
                    odds = self.game_odds.get('liarspoker', 2.0)
                    payout = bet.amount * odds
                    self.process_payout(bet, payout, f"Liar's Poker win")
                else:
                    self.process_loss(bet, "Liar's Poker loss")
                    
        except Exception as e:
            logger.error(f"Error processing simple game result: {e}")
    
    def process_payout(self, bet: GameBet, payout_amount: float, result: str):
        """Process a winning payout"""
        try:
            # Send payout via beem custom_json
            casino_account = Account(self.config['casino_account'], blockchain_instance=self.hive)
            
            payout_result = casino_account.custom_json(
                id='ssc-mainnet-hive',
                json_data=json.dumps({
                    'contractName': 'tokens',
                    'contractAction': 'transfer',
                    'contractPayload': {
                        'symbol': 'PEK',
                        'to': bet.player,
                        'quantity': f"{payout_amount:.8f}",
                        'memo': f"Casino payout: {result} - Bet TXID: {bet.txid}"
                    }
                }),
                required_auths=[],
                required_posting_auths=[self.config['casino_account']]
            )
            
            if payout_result:
                bet.processed = True
                bet.result = "WIN"
                bet.payout_amount = payout_amount
                bet.payout_txid = payout_result.get('id', '')
                
                logger.info(f"PAYOUT: {bet.player} won {payout_amount:.8f} PEK for {bet.game}")
                
                # Log to file for audit
                self.log_game_result(bet)
            else:
                logger.error(f"Failed to send payout to {bet.player}")
                
        except Exception as e:
            logger.error(f"Error processing payout: {e}")
    
    def process_loss(self, bet: GameBet, result: str):
        """Process a losing bet (house keeps the money)"""
        bet.processed = True
        bet.result = "LOSS"
        bet.payout_amount = 0
        
        logger.info(f"LOSS: {bet.player} lost {bet.amount} PEK on {bet.game}")
        
        # Log to file for audit
        self.log_game_result(bet)
    
    def log_game_result(self, bet: GameBet):
        """Log game result for audit purposes"""
        try:
            log_entry = {
                "timestamp": bet.timestamp.isoformat(),
                "txid": bet.txid,
                "player": bet.player,
                "game": bet.game,
                "bet_amount": bet.amount,
                "result": bet.result,
                "payout_amount": bet.payout_amount or 0,
                "payout_txid": bet.payout_txid or "",
                "memo": bet.memo
            }
            
            # Append to audit log
            with open('casino_audit.jsonl', 'a') as f:
                f.write(json.dumps(log_entry) + '\n')
                
        except Exception as e:
            logger.error(f"Error logging game result: {e}")
    
    def cleanup_old_bets(self):
        """Clean up old processed bets to prevent memory issues"""
        cutoff = datetime.now() - timedelta(hours=24)
        to_remove = []
        
        for txid, bet in self.active_bets.items():
            if bet.processed and bet.timestamp < cutoff:
                to_remove.append(txid)
        
        for txid in to_remove:
            del self.active_bets[txid]
            
        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} old processed bets")
    
    def get_stats(self) -> dict:
        """Get current casino statistics"""
        total_bets = len(self.active_bets)
        processed_bets = sum(1 for bet in self.active_bets.values() if bet.processed)
        total_wagered = sum(bet.amount for bet in self.active_bets.values())
        total_paid_out = sum(bet.payout_amount or 0 for bet in self.active_bets.values())
        
        return {
            "total_bets": total_bets,
            "processed_bets": processed_bets,
            "pending_bets": total_bets - processed_bets,
            "total_wagered": total_wagered,
            "total_paid_out": total_paid_out,
            "house_profit": total_wagered - total_paid_out,
            "active_games": list(set(bet.game for bet in self.active_bets.values()))
        }
    
    def run(self):
        """Main loop - watch and process transactions"""
        logger.info("Starting PeakeCoin Casino Floor Manager...")
        
        while True:
            try:
                self.watch_transactions()
                self.cleanup_old_bets()
                self.save_config()
                
                # Print stats every 10 minutes
                if int(time.time()) % 600 == 0:
                    stats = self.get_stats()
                    logger.info(f"Casino Stats: {stats}")
                
                time.sleep(self.config['watch_interval'])
                
            except KeyboardInterrupt:
                logger.info("Shutting down Floor Manager...")
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}")
                time.sleep(60)  # Wait a minute before retrying

if __name__ == "__main__":
    # Create and run the floor manager
    manager = FloorManager()
    manager.run()
