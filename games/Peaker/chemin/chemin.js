// Chemin de Fer (Baccarat variant) implementation (single player)
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
    if (card.rank === 'A') return 1;
    if (['10', 'J', 'Q', 'K'].includes(card.rank)) return 0;
    return parseInt(card.rank);
}

function handValue(hand) {
    let total = hand.reduce((sum, c) => sum + cardValue(c), 0);
    return total % 10;
}

function handToString(hand) {
    return hand.map(c => c.rank + c.suit).join(' ');
}

// UI elements
const dealBtn = document.getElementById('chemin-deal');
const betInput = document.getElementById('chemin-bet');
const resultDiv = document.getElementById('chemin-result');
const playerDiv = document.getElementById('chemin-player-cards');
const bankerDiv = document.getElementById('chemin-banker-cards');
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
        bet: 0,
        active: false
    };
    playerDiv.textContent = '';
    bankerDiv.textContent = '';
    resultDiv.textContent = '';
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
    gameState.active = true;
    // Deal two cards each
    let player = [gameState.deck.pop(), gameState.deck.pop()];
    let banker = [gameState.deck.pop(), gameState.deck.pop()];
    playerDiv.textContent = handToString(player) + ' (' + handValue(player) + ')';
    bankerDiv.textContent = handToString(banker) + ' (' + handValue(banker) + ')';
    // Draw third card if needed (simplified: always draw on 5 or less)
    if (handValue(player) <= 5) {
        player.push(gameState.deck.pop());
        playerDiv.textContent = handToString(player) + ' (' + handValue(player) + ')';
    }
    if (handValue(banker) <= 5) {
        banker.push(gameState.deck.pop());
        bankerDiv.textContent = handToString(banker) + ' (' + handValue(banker) + ')';
    }
    // Compare
    let pVal = handValue(player);
    let bVal = handValue(banker);
    if (pVal > bVal) {
        resultDiv.textContent = 'Player wins!';
    } else if (bVal > pVal) {
        resultDiv.textContent = 'Banker wins!';
    } else {
        resultDiv.textContent = 'Tie.';
    }
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
    placeBet(user, casinoAccount, amount.toFixed(8), 'Chemin de Fer bet', function(response) {
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

resetGame();
