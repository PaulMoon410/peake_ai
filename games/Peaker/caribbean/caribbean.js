// ==UserScript==
// @name         Caribbean Stud Poker
// @namespace    http://tampermonkey.net/
// @version      0.1
// @description  Play Caribbean Stud Poker against an AI dealer
// @author       You
// @match        http://example.com/*
// @grant        none
// ==/UserScript==

(function() {
    'use strict';

    // Caribbean Stud Poker: 5-card showdown, player vs AI
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
    function handScore(hand) {
        let vals = hand.map(c=>ranks.indexOf(c.r)).sort((a,b)=>a-b);
        let suitsArr = hand.map(c=>c.s);
        let flush = suitsArr.every(s=>s===suitsArr[0]);
        let straight = vals.every((v,i,a)=>i===0||v===a[i-1]+1);
        let counts = {};
        for (let c of hand) counts[c.r]=(counts[c.r]||0)+1;
        let pairs = Object.values(counts).filter(v=>v===2).length;
        let threes = Object.values(counts).filter(v=>v===3).length;
        let fours = Object.values(counts).filter(v=>v===4).length;
        if (straight && flush) return 8;
        if (fours) return 7;
        if (threes && pairs) return 6;
        if (flush) return 5;
        if (straight) return 4;
        if (threes) return 3;
        if (pairs===2) return 2;
        if (pairs===1) return 1;
        return 0;
    }
    function handName(score) {
        return ['High Card','Pair','Two Pair','Three of a Kind','Straight','Flush','Full House','Four of a Kind','Straight Flush'][score];
    }
    function startGame() {
        let deck = buildDeck();
        let player = [deck.pop(),deck.pop(),deck.pop(),deck.pop(),deck.pop()];
        let ai = [deck.pop(),deck.pop(),deck.pop(),deck.pop(),deck.pop()];
        let ps = handScore(player), as = handScore(ai);
        let msg = `You: ${handToString(player)} (${handName(ps)}) | AI: ${handToString(ai)} (${handName(as)})\n`;
        if (ps > as) msg += 'You win!';
        else if (ps < as) msg += 'AI wins!';
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
        placeBet(user, casinoAccount, amount.toFixed(8), 'Caribbean Stud Poker bet', function(response) {
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
