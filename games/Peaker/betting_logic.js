// betting_logic.js
// Handles placing a bet using Hive Keychain and notifies the backend for bet logging
// Usage: placeBet(casinoUser, 'peakecoin.matic', amount, 'Game memo', callback)

function formatAmount(amount) {
    const n = Number(amount);
    if (!isFinite(n) || n <= 0) return '0.00000000';
    return n.toFixed(8);
}

function placeBet(from, to, amount, memo, callback) {
    const qty = formatAmount(amount);
    if (!window.hive_keychain) {
        alert('Hive Keychain extension is required.');
        if (callback) callback({success: false, error: 'No Keychain'});
        return;
    }
    window.hive_keychain.requestCustomJson(
        from,
        'ssc-mainnet-hive',
        'Active',
        JSON.stringify({
            contractName: 'tokens',
            contractAction: 'transfer',
            contractPayload: {
                symbol: 'PEK',
                to: to,
                quantity: qty,
                memo: memo || ''
            }
        }),
        'Place PEK Bet',
        function(response) {
            if (callback) callback(response);
            if (response.success) {
                alert('Bet placed! TXID: ' + response.result.id);
                // Notify backend for bet logging
                logBetToBackend(from, to, qty, memo, response.result.id);
            } else {
                alert('Bet failed or was rejected.');
            }
        }
    );
}

// Optional: log bet to backend for audit/provable fairness
function logBetToBackend(from, to, amount, memo, txid) {
    fetch('http://74.208.146.37/peksino/log_bet', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            from: from,
            to: to,
            amount: amount,
            memo: memo,
            txid: txid
        })
    });
}
