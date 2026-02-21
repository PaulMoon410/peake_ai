// ==UserScript==
// @name         Teen Patti Enhancer
// @namespace    http://tampermonkey.net/
// @version      0.1
// @description  Enhances the Teen Patti game with additional features
// @author       You
// @match        *://your-teen-patti-game-url/*
// @grant        none
// ==/UserScript==

(function(){
    // Teen Patti: Simple 3-card showdown
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
    function handToString(hand) { return hand.map(c=>`${c.r}${c.s}`).join(' '); }
    function handValue(hand) {
        // Simplified: only high card, pair, trail
        let vals = hand.map(c=>ranks.indexOf(c.r)).sort((a,b)=>a-b);
        let uniq = new Set(hand.map(c=>c.r));
        if (uniq.size === 1) return 3; // Trail
        if (uniq.size === 2) return 2; // Pair
        return 1; // High card
    }
    function handName(val) { return ['','High Card','Pair','Trail'][val]; }
    function startGame() {
        let deck = buildDeck();
        let player = [deck.pop(),deck.pop(),deck.pop()];
        let ai = [deck.pop(),deck.pop(),deck.pop()];
        let pv = handValue(player), av = handValue(ai);
        let msg = `You: ${handToString(player)} (${handName(pv)}) | AI: ${handToString(ai)} (${handName(av)})\n`;
        if (pv > av) msg += 'You win!';
        else if (pv < av) msg += 'AI wins!';
        else msg += 'It\'s a tie!';
        document.getElementById('messages').textContent = msg;
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
        placeBet(user, casinoAccount, amount.toFixed(8), 'Teen Patti bet', function(response) {
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
