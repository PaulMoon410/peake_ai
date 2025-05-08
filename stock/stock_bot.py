import time
from datetime import datetime, timedelta
from alpaca_trade_api.rest import REST, TimeFrame
import pytz

# Alpaca credentials
API_KEY = 'your_key'
SECRET_KEY = 'your_secret'
BASE_URL = 'https://paper-api.alpaca.markets'

# Bot settings
SYMBOL = 'IBM'
BUY_DROP_PERCENT = 0.02  # Buy if price drops 2% from recent high
SELL_GAIN_PERCENT = 0.03  # Sell if price rises 3% above buy
DOLLAR_AMOUNT = 10  # Trade size in USD
CHECK_INTERVAL = 60  # seconds between checks

# Setup
api = REST(API_KEY, SECRET_KEY, base_url=BASE_URL)
last_high = None
bought_price = None
timezone = pytz.timezone("America/New_York")

print("🤖 IBM trading bot starting...")

def wait_for_fill(order_id):
    """Waits up to 10 seconds for an order to fill"""
    for _ in range(10):
        order = api.get_order(order_id)
        if order.status == 'filled':
            print(f"🎯 Order filled: {order.side.upper()} ${order.filled_avg_price} for {order.filled_qty} shares.")
            return order
        time.sleep(1)
    print("⚠️ Order not filled in time.")
    return None

while True:
    try:
        # Check market status
        clock = api.get_clock()
        if not clock.is_open:
            print("⏸️ Market is closed. Next open:", clock.next_open)
            time.sleep(300)
            continue

        # Get the most recent minute bar
        start_time = (datetime.now(timezone) - timedelta(minutes=5)).isoformat()
        barset = api.get_bars(SYMBOL, TimeFrame.Minute, start=start_time)
        if not barset:
            print("⚠️ No data for IBM yet...")
            time.sleep(30)
            continue

        bar = barset[-1]
        current_price = bar.c
        now = datetime.now(timezone).strftime('%H:%M:%S')
        print(f"[{now}] IBM Price: ${current_price:.2f}")

        if last_high is None or current_price > last_high:
            last_high = current_price

        # BUY CONDITION
        if bought_price is None and current_price <= last_high * (1 - BUY_DROP_PERCENT):
            order = api.submit_order(
                symbol=SYMBOL,
                notional=DOLLAR_AMOUNT,
                side='buy',
                type='market',
                time_in_force='gtc'
            )
            print(f"✅ Buy submitted at ${current_price:.2f}")
            filled_order = wait_for_fill(order.id)
            if filled_order:
                bought_price = float(filled_order.filled_avg_price)
                last_high = bought_price

        # SELL CONDITION
        elif bought_price is not None and current_price >= bought_price * (1 + SELL_GAIN_PERCENT):
            order = api.submit_order(
                symbol=SYMBOL,
                notional=DOLLAR_AMOUNT,
                side='sell',
                type='market',
                time_in_force='gtc'
            )
            print(f"✅ Sell submitted at ${current_price:.2f}")
            filled_order = wait_for_fill(order.id)
            if filled_order:
                bought_price = None
                last_high = float(filled_order.filled_avg_price)

        time.sleep(CHECK_INTERVAL)

    except Exception as e:
        print("⚠️ Error:", e)
        time.sleep(10)
