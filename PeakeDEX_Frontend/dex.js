async function init() {
    updateOrderbook();
}

async function updateOrderbook() {
    const token = document.getElementById("token-select").value;
    document.getElementById("buy-orders").innerHTML = "Loading...";
    document.getElementById("sell-orders").innerHTML = "Loading...";

    const buyPayload = {
        jsonrpc: "2.0",
        method: "find",
        params: {
            contract: "market",
            table: "buyBook",
            query: { symbol: token },
            indexes: [{ index: "priceDec", descending: true }],
            limit: 10
        },
        id: 1
    };

    const sellPayload = JSON.parse(JSON.stringify(buyPayload));
    sellPayload.params.table = "sellBook";
    sellPayload.params.indexes = [{ index: "price", descending: false }];

    const [buyRes, sellRes] = await Promise.all([
        axios.post("https://api.hive-engine.com/rpc/contracts", buyPayload),
        axios.post("https://api.hive-engine.com/rpc/contracts", sellPayload)
    ]);

    const buys = buyRes.data.result.filter(o => o.priceSymbol === "PEK");
    const sells = sellRes.data.result.filter(o => o.priceSymbol === "PEK");

    document.getElementById("buy-orders").innerHTML = "<h4>Buy Orders</h4>" + buys.map(o =>
        `<div>${o.quantity} @ ${o.price} PEK</div>`).join("");

    document.getElementById("sell-orders").innerHTML = "<h4>Sell Orders</h4>" + sells.map(o =>
        `<div>${o.quantity} @ ${o.price} PEK</div>`).join("");
}

function placeOrder() {
    const username = document.getElementById("username").value;
    const token = document.getElementById("token-select").value;
    const quantity = parseFloat(document.getElementById("quantity").value).toFixed(8);
    const price = parseFloat(document.getElementById("price").value).toFixed(8);
    const side = document.getElementById("side").value;

    const json = JSON.stringify({
        contractName: "market",
        contractAction: side,
        contractPayload: {
            symbol: token,
            quantity: quantity,
            price: price
        }
    });

    hive_keychain.requestCustomJson(
        username,
        "ssc-mainnet-hive",
        "Active",
        json,
        `Place ${side} order`,
        function(response) {
            alert("Order sent: " + JSON.stringify(response));
            updateOrderbook();
        }
    );
}