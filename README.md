# Some finance API wrappers
<!-- TODO: add links to each service/documentation. -->
A python package containing three API wrappers for finance data and interaction: [Alpha Vantage](https://www.alphavantage.co/), [Finnhub](https://finnhub.io/docs/api), and [Robinhood's Crypto API](https://docs.robinhood.com/crypto/trading/). 

# Installation
Currently you can only install from Github:
```
python -m pip install git+https://github.com/shill1729/finapi.git
```


# API rate limits
Finnhubb has a 30 calls per second rate limit on top of all plans. Basic, standard, and professional are 150 API calls/minute, 300 API calls/minute, and 900 API calls/minute.

Alpha vantage is 75 calls per minute (for the basic paid plan).

See the link to Robinhood's Crypto API documentation for more details on their rate limits.

