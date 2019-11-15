from django.test import TestCase, Client
from mock import patch
from rest_framework.test import APIClient
from rest_framework.test import APIRequestFactory
from rest_framework.test import APITestCase
from rest_framework import status
import core.utils
from .models import *
from .views import *
from .utils import *


class ShareTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        Miner.objects.create(public_key="2", nick_name="Parsa")

    @patch('core.utils.prop')
    def test_prop_call(self, mocked_call_prop):
        mocked_call_prop.return_value = None
        core.utils.prop(None)
        data = {'share': '1',
                'miner': '1',
                'nonce': '1',
                'status': '2'}
        response = self.client.post('/shares/', data, format='json')
        self.assertTrue(mocked_call_prop.isCalled())

    @patch('core.utils.prop')
    def test_prop_not_call(self, mocked_not_call_prop):
        mocked_not_call_prop.return_value = None
        core.utils.prop(None)
        data = {'share': '1',
                'miner': '1',
                'nonce': '1',
                'status': '2'}
        response = self.client.post('/shares/', data, format='json')
        self.assertFalse(mocked_not_call_prop.isCalled())

