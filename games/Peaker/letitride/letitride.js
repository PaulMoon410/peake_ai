// Let It Ride Poker implementation
// Assumes login/balance logic is already handled in the page

const deckSuits = ['♠', '♥', '♦', '♣'];
const deckRanks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A'];

function createDeck() {
    let deck = [];
    for (let s of deckSuits) {
        for (let r of deckRanks) {
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

function cardToString(card) {
    return card.rank + card.suit;
}

function handToString(hand) {
    return hand.map(cardToString).join(' ');
}

// Simple hand evaluator for Let It Ride (payouts for pair of 10s+ and up)
function evaluateLetItRideHand(cards) {
    // cards: array of 5 card objects
    // Returns {rank: string, payout: number}
    // Payouts: https://en.wikipedia.org/wiki/Let_It_Ride#Payouts
    // Royal Flush: 1000x, Straight Flush: 200x, Four of a Kind: 50x, Full House: 11x, Flush: 8x, Straight: 5x, Three of a Kind: 3x, Two Pair: 2x, Pair of 10s or better: 1x
    // Otherwise: 0
    const ranks = cards.map(c => c.rank);
    const suits = cards.map(c => c.suit);
    const rankCounts = {};
    for (let r of ranks) rankCounts[r] = (rankCounts[r] || 0) + 1;
    const counts = Object.values(rankCounts).sort((a,b)=>b-a);
    const isFlush = suits.every(s => s === suits[0]);
    const rankValues = ranks.map(r => deckRanks.indexOf(r));
    rankValues.sort((a,b)=>a-b);
    let isStraight = false;
    // Check for Ace-low straight
    if (rankValues.join(',') === '0,1,2,3,12') isStraight = true;
    else isStraight = rankValues.every((v,i,arr)=>i===0||v-arr[i-1]===1);
    // Royal Flush
    if (isFlush && isStraight && rankValues[0] === 8) return {rank:'Royal Flush', payout:1000};
    // Straight Flush
    if (isFlush && isStraight) return {rank:'Straight Flush', payout:200};
    // Four of a Kind
    if (counts[0] === 4) return {rank:'Four of a Kind', payout:50};
    // Full House
    if (counts[0] === 3 && counts[1] === 2) return {rank:'Full House', payout:11};
    // Flush
    if (isFlush) return {rank:'Flush', payout:8};
    // Straight
    if (isStraight) return {rank:'Straight', payout:5};
    // Three of a Kind
    if (counts[0] === 3) return {rank:'Three of a Kind', payout:3};
    // Two Pair
    if (counts[0] === 2 && counts[1] === 2) return {rank:'Two Pair', payout:2};
    // Pair of 10s or better
    if (counts[0] === 2) {
        // Find the pair's rank
        let pairRank = Object.keys(rankCounts).find(r => rankCounts[r] === 2);
        if (deckRanks.indexOf(pairRank) >= 8) return {rank:'Pair of 10s or Better', payout:1};
    }
    return {rank:'No Win', payout:0};
}

// UI elements
const dealBtn = document.getElementById('letitride-deal');
const pull1Btn = document.getElementById('letitride-pull1');
const pull2Btn = document.getElementById('letitride-pull2');
const resultDiv = document.getElementById('letitride-result');
const playerCardsDiv = document.getElementById('letitride-player-cards');
const communityDiv = document.getElementById('letitride-community-cards');
const betInput = document.getElementById('letitride-bet');
const balanceDiv = document.getElementById('letitride-balance');

let gameState = null;

function resetGame() {
    gameState = {
        deck: shuffle(createDeck()),
        player: [],
        community: [],
        bet: 0,
        pulls: 0,
        active: false
    };
    playerCardsDiv.textContent = '';
    communityDiv.textContent = '';
    resultDiv.textContent = '';
    pull1Btn.disabled = true;
    pull2Btn.disabled = true;
    dealBtn.disabled = false;
    betInput.disabled = false;
}

function startDeal() {
    let bet = parseFloat(betInput.value);
    if (isNaN(bet) || bet < 1) {
        resultDiv.textContent = 'Enter a valid bet (min 1 PEK).';
        return;
    }
    // Optionally: check balance here
    gameState.bet = bet;
    gameState.deck = shuffle(createDeck());
    gameState.player = [gameState.deck.pop(), gameState.deck.pop(), gameState.deck.pop()];
    gameState.community = [gameState.deck.pop(), gameState.deck.pop()];
    gameState.pulls = 0;
    gameState.active = true;
    playerCardsDiv.textContent = handToString(gameState.player);
    communityDiv.textContent = '[??] [??]';
    resultDiv.textContent = 'You may pull back your first bet or Let It Ride.';
    pull1Btn.disabled = false;
    pull2Btn.disabled = true;
    dealBtn.disabled = true;
    betInput.disabled = true;
}

function pullBet() {
    if (!gameState.active) return;
    if (gameState.pulls === 0) {
        // Reveal first community card
        communityDiv.textContent = cardToString(gameState.community[0]) + ' [??]';
        resultDiv.textContent = 'You may pull back your second bet or Let It Ride.';
        pull1Btn.disabled = true;
        pull2Btn.disabled = false;
        gameState.pulls = 1;
    } else if (gameState.pulls === 1) {
        // Reveal both community cards and resolve
        communityDiv.textContent = cardToString(gameState.community[0]) + ' ' + cardToString(gameState.community[1]);
        let finalHand = gameState.player.concat(gameState.community);
        let evalResult = evaluateLetItRideHand(finalHand);
        let totalBet = gameState.bet * (3 - gameState.pulls); // Each pull removes one bet
        let win = evalResult.payout * totalBet;
        resultDiv.textContent = evalResult.rank + (win > 0 ? `! You win ${win} PEK.` : '. No win.');
        pull2Btn.disabled = true;
        dealBtn.disabled = false;
        betInput.disabled = false;
        gameState.active = false;
    }
}

function letItRide() {
    if (!gameState.active) return;
    if (gameState.pulls === 0) {
        // Reveal first community card
        communityDiv.textContent = cardToString(gameState.community[0]) + ' [??]';
        resultDiv.textContent = 'You may pull back your second bet or Let It Ride.';
        pull1Btn.disabled = true;
        pull2Btn.disabled = false;
        gameState.pulls = 1;
    } else if (gameState.pulls === 1) {
        // Reveal both community cards and resolve
        communityDiv.textContent = cardToString(gameState.community[0]) + ' ' + cardToString(gameState.community[1]);
        let finalHand = gameState.player.concat(gameState.community);
        let evalResult = evaluateLetItRideHand(finalHand);
        let totalBet = gameState.bet * (3 - gameState.pulls); // Each pull removes one bet
        let win = evalResult.payout * totalBet;
        resultDiv.textContent = evalResult.rank + (win > 0 ? `! You win ${win} PEK.` : '. No win.');
        pull2Btn.disabled = true;
        dealBtn.disabled = false;
        betInput.disabled = false;
        gameState.active = false;
    }
}

dealBtn.onclick = startDeal;
pull1Btn.onclick = function() {
    // Pull first bet (remove one bet)
    if (!gameState.active || gameState.pulls !== 0) return;
    gameState.pulls = 1;
    resultDiv.textContent = 'First bet pulled back. Reveal first community card.';
    communityDiv.textContent = cardToString(gameState.community[0]) + ' [??]';
    pull1Btn.disabled = true;
    pull2Btn.disabled = false;
};
pull2Btn.onclick = function() {
    // Pull second bet (remove another bet and resolve)
    if (!gameState.active || gameState.pulls !== 1) return;
    gameState.pulls = 2;
    communityDiv.textContent = cardToString(gameState.community[0]) + ' ' + cardToString(gameState.community[1]);
    let finalHand = gameState.player.concat(gameState.community);
    let evalResult = evaluateLetItRideHand(finalHand);
    let totalBet = gameState.bet * (3 - gameState.pulls); // Each pull removes one bet
    let win = evalResult.payout * totalBet;
    resultDiv.textContent = evalResult.rank + (win > 0 ? `! You win ${win} PEK.` : '. No win.');
    pull2Btn.disabled = true;
    dealBtn.disabled = false;
    betInput.disabled = false;
    gameState.active = false;
};

resetGame();
