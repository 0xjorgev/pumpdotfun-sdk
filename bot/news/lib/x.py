import tweepy
from requests_oauthlib import OAuth1Session


API_KEY = 'your_api_key'
API_SECRET = 'your_api_secret'
ACCESS_TOKEN = 'your_access_token'
ACCESS_SECRET = 'your_access_secret'


class X:
    def __init__(self):
        # Authenticate
        auth = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET)
        self.api = tweepy.API(auth)

    def post_tweet(self, message: str, image_path: str = None):
        payload = {
            "text": message,
        }
        if image_path:
            # Upload media
            media = self.api.media_upload(image_path)
            payload["media"] = {
                "media_ids": [media.media_id_string]
            }

        oauth = OAuth1Session(
            client_key=API_KEY,
            client_secret=API_SECRET,
            resource_owner_key=ACCESS_TOKEN,
            resource_owner_secret=ACCESS_SECRET,
        )
        response = oauth.post(
            "https://api.twitter.com/2/tweets",
            json=payload,
        )

        if response.status_code != 201:
            raise Exception(
                "Request returned an error: {} {}".format(response.status_code, response.text)
            )

        # Saving the response as JSON
        json_response = response.json()
        id = json_response["data"]["id"]
        print(f"Tweet posted: https://x.com/ghost_funds_xyz/status/{id}")
