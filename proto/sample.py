import requests

url = "https://www.alphavantage.co/query"

query = "AAPL"

querystring = {"function":"TIME_SERIES_INTRADAY","symbol":query,"interval":"5min","apikey":"N9U9SP687FD676TQ"}

headers = {
    'Content-Type': "application/json",
    'cache-control': "no-cache",
    'Postman-Token': "5284e93d-daa8-4884-9aff-b14c160f5a9b"
    }

response = requests.request("GET", url, headers=headers, params=querystring)

print(response.text)