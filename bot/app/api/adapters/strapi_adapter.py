import logging
import requests

from typing import List
from api.config import appconfig


class Middelware:
    def __init__(self):
        self.base_url = appconfig.MIDDLEWARE_BASE_URL_STRAPI
        self.referral_commissions_endpoint = "referral-commissions/"

    def get_remote_commissions(self, pubkey: str) -> List:
        referrrals = []
        try:
            response = requests.get(
                url="{}{}{}".format(
                    self.base_url,
                    self.referral_commissions_endpoint,
                    pubkey
                ),
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            referrrals = response.json()

        except Exception as e:
            logging.error(
                "Failed to fetch commissions from middleware {}{}{}. Error: {}".format(
                    self.base_url,
                    self.referral_commissions_endpoint,
                    pubkey,
                    str(e)
                )
            )

        return referrrals
