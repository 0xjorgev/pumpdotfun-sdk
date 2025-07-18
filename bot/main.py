import asyncio
import logging
from datetime import datetime, timedelta
from module.pump import Pump, TradeRoadmap
from bot.libs.utils import Trader
from config import appconfig
from bot.libs.pump_buy import main as tax_collector_main


async def main():
    pump = Pump(
        executor_name="sniper2",
        trader_type=Trader.sniper
    )

    scanner = Pump(
        executor_name="scanner",
        trader_type=Trader.scanner
    )

    tasks = [
        # pump.subscribe(steps=TradeRoadmap.sniper_3_sell_artifical_pump),
        scanner.subscribe(steps=TradeRoadmap.scanner),
        # tax_collector_main(trades=1)
    ]
    start_time = datetime.now().strftime(appconfig.TIME_FORMAT).lower()
    # TODO: implement trader execution from input parameters
    print("Starting {} program at {}".format(Trader.sniper.value, start_time))

    await asyncio.gather(*tasks)
    stop_time = datetime.now().strftime(appconfig.TIME_FORMAT).lower()
    print("Stoping {} program at {}".format(Trader.scanner.value, stop_time))


if __name__ == "__main__":
    asyncio.run(main())
