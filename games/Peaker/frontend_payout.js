// frontend_payout.js
// Call this function from your game when a user wins and should be paid out
// Example: enqueuePayout('winnerusername', 100, 'Blackjack win')

// Configure backend API base (production: your VPS)
const API_BASE = 'http://74.208.146.37:5000/peksino';

function formatAmount(amount) {
    const n = Number(amount);
    if (!isFinite(n) || n <= 0) return '0.00000000';
    // 8 decimal places string
    return n.toFixed(8);
}

function enqueuePayout(to, amount, memo, callback) {
    const qty = formatAmount(amount);
    fetch(`${API_BASE}/enqueue_payout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            to: to,
            amount: qty,
            memo: memo || ''
        })
    })
    .then(r => r.json())
    .then(data => {
        if (callback) callback(data);
        if (data.status === 'queued') {
            alert('Payout queued for ' + to + ' (' + qty + ' PEK)');
        } else {
            alert('Payout error: ' + (data.error || 'Unknown error'));
        }
    })
    .catch(err => {
        if (callback) callback({error: err});
        alert('Payout request failed: ' + err);
    });
}
