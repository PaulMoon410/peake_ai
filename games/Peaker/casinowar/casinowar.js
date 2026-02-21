// ...existing code from casinowar.js...
(function(){
    window.addEventListener('DOMContentLoaded', function() {
        // Casino War: Player and dealer each get a card, high card wins
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
            let player = deck.pop(), dealer = deck.pop();
            let pv = cardValue(player), dv = cardValue(dealer);
            let msg = `You: ${player.r}${player.s} | Dealer: ${dealer.r}${dealer.s}. `;
            if (pv > dv) msg += 'You win!';
            else if (pv < dv) msg += 'Dealer wins!';
            else msg += 'War! (Tie)';
            document.getElementById('messages').textContent = msg;
        }
        document.getElementById('start-btn').onclick = startGame;
        // Wallet/session logic
        let storedUser = null;
        try { storedUser = localStorage.getItem('peakecoin_user'); } catch (e) {}
        if (storedUser) {
            document.getElementById('main-content').style.display = '';
            document.getElementById('wallet-address').textContent = '@' + storedUser;
        }
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
            placeBet(user, casinoAccount, amount.toFixed(8), 'Casino War bet', function(response) {
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
// ...existing code from casinowar.js...
