const npcData = {
  "Misty Forest": [
    {
      name: "Wandering Hermit",
      dialogue: "The forest remembers, child. What is it you're seeking?",
      type: "questgiver"
    }
  ],
  "Old Trading Post": [
    {
      name: "Rusty Merchant",
      dialogue: "I've seen better days. Want to trade?",
      type: "vendor"
    }
  ]
};

function getCurrentNPC(roomName) {
  return npcData[roomName] || [];
}

function talkToNPC(roomName) {
  const npcs = getCurrentNPC(roomName);
  if (npcs.length === 0) {
    alert("There's no one here to talk to.");
    return;
  }

  let dialogue = npcs.map(npc => `${npc.name} says: "${npc.dialogue}"`).join('\n');
  alert(dialogue);
}
