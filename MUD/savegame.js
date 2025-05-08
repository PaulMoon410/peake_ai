function saveGame() {
    const gameState = {
        position: currentPosition, // e.g., {x: 5, y: 7}
        inventory: inventory,
        npcState: npcState // assume this is a global object
    };
    localStorage.setItem("mudSave", JSON.stringify(gameState));
    alert("Game saved!");
}

function loadGame() {
    const saved = localStorage.getItem("mudSave");
    if (!saved) return alert("No saved game found.");

    const gameState = JSON.parse(saved);
    currentPosition = gameState.position;
    inventory = gameState.inventory || [];
    npcState = gameState.npcState || {};

    renderRoom(); // update the game view
    updateInventory(); // refresh inventory display
    alert("Game loaded!");
}
