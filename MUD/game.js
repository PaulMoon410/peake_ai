let mapData;
let player = {
  x: 0,
  y: 0
};

async function loadMap() {
  const response = await fetch('maps/map_1.json');
  mapData = await response.json();
  updateLocation();
}

async function updateLocation() {
  const tileName = mapData.tiles[player.y][player.x];
  document.getElementById('locationName').innerText = tileName;

  // Try to fetch a detailed room description
  try {
    const roomResponse = await fetch(`rooms/${tileName.toLowerCase().replace(/ /g, "_")}.json`);
    if (roomResponse.ok) {
      const roomData = await roomResponse.json();
      document.getElementById('locationDescription').innerText = roomData.description;
    } else {
      document.getElementById('locationDescription').innerText = mapData.start.description;
    }
  } catch (error) {
    document.getElementById('locationDescription').innerText = mapData.start.description;
  }
}

function move(direction) {
  if (direction === 'north' && player.y > 0) player.y--;
  else if (direction === 'south' && player.y < mapData.size[1] - 1) player.y++;
  else if (direction === 'west' && player.x > 0) player.x--;
  else if (direction === 'east' && player.x < mapData.size[0] - 1) player.x++;
  else {
    alert("You can't go that way!");
    return;
  }
  updateLocation();
}

loadMap();
