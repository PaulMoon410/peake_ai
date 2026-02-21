// Baccarat: Player vs Banker, single round
(function(){
    function randCard() { return Math.floor(Math.random()*10)+1; }
    function handValue(cards) {
        return cards.reduce((a,b)=>a+b,0)%10;
    }
    function startGame() {
        let player = [randCard(),randCard()];
        let banker = [randCard(),randCard()];
        let pv = handValue(player), bv = handValue(banker);
        let msg = `Player: [${player.join(', ')}] (${pv}) | Banker: [${banker.join(', ')}] (${bv})\n`;
        if (pv > bv) {
            msg += 'You win!';
            placeBet({ user: casinoUser, amount: betAmount, game: 'baccarat', result: 'win' });
        }
        else if (pv < bv) {
            msg += 'Banker wins!';
            placeBet({ user: casinoUser, amount: betAmount, game: 'baccarat', result: 'lose' });
        }
        else {
            msg += 'Tie!';
            placeBet({ user: casinoUser, amount: betAmount, game: 'baccarat', result: 'tie' });
        }
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
    placeBet(user, casinoAccount, amount.toFixed(8), 'Baccarat bet', function(response) {
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
