from seleniumbase import BaseCase

import os

BaseCase.main(__name__, __file__)

USERNAME = os.environ.get("USERNAME")
PASSWORD = os.environ.get("PASSWORD")
SITE_ID = os.environ.get("SITE_ID")
WEB_VERSION = os.environ.get("WEB_VERSION")

class RecorderTest(BaseCase):
    def test_recording(self):
        self.open("https://enlighten.enphaseenergy.com/")
        self.type("input#user_email", USERNAME)
        self.type("input#user_password", PASSWORD)
        self.click("input#submit")
        self.open_if_not_url(f"https://enlighten.enphaseenergy.com/web/{SITE_ID}?v={WEB_VERSION}")
        self.click("div#browser_menu span svg")
        self.click("div.header-menu-list div:nth-of-type(3) div")
        self.click("div#BprofileMenu div div:nth-of-type(2) div:nth-of-type(2)")
        self.switch_to_frame('iframe[title="battery module"]')
        self.click("div#sp-profile > div:nth-of-type(2)")
        self.click('button:contains("Edit")')
        self.click("div.bp__system-profile--card > section > div > div:nth-of-type(3) > div > div")
        self.click('button:contains("Apply")')
        self.click("div#sp-profile > div:nth-of-type(2)")
