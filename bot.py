import os
import asyncio
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv('GRVT_API_KEY')
private_key = os.getenv('GRVT_PRIVATE_KEY')
trading_account_id = os.getenv('GRVT_SUB_ACCOUNT_ID') or os.getenv('GRVT_TRADING_ACCOUNT_ID')
environment = os.getenv('ENVIRONMENT', 'testnet')

from pysdk.grvt_ccxt_pro import GrvtCcxtPro
from pysdk.grvt_ccxt_env import GrvtEnv


class GRVTVolumeBot:
    def __init__(self):
        self.market = os.getenv('MARKET', 'BTC_USDT_Perp')
        self.leverage = int(os.getenv('LEVERAGE', '50'))
        self.investment_usdc = float(os.getenv('INVESTMENT_USDC', '10'))

        self.spread_bps = float(os.getenv('SPREAD_BPS', '1'))
        self.order_size_percent = float(os.getenv('ORDER_SIZE_PERCENT', '0.6'))
        self.refresh_interval = float(os.getenv('REFRESH_INTERVAL', '3'))

        self.delay_after_cancel = 0.2
        self.client = None
        self.start_time = None

    async def initialize(self):
        env_map = {
            'testnet': GrvtEnv.TESTNET,
            'prod': GrvtEnv.PROD,
            'production': GrvtEnv.PROD
        }

        env = env_map.get(environment.lower(), GrvtEnv.TESTNET)
        self.client = GrvtCcxtPro(env=env)

        self.client._api_key = api_key
        self.client._private_key = private_key
        self.client._trading_account_id = trading_account_id

        await self.client.load_markets()
        self.start_time = datetime.now()

        print("🚀 Bot started")
        print(f"Market: {self.market}")
        print(f"TP: 3 bps")
        print("=" * 60)

    async def cancel_all_orders(self):
        try:
            await self.client.cancel_all_orders(self.market)
            await asyncio.sleep(self.delay_after_cancel)
        except Exception as e:
            print("Cancel error:", e)

    def round_price(self, price):
        return round(price / 0.1) * 0.1

    def round_size(self, size):
        return round(size / 0.001) * 0.001

    async def get_mid_price(self):
        ob = await self.client.fetch_order_book(self.market)

        # Handle dict format
        if isinstance(ob['bids'][0], dict):
            bid = float(ob['bids'][0]['price'])
            ask = float(ob['asks'][0]['price'])
        else:
            bid = float(ob['bids'][0][0])
            ask = float(ob['asks'][0][0])

        return (bid + ask) / 2

    async def place_maker_orders(self, mid_price):
        spread_amount = mid_price * (self.spread_bps / 10000)

        capital = self.investment_usdc * self.leverage
        order_value = capital * self.order_size_percent

        # Enforce minimum notional ($100 safe)
        min_notional = 110
        if order_value < min_notional:
            order_value = min_notional

        order_size = self.round_size(order_value / mid_price)

        for side in ['buy', 'sell']:
            price = mid_price - spread_amount if side == 'buy' else mid_price + spread_amount
            price = self.round_price(price)

            try:
                await self.client.create_order(
                    self.market,
                    'limit',
                    side,
                    order_size,
                    price,
                    {
                        'sub_account_id': trading_account_id,
                        'post_only': True
                    }
                )
                print(f"{side.upper()} placed @ {price}")
            except Exception as e:
                print("Order error:", e)

    async def place_take_profit(self):
        try:
            positions = await self.client.fetch_positions()
            if not positions:
                return

            for pos in positions:
                if pos.get('symbol') != self.market:
                    continue

                size = float(pos.get('contracts') or pos.get('size') or 0)
                entry = float(pos.get('entryPrice') or pos.get('entry_price') or 0)

                if size == 0:
                    continue

                tp_percent = 3 / 10000

                if size > 0:
                    tp_price = entry * (1 + tp_percent)
                    side = 'sell'
                else:
                    tp_price = entry * (1 - tp_percent)
                    side = 'buy'

                tp_price = self.round_price(tp_price)

                await self.client.create_order(
                    self.market,
                    'limit',
                    side,
                    abs(size),
                    tp_price,
                    {
                        'sub_account_id': trading_account_id,
                        'reduce_only': True,
                        'post_only': True
                    }
                )

                print(f"🎯 TP placed @ {tp_price}")

        except Exception as e:
            print("TP error:", e)

    async def run(self):
        await self.initialize()

        while True:
            try:
                mid = await self.get_mid_price()

                await self.cancel_all_orders()
                await self.place_maker_orders(mid)
                await self.place_take_profit()

                await asyncio.sleep(self.refresh_interval)

            except Exception as e:
                print("Loop error:", e)
                await asyncio.sleep(2)


if __name__ == "__main__":
    bot = GRVTVolumeBot()
    asyncio.run(bot.run())
