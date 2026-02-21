// ...existing code from andarbahar.js...
(function(){
    // Andar Bahar: Randomly pick Andar or Bahar, player guesses
    function startGame(guess) {
        let result = Math.random() < 0.5 ? 'Andar' : 'Bahar';
        let msg = `Result: ${result}. `;
        if (guess === result) msg += 'You win!';
        else msg += 'You lose!';
        document.getElementById('messages').textContent = msg;
    }
    document.getElementById('andar-btn').onclick = function(){ startGame('Andar'); };
    document.getElementById('bahar-btn').onclick = function(){ startGame('Bahar'); };
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
        placeBet(user, casinoAccount, amount.toFixed(8), 'Andar Bahar bet', function(response) {
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
