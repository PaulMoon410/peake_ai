window.onload = function () {
    let player = window.createPlayer();
    let inRoom = null; // null if on the main map, or room key like 'shop_5_5'
  
    const map = window.gameMap;
    const rooms = window.roomDetails || {};
   
   
   
    function writeToConsole(message, append = true) {
        const consoleBox = document.getElementById("console");
        if (!append) consoleBox.innerHTML = ""; // clear console if needed
        const line = document.createElement("div");
        line.textContent = message;
        consoleBox.appendChild(line);
        consoleBox.scrollTop = consoleBox.scrollHeight;
      }
      
   
      function describeLocation() {
        const key = getLocationKey(player.x, player.y);
        const roomKey = inRoom || key;
        const room = rooms[roomKey];
        const mapDesc = map[key] || "You see nothing of interest.";
      
        let desc = room ? `${room.name}\n\n${room.description}` : mapDesc;
      
        if (room?.npcs) {
          desc += `\n\nNPCs here: ${room.npcs.join(", ")}`;
        }
      
        if (room?.objects) {
          desc += `\nObjects: ${room.objects.join(", ")}`;
        }
      
        if (room?.exits) {
          const exits = Object.keys(room.exits)
            .map((dir) => dir.toUpperCase())
            .join(", ");
          desc += `\nExits: ${exits}`;
        } else {
          desc += `\nExits: NORTH, SOUTH, EAST, WEST (if not blocked)`;
        }
      
        return desc;
      }
      
        
    function getLocationKey(x, y) {
      return `${x},${y}`;
    }
  
    function getRoomDetails(x, y) {
      return rooms[getLocationKey(x, y)];
    }
  
    function describeLocation() {
      const key = getLocationKey(player.x, player.y);
      const mapDesc = map[key] || "You see nothing of interest.";
      const room = getRoomDetails(player.x, player.y);
  
      let desc = room ? `${room.name}\n\n${room.description}` : mapDesc;
  
      if (room?.npcs) {
        desc += `\n\nNPCs here: ${room.npcs.join(", ")}`;
      }
  
      if (room?.objects) {
        desc += `\nObjects: ${room.objects.join(", ")}`;
      }
  
      return desc;
    }
  
    function render() {
        writeToConsole(describeLocation(), false);  // overwrite console each move
        document.getElementById("stats").innerText = `HP: ${player.hp}\nStamina: ${player.stamina}`;
      
        const inventoryList = document.getElementById("inventory");
        inventoryList.innerHTML = "";
        player.inventory.forEach((item) => {
          const li = document.createElement("li");
          li.textContent = item;
          inventoryList.appendChild(li);
        });
      
        if (!inRoom && getLocationKey(player.x, player.y) === "5,5") {
          displayShop("your_hive_username"); // Replace with logic later
        } else {
          document.getElementById("shop").innerHTML = "";
        }
      }
      
  
    window.move = function (direction) {
      let newX = player.x;
      let newY = player.y;
  
      switch (direction) {
        case "n": newY--; break;
        case "s": newY++; break;
        case "e": newX++; break;
        case "w": newX--; break;
      }
  
      const key = getLocationKey(newX, newY);
      if (map.hasOwnProperty(key)) {
        player.x = newX;
        player.y = newY;
        player.stamina = Math.max(0, player.stamina - 1);
      } else {
        writeToConsole("You can't go that way.");
      }
  
      render();
    };
  
    window.enter = function () {
        const key = getLocationKey(player.x, player.y);
        const possibleRoomKey = `shop_${key}`; // e.g. 5,5 → shop_5_5
        if (rooms[possibleRoomKey]) {
          inRoom = possibleRoomKey;
          render();
        } else {
          writeToConsole("There is nothing to enter here.");
        }
      };
      
      window.exitRoom = function () {
        if (!inRoom) {
          writeToConsole("You're not in a room.");
          return;
        }
        const room = rooms[inRoom];
        if (room?.exits?.out) {
          const exit = room.exits.out;
          if (exit.startsWith("mainMap:")) {
            const coords = exit.split(":")[1].split(",");
            player.x = parseInt(coords[0]);
            player.y = parseInt(coords[1]);
            inRoom = null;
            render();
          }
        } else {
          writeToConsole("There is no exit.");
        }
      };
      
      window.saveGame = function () {
      const data = btoa(JSON.stringify(player));
      navigator.clipboard.writeText(data);
      writeToConsole("Save code copied!");
    };
  
    window.downloadSave = function () {
      const data = btoa(JSON.stringify(player));
      const a = document.createElement("a");
      a.href = `data:text/plain;charset=utf-8,${data}`;
      a.download = "savegame.txt";
      a.click();
    };
  
    window.loadGame = function () {
      try {
        const data = document.getElementById("loadInput").value;
        const parsed = JSON.parse(atob(data));
        Object.assign(player, parsed);
        render();
      } catch (e) {
        writeToConsole("Failed to load game.");
      }
    };
  
    window.handleCommand = function () {
      const input = document.getElementById("commandInput").value.trim().toLowerCase();
      const key = getLocationKey(player.x, player.y);
      const room = getRoomDetails(player.x, player.y);
  
      if (input === "look") {
        writeToConsole(describeLocation());
      } else if (input === "help") {
        writeToConsole("Available commands:\nlook\nenter\nexit\ntalk [name]\nuse [item]");
      } else if (input === "enter") {
        if (room?.exits?.enter) {
          const [x, y] = room.exits.enter.split(",").map(Number);
          player.x = x;
          player.y = y;
          render();
        } else {
          writeToConsole("There's nowhere to enter here.");
        }
      } else if (input === "exit" || input === "out") {
        if (room?.exits?.out) {
          const [x, y] = room.exits.out.split(",").map(Number);
          player.x = x;
          player.y = y;
          render();
        } else {
          writeToConsole("There's no exit here.");
        }
      } else if (input.startsWith("talk ")) {
        const npcName = input.slice(5);
        if (room?.npcs?.includes(npcName)) {
          writeToConsole(`${npcName} stares at you silently... (NPC interaction placeholder)`);
        } else {
          writeToConsole("That person isn't here.");
        }
      } else if (input.startsWith("use ")) {
        const item = input.slice(4);
        if (player.inventory.includes(item)) {
          writeToConsole(`You use the ${item}. Nothing happens (yet).`);
        } else {
          writeToConsole("You don't have that item.");
        }
      } else {
        writeToConsole("Unrecognized command. Type 'help' for options.");
      }
  
      document.getElementById("commandInput").value = "";
    };
  
    render();
  };
  