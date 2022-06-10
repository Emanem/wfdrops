# wfdrops
Simple python utility to scan the official [Warframe PC Drops list](https://n8k6e2y6.ssl.hwcdn.net/repos/hnfvc0o3jnfvc873njb03enrf56.html) and suggest the statistically better farming routes.

Also note this is now pretty much ***work in progress*** and it's quite prototype; also it doesn't scan the entrie file but just _Missions_ for now, so some suggested routes may not be the best (for example, the _Axi S3 Relic_ is better farmed with _Cetus_ bounties - but the utility only shows _Missions_)

## Running it
Simply invoke _wfdrops_ from command line (for now the python script will scan a copy of the PC Drops). Just needs _python3_,  _python3-tk_ and _python3-matplotlib_ (i.e. `sudo apt install python3 python3-tk python3-matplotlib` on Ubuntu).

# wfmarkethist
_wfmarkethist_ is a simple script which does many actions:

* download historical market data from _Warframe Market_
* save it in a local DB 
* expose funcitonality to extract in CSV format
* expose GUI to show both the historical prices, volumes and also a treemap of the prices for given items

Run with _-h_ (or _--help_) to find all the options.
