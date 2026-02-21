// Faro implementation (simplified, single player)
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

// UI elements
const dealBtn = document.getElementById('faro-deal');
const betInput = document.getElementById('faro-bet');
const rankInput = document.getElementById('faro-rank');
const resultDiv = document.getElementById('faro-result');
const cardsDiv = document.getElementById('faro-cards');
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
        rank: '',
        active: false
    };
    resultDiv.textContent = '';
    cardsDiv.textContent = '';
    dealBtn.disabled = false;
    betInput.disabled = false;
    rankInput.disabled = false;
}

function startDeal() {
    let bet = parseFloat(betInput.value);
    let rank = rankInput.value;
    if (isNaN(bet) || bet < 1) {
        resultDiv.textContent = 'Enter a valid bet (min 1 PEK).';
        return;
    }
    if (!ranks.includes(rank)) {
        resultDiv.textContent = 'Enter a valid rank (A,2-10,J,Q,K).';
        return;
    }
    gameState.bet = bet;
    gameState.rank = rank;
    gameState.deck = shuffle(createDeck());
    gameState.active = true;
    // Draw two cards: one for dealer (losing), one for player (winning)
    let dealerCard = gameState.deck.pop();
    let playerCard = gameState.deck.pop();
    cardsDiv.textContent = 'Dealer: ' + dealerCard.rank + dealerCard.suit + ' | Player: ' + playerCard.rank + playerCard.suit;
    if (playerCard.rank === rank && dealerCard.rank !== rank) {
        resultDiv.textContent = 'You win!';
    } else if (dealerCard.rank === rank && playerCard.rank !== rank) {
        resultDiv.textContent = 'You lose.';
    } else if (dealerCard.rank === rank && playerCard.rank === rank) {
        resultDiv.textContent = 'Standoff (push).';
    } else {
        resultDiv.textContent = 'No win/loss (neither card matches).';
    }
    dealBtn.disabled = false;
    betInput.disabled = false;
    rankInput.disabled = false;
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
    placeBet(user, casinoAccount, amount.toFixed(8), 'Faro bet', function(response) {
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
