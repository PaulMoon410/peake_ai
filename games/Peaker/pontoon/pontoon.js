// Pontoon (British Blackjack) implementation
// Assumes login/balance logic is already handled in the page

const suits = ['♠', '♥', '♦', '♣'];
const ranks = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K'];

function createDeck() {
    let deck = [];
    for (let s of suits) {
        for (let r of ranks) {
            deck.push({ rank: r, suit: s });
        }
    }
    return deck;
}

function shuffle(deck) {
    for (let i = deck.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [deck[i], deck[j]] = [deck[j], deck[i]];
    }
    return deck;
}

function cardValue(card) {
    if (card.rank === 'A') return 11;
    if (['J', 'Q', 'K'].includes(card.rank)) return 10;
    return parseInt(card.rank);
}

function handValue(hand) {
    let total = 0, aces = 0;
    for (let c of hand) {
        total += cardValue(c);
        if (c.rank === 'A') aces++;
    }
    while (total > 21 && aces > 0) {
        total -= 10;
        aces--;
    }
    return total;
}

function handToString(hand) {
    return hand.map(c => c.rank + c.suit).join(' ');
}

// UI elements
const dealBtn = document.getElementById('pontoon-deal');
const twistBtn = document.getElementById('pontoon-twist');
const stickBtn = document.getElementById('pontoon-stick');
const buyBtn = document.getElementById('pontoon-buy');
const resultDiv = document.getElementById('pontoon-result');
const playerDiv = document.getElementById('pontoon-player-cards');
const dealerDiv = document.getElementById('pontoon-dealer-cards');
const betInput = document.getElementById('pontoon-bet');
const placeBetBtn = document.getElementById('place-bet-btn');
const betAmountInput = document.getElementById('bet-amount');
const betStatus = document.getElementById('bet-status');

let gameState = null;
let betPlaced = false;
let lastBetAmount = 0;
const casinoAccount = 'peakecoin.casino';

function resetGame() {
    gameState = {
        deck: shuffle(createDeck()),
        player: [],
        dealer: [],
        bet: 0,
        active: false,
        bought: false
    };
    playerDiv.textContent = '';
    dealerDiv.textContent = '';
    resultDiv.textContent = '';
    twistBtn.disabled = true;
    stickBtn.disabled = true;
    buyBtn.disabled = true;
    dealBtn.disabled = false;
    betInput.disabled = false;
}

function startDeal() {
    let bet = parseFloat(betInput.value);
    if (isNaN(bet) || bet < 1) {
        resultDiv.textContent = 'Enter a valid bet (min 1 PEK).';
        return;
    }
    gameState.bet = bet;
    gameState.deck = shuffle(createDeck());
    gameState.player = [gameState.deck.pop(), gameState.deck.pop()];
    gameState.dealer = [gameState.deck.pop(), gameState.deck.pop()];
    gameState.active = true;
    gameState.bought = false;
    playerDiv.textContent = handToString(gameState.player) + ' (' + handValue(gameState.player) + ')';
    dealerDiv.textContent = '[??] [??]';
    resultDiv.textContent = 'Twist (hit), Stick (stand), or Buy (double)?';
    twistBtn.disabled = false;
    stickBtn.disabled = false;
    buyBtn.disabled = false;
    dealBtn.disabled = true;
    betInput.disabled = true;
}

function playerTwist() {
    if (!gameState.active) return;
    gameState.player.push(gameState.deck.pop());
    playerDiv.textContent = handToString(gameState.player) + ' (' + handValue(gameState.player) + ')';
    if (handValue(gameState.player) > 21) {
        endGame('Bust! Dealer wins.');
    } else if (gameState.player.length === 5 && handValue(gameState.player) <= 21) {
        endGame('Five Card Trick! You win!');
    }
}

function playerStick() {
    if (!gameState.active) return;
    // Dealer reveals and plays
    dealerDiv.textContent = handToString(gameState.dealer) + ' (' + handValue(gameState.dealer) + ')';
    while (handValue(gameState.dealer) < 17) {
        gameState.dealer.push(gameState.deck.pop());
        dealerDiv.textContent = handToString(gameState.dealer) + ' (' + handValue(gameState.dealer) + ')';
    }
    let playerVal = handValue(gameState.player);
    let dealerVal = handValue(gameState.dealer);
    if (dealerVal > 21 || playerVal > dealerVal) {
        endGame('You win!');
    } else if (playerVal < dealerVal) {
        endGame('Dealer wins.');
    } else {
        endGame('Push.');
    }
}

function playerBuy() {
    if (!gameState.active || gameState.bought) return;
    gameState.bet *= 2;
    gameState.bought = true;
    playerTwist();
    if (gameState.active) playerStick();
}

function endGame(msg) {
    resultDiv.textContent = msg;
    twistBtn.disabled = true;
    stickBtn.disabled = true;
    buyBtn.disabled = true;
    dealBtn.disabled = false;
    betInput.disabled = false;
    gameState.active = false;
}

placeBetBtn.onclick = function() {
    const user = window.casinoUser || localStorage.getItem('peakecoin_user');
    const amount = parseFloat(betAmountInput.value);
    if (!user) {
        betStatus.textContent = 'Login required.';
        return;
    }
    if (!amount || amount < 1) {
        betStatus.textContent = 'Enter a valid bet amount.';
        return;
    }
    betStatus.textContent = 'Placing bet...';
    placeBet(user, casinoAccount, amount.toFixed(8), 'Pontoon bet', function(response) {
        if (response.success) {
            betPlaced = true;
            lastBetAmount = amount;
            betStatus.textContent = 'Bet placed! You may now play.';
            placeBetBtn.disabled = true;
            betAmountInput.disabled = true;
            // Enable gameplay here
        } else {
            betStatus.textContent = 'Bet failed or rejected.';
        }
    });
};

dealBtn.onclick = startDeal;
twistBtn.onclick = playerTwist;
stickBtn.onclick = playerStick;
buyBtn.onclick = playerBuy;

resetGame();
