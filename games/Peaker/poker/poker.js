// ...existing code from poker.js...
(function(){
    // Poker: Simple 5-card draw vs AI
    const suits = ['♠','♥','♦','♣'];
    const ranks = ['2','3','4','5','6','7','8','9','10','J','Q','K','A'];
    let deck = [], playerHand = [], aiHand = [], gameActive = false;
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
    function handToString(hand) {
        return hand.map(c=>`${c.r}${c.s}`).join(' ');
    }
    function startGame() {
        deck = buildDeck();
        playerHand = [dealCard(),dealCard(),dealCard(),dealCard(),dealCard()];
        aiHand = [dealCard(),dealCard(),dealCard(),dealCard(),dealCard()];
        gameActive = true;
        render();
        showMsg('Choose cards to hold, then Draw!');
    }
    function render() {
        const ph = document.getElementById('player-hand');
        ph.innerHTML = '';
        playerHand.forEach((c,i)=>{
            const btn = document.createElement('button');
            btn.textContent = `${c.r}${c.s}`;
            btn.className = held[i] ? 'held' : '';
            btn.onclick = ()=>{ if(gameActive){ held[i]=!held[i]; render(); } };
            ph.appendChild(btn);
        });
        document.getElementById('ai-hand').textContent = aiRevealed ? handToString(aiHand) : '?????';
    }
    let held = [false,false,false,false,false], aiRevealed = false;
    function draw() {
        if (!gameActive) return;
        for (let i=0;i<5;i++) if (!held[i]) playerHand[i]=dealCard();
        aiRevealed = true;
        render();
        endGame();
    }
    function endGame() {
        gameActive = false;
        let pScore = handScore(playerHand);
        let aScore = handScore(aiHand);
        let msg = `You: ${handName(pScore)} | AI: ${handName(aScore)}. `;
        if (pScore > aScore) msg += 'You win!';
        else if (pScore < aScore) msg += 'AI wins!';
        else msg += 'It\'s a tie!';
        showMsg(msg);
    }
    function showMsg(msg) { document.getElementById('messages').textContent = msg; }
    // Poker hand scoring (very basic)
    function handScore(hand) {
        // Returns a number, higher is better
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
    // On load, show wallet and game if logged in
    window.addEventListener('DOMContentLoaded', function() {
        let storedUser = null;
        try { storedUser = localStorage.getItem('peakecoin_user'); } catch (e) {}
        if (storedUser) {
            document.getElementById('main-content').style.display = '';
            document.getElementById('wallet-address').textContent = '@' + storedUser;
        }
        // Always assign button handlers, regardless of login state
        var dealBtn = document.getElementById('deal-btn');
        if (dealBtn) dealBtn.onclick = function(){
            held = [false,false,false,false,false];
            aiRevealed = false;
            startGame();
        };
        var drawBtn = document.getElementById('draw-btn');
        if (drawBtn) drawBtn.onclick = draw;
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
            placeBet(user, casinoAccount, amount.toFixed(8), 'Poker bet', function(response) {
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
        // Replace any direct bet logic with:
        // placeBet({ user: casinoUser, amount: betAmount, game: 'poker', ...otherParams });
    });
})();
