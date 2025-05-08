<!-- Include Hive Keychain -->
<script src="https://cdn.jsdelivr.net/npm/hive-keychain/dist/hive-keychain.min.js"></script>
<script src="shop_items.js"></script>
<script>
  const SHOP_ACCOUNT = "yourshopacct"; // replace with your Hive account

  function displayShop(username) {
    const container = document.getElementById("shop");
    container.innerHTML = "<h3>Welcome to the Shop (Prices in PEK)</h3>";
    
    for (const item in window.shopItems) {
      const cost = window.shopItems[item];
      const btn = document.createElement("button");
      btn.innerText = `Buy ${item} - ${cost} PEK`;
      btn.onclick = () => buyItemWithKeychain(username, item, cost);
      container.appendChild(btn);
      container.appendChild(document.createElement("br"));
    }
  }

  function buyItemWithKeychain(username, itemName, itemCost) {
    hive_keychain.requestTransfer(
      username,
      SHOP_ACCOUNT,
      itemCost.toFixed(3),
      `Buy:${itemName}`,
      "PEK",
      (response) => {
        if (response.success) {
          alert(`Transaction broadcasted for ${itemName}!`);
        } else {
          alert("Purchase failed or cancelled.");
        }
      }
    );
  }
</script>

<div id="shop"></div>
