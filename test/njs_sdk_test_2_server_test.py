import unittest
import os
import json
import time
 
from os import environ
from configparser import ConfigParser
from pprint import pprint

from njs_sdk_test_2.njs_sdk_test_2Impl import njs_sdk_test_2


class njs_sdk_test_2Test(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        token = environ.get('KB_AUTH_TOKEN', None)
        cls.ctx = {'token': token, 'provenance': [{'service': 'njs_sdk_test_2',
            'method': 'please_never_use_it_in_production', 'method_params': []}],
            'authenticated': 1}
        config_file = environ.get('KB_DEPLOYMENT_CONFIG', None)
        cls.cfg = {}
        config = ConfigParser()
        config.read(config_file)
        for nameval in config.items('njs_sdk_test_2'):
            cls.cfg[nameval[0]] = nameval[1]
        cls.wsURL = cls.cfg['workspace-url']
        cls.serviceImpl = njs_sdk_test_2(cls.cfg)

    def getImpl(self):
        return self.__class__.serviceImpl

    def getContext(self):
        return self.__class__.ctx

    def test_thingy(self):
        print("This is a test repo, dummy.")
