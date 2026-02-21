// ==UserScript==
// @name         Playable Red Dog
// @namespace    http://tampermonkey.net/
// @version      0.1
// @description  Add a simple playable Red Dog game: player bets if next card is between two others
// @author       You
// @match        http://yourgameurl.com/*
// @grant        none
// ==/UserScript==

(function(){
    // Red Dog: Player bets if next card is between two others
    const suits = ['♠','♥','♦','♣'];
    const ranks = ['2','3','4','5','6','7','8','9','10','J','Q','K','A'];
    function buildDeck() {
        let d = [];
        for (let s of suits) for (let r of ranks) d.push({s,r});
        for (let i = d.length - 1; i > 0; i--) {
            let j = Math.floor(Math.random() * (i + 1));
            [d[i], d[j]] = [d[j], d[i]];
        }
        return d;
    }
    function cardValue(c) { return ranks.indexOf(c.r); }
    function startGame() {
        let deck = buildDeck();
        let c1 = deck.pop(), c2 = deck.pop();
        let min = Math.min(cardValue(c1), cardValue(c2));
        let max = Math.max(cardValue(c1), cardValue(c2));
        let msg = `First: ${c1.r}${c1.s}, Second: ${c2.r}${c2.s}. Bet: Will next card be between?`;
        document.getElementById('messages').textContent = msg;
        document.getElementById('bet-btn').onclick = function(){
            let c3 = deck.pop();
            let v = cardValue(c3);
            let result = (v > min && v < max) ? 'You win!' : 'You lose!';
            document.getElementById('messages').textContent = `Third: ${c3.r}${c3.s}. ${result}`;
        };
    }
    document.getElementById('start-btn').onclick = startGame;
    window.addEventListener('DOMContentLoaded', function() {
        let storedUser = null;
        try { storedUser = localStorage.getItem('peakecoin_user'); } catch (e) {}
        if (storedUser) {
            document.getElementById('main-content').style.display = '';
            document.getElementById('wallet-address').textContent = '@' + storedUser;
        }
    });
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
        placeBet(user, casinoAccount, amount.toFixed(8), 'Red Dog bet', function(response) {
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
})();
