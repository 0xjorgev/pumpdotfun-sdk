from enum import Enum

import logging
import openai
import re


class Language(Enum):
    English = "English"
    Spanish = "Spanish"
    Italian = "Italian"
    French = "French"
    German = "German"
    Chinese = "Chinese"
    Russian = "Russian"
    Arabic = "Arabic"


class GPT:
    def __init__(self) -> None:
        self.api_key = ""  # noqa: E501

        # Set up logging
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO
        )
        self.logger = logging.getLogger(__name__)

    def url_treatment(
        self,
        text: str
    ) -> tuple[str, str]:
        # Extract the URL using a regex pattern
        url_pattern = r'(https?://\S+)'
        match = re.search(url_pattern, text)
        if match:
            url = match.group(0)  # Extracted URL
            text_without_url = text.replace(url, "").strip()
        else:
            url = None
            text_without_url = text

        return text_without_url, url

    def translate_text(
        self,
        origin_language: Language,
        target_languege: Language,
        text: str
    ) -> str:
        # Set up the OpenAI API key
        openai.api_key = self.api_key

        text_without_url, url = self.url_treatment(text=text)

        if not text_without_url:
            return text

        messages = [
            {
                "role": "assistant",
                "content": "You are a helpful assistant that translates {} text to {}.".format(  # noqa: E501
                    origin_language.value,
                    target_languege.value
                )
            },
            {
                "role": "user",
                "content": "Translate the following {} text to {}:\n\n{}".format(  # noqa: E501
                    origin_language.value,
                    target_languege.value,
                    text_without_url
                )
            }
        ]

        # Call the OpenAI API to translate the text
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4o-mini",  # other engines like gpt-4
                messages=messages,
                max_tokens=200,  # Limit for response length
                temperature=0.2,  # Low temperature for more accurate translations  # noqa: E501
                n=1,  # Number of responses to generate
                stop=None  # No specific stopping condition
            )

            # Extract and return the translation from the response
            translation = response.choices[0].message.content.strip()
            if url:
                translation += f"\n{url}"
            return translation

        except Exception as e:
            self.logger.error("GPT Exception: {}".format(e))
            return None
