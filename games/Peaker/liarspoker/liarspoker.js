// Liar's Poker implementation (single player, simplified)
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
const guessInput = document.getElementById('liarspoker-guess');
const resultDiv = document.getElementById('liarspoker-result');
const handDiv = document.getElementById('liarspoker-hand');
const placeBetBtn = document.getElementById('place-bet-btn');
const betAmountInput = document.getElementById('bet-amount');
const betStatus = document.getElementById('bet-status');
const dealBtn = document.getElementById('liarspoker-deal');

let gameState = null;
let betPlaced = false;
let lastBetAmount = 0;
const casinoAccount = 'peakecoin.casino';

function resetGame() {
    gameState = {
        deck: shuffle(createDeck()),
        hand: [],
        active: false
    };
    handDiv.textContent = '';
    resultDiv.textContent = '';
    dealBtn.disabled = false;
    guessInput.disabled = false;
}

function startDeal() {
    gameState.deck = shuffle(createDeck());
    gameState.hand = [];
    for (let i = 0; i < 5; i++) {
        gameState.hand.push(gameState.deck.pop());
    }
    handDiv.textContent = 'Your hand: ' + gameState.hand.map(c => c.rank + c.suit).join(' ');
    resultDiv.textContent = 'Guess the highest poker hand you have (e.g., Pair, Two Pair, Three of a Kind, Straight, Flush, Full House, Four of a Kind, Straight Flush, Royal Flush)';
    gameState.active = true;
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
    placeBet(user, casinoAccount, amount.toFixed(8), 'Liarspoker bet', function(response) {
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

dealBtn.onclick = function() {
    if (!betPlaced) {
        betStatus.textContent = 'Place a bet first!';
        return;
    }
    startDeal();
    // Optionally, reset betPlaced here if you want a bet per hand
    // betPlaced = false;
    // dealBtn.disabled = true;
    // placeBetBtn.disabled = false;
    // betAmountInput.disabled = false;
};

guessInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && gameState.active) {
        let guess = guessInput.value.trim().toLowerCase();
        let actual = evaluateHand(gameState.hand).toLowerCase();
        if (guess === actual) {
            resultDiv.textContent = 'Correct! You have: ' + actual;
        } else {
            resultDiv.textContent = 'Incorrect. You have: ' + actual;
        }
        gameState.active = false;
    }
});

function evaluateHand(cards) {
    // Returns best hand as string
    // ...basic poker hand evaluator...
    const rankOrder = {'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,'10':10,'J':11,'Q':12,'K':13,'A':14};
    let ranksArr = cards.map(c=>rankOrder[c.rank]).sort((a,b)=>a-b);
    let suitsArr = cards.map(c=>c.suit);
    let counts = {};
    for (let r of cards.map(c=>c.rank)) counts[r] = (counts[r]||0)+1;
    let vals = Object.values(counts).sort((a,b)=>b-a);
    let isFlush = suitsArr.every(s=>s===suitsArr[0]);
    let isStraight = ranksArr.every((v,i,arr)=>i===0||v-arr[i-1]===1) || (ranksArr.join(',')==='2,3,4,5,14');
    if (isFlush && isStraight && ranksArr[0]===10) return 'Royal Flush';
    if (isFlush && isStraight) return 'Straight Flush';
    if (vals[0]===4) return 'Four of a Kind';
    if (vals[0]===3 && vals[1]===2) return 'Full House';
    if (isFlush) return 'Flush';
    if (isStraight) return 'Straight';
    if (vals[0]===3) return 'Three of a Kind';
    if (vals[0]===2 && vals[1]===2) return 'Two Pair';
    if (vals[0]===2) return 'Pair';
    return 'High Card';
}

resetGame();
