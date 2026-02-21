// Spanish 21 implementation (basic)
// Assumes login/balance logic is already handled in the page

const suits = ['♠', '♥', '♦', '♣'];
const ranks = ['A', '2', '3', '4', '5', '6', '7', '8', '9', 'J', 'Q', 'K']; // No 10s in Spanish 21

function createSpanishDeck() {
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
const dealBtn = document.getElementById('spanish21-deal');
const hitBtn = document.getElementById('spanish21-hit');
const standBtn = document.getElementById('spanish21-stand');
const doubleBtn = document.getElementById('spanish21-double');
const resultDiv = document.getElementById('spanish21-result');
const playerDiv = document.getElementById('spanish21-player-cards');
const dealerDiv = document.getElementById('spanish21-dealer-cards');
const betInput = document.getElementById('spanish21-bet');

let gameState = null;

function resetGame() {
    gameState = {
        deck: shuffle(createSpanishDeck()),
        player: [],
        dealer: [],
        bet: 0,
        active: false,
        doubled: false
    };
    playerDiv.textContent = '';
    dealerDiv.textContent = '';
    resultDiv.textContent = '';
    hitBtn.disabled = true;
    standBtn.disabled = true;
    doubleBtn.disabled = true;
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
    gameState.deck = shuffle(createSpanishDeck());
    gameState.player = [gameState.deck.pop(), gameState.deck.pop()];
    gameState.dealer = [gameState.deck.pop(), gameState.deck.pop()];
    gameState.active = true;
    gameState.doubled = false;
    playerDiv.textContent = handToString(gameState.player) + ' (' + handValue(gameState.player) + ')';
    dealerDiv.textContent = cardToString(gameState.dealer[0]) + ' [??]';
    resultDiv.textContent = 'Hit, Stand, or Double?';
    hitBtn.disabled = false;
    standBtn.disabled = false;
    doubleBtn.disabled = false;
    dealBtn.disabled = true;
    betInput.disabled = true;
}

function cardToString(card) {
    return card.rank + card.suit;
}

function playerHit() {
    if (!gameState.active) return;
    gameState.player.push(gameState.deck.pop());
    playerDiv.textContent = handToString(gameState.player) + ' (' + handValue(gameState.player) + ')';
    if (handValue(gameState.player) > 21) {
        endGame('Bust! Dealer wins.');
    }
}

function playerStand() {
    if (!gameState.active) return;
    dealerDiv.textContent = handToString(gameState.dealer) + ' (' + handValue(gameState.dealer) + ')';
    // Dealer hits soft 17
    while (handValue(gameState.dealer) < 17 || (handValue(gameState.dealer) === 17 && gameState.dealer.some(c=>c.rank==='A'))) {
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

function playerDouble() {
    if (!gameState.active) return;
    if (gameState.doubled) return;
    gameState.bet *= 2;
    gameState.doubled = true;
    playerHit();
    if (gameState.active) playerStand();
}

function endGame(msg) {
    resultDiv.textContent = msg;
    hitBtn.disabled = true;
    standBtn.disabled = true;
    doubleBtn.disabled = true;
    dealBtn.disabled = false;
    betInput.disabled = false;
    gameState.active = false;
}

dealBtn.onclick = startDeal;
hitBtn.onclick = playerHit;
standBtn.onclick = playerStand;
doubleBtn.onclick = playerDouble;

resetGame();
