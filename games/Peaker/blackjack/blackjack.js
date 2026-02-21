// Blackjack game logic
(function(){
    // --- Blackjack Game Logic ---
    const suits = ['♠','♥','♦','♣'];
    const ranks = ['A','2','3','4','5','6','7','8','9','10','J','Q','K'];
    let deck = [];
    let playerHand = [];
    let dealerHand = [];
    let gameActive = false;
    let playerStands = false;

    function buildDeck() {
        let d = [];
        for (let s of suits) for (let r of ranks) d.push({s,r});
        for (let i = d.length - 1; i > 0; i--) {
            let j = Math.floor(Math.random() * (i + 1));
            [d[i], d[j]] = [d[j], d[i]];
        }
        return d;
    }
    function dealCard() { return deck.pop(); }
    function handValue(hand) {
        let val = 0, aces = 0;
        for (let c of hand) {
            if (c.r === 'A') { val += 11; aces++; }
            else if (['K','Q','J'].includes(c.r)) val += 10;
            else val += +c.r;
        }
        while (val > 21 && aces) { val -= 10; aces--; }
        return val;
    }
    function renderHand(hand, id, hideFirst) {
        const el = document.getElementById(id);
        el.innerHTML = hand.map((c,i)=>hideFirst&&i===0?'<span class="card">?</span>':`<span class="card">${c.r}${c.s}</span>`).join(' ');
    }
    function showMessage(msg) {
        document.getElementById('messages').textContent = msg;
    }
    function startGame() {
        deck = buildDeck();
        playerHand = [dealCard(), dealCard()];
        dealerHand = [dealCard(), dealCard()];
        gameActive = true;
        playerStands = false;
        renderHand(playerHand, 'player-hand');
        renderHand(dealerHand, 'dealer-hand', true);
        document.getElementById('hit-btn').style.display = '';
        document.getElementById('stand-btn').style.display = '';
        document.getElementById('start-btn').style.display = 'none';
        document.getElementById('restart-btn').style.display = 'none';
        showMessage('Your move!');
        checkPlayerBlackjack();
    }
    function hit() {
        if (!gameActive || playerStands) return;
        playerHand.push(dealCard());
        renderHand(playerHand, 'player-hand');
        if (handValue(playerHand) > 21) endGame();
    }
    function stand() {
        if (!gameActive) return;
        playerStands = true;
        dealerTurn();
    }
    function dealerTurn() {
        renderHand(dealerHand, 'dealer-hand');
        while (handValue(dealerHand) < 17) {
            dealerHand.push(dealCard());
            renderHand(dealerHand, 'dealer-hand');
        }
        endGame();
    }
    function checkPlayerBlackjack() {
        if (handValue(playerHand) === 21) {
            playerStands = true;
            dealerTurn();
        }
    }
    function endGame() {
        gameActive = false;
        renderHand(dealerHand, 'dealer-hand');
        document.getElementById('hit-btn').style.display = 'none';
        document.getElementById('stand-btn').style.display = 'none';
        document.getElementById('start-btn').style.display = '';
        document.getElementById('restart-btn').style.display = '';
        const playerVal = handValue(playerHand);
        const dealerVal = handValue(dealerHand);
        let msg = '';
        if (playerVal > 21) msg = 'You bust! Dealer wins.';
        else if (dealerVal > 21) msg = 'Dealer busts! You win!';
        else if (playerVal > dealerVal) msg = 'You win!';
        else if (playerVal < dealerVal) msg = 'Dealer wins!';
        else msg = 'Push! It\'s a tie.';
        showMessage(msg + ` (Your hand: ${playerVal}, Dealer: ${dealerVal})`);
    }
    function restartGame() {
        document.getElementById('restart-btn').style.display = 'none';
        startGame();
    }
    window.addEventListener('DOMContentLoaded', function() {
        // Session and wallet logic (already present)
        let storedUser = null;
        try { storedUser = localStorage.getItem('peakecoin_user'); } catch (e) {}
        if (storedUser) {
            document.getElementById('main-content').style.display = '';
            document.getElementById('wallet-address').textContent = '@' + storedUser;
        }

        document.getElementById('start-btn').onclick = startGame;
        document.getElementById('hit-btn').onclick = hit;
        document.getElementById('stand-btn').onclick = stand;
        var restartBtn = document.getElementById('restart-btn');
        if (restartBtn) restartBtn.onclick = restartGame;
        if (restartBtn) restartBtn.style.display = 'none';

        // Betting logic
        const placeBetBtn = document.getElementById('place-bet-btn');
        const betAmountInput = document.getElementById('bet-amount');
        const betStatus = document.getElementById('bet-status');

        let betPlaced = false;
        let lastBetAmount = 0;
        const casinoAccount = 'peakecoin.casino';

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
            placeBet(user, casinoAccount, amount.toFixed(8), 'Blackjack bet', function(response) {
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
    });
})();
