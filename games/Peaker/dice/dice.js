// Dice Game Logic
let isRolling = false;

function rollDice() {
    if (isRolling) {
        alert('Dice are already rolling!');
        return;
    }

    const playerName = document.getElementById('playerName').value.trim();
    const betAmount = parseFloat(document.getElementById('betAmount').value);
    const betType = document.getElementById('betType').value;

    if (!playerName) {
        alert('Please enter your player name');
        return;
    }

    if (!betAmount || betAmount <= 0) {
        alert('Please enter a valid bet amount');
        return;
    }

    isRolling = true;
    document.getElementById('rollButton').disabled = true;

    // Generate random dice rolls
    const dice1Result = Math.floor(Math.random() * 6) + 1;
    const dice2Result = Math.floor(Math.random() * 6) + 1;
    const total = dice1Result + dice2Result;

    // Determine win/loss
    let isWin = false;
    let payout = 0;

    if (betType === 'over') {
        isWin = total > 7;
        payout = isWin ? betAmount * 1.98 : 0;
    } else if (betType === 'under') {
        isWin = total < 7;
        payout = isWin ? betAmount * 1.98 : 0;
    } else if (betType === 'lucky7') {
        isWin = total === 7;
        payout = isWin ? betAmount * 3.50 : 0;
    }

    // Animate dice rolls
    animateDice(dice1Result, dice2Result, () => {
        displayResult(playerName, betAmount, betType, total, isWin, payout);
        isRolling = false;
    });
}

function animateDice(dice1, dice2, callback) {
    const die1 = document.getElementById('dice1');
    const die2 = document.getElementById('dice2');

    // Rapid rotation animation
    let rotation = 0;
    const animationInterval = setInterval(() => {
        rotation += 15;
        die1.style.transform = `rotateX(${rotation}deg) rotateY(${rotation}deg)`;
        die2.style.transform = `rotateX(${rotation}deg) rotateY(${rotation}deg)`;
    }, 10);

    // Stop after 2 seconds and show final result
    setTimeout(() => {
        clearInterval(animationInterval);

        // Set final positions based on dice results
        const die1Rotation = getDiceRotation(dice1);
        const die2Rotation = getDiceRotation(dice2);

        die1.style.transform = die1Rotation;
        die2.style.transform = die2Rotation;

        callback();
    }, 2000);
}

function getDiceRotation(value) {
    const rotations = {
        1: 'rotateX(0deg) rotateY(0deg)',
        2: 'rotateX(0deg) rotateY(-90deg)',
        3: 'rotateX(0deg) rotateY(90deg)',
        4: 'rotateX(0deg) rotateY(180deg)',
        5: 'rotateX(-90deg) rotateY(0deg)',
        6: 'rotateX(90deg) rotateY(0deg)'
    };
    return rotations[value] || 'rotateX(0deg) rotateY(0deg)';
}

function displayResult(playerName, betAmount, betType, total, isWin, payout) {
    const resultArea = document.getElementById('resultArea');
    const resultText = document.getElementById('resultText');
    const resultDetails = document.getElementById('resultDetails');

    const betTypeLabel = {
        'over': 'Over 7',
        'under': 'Under 7',
        'lucky7': 'Lucky 7'
    };

    if (isWin) {
        resultText.textContent = `🎉 YOU WIN! 🎉`;
        resultDetails.textContent = `Total: ${total} | Bet: ${betTypeLabel[betType]} | You won ${payout.toFixed(2)} PEK!`;

        // Queue payout
        enqueuePayout(playerName, payout, `Dice win - ${betTypeLabel[betType]}, rolled ${total}`, (data) => {
            console.log('Payout queued:', data);
        });
    } else {
        resultText.textContent = `❌ LOSS`;
        resultDetails.textContent = `Total: ${total} | Bet: ${betTypeLabel[betType]} | Better luck next time!`;
    }

    resultArea.style.display = 'block';
}

function resetGame() {
    document.getElementById('playerName').value = '';
    document.getElementById('betAmount').value = '';
    document.getElementById('betType').value = 'over';
    document.getElementById('resultArea').style.display = 'none';
    document.getElementById('rollButton').disabled = false;

    const die1 = document.getElementById('dice1');
    const die2 = document.getElementById('dice2');
    die1.style.transform = 'rotateX(0deg) rotateY(0deg)';
    die2.style.transform = 'rotateX(0deg) rotateY(0deg)';
}
