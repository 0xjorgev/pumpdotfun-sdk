import tweepy
from requests_oauthlib import OAuth1Session

from config import appconfig


class X:
    def __init__(self):
        # Authenticate
        auth = tweepy.OAuth1UserHandler(
            appconfig.X_API_KEY,
            appconfig.X_API_SECRET,
            appconfig.X_ACCESS_TOKEN,
            appconfig.X_ACCESS_SECRET
        )
        self.api = tweepy.API(auth, wait_on_rate_limit=True)

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
            client_key=appconfig.X_API_KEY,
            client_secret=appconfig.X_API_SECRET,
            resource_owner_key=appconfig.X_ACCESS_TOKEN,
            resource_owner_secret=appconfig.X_ACCESS_SECRET,
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
