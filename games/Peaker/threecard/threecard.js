// ...existing code from threecard.js...
(function(){
    // Three Card Poker: 3-card showdown, player vs AI
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
        // Simplified: straight flush > three of a kind > straight > flush > pair > high card
        let vals = hand.map(c=>ranks.indexOf(c.r)).sort((a,b)=>a-b);
        let suitsArr = hand.map(c=>c.s);
        let flush = suitsArr.every(s=>s===suitsArr[0]);
        let straight = vals[2]-vals[0]===2 && new Set(vals).size===3;
        let uniq = new Set(hand.map(c=>c.r));
        if (flush && straight) return 5;
        if (uniq.size === 1) return 4;
        if (straight) return 3;
        if (flush) return 2;
        if (uniq.size === 2) return 1;
        return 0;
    }
    function handName(val) { return ['High Card','Pair','Flush','Straight','Three of a Kind','Straight Flush'][val]; }
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
})();

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
    placeBet(user, casinoAccount, amount.toFixed(8), 'Three Card Poker bet', function(response) {
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
