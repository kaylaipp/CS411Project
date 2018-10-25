import tweepy
import json
from flask import Flask, render_template, Response, request, redirect, url_for
import re
from random import randint
import config
import requests
from datetime import date, timedelta

#twitter authentication - put keys in config.py & gitignore 
CONSUMER_KEY = config.consumer_key
CONSUMER_SECRET = config.consumer_secret
ACCESS_KEY = config.access_token_key
ACCESS_SECRET = config.access_token_secret

auth = tweepy.auth.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
auth.set_access_token(ACCESS_KEY, ACCESS_SECRET)
twitter_api = tweepy.API(auth)

stockURL = "https://www.alphavantage.co/query"
#query = "AAPL"



app = Flask(__name__)
@app.route('/')
def mainPage():
    return render_template('index.html')

#get list of tweets based on query 
def getTweets(query):
    search_results = twitter_api.search(query, count=10)
    tweets = []
    for tweet in search_results:
        tweets.append(tweet.text)
    return tweets

def getQuote(query):
    yesterday = date.today() - timedelta(days=1)
    querystring = {"function":"TIME_SERIES_DAILY","symbol":query,"interval":"5min","apikey":"N9U9SP687FD676TQ"}
    headers = {
        'Content-Type': "application/json",
        'cache-control': "no-cache",
        'Postman-Token': "5284e93d-daa8-4884-9aff-b14c160f5a9b"
        }
    response = requests.request("GET", stockURL, headers=headers, params=querystring)
    quotes = [response.json()["Time Series (Daily)"][str(yesterday)]["4. close"]]
    # for quote in response:
    #     quotes.append(quote)
    return quotes

@app.route('/search', methods=['POST'])
def searchResults(): 
    query = request.form.get('query')
    tweets = getTweets(query)
    quotes = getQuote(query)
    return render_template('search.html', tweets = tweets, quotes = quotes)

if __name__ == '__main__':
    app.run()

