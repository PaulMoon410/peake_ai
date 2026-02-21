// Roulette Game Logic
let isSpinning = false;

function spinRoulette() {
    if (isSpinning) {
        alert('Wheel is already spinning!');
        return;
    }

    const playerName = document.getElementById('playerName').value.trim();
    const betAmount = parseFloat(document.getElementById('betAmount').value);
    const betNumber = parseInt(document.getElementById('betNumber').value);

    if (!playerName) {
        alert('Please enter your player name');
        return;
    }

    if (!betAmount || betAmount <= 0) {
        alert('Please enter a valid bet amount');
        return;
    }

    if (betNumber < 0 || betNumber > 9) {
        alert('Please select a number between 0 and 9');
        return;
    }

    isSpinning = true;
    document.getElementById('spinButton').disabled = true;

    // Generate random winning number
    const winningNumber = Math.floor(Math.random() * 10);
    const isWin = winningNumber === betNumber;

    // Spin animation
    const wheel = document.getElementById('rouletteWheel');
    const rotations = 10 + (winningNumber / 10);
    wheel.style.transform = `rotate(${rotations * 360}deg)`;

    // Wait for spin to complete
    setTimeout(() => {
        displayResult(playerName, betAmount, betNumber, winningNumber, isWin);
        isSpinning = false;
    }, 3000);
}

function displayResult(playerName, betAmount, betNumber, winningNumber, isWin) {
    const resultArea = document.getElementById('resultArea');
    const resultText = document.getElementById('resultText');
    const resultDetails = document.getElementById('resultDetails');

    if (isWin) {
        const payout = betAmount * 1.97;
        resultText.textContent = `🎉 YOU WIN! 🎉`;
        resultDetails.textContent = `The wheel landed on ${winningNumber}! You won ${payout.toFixed(2)} PEK!`;

        // Queue payout
        enqueuePayout(playerName, payout, `Roulette win - bet on ${betNumber}, landed on ${winningNumber}`, (data) => {
            console.log('Payout queued:', data);
        });
    } else {
        resultText.textContent = `❌ LOSS`;
        resultDetails.textContent = `The wheel landed on ${winningNumber}. Better luck next time!`;
    }

    resultArea.style.display = 'block';
}

function resetGame() {
    document.getElementById('playerName').value = '';
    document.getElementById('betAmount').value = '';
    document.getElementById('betNumber').value = '';
    document.getElementById('resultArea').style.display = 'none';
    document.getElementById('spinButton').disabled = false;
    document.getElementById('rouletteWheel').style.transform = 'rotate(0deg)';
}
