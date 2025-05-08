// inventory.js

const inventory = [];

function addItem(item) {
  inventory.push(item);
  console.log(`🧾 Added: ${item}`);
}

function removeItem(item) {
  const index = inventory.indexOf(item);
  if (index !== -1) {
    inventory.splice(index, 1);
    console.log(`🗑️ Removed: ${item}`);
  } else {
    console.log(`❌ Item not found: ${item}`);
  }
}

function listInventory() {
  if (inventory.length === 0) {
    console.log("🧳 Inventory is empty.");
  } else {
    console.log("🎒 Inventory:");
    inventory.forEach((item, index) => {
      console.log(`${index + 1}. ${item}`);
    });
  }
}

// Optionally expose functions to global scope for interaction
window.inventorySystem = {
  addItem,
  removeItem,
  listInventory,
  getItems: () => [...inventory]  // safe copy
};
