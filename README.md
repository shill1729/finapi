# Some finance API wrappers
<!-- TODO: add links to each service/documentation. -->
A python package containing three API wrappers for finance data and interaction: alpha-vantage, Finn-Hub, and Robinhood's Crypto API. 

# How to install from github
```
python -m pip install git+https://github.com/shill1729/finapi.git
```
# API rate limits
Finnhubb has a 30 calls per second rate limit on top of all plans. Basic, standard, and professional are 150 API calls/minute, 300 API calls/minute, and 900 API calls/minute.

Alpha vantage is 75 calls per minute (for my plan).

Information on Robinhood's crypto API rate limits is as follows:

Rate Limits

    Requests per minute per user account: 100
    Requests per minute per user account in bursts: 300

Rate limiting is applied using a token bucket implementation. The burst size or capacity is the number of tokens you can use to call an endpoint. This capacity is initialized at the maximum capacity and will be refilled using a refill amount at a timed interval called refill interval until the max capacity is once again reached.
Rate Limiting Terms

Max capacity: The maximum amount of tokens allowed. Will no longer continue refilling if this amount is reached.

Remaining amount: The number of tokens remaining that can be consumed to call an endpoint.

Refill amount: 	The number of tokens that are refilled at each refill interval.

Refill interval: 	The timed interval at which the tokens are refilled.

The actual values of the configuration will fluctuate depending on the availability of our service and our current expected volume at the time of service. Rate limits are applied per endpoint and may differ among each endpoint depending on their expected use case.

Example rate limiting configuration:

Term 	Value
Max capacity 	    5
Remaining amount 	2
Refill amount 	    1
Refill interval 	1 second

