import json
import os
import random
import string
import uuid
from datetime import timedelta, datetime
from pydoc import locate
from urllib.parse import urlparse, urljoin

from django.db.models import Sum, Max
from django.test import TestCase, Client, TransactionTestCase, override_settings
from django.utils import timezone
from mock import patch, call
from rest_framework import status
from django.conf import settings

from core.models import CONFIGURATION_KEY_CHOICE, AggregateShare, Share, Balance, Miner, Configuration, \
    CONFIGURATION_DEFAULT_KEY_VALUE, CONFIGURATION_KEY_TO_TYPE, Address
from core.serializers import AggregateShareSerializer, BalanceSerializer, ShareSerializer
from core.tasks import immature_to_mature, periodic_withdrawal, aggregate, generate_and_send_transaction
from core.utils import RewardAlgorithm, compute_hash_rate, get_miner_payment_address


def random_string(length=10):
    """Generate a random string of fixed length """
    letters = string.ascii_lowercase + string.ascii_uppercase + string.digits
    return ''.join(random.choice(letters) for i in range(length))


class ShareTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        Miner.objects.create(public_key="2", nick_name="Parsa")
        self.addresses = {
            'miner_address': random_string(),
            'lock_address': random_string(),
            'withdraw_address': random_string()
        }

    @patch('core.utils.RewardAlgorithm.get_instance')
    def test_prop_call(self, mocked_call_prop):
        mocked_call_prop.return_value = None
        data = {'share': '1',
                'miner': '1',
                'nonce': '1',
                'status': '2',
                'difficulty': 123456}
        self.client.post('/shares/', data, format='json')
        self.assertTrue(mocked_call_prop.isCalled())

    @patch('core.utils.RewardAlgorithm.get_instance')
    def test_prop_not_call(self, mocked_not_call_prop):
        mocked_not_call_prop.return_value = None
        data = {'share': '1',
                'miner': '1',
                'nonce': '1',
                'status': '2',
                'difficulty': 123456}
        self.client.post('/shares/', data, format='json')
        self.assertFalse(mocked_not_call_prop.called)

    def test_solved_share_without_transaction_id(self):
        """
        test if a solution submitted without transaction id no solution must store in database
        :return:
        """
        share = uuid.uuid4().hex
        data = {'share': share,
                'miner': '1',
                'nonce': '1',
                'status': '1',
                'difficulty': 123456}
        data.update(self.addresses)
        self.client.post('/shares/', data, format='json')
        self.assertFalse(Share.objects.filter(share=share).exists())

    def test_solved_share_without_block_height(self):
        """
        test if a solution submitted without block height no solution must store in database
        :return:
        """
        share = uuid.uuid4().hex
        data = {'share': share,
                'miner': '1',
                'nonce': '1',
                "transaction_id": "this is a transaction id",
                'status': '1',
                'difficulty': 123456}
        data.update(self.addresses)
        self.client.post('/shares/', data, format='json')
        self.assertFalse(Share.objects.filter(share=share).exists())

    def test_solved_share(self):
        """
        test if a solution submitted must store in database
        :return:
        """
        share = uuid.uuid4().hex
        data = {'share': share,
                'miner': '1',
                'nonce': '1',
                "transaction_id": "this is a transaction id",
                "block_height": 40404,
                'status': 'solved',
                'difficulty': 123456}
        data.update(self.addresses)
        self.client.post('/shares/', data, format='json')
        self.assertTrue(Share.objects.filter(share=share).exists())

    def test_validate_unsolved_share_store_addresses(self):
        """
        test if a non-solution submitted share must store with None in transaction_id and block_height
        3 address must be generated for miner
        """
        share = uuid.uuid4().hex
        data = {'share': share,
                'miner': '1',
                'nonce': '1',
                "transaction_id": "this is a transaction id",
                "block_height": 40404,
                'status': 'valid',
                'difficulty': 123456}
        data.update(self.addresses)
        self.client.post('/shares/', data, format='json')
        self.assertEqual(Share.objects.filter(share=share).count(), 1)
        transaction = Share.objects.filter(share=share).first()
        self.assertIsNone(transaction.transaction_id)
        self.assertIsNone(transaction.block_height)
        self.assertEqual(Address.objects.filter(address_miner__public_key='1', address=self.addresses['miner_address'],
                                                category='miner').count(), 1)
        self.assertEqual(Address.objects.filter(address_miner__public_key='1', address=self.addresses['lock_address'],
                                                category='lock').count(), 1)
        self.assertEqual(
            Address.objects.filter(address_miner__public_key='1', address=self.addresses['withdraw_address'],
                                   category='withdraw').count(), 1)

    def test_validate_unsolved_share_update_last_used(self):
        """
        test if a non-solution submitted share must store with None in transaction_id and block_height
        addresses are present, last_used field must be updated
        """
        miner_last_used = Address.objects.create(address_miner=Miner.objects.get(public_key='2'),
                                                 address=self.addresses['miner_address'], category='miner').last_used
        lock_last_used = Address.objects.create(address_miner=Miner.objects.get(public_key='2'),
                                                address=self.addresses['lock_address'], category='lock').last_used
        withdraw_last_used = Address.objects.create(address_miner=Miner.objects.get(public_key='2'),
                                                    address=self.addresses['withdraw_address'],
                                                    category='withdraw').last_used
        share = uuid.uuid4().hex
        data = {'share': share,
                'miner': '2',
                'nonce': '1',
                "transaction_id": "this is a transaction id",
                "block_height": 40404,
                'status': 'valid',
                'difficulty': 123456}
        data.update(self.addresses)
        self.client.post('/shares/', data, format='json')
        self.assertEqual(Share.objects.filter(share=share).count(), 1)
        transaction = Share.objects.filter(share=share).first()
        self.assertIsNone(transaction.transaction_id)
        self.assertIsNone(transaction.block_height)
        self.assertEqual(Address.objects.filter(address_miner__public_key='2', address=self.addresses['miner_address'],
                                                category='miner').count(), 1)
        self.assertEqual(Address.objects.filter(address_miner__public_key='2', address=self.addresses['lock_address'],
                                                category='lock').count(), 1)
        self.assertEqual(
            Address.objects.filter(address_miner__public_key='2', address=self.addresses['withdraw_address'],
                                   category='withdraw').count(), 1)
        self.assertTrue(Address.objects.filter(address_miner__public_key='2', address=self.addresses['miner_address'],
                                               category='miner').first().last_used > miner_last_used)
        self.assertTrue(Address.objects.filter(address_miner__public_key='2', address=self.addresses['lock_address'],
                                               category='lock').first().last_used > lock_last_used)
        self.assertTrue(
            Address.objects.filter(address_miner__public_key='2', address=self.addresses['withdraw_address'],
                                   category='withdraw').first().last_used > withdraw_last_used)

    def tearDown(self):
        Address.objects.all().delete()


class PropFunctionTest(TestCase):
    """
    Test class for prop function
    In all the test functions we assume that 'MAX_REWARD' is 35erg and 'TOTAL_REWARD' is 65erg.
    So in other situations the results may not be valid.
    """

    def setUp(self):
        """
        create 5 miners and 33 shares.
        share indexes [14, 34, 35] are solved (indexes are from 0) odd indexes are invalid other are valid
        setUp function to create 5 miners for testing prop function
        :return:
        """
        Configuration.objects.create(key='REWARD_ALGORITHM', value='Prop')
        Configuration.objects.create(key='TOTAL_REWARD', value=str(int(67.5e9)))
        Configuration.objects.create(key='FEE_FACTOR', value='0')
        Configuration.objects.create(key='REWARD_FACTOR', value=str(65 / 67.5))
        # create miners lists
        miners = [Miner.objects.create(nick_name="miner %d" % i, public_key=str(i)) for i in range(3)]
        # create shares list
        shares = [Share.objects.create(
            share=str(i),
            miner=miners[i % 3],
            status="solved" if i in [14, 34, 35] else "valid" if i % 2 == 0 else "invalid",
            difficulty=1000
        ) for i in range(36)]
        # set create date for each shares to make them a sequence valid
        start_date = timezone.now() + timedelta(seconds=-100)
        for share in shares:
            share.created_at = start_date
            share.save()
            start_date += timedelta(seconds=1)
        self.miners = miners
        self.shares = shares
        self.prop = RewardAlgorithm.get_instance().perform_logic

    def test_prop_with_0_solved_share(self):
        """
        In this scenario we test the functionality of prop function when there isn't any 'solved' share in the database.
        We have 5 miners and 10 shares which are not 'solved'.
        Then we call 'prop' function for one of the shares mentioned above and
        we expect it to not exist any balance object corresponding to that 'not solved' input share.
        :return:
        """
        # call prop function for an invalid (not solved) share, 8th for example
        share = self.shares[12]
        self.prop(share)
        self.assertEqual(Balance.objects.filter(share=share).count(), 0)

    def get_share_balance(self, sh):
        return dict(Balance.objects.filter(share=sh).values_list('miner__public_key').annotate(Sum('balance')))

    def test_prop_with_first_solved_share(self):
        """
        in this scenario we call prop function with first solved share in database.
        we generate 15 share 7 are invalid 7 are valid and one is solved

        :return:
        """
        share = self.shares[14]
        self.prop(share)
        balances = self.get_share_balance(share)
        self.assertEqual(balances, {'0': int(24.375e9), '1': int(16.25e9), '2': int(24.375e9)})

    def test_prop_between_two_solved_shares(self):
        """
        this function check when we have two solved share and some valid share between them.
        in this case we have 9 valid share 9 invalid share and one solved share.
        :return:
        """
        share = self.shares[34]
        self.prop(share)
        balances = self.get_share_balance(share)
        self.assertEqual(balances, {'0': int(19.5e9), '1': int(26.0e9), '2': int(19.5e9)})

    def test_prop_with_with_no_valid_share(self):
        """
        in this case we test when no valid share between solved shares
        in this case we only have one share and reward must be minimum of MAX_REWARD and TOTAL_REWARD
        :return:
        """
        share = self.shares[35]
        self.prop(share)
        balances = self.get_share_balance(share)
        reward_value = min(Configuration.objects.MAX_REWARD, Configuration.objects.TOTAL_REWARD)
        self.assertEqual(balances, {'2': float(reward_value)})

    def test_prop_called_multiple(self):
        """
        in this case we call prop function 5 times. after each call balance for each miner must be same as expected
        :return:
        """
        share = self.shares[34]
        for i in range(5):
            self.prop(share)
            balances = self.get_share_balance(share)
            self.assertEqual(balances, {'0': int(19.5e9), '1': int(26.0e9), '2': int(19.5e9)})

    def test_prop_with_first_solved_share_with_fee(self):
        """
        in this scenario we call prop function with first solved share in database.
        we generate 15 share 7 are invalid 7 are valid and one is solved

        :return:
        """
        reward = RewardAlgorithm.get_instance().get_reward_to_share()
        Configuration.objects.create(key='FEE_FACTOR', value=str(10e9 / reward))
        share = self.shares[14]
        self.prop(share)
        balances = self.get_share_balance(share)
        self.assertEqual(balances, {'0': int(20.625e9), '1': int(13.75e9), '2': int(20.625e9)})

    def test_prop_between_two_solved_shares_with_fee(self):
        """
        this function check when we have two solved share and some valid share between them.
        in this case we have 9 valid share 9 invalid share and one solved share.
        :return:
        """
        reward = RewardAlgorithm.get_instance().get_reward_to_share()
        Configuration.objects.create(key='FEE_FACTOR', value=str(10e9 / reward))
        share = self.shares[34]
        self.prop(share)
        balances = self.get_share_balance(share)
        self.assertEqual(balances, {'0': int(16.5e9), '1': int(22.0e9), '2': int(16.5e9)})

    def test_prop_with_with_no_valid_share_with_fee(self):
        """
        in this case we test when no valid share between solved shares
        in this case we only have one share and reward must be minimum of MAX_REWARD and TOTAL_REWARD
        :return:
        """
        reward = RewardAlgorithm.get_instance().get_reward_to_share()
        Configuration.objects.create(key='FEE_FACTOR', value=str(10e9 / reward))
        share = self.shares[35]
        self.prop(share)
        balances = self.get_share_balance(share)
        reward_value = min(Configuration.objects.MAX_REWARD,
                           Configuration.objects.TOTAL_REWARD - Configuration.objects.FEE_FACTOR)
        self.assertEqual(balances, {'2': reward_value})

    def test_prop_called_multiple_with_fee(self):
        """
        in this case we call prop function 5 times. after each call balance for each miner must be same as expected
        :return:
        """
        reward = RewardAlgorithm.get_instance().get_reward_to_share()
        Configuration.objects.create(key='FEE_FACTOR', value=str(10e9 / reward))
        share = self.shares[34]
        for i in range(5):
            self.prop(share)
            balances = self.get_share_balance(share)
            self.assertEqual(balances, {'0': int(16.5e9), '1': int(22.0e9), '2': int(16.5e9)})

    def test_prop_with_first_solved_share_different_difficulty(self):
        """
        same scenario as first_solved_share but with different difficulties
        """
        share = self.shares[14]
        miner = Miner.objects.get(public_key='0')
        Share.objects.filter(miner=miner).delete()
        others_difficulty = Share.objects.filter(created_at__lte=share.created_at, miner__public_key__in=['1', '2'],
                                                 status__in=['solved', 'valid']) \
            .aggregate(Sum('difficulty'))
        others_difficulty = others_difficulty['difficulty__sum']
        cur = Share.objects.create(miner=miner, status='valid', difficulty=others_difficulty)
        cur.created_at = share.created_at - timedelta(seconds=1)
        cur.save()

        self.prop(share)
        balances = self.get_share_balance(share)
        self.assertEqual(balances, {'0': int(65e9 / 2), '1': int(13.0e9), '2': int(19.5e9)})

    def test_prop_between_two_solved_shares_different_difficulty(self):
        """
        same scenario as between_two_solved_shares but with different difficulties
        """
        Configuration.objects.create(key='MAX_REWARD', value=int(65e9))
        share = self.shares[34]
        miner = Miner.objects.get(public_key='1')
        Share.objects.filter(miner=miner).update(difficulty=0)
        others_difficulty = Share.objects.filter(created_at__lte=share.created_at,
                                                 created_at__gt=self.shares[14].created_at,
                                                 miner__public_key__in=['0', '2'], status__in=['solved', 'valid']) \
            .aggregate(Sum('difficulty'))
        others_difficulty = others_difficulty['difficulty__sum']
        cur = Share.objects.create(miner=miner, status='valid', difficulty=others_difficulty * 2)
        cur.created_at = share.created_at - timedelta(seconds=1)
        cur.save()
        self.prop(share)
        balances = self.get_share_balance(share)
        val = 65. / 3
        self.assertEqual(balances, {'0': int(val * 0.5e9), '1': int(val * 2e9), '2': int(val * 0.5e9)})

    def tearDown(self):
        """
        tearDown function to delete miners created in setUp function
        :return:
        """
        Configuration.objects.all().delete()
        # delete all miners objects. all related objects are deleted
        for miner in self.miners:
            miner.delete()


class DashboardTestCase(TestCase):
    def setUp(self) -> None:
        self.client = Client()

        # Create two miner; abc and xyz
        miners = [
            Miner.objects.create(public_key='abc', nick_name='ABC'),
            Miner.objects.create(public_key='xyz', nick_name='XYZ')
        ]

        # Set current time
        self.now = datetime.now()

        # Create shares
        shares = [
            Share.objects.create(share=random_string(), miner=miners[0], status="solved",
                                 created_at=self.now, difficulty=1000),
            Share.objects.create(share=random_string(), miner=miners[0], status="valid",
                                 created_at=self.now + timedelta(minutes=1), difficulty=1000),
            Share.objects.create(share=random_string(), miner=miners[0], status="valid",
                                 created_at=self.now + timedelta(minutes=2), difficulty=1000),
            Share.objects.create(share=random_string(), miner=miners[0], status="invalid",
                                 created_at=self.now + timedelta(minutes=3), difficulty=1000),
            Share.objects.create(share=random_string(), miner=miners[1], status="valid",
                                 created_at=self.now + timedelta(minutes=4), difficulty=1000),
            Share.objects.create(share=random_string(), miner=miners[1], status="valid",
                                 created_at=self.now + timedelta(minutes=5), difficulty=1000),
        ]

        # Create balances
        balances = [
            Balance.objects.create(miner=miners[0], share=shares[0], balance=100, status="immature"),
            Balance.objects.create(miner=miners[0], share=shares[1], balance=200, status="immature"),
            Balance.objects.create(miner=miners[0], share=shares[2], balance=300, status="mature"),
            Balance.objects.create(miner=miners[0], share=shares[3], balance=400, status="withdraw"),
            Balance.objects.create(miner=miners[1], share=shares[4], balance=500, status="mature"),
            Balance.objects.create(miner=miners[1], share=shares[5], balance=600, status="mature"),
        ]

    def test_get_all(self):
        """
        Purpose: Check if Dashboard view returns the correct info for all miners.
        Prerequisites: Nothing
        Scenario: Sends a request to /dashboard/ and checks if response is correct
        Test Conditions:
        * status is 200
        * Content-Type is application/json
        * Content is :
        {
            'round_valid_shares': 4,
            'round_invalid_shares': 1,
            'timestamp': self.now.strftime('%Y-%m-%d %H:%M:%S'),
            'hash_rate': 1
            'users': {
                'abc': {
                    "round_valid_shares": 2,
                    "round_invalid_shares": 0,
                    "immature": 300.0,
                    "mature": 300.0,
                    "withdraw": 400.0
                },
                'xyz': {
                    "round_valid_shares": 2,
                    "round_invalid_shares": 1,
                    "immature": 0,
                    "mature": 1100.0,
                    "withdraw": 0
                }
            }
        }
        """
        response = self.client.get('/dashboard/').json()
        self.assertDictEqual(response, {
            'round_valid_shares': 4,
            'round_invalid_shares': 1,
            'timestamp': self.now.strftime('%Y-%m-%d %H:%M:%S'),
            'hash_rate': 1,
            'users': {
                'abc': {
                    "round_valid_shares": 2,
                    "round_invalid_shares": 1,
                    "immature": 300.0,
                    "mature": 300.0,
                    "withdraw": 400.0
                },
                'xyz': {
                    "round_valid_shares": 2,
                    "round_invalid_shares": 0,
                    "immature": 0,
                    "mature": 1100.0,
                    "withdraw": 0
                }
            }
        })

    def test_get_specified_pk(self):
        """
        Purpose: Check if Dashboard view returns the correct info for the specified miner (abc)
        Prerequisites: Nothing
        Scenario: Sends a request to /dashboard/abc and checks if response is correct for miner 'abc'
        Test Conditions:
        * status is 200
        * Content-Type is application/json
        * Content is :
        {
            'round_shares': 4,
            'timestamp': self.now.strftime('%Y-%m-%d %H:%M:%S'),
            'users': {
                'abc': {
                    "round_shares": 2,
                    "immature": 300.0,
                    "mature": 300.0,
                    "withdraw": 400.0
                }
            }
        }
        """
        content = self.client.get('/dashboard/abc/')
        response = content.json()
        self.assertDictEqual(response, {
            'round_valid_shares': 4,
            'round_invalid_shares': 1,
            'timestamp': self.now.strftime('%Y-%m-%d %H:%M:%S'),
            'hash_rate': 1,
            'users': {
                'abc': {
                    "round_valid_shares": 2,
                    "round_invalid_shares": 1,
                    "immature": 300.0,
                    "mature": 300.0,
                    "withdraw": 400.0
                }
            }
        })


class ConfigurationAPITest(TestCase):
    """
    Test class for Configuration API
    Test scenarios:
    1) using http 'get' method to retrieve a list of existing configurations
    2) using http 'post' method to create a new configuration
    3) using http 'post' method to update an existing configuration
    4) type conversion test, after retrieving the value, it must be converted to valid value_type
    """

    def setUp(self):
        """
        setUp function for 'ConfigurationAPITest' class do nothing
        :return:
        """
        pass

    def test_configuration_api_get_method_list(self):
        """
        In this scenario we want to test the functionality of Configuration API when
        it is called by a http 'get' method.
        For the above purpose first we create some configurations in the database and then
        we send a http 'get' method to retrieve a list of them.
        We expect that the status code of response be '200 ok' and
        the json format of response be as below (a list of dictionaries).
        :return:
        """
        # retrieve all possible keys for KEY_CHOICES
        keys = [key for (key, temp) in CONFIGURATION_KEY_CHOICE]
        # define expected response as an empty list
        expected_response = dict(CONFIGURATION_DEFAULT_KEY_VALUE)
        # create a json like dictionary for any key in keys
        for key in keys:
            Configuration.objects.create(key=key, value='1')
            val_type = CONFIGURATION_KEY_TO_TYPE[key]
            expected_response[key] = locate(val_type)('1')
        # send a http 'get' request to the configuration endpoint
        response = self.client.get('/conf/')
        # check the status of the response
        self.assertEqual(response.status_code, 200)
        # check the content of the response
        self.assertEqual(response.json(), expected_response)

    def test_configuration_api_post_method_create(self):
        """
        In this scenario we want to test the functionality of Configuration API when
        it is called by a http 'post' method to create a new configuration
        For this purpose we send a http 'post' method to create a new configuration with a non-existing key in database.
        We expect that the status code of response be '201' and
        the new configuration object exists in database with a value as below.
        :return:
        """
        # retrieve all possible keys for KEY_CHOICES
        keys = [key for (key, temp) in CONFIGURATION_KEY_CHOICE]
        # send http 'post' request to the configuration endpoint and validate the result
        for key in keys:
            # send http 'post' request to the endpoint
            response = self.client.post('/conf/', {'key': key, 'value': '1'})
            # check the status of the response
            self.assertEqual(response.status_code, 201)
            # retrieve the new created configuration from database
            configuration = Configuration.objects.get(key=key)
            # check whether the above object is created and saved to database or not
            self.assertIsNotNone(configuration)
            # check the value of the new created object
            self.assertEqual(configuration.value, '1')

    def test_configuration_api_post_method_update(self):
        """
        In this scenario we want to test the functionality of Configuration API when
        it is called by a http 'post' method to update an existing configuration.
        For this purpose we send a http 'post' request for an existing configuration object in database.
        We expect that the status code of response be '201' and
        the new configuration object be updated in database with a new value as below.
        :return:
        """
        # retrieve all possible keys for KEY_CHOICES
        keys = [key for (key, temp) in CONFIGURATION_KEY_CHOICE]
        # send http 'post' request to the configuration endpoint and validate the result
        for key in keys:
            # create a configuration object to check the functionality of 'post' method
            Configuration.objects.create(key=key, value='1')
            # send http 'post' request to the endpoint
            response = self.client.post('/conf/', {'key': key, 'value': '2'})
            # check the status of the response
            self.assertEqual(response.status_code, 201)
            # retrieve the new created configuration from database
            configurations = Configuration.objects.filter(key=key)
            # check whether the above object is created and saved to database or not
            self.assertEqual(configurations.count(), 1)
            # check the value of the new created object
            self.assertEqual(configurations.first().value, '2')

    def test_value_type_conversion(self):
        keys = [key for (key, temp) in CONFIGURATION_KEY_CHOICE]
        for i, key in enumerate(keys):
            Configuration.objects.create(key=key, value='1')

        # checking validity of conversion
        for i, key in enumerate(keys):
            val = Configuration.objects.__getattr__(key)
            val_type = CONFIGURATION_KEY_TO_TYPE[key]

            self.assertEqual(locate(val_type), type(val))

    def test_available_config_restore(self):
        """
        check manager model of configuration to get expected value when exists
        :return:
        """
        for key, label in CONFIGURATION_KEY_CHOICE:
            Configuration.objects.create(key=key, value='100000')
        for key, label in CONFIGURATION_KEY_CHOICE:
            val_type = CONFIGURATION_KEY_TO_TYPE[key]
            self.assertEqual(getattr(Configuration.objects, key), locate(val_type)('100000'))

    def test_default_config_restore(self):
        """
        check manager model of configuration to get default value when not exists in model
        :return:
        """
        Configuration.objects.all().delete()
        for key, label in CONFIGURATION_KEY_CHOICE:
            self.assertEqual(getattr(Configuration.objects, key), CONFIGURATION_DEFAULT_KEY_VALUE.get(key))

    def test_invalid_configuration_format(self):
        """
        set configuration for key TOTAL_REWARD with string value.
        then get this configuration must return DEFAULT value of this configuration
        :return:
        """
        Configuration.objects.create(key="TOTAL_REWARD", value='teststr')
        self.assertEqual(Configuration.objects.TOTAL_REWARD, CONFIGURATION_DEFAULT_KEY_VALUE["TOTAL_REWARD"])

    def tearDown(self):
        """
        tearDown function to delete all configuration objects
        :return:
        """
        # delete all configuration objects
        Configuration.objects.all().delete()


class PPLNSFunctionTest(TestCase):
    """
    Test class for 'PPLNS' function
    In all the test functions we assume that 'MAX_REWARD' is 35erg and
    'TOTAL_REWARD' is 65erg and 'N' is 5.
    So in other situations the results may not be valid.
    """

    def setUp(self):
        """
        setUp function to create 3 miners and 36 test
        :return:
        """
        Configuration.objects.create(key='REWARD_ALGORITHM', value='PPLNS')
        Configuration.objects.create(key='TOTAL_REWARD', value=str(int(67.5e9)))
        Configuration.objects.create(key='FEE_FACTOR', value='0')
        Configuration.objects.create(key='REWARD_FACTOR', value=str(65 / 67.5))
        self.PPLNS = RewardAlgorithm.get_instance().perform_logic
        # create miners lists
        miners = [Miner.objects.create(nick_name="miner %d" % i, public_key=str(i)) for i in range(3)]
        # create shares list
        shares = [Share.objects.create(
            share=str(i),
            miner=miners[int(i / 2) % 3],
            status="solved" if i in [14, 44, 45] else "valid" if i % 2 == 0 else "invalid",
            difficulty=1000
        ) for i in range(46)]
        # set create date for each shares to make them a sequence valid
        start_date = timezone.now() + timedelta(seconds=-100)
        for share in shares:
            share.created_at = start_date
            share.save()
            start_date += timedelta(seconds=1)
        # set pplns prev count to 10
        Configuration.objects.create(key="PPLNS_N", value='10')
        self.miners = miners
        self.shares = shares

    def get_share_balance(self, sh):
        return dict(Balance.objects.filter(share=sh).values_list('miner__public_key').annotate(Sum('balance')))

    def test_pplns_with_invalid_share(self):
        """
        in this scenario we pass not solved share and function must do nothing
        :return:
        """
        share = self.shares[13]
        self.PPLNS(share)
        self.assertEqual(Balance.objects.filter(share=share).count(), 0)

    def test_pplns_with_lower_amount_of_shares(self):
        """
        in this case we have 8 shares and pplns must work with this amount of shares
        :return:
        """
        share = self.shares[14]
        self.PPLNS(share)
        balances = self.get_share_balance(share)
        self.assertEqual(balances, {'0': int(24.375e9), '1': int(24.375e9), '2': int(16.25e9)})

    def test_pplns_with_more_than_n_shares(self):
        """
        this function check when we have two solved share and some valid share between them.
        in this case we have 9 valid share 9 invalid share and one solved share.
        :return:
        """
        share = self.shares[44]
        self.PPLNS(share)
        balances = self.get_share_balance(share)
        self.assertEqual(balances, {'0': int(19.5e9), '1': int(26.0e9), '2': int(19.5e9)})

    def test_pplns_multiple(self):
        """
        in this case we call pplns function 5 times. after each call balance for each miner must be same as expected
        :return:
        """
        share = self.shares[44]
        for i in range(5):
            self.PPLNS(share)
            balances = self.get_share_balance(share)
            self.assertEqual(balances, {'0': int(19.5e9), '1': int(26.0e9), '2': int(19.5e9)})

    def test_pplns_with_lower_amount_of_shares_with_fee(self):
        """
        in this case we have 8 shares and pplns must work with this amount of shares with fee: 10
        :return:
        """
        share = self.shares[14]
        reward = RewardAlgorithm.get_instance().get_reward_to_share()
        Configuration.objects.create(key='FEE_FACTOR', value=str(10e9 / reward))
        self.PPLNS(share)
        balances = self.get_share_balance(share)
        self.assertEqual(balances, {'0': int(20.625e9), '1': int(20.625e9), '2': int(13.75e9)})

    def test_pplns_with_more_than_n_shares_with_fee(self):
        """
        this function check when we have two solved share and some valid share between them.
        in this case we have 9 valid share 9 invalid share and one solved share.
        :return:
        """
        share = self.shares[44]
        reward = RewardAlgorithm.get_instance().get_reward_to_share()
        Configuration.objects.create(key='FEE_FACTOR', value=str(10e9 / reward))
        self.PPLNS(share)
        balances = self.get_share_balance(share)
        self.assertEqual(balances, {'0': int(16.5e9), '1': int(22.0e9), '2': int(16.5e9)})

    def test_pplns_multiple_with_fee(self):
        """
        in this case we call pplns function 5 times. after each call balance for each miner must be same as expected
        :return:
        """
        share = self.shares[44]
        reward = RewardAlgorithm.get_instance().get_reward_to_share()
        Configuration.objects.create(key='FEE_FACTOR', value=str(10e9 / reward))
        for i in range(5):
            self.PPLNS(share)
            balances = self.get_share_balance(share)
            self.assertEqual(balances, {'0': int(16.5e9), '1': int(22.0e9), '2': int(16.5e9)})

    def test_pplns_with_lower_amount_of_shares_different_difficulty(self):
        """
        same scenario as with_lower_amount_of_shares but with different difficulties
        :return:
        """
        share = self.shares[14]
        miner = Miner.objects.get(public_key='2')
        Share.objects.filter(miner=miner).delete()
        others_difficulty = Share.objects.filter(created_at__lte=share.created_at, miner__public_key__in=['0', '1'],
                                                 status__in=['solved', 'valid']) \
            .aggregate(Sum('difficulty'))
        others_difficulty = others_difficulty['difficulty__sum']
        cur = Share.objects.create(miner=miner, status='valid', difficulty=others_difficulty)
        cur.created_at = share.created_at - timedelta(seconds=1)
        cur.save()

        self.PPLNS(share)
        balances = self.get_share_balance(share)
        val = 65. / 4
        self.assertEqual(balances, {'0': int(val * 1e9), '1': int(val * 1e9), '2': int(val * 2e9)})

    def tearDown(self):
        """
        tearDown function to delete miners created in setUp function
        :return:
        """
        # delete all Balance objects
        Balance.objects.all().delete()
        # delete all Share objects
        Share.objects.all().delete()
        # delete all Miner objects
        Miner.objects.all().delete()
        # delete all configurations
        Configuration.objects.all().delete()


class ComputeHashRateTest(TransactionTestCase):
    """
    For test function compute_hash_rate for calculate
     hash_rate for one public_key or all public_key between two timestamp.

    """
    reset_sequences = True

    def test_compute_hash_rate(self):
        """
        In this function create 2 miner and 4 share for calculate hash rate between two timestamp.
        Pass two time_stamp to function compute_hash_rate and get hash_rate between this time_stamps that are
         'valid' or 'solved'.
        :return:
        """
        # Create objects for test

        Miner.objects.create(nick_name="moein", public_key="12345678976543",
                             created_at=datetime(2019, 12, 22, 8, 33, 45, 395985),
                             updated_at=datetime(2019, 12, 22, 8, 33, 45, 395985))
        Miner.objects.create(nick_name="amir", public_key="869675768342",
                             created_at=datetime(2019, 12, 23, 8, 33, 45, 395985),
                             updated_at=datetime(2019, 12, 23, 8, 33, 45, 395985))
        share = Share.objects.create(share="12345", miner_id=1, block_height=23456,
                                     transaction_id="234567uhgt678", status="solved", difficulty=4253524523)
        share.created_at = "2019-12-22 14:18:57.395985+00"
        share.updated_at = "2019-12-22 14:18:57.395985+00"
        share.save()
        share = Share.objects.create(share="234567", miner_id=1, block_height=23456,
                                     transaction_id="234567uhgt678", status="valid", difficulty=4253524523)
        share.created_at = "2019-12-22 18:18:57.376576+00"
        share.updated_at = "2019-12-22 18:18:57.376576+00"
        share.save()
        share = Share.objects.create(share="8765678", miner_id=2, block_height=23456,
                                     transaction_id="234567uhgt678", status="solved", difficulty=4253524523)
        share.created_at = "2019-12-22 20:05:00.376576+00"
        share.updated_at = "2019-12-22 20:05:00.376576+00"
        share.save()
        share = Share.objects.create(share="345678", miner_id=2, block_height=23456,
                                     transaction_id="234567uhgt678", status="valid", difficulty=4253524523)
        share.created_at = "2019-12-22 20:00:00.376576+00"
        share.updated_at = "2019-12-22 20:00:00.376576+00"
        share.save()
        # Calculate hash rate
        miners = compute_hash_rate(datetime(2019, 12, 22, 20, 5, 00, 370000, tzinfo=timezone.utc),
                                   datetime(2019, 12, 24, 6, 39, 28, 887529, tzinfo=timezone.utc))

        # check the function compute_hash_rate
        self.assertEqual(miners, {'869675768342': {'hash_rate': 34174},
                                  'total_hash_rate': 34174})


class BlockTestCase(TestCase):
    """
    Test for different modes call api /blocks
    Api using limit and offset, period time, sortBy and sortDirection and check that this block mined by miner of pool
     if mined there was flag "inpool": True
    """

    def mocked_get_request(urls, params=None, **kwargs):
        """
        mock requests with method get for urls 'blocks'
        """

        class MockResponse:
            def __init__(self, json_data):
                self.json_data = json_data

            def json(self):
                return self.json_data

        with open("core/data_mock_testing/test_get_blocks.json", "r") as read_file:
            response = json.load(read_file)
        return MockResponse(response)

    def setUp(self):
        """
        Create a miner and after that create 3 objects => solved = 2 and valid = 1
        :return:
        """
        # Create a miner in data_base
        miner = Miner.objects.create(nick_name="test", public_key="1245",
                                     created_at=datetime(2019, 12, 20, 8, 33, 45, 395985),
                                     updated_at=datetime(2019, 12, 20, 8, 33, 45, 395985))

        # Create 3 objects => solved = 2 and valid = 1
        i = 2
        while i <= 4:
            if i == 4:
                share = Share.objects.create(share=str(i), miner=miner, block_height=i, transaction_id=str(i),
                                             status="valid", difficulty=i)
            else:
                share = Share.objects.create(share=str(i), miner=miner, block_height=i, transaction_id=str(i),
                                             status="solved", difficulty=i)

            share.created_at = datetime(2020, 1, 1, 8 + i, 59, 20, 395985, tzinfo=timezone.utc)
            share.updated_at = datetime(2020, 1, 1, 8 + i, 59, 20, 395985, tzinfo=timezone.utc)
            share.save()
            i = i + 1

    @patch("requests.get", side_effect=mocked_get_request)
    def test_get_offset_limit(self, mocked):
        """
        Send a http 'get' request for get blocks with => page = 1 and size = 4 in this test, we must get 4 blocks and
         set the pool flag to True if it has been mined by the miner in the pool
        """

        # Send a http 'get' request for get blocks with limits => size = 30 and page = 1
        response = self.client.get('/blocks/?page=1&size=4')
        # check the status of the response
        self.assertEqual(response.status_code, 200)
        response = response.json()
        # check the content of the response
        # For check flag ' pool'
        blocks_pool = [3, 2]
        blocks_pool_result = []
        # For Check true block heights
        heights = [4, 3, 2, 1]
        heights_result = []
        for res in response['results']:
            heights_result.append(res['height'])
            if res['pool']:
                blocks_pool_result.append(res['height'])

        self.assertEqual(heights_result, heights)
        self.assertEqual(blocks_pool_result, blocks_pool)

    @patch("requests.get", side_effect=mocked_get_request)
    def test_pass_extra_queries(self, mocked):
        """
        call function with extra get arguments must cause pass arguments as get to api
        """

        # Send a http 'get' request for get blocks with sort according to height and Direction asc
        response = self.client.get('http://google.com/blocks/?sortBy=height&sortDirection=asc')
        # check the status of the response
        self.assertEqual(response.status_code, 200)
        # get passed url
        parsed_url = urlparse(mocked.call_args[0][0])
        # get passed params to url
        query = mocked.call_args[0][1] or {}
        if parsed_url.query:
            query.update(parsed_url.query)
        # query must contain only two keys
        self.assertEqual(sorted(list(query.keys())), ["limit", "offset", "sortBy", "sortDirection"])
        # sortBy parameter must contains only "height"
        sort_by = query.get("sortBy", [])
        if isinstance(sort_by, str):
            sort_by = [sort_by]
        self.assertEqual(sort_by, ["height"])
        # sortDirection parameter must contains only "asc"
        sort_by = query.get("sortDirection", [])
        if isinstance(sort_by, str):
            sort_by = [sort_by]
        self.assertEqual(sort_by, ["asc"])


def mocked_node_request_transaction_generate_test(*args, **kwargs):
    """
    mock requests with method post
    """
    url = args[0]

    if url == 'wallet/boxes/unspent':
        with open("core/data_mock_testing/test_boxes.json", "r") as read_file:
            return {
                'response': json.load(read_file),
                'status': 'success'
            }

    if 'utxo/byIdBinary/' in url:
        last_part = url.split('/')[-1]
        return {
            'response': {
                'boxId': last_part,
                'bytes': last_part
            },
            'status': 'success'
        }

    if url == 'wallet/transaction/send':
        data = str(kwargs['data'])
        if 'invalid_input' in data:
            return {
                'status': 'error'
            }

        return {
            'status': 'success'
        }

    return {
        'response': None,
        'status': 'error'
    }


@patch('core.tasks.node_request', side_effect=mocked_node_request_transaction_generate_test)
class TransactionGenerateTestCase(TestCase):
    """
    Test class for transaction generate and send method
    Balance statuses: 2: mature, 3: withdraw, 4: pending_withdrawal
    """

    def setUp(self):
        """
        creates necessary configuration and objects and a default output list
        :return:
        """
        # setting configuration
        Configuration.objects.create(key='MAX_NUMBER_OF_OUTPUTS', value='4')

        # creating 10 miners
        pks = [random_string() for i in range(10)]
        for pk in pks:
            Miner.objects.create(public_key=pk)

        # create output for each miner
        self.outputs = [(pk, int((i + 1) * 1e10)) for i, pk in enumerate(pks)]
        self.pending_balances = [Balance(miner=Miner.objects.get(public_key=x[0]), balance=-x[1], status="pending_withdrawal") for x in
                                 self.outputs]
        for pk, _ in self.outputs:
            Address.objects.create(address_miner=Miner.objects.get(public_key=pk), category='withdraw', address=pk)

    def test_generate_three_transactions_max_num_output_4(self, mocked_request):
        """
        calling the function with all outputs and MAX_NUMBER_OF_OUTPUT = 4
        must create 3 transactions and required balances
        """
        outputs = self.outputs[:]
        for i, _ in enumerate(outputs):
            self.pending_balances[i].save()
            outputs[i] = (outputs[i][0], outputs[i][1], self.pending_balances[i].pk)

        TRANSACTION_FEE = Configuration.objects.TRANSACTION_FEE
        generate_and_send_transaction(outputs)
        chunks = [outputs[i:i + 4] for i in range(0, len(outputs), 4)]
        reqs = [{
            'requests': [
                {
                    'address': pk,
                    'value': value
                } for pk, value, _ in chunk
            ],
            'fee': TRANSACTION_FEE,
            'inputsRaw': []
        } for chunk in chunks]

        reqs[0]['inputsRaw'] = ['a', 'b', 'c', 'd']
        reqs[1]['inputsRaw'] = ['e', 'f', 'g']
        reqs[2]['inputsRaw'] = ['h', 'i']
        mocked_request.assert_any_call('wallet/transaction/send', data=reqs[0], request_type='post')
        mocked_request.assert_any_call('wallet/transaction/send', data=reqs[1], request_type='post')
        mocked_request.assert_any_call('wallet/transaction/send', data=reqs[2], request_type='post')

        for pk, value in self.outputs:
            self.assertEqual(Balance.objects.filter(miner__public_key=pk, balance=-value, status="withdraw").count(), 1)

        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 0)

    def test_generate_one_transactions_max_num_output_4(self, mocked_request):
        """
        calling the function with 4 outputs and MAX_NUMBER_OF_OUTPUT = 4
        must create 1 transactions and required balances
        """
        outputs = self.outputs[0:4]
        for i, _ in enumerate(outputs):
            self.pending_balances[i].save()
            outputs[i] = (outputs[i][0], outputs[i][1], self.pending_balances[i].pk)

        TRANSACTION_FEE = Configuration.objects.TRANSACTION_FEE
        generate_and_send_transaction(outputs)
        chunks = [outputs[i:i + 4] for i in range(0, len(outputs), 4)]
        reqs = [{
            'requests': [
                {
                    'address': pk,
                    'value': value
                } for pk, value, _ in chunk
            ],
            'fee': TRANSACTION_FEE,
            'inputsRaw': []
        } for chunk in chunks]

        reqs[0]['inputsRaw'] = ['a', 'b', 'c', 'd']
        mocked_request.assert_any_call('wallet/transaction/send', data=reqs[0], request_type='post')

        for pk, value, _ in outputs:
            self.assertEqual(Balance.objects.filter(miner__public_key=pk, balance=-value, status="withdraw").count(), 1)

        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 0)

    def test_generate_three_transactions_max_num_output_20(self, mocked_request):
        """
        calling the function with all outputs and MAX_NUMBER_OF_OUTPUT = 20
        must create 1 transactions and required balances
        """
        outputs = self.outputs
        for i, _ in enumerate(outputs):
            self.pending_balances[i].save()
            outputs[i] = (outputs[i][0], outputs[i][1], self.pending_balances[i].pk)

        Configuration.objects.create(key='MAX_NUMBER_OF_OUTPUTS', value='20')
        TRANSACTION_FEE = Configuration.objects.TRANSACTION_FEE
        generate_and_send_transaction(outputs)
        reqs = {
            'requests': [
                {
                    'address': pk,
                    'value': value
                } for pk, value, _ in outputs
            ],
            'fee': TRANSACTION_FEE,
            'inputsRaw': [x for x in 'abcdefghi']
        }

        mocked_request.assert_any_call('wallet/transaction/send', data=reqs, request_type='post')

        for pk, value, _ in outputs:
            self.assertEqual(Balance.objects.filter(miner__public_key=pk, balance=-value, status="withdraw").count(), 1)

        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 0)

    def test_one_output_with_fee(self, mocked_request):
        """
        calling the function with one output and MAX_NUMBER_OF_OUTPUT = 10 and subtract_fee = true
        must create 1 transactions with subtracted value and required balances
        """
        outputs = self.outputs[9:]
        for i, _ in enumerate(outputs):
            self.pending_balances[i].save()
            outputs[i] = (outputs[i][0], outputs[i][1], self.pending_balances[i].pk)

        Configuration.objects.create(key='MAX_NUMBER_OF_OUTPUTS', value='10')
        TRANSACTION_FEE = Configuration.objects.TRANSACTION_FEE
        generate_and_send_transaction(outputs, subtract_fee=True)
        reqs = {
            'requests': [
                {
                    'address': pk,
                    'value': value - TRANSACTION_FEE
                } for pk, value, _ in outputs
            ],
            'fee': TRANSACTION_FEE,
            'inputsRaw': [x for x in 'abcd']
        }

        mocked_request.assert_any_call('wallet/transaction/send', data=reqs, request_type='post')

        for pk, value, _ in outputs:
            self.assertEqual(Balance.objects.filter(miner__public_key=pk, balance=-value, status="withdraw").count(), 1)

        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 0)

    def test_node_generate_and_send_request_error(self, mocked_request):
        """
        when node is not available for any reason or returns error then nothing must happen
        no balance must be created!
        """
        Configuration.objects.create(key='MAX_NUMBER_OF_OUTPUTS', value='10')
        outputs = self.outputs[:]
        miner = Miner.objects.create(public_key='invalid_input')
        Address.objects.create(address_miner=miner, category='withdraw', address='invalid_input')
        outputs[0] = ('invalid_input', int(1e10))

        for i, _ in enumerate(outputs):
            self.pending_balances[i].save()
            outputs[i] = (outputs[i][0], outputs[i][1], self.pending_balances[i].pk)

        generate_and_send_transaction(outputs)

        for pk, value, _ in outputs:
            self.assertEqual(Balance.objects.filter(miner__public_key=pk, balance=-value, status="withdraw").count(), 0)

        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 0)

    def test_generate_one_transactions_max_num_output_4_with_other_pending(self, mocked_request):
        """
        calling the function with 4 outputs and MAX_NUMBER_OF_OUTPUT = 4
        must create 1 transactions and required balances
        other pending_withdrawal balance is present, they must not be deleted
        """
        outputs = self.outputs[0:4]
        for i, _ in enumerate(outputs):
            self.pending_balances[i].save()
            outputs[i] = (outputs[i][0], outputs[i][1], self.pending_balances[i].pk)

        for pk, balance in self.outputs:
            miner = Miner.objects.get(public_key=pk)
            Balance.objects.create(miner=miner, balance=-balance / 1e10, status="pending_withdrawal")

        TRANSACTION_FEE = Configuration.objects.TRANSACTION_FEE
        generate_and_send_transaction(outputs)
        chunks = [outputs[i:i + 4] for i in range(0, len(outputs), 4)]
        reqs = [{
            'requests': [
                {
                    'address': pk,
                    'value': value
                } for pk, value, _ in chunk
            ],
            'fee': TRANSACTION_FEE,
            'inputsRaw': []
        } for chunk in chunks]

        reqs[0]['inputsRaw'] = ['a', 'b', 'c', 'd']
        mocked_request.assert_any_call('wallet/transaction/send', data=reqs[0], request_type='post')

        for pk, value, _ in outputs:
            self.assertEqual(Balance.objects.filter(miner__public_key=pk, balance=-value, status="withdraw").count(), 1)

        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), len(self.outputs))

    def test_generate_three_transactions_max_num_output_20_with_other_pending(self, mocked_request):
        """
        calling the function with all outputs and MAX_NUMBER_OF_OUTPUT = 20
        must create 1 transactions and required balances
        """
        outputs = self.outputs[:]
        for i, _ in enumerate(outputs):
            self.pending_balances[i].save()
            outputs[i] = (outputs[i][0], outputs[i][1], self.pending_balances[i].pk)

        for pk, balance in self.outputs[0:4]:
            miner = Miner.objects.get(public_key=pk)
            Balance.objects.create(miner=miner, balance=-balance / 1e10, status="pending_withdrawal")

        Configuration.objects.create(key='MAX_NUMBER_OF_OUTPUTS', value='20')
        TRANSACTION_FEE = Configuration.objects.TRANSACTION_FEE
        generate_and_send_transaction(outputs)
        reqs = {
            'requests': [
                {
                    'address': pk,
                    'value': value
                } for pk, value, _ in outputs
            ],
            'fee': TRANSACTION_FEE,
            'inputsRaw': [x for x in 'abcdefghi']
        }

        mocked_request.assert_any_call('wallet/transaction/send', data=reqs, request_type='post')

        for pk, value, _ in outputs:
            self.assertEqual(Balance.objects.filter(miner__public_key=pk, balance=-value, status="withdraw").count(), 1)

        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 4)

    def tearDown(self):
        """
        tearDown function to clean up objects created in setUp function
        :return:
        """
        Configuration.objects.all().delete()
        Miner.objects.all().delete()
        # delete all miners objects. all related objects are deleted


@patch('core.tasks.generate_and_send_transaction')
class PeriodicWithdrawalTestCase(TestCase):
    """
    Test class for periodic withdrawal and send method
    Balance statuses: mature, withdraw, pending_withdrawal
    """

    def setUp(self):
        """
        creates necessary configuration and objects and a default output list
        :return:
        """
        # setting configuration
        Configuration.objects.create(key='DEFAULT_WITHDRAW_THRESHOLD', value=str(int(100e9)))

        # creating 10 miners
        pks = [random_string() for i in range(10)]
        for pk in pks:
            Miner.objects.create(public_key=pk)

        self.miners = Miner.objects.all()

        # by default all miners have balance of 80 erg
        for miner in Miner.objects.all():
            Balance.objects.create(miner=miner, balance=int(100e9), status="mature")
            Balance.objects.create(miner=miner, balance=int(-20e9), status="withdraw")

        self.outputs = [(pk, int(80e9)) for pk in pks]

    def test_all_miners_below_defualt_threshold(self, mocked_generate_txs):
        """
        all miners balances are below default threshold
        """
        periodic_withdrawal()
        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 0)
        mocked_generate_txs.assert_has_calls([call([])])

    def test_all_miners_except_one_below_default_threshold(self, mocked_generate_txs):
        """
        all miners balances are below default threshold but one
        """
        Balance.objects.create(miner=self.miners[0], balance=int(100e9), status="mature")
        max_id = Balance.objects.all().aggregate(Max('pk'))['pk__max']
        periodic_withdrawal()
        mocked_generate_txs.assert_has_calls([call([(self.miners[0].public_key, int(180e9), max_id + 1)])])

        self.assertEqual(Balance.objects.filter(miner=self.miners[0], balance=int(-180e9), status="pending_withdrawal").count(), 1)

    def test_all_miner_below_default_threshold_one_explicit_threshold(self, mocked_generate_txs):
        """
        all miners balances are below default threshold
        one miner has explicit threshold, his balance is above this threshold
        """
        miner = self.miners[0]
        miner.periodic_withdrawal_amount = int(20e9)
        miner.save()
        max_id = Balance.objects.all().aggregate(Max('pk'))['pk__max']
        periodic_withdrawal()
        mocked_generate_txs.assert_has_calls([call([(miner.public_key, int(80e9), max_id + 1)])])

        self.assertEqual(Balance.objects.filter(miner=miner, balance=int(-80e9), status="pending_withdrawal").count(), 1)
        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 1)

    def test_all_miner_below_default_threshold_two_explicit_threshold(self, mocked_generate_txs):
        """
        all miners balances are below default threshold
        two miners have explicit threshold, conf of one of them is exactly his balance
        """
        miner1 = self.miners[0]
        miner1.periodic_withdrawal_amount = int(20e9)
        miner1.save()
        miner2 = self.miners[1]
        miner2.periodic_withdrawal_amount = int(80e9)
        miner2.save()
        max_id = Balance.objects.all().aggregate(Max('pk'))['pk__max']
        periodic_withdrawal()
        mocked_generate_txs.assert_has_calls([call([(miner1.public_key, int(80e9), max_id + 1),
                                                    (miner2.public_key, int(80e9), max_id + 2)])])
        for miner in [miner1, miner2]:
            self.assertEqual(Balance.objects.filter(miner=miner, balance=int(-80e9), status="pending_withdrawal").count(), 1)
        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 2)

    def test_all_miners_but_one_below_default_threshold_two_explicit_threshold_one_not_above(self, mocked_generate_txs):
        """
        all miners balances are below default threshold but one
        two miners have explicit threshold, balance of one of them is below the explicit conf
        """
        miner1 = self.miners[0]
        miner1.periodic_withdrawal_amount = int(20e9)
        miner1.save()
        miner2 = self.miners[1]
        miner2.periodic_withdrawal_amount = int(90e9)
        miner2.save()
        max_id = Balance.objects.all().aggregate(Max('pk'))['pk__max']
        periodic_withdrawal()
        mocked_generate_txs.assert_has_calls([call([(miner1.public_key, int(80e9), max_id + 1)])])

        self.assertEqual(Balance.objects.filter(miner=miner1, balance=int(-80e9), status="pending_withdrawal").count(), 1)
        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 1)

    def test_all_miners_but_one_below_default_one_above_default_below_explicit(self, mocked_generate_txs):
        """
        all miners balances are below default threshold but one
        two miners have explicit threshold, balance of one of them is below the explicit conf
        """
        miner1 = self.miners[0]
        Balance.objects.create(miner=miner1, balance=int(30e9), status="mature")
        miner1.periodic_withdrawal_amount = int(120e9)
        miner1.save()
        periodic_withdrawal()
        mocked_generate_txs.assert_has_calls([call([])])

        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 0)

    def test_all_miners_above_default_but_one(self, mocked_generate_txs):
        """
        all miners balances are above default threshold but one
        """
        for miner in self.miners:
            Balance.objects.create(miner=miner, balance=int(30e9), status="mature")
        miner1 = self.miners[0]
        Balance.objects.create(miner=miner1, balance=int(-80e9), status="mature")
        max_id = Balance.objects.all().aggregate(Max('pk'))['pk__max']
        outputs = [(miner.public_key, int(110e9), max_id + 1 + i) for i, miner in enumerate(self.miners[1:])]
        periodic_withdrawal()
        mocked_generate_txs.assert_has_calls([call(outputs)])

        for miner in self.miners[1:]:
            self.assertEqual(Balance.objects.filter(miner=miner, balance=int(-110e9), status="pending_withdrawal").count(), 1)
        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), len(self.miners) - 1)

    def test_all_miners_above_default_but_one_no_balance(self, mocked_generate_txs):
        """
        all miners balances are above default threshold but one
        one doesn't have any balance
        """
        for miner in self.miners:
            Balance.objects.create(miner=miner, balance=int(30e9), status="mature")
        miner1 = self.miners[0]
        Balance.objects.filter(miner=miner1).delete()
        max_id = Balance.objects.all().aggregate(Max('pk'))['pk__max']
        outputs = [(miner.public_key, int(110e9), max_id + 1 + i) for i, miner in enumerate(self.miners[1:])]
        periodic_withdrawal()
        mocked_generate_txs.assert_has_calls([call(outputs)])

        for miner in self.miners[1:]:
            self.assertEqual(Balance.objects.filter(miner=miner, balance=int(-110e9), status="pending_withdrawal").count(), 1)
        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), len(self.miners) - 1)

    def test_no_balance(self, mocked_generate_txs):
        """
        no balance, empty output
        """
        Balance.objects.all().delete()
        periodic_withdrawal()
        mocked_generate_txs.assert_has_calls([call([])])
        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 0)

    def tearDown(self):
        """
        tearDown function to clean up objects created in setUp function
        :return:
        """
        Configuration.objects.all().delete()
        Miner.objects.all().delete()
        # delete all miners objects. all related objects are deleted


class MinerViewTestCase(TestCase):
    """
    Test class for MinerView
    Balance statuses: mature, withdraw, pending_withdrawal
    """

    def setUp(self):
        """
        creates necessary configuration and objects and a default output list
        :return:
        """
        self.client = Client()

        # setting configuration
        Configuration.objects.create(key='MAX_WITHDRAW_THRESHOLD', value=str(int(100e9)))
        Configuration.objects.create(key='MIN_WITHDRAW_THRESHOLD', value=str(int(1e9)))

        # creating 10 miners
        pks = [random_string() for i in range(10)]
        for pk in pks:
            Miner.objects.create(public_key=pk)

        self.miners = Miner.objects.all()
        # by default every miner has 80 erg balance
        for miner in Miner.objects.all():
            Balance.objects.create(miner=miner, balance=int(100e9), status="mature")
            Balance.objects.create(miner=miner, balance=int(-20e9), status="withdraw")

    def get_threshold_url(self, pk):
        return urljoin('/miner/', pk) + '/'

    def get_withdraw_url(self, pk):
        return urljoin(urljoin('/miner/', pk) + '/', 'withdraw') + '/'

    def test_miner_not_specified_threshold_valid(self):
        """
        miner is not specified in request
        """
        data = {
            'periodic_withdrawal_amount': int(20e9)
        }

        res = self.client.patch('/miner/', data, content_type='application/json')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_miner_not_valid_threshold_valid(self):
        """
        miner specified but not valid
        """
        miner = self.miners[0]
        data = {
            'periodic_withdrawal_amount': int(20e9)
        }

        bef = miner.periodic_withdrawal_amount
        res = self.client.patch('/miner/not_valid/', data, content_type='application/json')

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(bef, Miner.objects.get(public_key=miner.public_key).periodic_withdrawal_amount)

    def test_miner_valid_threshold_not_valid(self):
        """
        miner is specified and valid, threshold specified but not valid
        """
        miner = self.miners[0]
        data = {
            'periodic_withdrawal_amount': int(1000e9)
        }

        bef = miner.periodic_withdrawal_amount
        res = self.client.patch(self.get_threshold_url(miner.public_key), data, content_type='application/json')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(bef, Miner.objects.get(public_key=miner.public_key).periodic_withdrawal_amount)

    def test_miner_valid_threshold_valid(self):
        """
        miner is specified and valid, threshold specified and valid
        """
        miner = self.miners[0]
        data = {
            'periodic_withdrawal_amount': int(20e9)
        }

        res = self.client.patch(self.get_threshold_url(miner.public_key), data, content_type='application/json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(int(20e9), Miner.objects.get(public_key=miner.public_key).periodic_withdrawal_amount)

    def test_miner_valid_threshold_type_not_valid(self):
        """
        miner is specified and valid, threshold type is not valid
        """
        miner = self.miners[0]
        data = {
            'periodic_withdrawal_amount': 'not_valid'
        }

        bef = miner.periodic_withdrawal_amount
        res = self.client.patch(self.get_threshold_url(miner.public_key), data, content_type='application/json')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(bef, Miner.objects.get(public_key=miner.public_key).periodic_withdrawal_amount)

    @patch('core.views.generate_and_send_transaction')
    def test_withdraw_invalid_amount(self, mocked_generate_and_send_txs):
        """
        withdraw type is not valid
        """
        miner = self.miners[0]
        data = {
            'withdraw_amount': 'not_valid'
        }

        res = self.client.post(self.get_withdraw_url(miner.public_key), data, content_type='application/json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(mocked_generate_and_send_txs.delay.not_called)

        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 0)

    @patch('core.views.generate_and_send_transaction')
    def test_withdraw_invalid_amount_smaller_than_fee(self, mocked_generate_and_send_txs):
        """
        withdraw type is not valid
        """
        TRANSACTION_FEE = Configuration.objects.TRANSACTION_FEE
        miner = self.miners[0]
        data = {
            'withdraw_amount': TRANSACTION_FEE / 2
        }

        res = self.client.post(self.get_withdraw_url(miner.public_key), data, content_type='application/json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(mocked_generate_and_send_txs.delay.not_called)

        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 0)

    @patch('core.views.generate_and_send_transaction')
    def test_withdraw_not_enough_balance(self, mocked_generate_and_send_txs):
        """
        not enough balance for the request
        """
        miner = self.miners[0]
        data = {
            'withdraw_amount': int(100e9)
        }

        res = self.client.post(self.get_withdraw_url(miner.public_key), data, content_type='application/json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(mocked_generate_and_send_txs.delay.not_called)

        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 0)

    @patch('core.views.generate_and_send_transaction')
    def test_withdraw_not_enough_balance_because_of_pending(self, mocked_generate_and_send_txs):
        """
        not enough balance for the request
        """
        miner = self.miners[0]
        Balance.objects.create(miner=miner, balance=int(-40e9), status="pending_withdrawal")
        data = {
            'withdraw_amount': int(50e9)
        }

        res = self.client.post(self.get_withdraw_url(miner.public_key), data, content_type='application/json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(mocked_generate_and_send_txs.delay.not_called)

        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 1)

    @patch('core.views.generate_and_send_transaction')
    def test_withdraw_enough_balance_successful(self, mocked_generate_and_send_txs):
        """
        enough balance, successful
        """
        miner = self.miners[0]
        data = {
            'withdraw_amount': int(60e9)
        }

        res = self.client.post(self.get_withdraw_url(miner.public_key), data, content_type='application/json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        max_id = Balance.objects.all().aggregate(Max('pk'))['pk__max']
        mocked_generate_and_send_txs.delay.assert_has_calls(
            [call([(miner.public_key, int(60e9), max_id)], subtract_fee=True)])

        self.assertEqual(Balance.objects.filter(status="pending_withdrawal", miner=miner, balance=int(-60e9)).count(), 1)
        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 1)

    @patch('core.views.generate_and_send_transaction')
    def test_withdraw_enough_balance_successful_with_pending(self, mocked_generate_and_send_txs):
        """
        enough balance, successful
        """
        miner = self.miners[0]
        Balance.objects.create(miner=miner, balance=10, status="pending_withdrawal")
        data = {
            'withdraw_amount': int(60e9)
        }

        res = self.client.post(self.get_withdraw_url(miner.public_key), data, content_type='application/json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        max_id = Balance.objects.all().aggregate(Max('pk'))['pk__max']
        mocked_generate_and_send_txs.delay.assert_has_calls(
            [call([(miner.public_key, int(60e9), max_id)], subtract_fee=True)])

        self.assertEqual(Balance.objects.filter(status="pending_withdrawal", miner=miner, balance=int(-60e9)).count(), 1)
        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 2)

    @patch('core.views.generate_and_send_transaction')
    def test_withdraw_all_balance_successful(self, mocked_generate_and_send_txs):
        """
        enough balance, withdraw all the balance, successful
        """
        miner = self.miners[0]
        data = {
            'withdraw_amount': int(80e9)
        }

        res = self.client.post(self.get_withdraw_url(miner.public_key), data, content_type='application/json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        max_id = Balance.objects.all().aggregate(Max('pk'))['pk__max']
        mocked_generate_and_send_txs.delay.assert_has_calls(
            [call([(miner.public_key, int(80e9), max_id)], subtract_fee=True)])
        self.assertEqual(Balance.objects.filter(status="pending_withdrawal", miner=miner, balance=int(-80e9)).count(), 1)
        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 1)

    def tearDown(self):
        """
        tearDown function to clean up objects created in setUp function
        :return:
        """
        Configuration.objects.all().delete()
        Miner.objects.all().delete()
        # delete all miners objects. all related objects are deleted


class ImmatureToMatureTestCase(TestCase):
    """
    Test class for immature_to_mature function
    """
    CURRENT_HEIGHT = 20000

    def mocked_node_request(*args, **kwargs):
        """
        mock requests with method post
        """
        url = args[0]

        if url == 'info':
            return {
                'response': {'fullHeight': ImmatureToMatureTestCase.CURRENT_HEIGHT},
                'status': 'success'
            }

        if url == 'wallet/transactionById':
            params = kwargs['params']
            num_confirmation = int(params['id'].split('_')[1])
            return {
                'response': {'numConfirmations': num_confirmation},
                'status': 'success'
            }

        return {
            'response': None,
            'status': 'error'
        }

    def setUp(self):
        """
        creates necessary configuration and objects and a default output list
        20 confirmed shares
        5 valid shares
        5 unconfirmed shares
        10 miner
        for each miner and share: 3 balance with different statuses
        :return:
        """
        self.client = Client()
        self.CURRENT_HEIGHT = ImmatureToMatureTestCase.CURRENT_HEIGHT

        # setting configuration
        Configuration.objects.create(key='CONFIRMATION_LENGTH', value='720')

        # creating 10 miners
        pks = [random_string() for i in range(10)]
        for pk in pks:
            Miner.objects.create(public_key=pk)

        self.miners = Miner.objects.all()
        CONFIRMATION_LENGTH = Configuration.objects.CONFIRMATION_LENGTH
        for i in range(5):
            # not important shares
            num_confirmation = CONFIRMATION_LENGTH + 10
            block_height = self.CURRENT_HEIGHT - num_confirmation
            tx_id = '_'.join([random_string(), str(num_confirmation)])
            Share.objects.create(miner=self.miners[0], transaction_id=tx_id, difficulty=1,
                                 block_height=block_height, status='valid')

            # confirmed shares
            num_confirmation = CONFIRMATION_LENGTH + 10
            block_height = self.CURRENT_HEIGHT - num_confirmation
            tx_id = '_'.join([random_string(), str(num_confirmation)])
            Share.objects.create(miner=self.miners[0], transaction_id=tx_id, difficulty=1,
                                 block_height=block_height, status='solved')

            # confirmed just now
            num_confirmation = CONFIRMATION_LENGTH
            block_height = self.CURRENT_HEIGHT - num_confirmation
            tx_id = '_'.join([random_string(), str(num_confirmation)])
            Share.objects.create(miner=self.miners[0], transaction_id=tx_id, difficulty=1,
                                 block_height=block_height, status='solved')

            # unconfirmed shares
            num_confirmation = CONFIRMATION_LENGTH - 10
            block_height = self.CURRENT_HEIGHT - num_confirmation
            tx_id = '_'.join([random_string(), str(num_confirmation)])
            Share.objects.create(miner=self.miners[0], transaction_id=tx_id, difficulty=1,
                                 block_height=block_height, status='solved')

        # by default all shares have immature balances for each miner
        for share in Share.objects.all():
            for miner in self.miners:
                Balance.objects.create(share=share, miner=miner, balance=int(100e9), status='immature')
                Balance.objects.create(share=share, miner=miner, balance=int(100e9), status='mature')
                Balance.objects.create(miner=miner, balance=int(-20e9), status='withdraw')

    @patch('core.tasks.node_request', side_effect=mocked_node_request)
    def test_20_shares_possible_20_confirmed(self, mocked_node_request):
        """
        20 shares have immature balances and their block_height is less than the threshold
        the same 20 shares are confirmed
        """
        current_height = ImmatureToMatureTestCase.CURRENT_HEIGHT
        CONFIRMATION_LENGTH = Configuration.objects.CONFIRMATION_LENGTH
        confirmed_shares = [x.id for x in Share.objects.filter(balance__status='immature',
                                                               block_height__lte=(current_height - CONFIRMATION_LENGTH),
                                                               status='solved').distinct()]
        balances_to_status = {
            balance.id: balance.status for balance in Balance.objects.all()
        }

        immature_to_mature()
        for balance in Balance.objects.all():
            if balance.share is None or balance.share.id not in confirmed_shares:
                self.assertEqual(balance.status, balances_to_status[balance.id])

            else:
                if balances_to_status[balance.id] == "immature":
                    self.assertEqual(balance.status, "mature")

                else:
                    self.assertEqual(balance.status, balances_to_status[balance.id])

    @patch('core.tasks.node_request', side_effect=mocked_node_request)
    def test_20_shares_possible_15_confirmed(self, mocked_node_request):
        """
        20 shares have immature balances and their block_height is less than the threshold
        15 of these shares are confirmed
        """
        current_height = ImmatureToMatureTestCase.CURRENT_HEIGHT
        CONFIRMATION_LENGTH = Configuration.objects.CONFIRMATION_LENGTH
        cur_unconfirmed = Share.objects.filter(balance__status='immature',
                                               block_height=(current_height - CONFIRMATION_LENGTH),
                                               status='solved').distinct()[:5]
        for share in cur_unconfirmed:
            num_confirmed = int(share.transaction_id.split('_')[-1])
            share.transaction_id = '_'.join([random_string(), str(num_confirmed - 1)])
            share.save()

        cur_unconfirmed = [x.id for x in cur_unconfirmed]

        confirmed_shares = [x.id for x in Share.objects.filter(balance__status='immature',
                                                               block_height__lte=(current_height - CONFIRMATION_LENGTH),
                                                               status='solved').distinct() if
                            x.id not in cur_unconfirmed]
        balances_to_status = {
            balance.id: balance.status for balance in Balance.objects.all()
        }

        immature_to_mature()
        for balance in Balance.objects.all():
            if balance.share is None or balance.share.id not in confirmed_shares:
                self.assertEqual(balance.status, balances_to_status[balance.id])

            else:
                if balances_to_status[balance.id] == "immature":
                    self.assertEqual(balance.status, "mature")

                else:
                    self.assertEqual(balance.status, balances_to_status[balance.id])

    @patch('core.tasks.node_request', side_effect=mocked_node_request)
    def test_20_shares_possible_0_confirmed(self, mocked_node_request):
        """
        20 shares have immature balances and their block_height is less than the threshold
        0 of these shares are confirmed
        """
        current_height = ImmatureToMatureTestCase.CURRENT_HEIGHT
        CONFIRMATION_LENGTH = Configuration.objects.CONFIRMATION_LENGTH
        cur_unconfirmed = Share.objects.filter(balance__status='immature',
                                               block_height__lte=(current_height - CONFIRMATION_LENGTH),
                                               status='solved').distinct()
        for share in cur_unconfirmed:
            num_confirmed = int(share.transaction_id.split('_')[-1])
            share.transaction_id = '_'.join([random_string(), str(num_confirmed - 100)])
            share.save()

        balances_to_status = {
            balance.id: balance.status for balance in Balance.objects.all()
        }

        immature_to_mature()
        for balance in Balance.objects.all():
            self.assertEqual(balance.status, balances_to_status[balance.id])

    @patch('core.tasks.node_request', side_effect=mocked_node_request)
    def test_0_shares_possible_0_confirmed(self, mocked_node_request):
        """
        0 shares have immature balances and their block_height is less than the threshold
        0 of these shares are confirmed
        """
        current_height = ImmatureToMatureTestCase.CURRENT_HEIGHT
        CONFIRMATION_LENGTH = Configuration.objects.CONFIRMATION_LENGTH
        cur_unconfirmed = Share.objects.filter(balance__status='immature',
                                               block_height__lte=(current_height - CONFIRMATION_LENGTH),
                                               status='solved').distinct()
        for share in cur_unconfirmed:
            share.block_height = current_height
            share.save()

        balances_to_status = {
            balance.id: balance.status for balance in Balance.objects.all()
        }

        immature_to_mature()
        for balance in Balance.objects.all():
            self.assertEqual(balance.status, balances_to_status[balance.id])

    def tearDown(self):
        """
        tearDown function to clean up objects created in setUp function
        :return:
        """
        Configuration.objects.all().delete()
        Miner.objects.all().delete()
        Share.objects.all().delete()
        Balance.objects.all().delete()


@override_settings(KEEP_BALANCE_WITH_DETAIL_NUM=8)
@override_settings(KEEP_SHARES_WITH_DETAIL_NUM=5)
@override_settings(KEEP_SHARES_AGGREGATION_NUM=3)
@override_settings(AGGREGATE_ROOT_FOLDER='/tmp')
@patch('core.tasks.datetime')
class AggregateTestCase(TestCase):
    """
    Test class for aggregation
    """

    def setUp(self):
        """
        creating 5 miners
        2 solved share for each
        for each status, 'valid', 'invalid' and 'repetitious create 8 shares
        for each solved share and each miner create 2 balance,
        one with status mature and one with withdrawal
        """
        date = '2020-01-27 12:19:46.196633'
        self.shares_detail_file = os.path.join(settings.AGGREGATE_ROOT_FOLDER,
                                               settings.SHARE_DETAIL_FOLDER, date) + '.json'
        self.shares_aggregate_file = os.path.join(settings.AGGREGATE_ROOT_FOLDER,
                                                  settings.SHARE_AGGREGATE_FOLDER, date) + '.json'
        self.balance_detail_file = os.path.join(settings.AGGREGATE_ROOT_FOLDER,
                                                settings.BALANCE_DETAIL_FOLDER, date) + '.json'

        # deleting files
        for file in [self.shares_aggregate_file, self.shares_detail_file, self.balance_detail_file]:
            if os.path.exists(file):
                os.remove(file)

        num_miners = 5
        for i in range(num_miners):
            Miner.objects.create(public_key=str(i))

        self.solved = []
        time = timezone.now()
        for i in range(10):
            solved_share = Share.objects.create(share=random_string(), miner=Miner.objects.all()[i % num_miners],
                                                difficulty=int((i + 1) * 1e8),
                                                status='solved')
            Share.objects.filter(id=solved_share.id).update(created_at=time - timedelta(seconds=i * 10))
            solved_share = Share.objects.get(id=solved_share.id)
            self.solved.insert(0, solved_share)

            for j in range(8):
                for stat in ['invalid', 'valid', 'repetitious']:
                    share = Share.objects.create(share=random_string(), miner=Miner.objects.all()[j % num_miners],
                                                 difficulty=10, status=stat)
                    Share.objects.filter(id=share.id).update(created_at=time - timedelta(seconds=i * 10 + 1))

            for m in Miner.objects.all():
                b = Balance.objects.create(miner=m, share=solved_share, balance=int(30e9), status='mature')
                Balance.objects.filter(id=b.id).update(created_at=solved_share.created_at - timedelta(seconds=1))
                b = Balance.objects.create(miner=m, share=solved_share, balance=int(-10e9), status='withdraw')
                Balance.objects.filter(id=b.id).update(created_at=solved_share.created_at - timedelta(seconds=1))

    def test_share_all_with_detail(self, mocked_time):
        """
        first time running the aggregate function
        all shares and balances are present
        """
        mocked_time.now.return_value = datetime.strptime('2020-01-27 12:19:46.196633',
                                                         '%Y-%m-%d %H:%M:%S.%f')
        share_detail_content = []

        for solved in self.solved[:-settings.KEEP_SHARES_WITH_DETAIL_NUM]:
            for share in Share.objects.filter(created_at=solved.created_at - timedelta(seconds=1)):
                share_detail_content.append(str(ShareSerializer(share).data))

        aggregate()

        # all shares in last 5 rounds must remain with details
        for solved in self.solved[-5:]:
            # the solved share must remain
            self.assertEqual(Share.objects.filter(id=solved.id).count(), 1)
            self.assertEqual(Share.objects.filter(created_at=solved.created_at - timedelta(seconds=1)).count(), 24)
            self.assertEqual(AggregateShare.objects.filter(solved_share=solved).count(), 0)
            self.assertEqual(Share.objects.get(id=solved.id).is_aggregated, False)

        # all shares in 3 rounds before above status must be aggregated
        for solved in self.solved[2:-5]:
            # the solved share must remain
            self.assertEqual(Share.objects.filter(id=solved.id).count(), 1)
            self.assertEqual(Share.objects.filter(created_at=solved.created_at - timedelta(seconds=1)).count(), 0)
            for miner in Miner.objects.all():
                self.assertEqual(AggregateShare.objects.filter(miner=miner, solved_share=solved).count(), 1)
                agg = AggregateShare.objects.get(miner=miner, solved_share=solved)
                parameters = [agg.valid_num, agg.invalid_num, agg.repetitious_num, agg.difficulty_sum]
                if miner.public_key in ['0', '1', '2']:
                    self.assertEqual(parameters, [2, 2, 2, 60])
                else:
                    self.assertEqual(parameters, [1, 1, 1, 30])
            self.assertEqual(Share.objects.get(id=solved.id).is_aggregated, True)

        # all other rounds must be aggregated and removed
        for solved in self.solved[0:2]:
            # the solved share must remain
            self.assertEqual(Share.objects.filter(id=solved.id).count(), 1)
            self.assertEqual(Share.objects.filter(created_at=solved.created_at - timedelta(seconds=1)).count(), 0)
            self.assertEqual(AggregateShare.objects.filter(solved_share=solved).count(), 0)

        share_detail_content = '\n'.join(sorted(share_detail_content))

        self.assertTrue(os.path.exists(self.shares_detail_file))
        with open(self.shares_detail_file, 'r') as file:
            content = file.read().rstrip()
            content = '\n'.join(sorted(content.split('\n')))
            self.assertEqual(share_detail_content, content)

        self.assertTrue(os.path.exists(self.shares_aggregate_file))
        with open(self.shares_aggregate_file, 'r') as file:
            content = file.read().rstrip()
            content = content.split('\n')
            self.assertEqual(len(content), 10)

    def test_share_6_with_detail_other_aggregated(self, mocked_time):
        """
        some aggregated must be removed, some details must be aggregated
        """
        mocked_time.now.return_value = datetime.strptime('2020-01-27 12:19:46.196633',
                                                         '%Y-%m-%d %H:%M:%S.%f')
        share_aggregate_content = []
        share_detail_content = []

        for share in Share.objects.filter(created_at=self.solved[4].created_at - timedelta(seconds=1)):
            share_detail_content.append(str(ShareSerializer(share).data))

        for solved in self.solved[:4]:
            solved.is_aggregated = True
            solved.save()
            Share.objects.filter(created_at=solved.created_at - timedelta(seconds=1)).delete()
            for miner in Miner.objects.all():
                if miner.public_key in ['0', '1', '2']:
                    AggregateShare.objects.create(miner=miner, solved_share=solved, valid_num=2,
                                                  invalid_num=2, repetitious_num=2, difficulty_sum=60)
                else:
                    AggregateShare.objects.create(miner=miner, solved_share=solved, valid_num=1,
                                                  invalid_num=1, repetitious_num=1, difficulty_sum=30)

        for solved in self.solved[:2]:
            for share_aggregate in AggregateShare.objects.filter(solved_share=solved):
                share_aggregate_content.append(str(AggregateShareSerializer(share_aggregate).data))

        aggregate()

        # all shares in last 5 rounds must remain with details
        for solved in self.solved[-5:]:
            # the solved share must remain
            self.assertEqual(Share.objects.filter(id=solved.id).count(), 1)
            self.assertEqual(Share.objects.filter(created_at=solved.created_at - timedelta(seconds=1)).count(), 24)
            self.assertEqual(AggregateShare.objects.filter(solved_share=solved).count(), 0)
            self.assertEqual(Share.objects.get(id=solved.id).is_aggregated, False)

        # 5th round must remain aggregated
        for solved in self.solved[2:5]:
            for miner in Miner.objects.all():
                self.assertEqual(AggregateShare.objects.filter(miner=miner, solved_share=solved).count(), 1)
            self.assertEqual(Share.objects.get(id=solved.id).is_aggregated, True)

        # 2 aggregated rounds must be removed
        for solved in self.solved[:2]:
            # the solved share must remain
            self.assertEqual(Share.objects.filter(id=solved.id).count(), 1)
            self.assertEqual(Share.objects.filter(created_at=solved.created_at - timedelta(seconds=1)).count(), 0)
            self.assertEqual(AggregateShare.objects.filter(solved_share=solved).count(), 0)

        share_aggregate_content = '\n'.join(sorted(share_aggregate_content))
        share_detail_content = '\n'.join(sorted(share_detail_content))

        for filename, expected_content in [(self.shares_aggregate_file, share_aggregate_content),
                                           (self.shares_detail_file, share_detail_content)]:
            self.assertTrue(os.path.exists(filename))
            with open(filename, 'r') as file:
                content = file.read().rstrip()
                content = '\n'.join(sorted(content.split('\n')))
                self.assertEqual(expected_content, content)

    def test_share_6_with_detail_other_aggregated_some_miners_not_exist_in_round(self, mocked_time):
        """
        some aggregated must be removed, some details must be aggregated
        some miners are not in the round to be aggregate, no aggregate object must be created for that miner
        """
        mocked_time.now.return_value = datetime.strptime('2020-01-27 12:19:46.196633',
                                                         '%Y-%m-%d %H:%M:%S.%f')
        share_aggregate_content = []
        share_detail_content = []

        # first miner is not present in 5th round, so nothing must be aggregated for him
        Share.objects.filter(created_at=self.solved[4].created_at - timedelta(seconds=1),
                             miner=Miner.objects.all()[0]).delete()

        for share in Share.objects.filter(created_at=self.solved[4].created_at - timedelta(seconds=1)):
            share_detail_content.append(str(ShareSerializer(share).data))

        for solved in self.solved[:4]:
            solved.is_aggregated = True
            solved.save()
            Share.objects.filter(created_at=solved.created_at - timedelta(seconds=1)).delete()
            for miner in Miner.objects.all():
                if miner.public_key in ['0', '1', '2']:
                    AggregateShare.objects.create(miner=miner, solved_share=solved, valid_num=2,
                                                  invalid_num=2, repetitious_num=2, difficulty_sum=60)
                else:
                    AggregateShare.objects.create(miner=miner, solved_share=solved, valid_num=1,
                                                  invalid_num=1, repetitious_num=1, difficulty_sum=30)

        for solved in self.solved[:2]:
            for share_aggregate in AggregateShare.objects.filter(solved_share=solved):
                share_aggregate_content.append(str(AggregateShareSerializer(share_aggregate).data))

        aggregate()

        # all shares in last 5 rounds must remain with details
        for solved in self.solved[-5:]:
            self.assertEqual(Share.objects.get(id=solved.id).is_aggregated, False)
            # the solved share must remain
            self.assertEqual(Share.objects.filter(id=solved.id).count(), 1)
            self.assertEqual(Share.objects.filter(created_at=solved.created_at - timedelta(seconds=1)).count(), 24)
            self.assertEqual(AggregateShare.objects.filter(solved_share=solved).count(), 0)

        # 2 rounds must remain aggregated with all miners
        for solved in self.solved[2:4]:
            self.assertEqual(Share.objects.get(id=solved.id).is_aggregated, True)
            for miner in Miner.objects.all():
                self.assertEqual(AggregateShare.objects.filter(miner=miner, solved_share=solved).count(), 1)

        # one round must be aggregated with all miners except the first onw
        for miner in Miner.objects.all()[1:]:
            self.assertEqual(AggregateShare.objects.filter(miner=miner, solved_share=self.solved[4]).count(), 1)
        self.assertEqual(
            AggregateShare.objects.filter(miner=Miner.objects.all()[0], solved_share=self.solved[4]).count(), 0)

        # 2 aggregated rounds must be removed
        for solved in self.solved[:2]:
            # the solved share must remain
            self.assertEqual(Share.objects.filter(id=solved.id).count(), 1)
            self.assertEqual(Share.objects.filter(created_at=solved.created_at - timedelta(seconds=1)).count(), 0)
            self.assertEqual(AggregateShare.objects.filter(solved_share=solved).count(), 0)

        share_aggregate_content = '\n'.join(sorted(share_aggregate_content))
        share_detail_content = '\n'.join(sorted(share_detail_content))

        for filename, expected_content in [(self.shares_aggregate_file, share_aggregate_content),
                                           (self.shares_detail_file, share_detail_content)]:
            self.assertTrue(os.path.exists(filename))
            with open(filename, 'r') as file:
                content = file.read().rstrip()
                content = '\n'.join(sorted(content.split('\n')))
                self.assertEqual(expected_content, content)

    def test_share_6_with_detail_other_aggregated_files_not_empty(self, mocked_time):
        """
        some aggregated must be removed, some details must be aggregated
        balance, shares_detail and shares_aggregate files are not empty, must be appended
        """
        mocked_time.now.return_value = datetime.strptime('2020-01-27 12:19:46.196633',
                                                         '%Y-%m-%d %H:%M:%S.%f')
        share_aggregate_content = ['just', 'something', 'random']
        share_detail_content = ['just', 'something', 'random']

        for file in [self.shares_aggregate_file, self.shares_detail_file]:
            with open(file, 'w') as cur:
                cur.write('just\nsomething\nrandom\n')

        for share in Share.objects.filter(created_at=self.solved[4].created_at - timedelta(seconds=1)):
            share_detail_content.append(str(ShareSerializer(share).data))

        for solved in self.solved[:4]:
            solved.is_aggregated = True
            solved.save()
            Share.objects.filter(created_at=solved.created_at - timedelta(seconds=1)).delete()
            for miner in Miner.objects.all():
                if miner.public_key in ['0', '1', '2']:
                    AggregateShare.objects.create(miner=miner, solved_share=solved, valid_num=2,
                                                  invalid_num=2, repetitious_num=2, difficulty_sum=60)
                else:
                    AggregateShare.objects.create(miner=miner, solved_share=solved, valid_num=1,
                                                  invalid_num=1, repetitious_num=1, difficulty_sum=30)

        for solved in self.solved[:2]:
            for share_aggregate in AggregateShare.objects.filter(solved_share=solved):
                share_aggregate_content.append(str(AggregateShareSerializer(share_aggregate).data))

        aggregate()

        # all shares in last 5 rounds must remain with details
        for solved in self.solved[-5:]:
            self.assertEqual(Share.objects.get(id=solved.id).is_aggregated, False)
            # the solved share must remain
            self.assertEqual(Share.objects.filter(id=solved.id).count(), 1)
            self.assertEqual(Share.objects.filter(created_at=solved.created_at - timedelta(seconds=1)).count(), 24)
            self.assertEqual(AggregateShare.objects.filter(solved_share=solved).count(), 0)

        # 5th round must remain aggregated
        for solved in self.solved[2:5]:
            self.assertEqual(Share.objects.get(id=solved.id).is_aggregated, True)
            for miner in Miner.objects.all():
                self.assertEqual(AggregateShare.objects.filter(miner=miner, solved_share=solved).count(), 1)

        # 2 aggregated rounds must be removed
        for solved in self.solved[:2]:
            # the solved share must remain
            self.assertEqual(Share.objects.filter(id=solved.id).count(), 1)
            self.assertEqual(Share.objects.filter(created_at=solved.created_at - timedelta(seconds=1)).count(), 0)
            self.assertEqual(AggregateShare.objects.filter(solved_share=solved).count(), 0)

        share_aggregate_content = '\n'.join(sorted(share_aggregate_content))
        share_detail_content = '\n'.join(sorted(share_detail_content))

        self.assertTrue(os.path.exists(self.shares_aggregate_file))
        for filename, expected_content in [(self.shares_aggregate_file, share_aggregate_content),
                                           (self.shares_detail_file, share_detail_content)]:
            with open(filename, 'r') as file:
                content = file.read().rstrip()
                content = '\n'.join(sorted(content.split('\n')))
                self.assertEqual(expected_content, content)

    def test_share_5_detail_3_aggregated(self, mocked_time):
        """
        all ok, nothing should happen
        """
        mocked_time.now.return_value = datetime.strptime('2020-01-27 12:19:46.196633',
                                                         '%Y-%m-%d %H:%M:%S.%f')
        mocked_time.now.return_value = datetime.strptime('2020-01-27 12:19:46.196633',
                                                         '%Y-%m-%d %H:%M:%S.%f')
        for solved in self.solved[:2]:
            solved.is_aggregated = True
            solved.save()
            Share.objects.filter(created_at=solved.created_at - timedelta(seconds=1)).delete()

        for solved in self.solved[2:5]:
            solved.is_aggregated = True
            solved.save()
            Share.objects.filter(created_at=solved.created_at - timedelta(seconds=1)).delete()
            for miner in Miner.objects.all():
                if miner.public_key in ['0', '1', '2']:
                    AggregateShare.objects.create(miner=miner, solved_share=solved, valid_num=2,
                                                  invalid_num=2, repetitious_num=2, difficulty_sum=60)
                else:
                    AggregateShare.objects.create(miner=miner, solved_share=solved, valid_num=1,
                                                  invalid_num=1, repetitious_num=1, difficulty_sum=30)

        aggregate()

        # all shares in last 5 rounds must remain with details
        for solved in self.solved[-5:]:
            self.assertEqual(Share.objects.get(id=solved.id).is_aggregated, False)
            # the solved share must remain
            self.assertEqual(Share.objects.filter(id=solved.id).count(), 1)
            self.assertEqual(Share.objects.filter(created_at=solved.created_at - timedelta(seconds=1)).count(), 24)
            self.assertEqual(AggregateShare.objects.filter(solved_share=solved).count(), 0)

        for solved in self.solved[2:5]:
            self.assertEqual(Share.objects.get(id=solved.id).is_aggregated, True)
            for miner in Miner.objects.all():
                self.assertEqual(AggregateShare.objects.filter(miner=miner, solved_share=solved).count(), 1)

        self.assertTrue(not os.path.exists(self.shares_aggregate_file))
        self.assertTrue(not os.path.exists(self.shares_detail_file))

    def test_balance_all_with_detail(self, mocked_time):
        """
        all balances are with details
        """
        mocked_time.now.return_value = datetime.strptime('2020-01-27 12:19:46.196633',
                                                         '%Y-%m-%d %H:%M:%S.%f')
        balance_detail_content = []

        for balance in Balance.objects.filter(created_at__lte=self.solved[1].created_at):
            balance_detail_content.append(str(BalanceSerializer(balance).data))

        aggregate()

        for miner in Miner.objects.all():
            self.assertEqual(Balance.objects.filter(miner=miner, status='mature', balance=int(60e9)).count(), 1)
            self.assertEqual(Balance.objects.filter(miner=miner, status='withdraw', balance=int(-20e9)).count(), 1)

        for solved in self.solved[2:]:
            for miner in Miner.objects.all():
                self.assertEqual(Balance.objects.filter(share=solved, miner=miner, status='mature',
                                                        balance=int(30e9)).count(), 1)
                self.assertEqual(Balance.objects.filter(share=solved, miner=miner, status='withdraw',
                                                        balance=int(-10e9)).count(), 1)

        balance_detail_content = '\n'.join(sorted(balance_detail_content))

        for filename, expected_content in [(self.balance_detail_file, balance_detail_content)]:
            self.assertTrue(os.path.exists(filename))
            with open(filename, 'r')as file:
                content = file.read().rstrip()
                content = '\n'.join(sorted(content.split('\n')))
                self.assertEqual(expected_content, content)

    def test_balance_all_with_detail_file_not_empty(self, mocked_time):
        """
        all balances are with details
        balance detail file is already present with some values
        should be appended to the end of the file
        """
        mocked_time.now.return_value = datetime.strptime('2020-01-27 12:19:46.196633',
                                                         '%Y-%m-%d %H:%M:%S.%f')
        balance_detail_content = ['just', 'something', 'random']

        with open(self.balance_detail_file, 'w') as file:
            file.write('just\nsomething\nrandom\n')

        for balance in Balance.objects.filter(created_at__lte=self.solved[1].created_at):
            balance_detail_content.append(str(BalanceSerializer(balance).data))

        aggregate()

        for miner in Miner.objects.all():
            self.assertEqual(Balance.objects.filter(miner=miner, status="mature", balance=int(60e9)).count(), 1)
            self.assertEqual(Balance.objects.filter(miner=miner, status="withdraw", balance=int(-20e9)).count(), 1)

        for solved in self.solved[2:]:
            for miner in Miner.objects.all():
                self.assertEqual(Balance.objects.filter(share=solved, miner=miner, status="mature",
                                                        balance=int(30e9)).count(), 1)
                self.assertEqual(Balance.objects.filter(share=solved, miner=miner, status="withdraw",
                                                        balance=int(-10e9)).count(), 1)

        balance_detail_content = '\n'.join(sorted(balance_detail_content))

        for filename, expected_content in [(self.balance_detail_file, balance_detail_content)]:
            self.assertTrue(os.path.exists(filename))
            with open(filename, 'r') as file:
                content = file.read().rstrip()
                content = '\n'.join(sorted(content.split('\n')))
                self.assertEqual(expected_content, content)

    def test_balance_all_with_detail_some_without_share(self, mocked_time):
        """
        all balances are with details
        some balances don't have share filed
        """
        mocked_time.now.return_value = datetime.strptime('2020-01-27 12:19:46.196633',
                                                         '%Y-%m-%d %H:%M:%S.%f')
        balance_detail_content = []

        b = Balance.objects.create(miner=Miner.objects.all()[0], balance=int(100e9), status="mature")
        Balance.objects.filter(id=b.id).update(created_at=self.solved[1].created_at - timedelta(seconds=1))
        b = Balance.objects.create(miner=Miner.objects.all()[0], balance=int(-50e9), status="withdraw")
        Balance.objects.filter(id=b.id).update(created_at=self.solved[1].created_at - timedelta(seconds=1))

        for balance in Balance.objects.filter(created_at__lte=self.solved[1].created_at):
            balance_detail_content.append(str(BalanceSerializer(balance).data))

        aggregate()

        for miner in Miner.objects.all()[1:]:
            self.assertEqual(Balance.objects.filter(miner=miner, status="mature", balance=int(60e9)).count(), 1)
            self.assertEqual(Balance.objects.filter(miner=miner, status="withdraw", balance=int(-20e9)).count(), 1)

        self.assertEqual(Balance.objects.filter(miner=Miner.objects.all()[0], status="mature", balance=int(160e9)).count(), 1)
        self.assertEqual(Balance.objects.filter(miner=Miner.objects.all()[0], status="withdraw", balance=int(-70e9)).count(), 1)

        for solved in self.solved[2:]:
            for miner in Miner.objects.all():
                self.assertEqual(Balance.objects.filter(share=solved, miner=miner, status="mature",
                                                        balance=int(30e9)).count(), 1)
                self.assertEqual(Balance.objects.filter(share=solved, miner=miner, status="withdraw",
                                                        balance=int(-10e9)).count(), 1)

        balance_detail_content = '\n'.join(sorted(balance_detail_content))

        for filename, expected_content in [(self.balance_detail_file, balance_detail_content)]:
            self.assertTrue(os.path.exists(filename))
            with open(filename, 'r') as file:
                content = file.read().rstrip()
                content = '\n'.join(sorted(content.split('\n')))
                self.assertEqual(expected_content, content)

    @override_settings(KEEP_BALANCE_WITH_DETAIL_NUM=0)
    def test_balance_all_with_detail_no_detail_remain(self, mocked_time):
        """
        no detail should remain, all should be aggregated
        """
        mocked_time.now.return_value = datetime.strptime('2020-01-27 12:19:46.196633',
                                                         '%Y-%m-%d %H:%M:%S.%f')
        balance_detail_content = []
        settings.KEEP_BALANCE_WITH_DETAIL_NUM = 0

        for balance in Balance.objects.all():
            balance_detail_content.append(str(BalanceSerializer(balance).data))

        aggregate()

        for miner in Miner.objects.all():
            self.assertEqual(Balance.objects.filter(miner=miner, status="mature", balance=int(300e9)).count(), 1)
            self.assertEqual(Balance.objects.filter(miner=miner, status="withdraw", balance=int(-100e9)).count(), 1)

        for solved in self.solved:
            for miner in Miner.objects.all():
                self.assertEqual(Balance.objects.filter(share=solved, miner=miner, status="mature",
                                                        balance=int(30e9)).count(), 0)
                self.assertEqual(Balance.objects.filter(share=solved, miner=miner, status="withdraw",
                                                        balance=int(-10e9)).count(), 0)

        balance_detail_content = '\n'.join(sorted(balance_detail_content))

        for filename, expected_content in [(self.balance_detail_file, balance_detail_content)]:
            self.assertTrue(os.path.exists(filename))
            with open(filename, 'r') as file:
                content = file.read().rstrip()
                content = '\n'.join(sorted(content.split('\n')))
                self.assertEqual(expected_content, content)

    def test_balance_all_with_detail_with_immature_and_pending(self, mocked_time):
        """
        no detail should remain, all should be aggregated
        immature and pending balances should remain the same
        """
        mocked_time.now.return_value = datetime.strptime('2020-01-27 12:19:46.196633',
                                                         '%Y-%m-%d %H:%M:%S.%f')
        balance_detail_content = []

        for file in [self.balance_detail_file]:
            if os.path.exists(file):
                os.remove(file)

        b = Balance.objects.create(miner=Miner.objects.all()[0], balance=int(100e9), status="immature")
        Balance.objects.filter(id=b.id).update(created_at=self.solved[1].created_at - timedelta(seconds=1))
        b = Balance.objects.create(miner=Miner.objects.all()[0], balance=int(-50e9), status="pending_withdrawal")
        Balance.objects.filter(id=b.id).update(created_at=self.solved[1].created_at - timedelta(seconds=1))

        for balance in Balance.objects.filter(created_at__lte=self.solved[1].created_at, status__in=["mature", "withdraw"]):
            balance_detail_content.append(str(BalanceSerializer(balance).data))

        aggregate()

        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 1)
        self.assertEqual(Balance.objects.filter(status="immature").count(), 1)

        for miner in Miner.objects.all():
            self.assertEqual(Balance.objects.filter(miner=miner, status="mature", balance=int(60e9)).count(), 1)
            self.assertEqual(Balance.objects.filter(miner=miner, status="withdraw", balance=int(-20e9)).count(), 1)

        for solved in self.solved[2:]:
            for miner in Miner.objects.all():
                self.assertEqual(Balance.objects.filter(share=solved, miner=miner, status="mature",
                                                        balance=int(30e9)).count(), 1)
                self.assertEqual(Balance.objects.filter(share=solved, miner=miner, status="withdraw",
                                                        balance=int(-10e9)).count(), 1)

        balance_detail_content = '\n'.join(sorted(balance_detail_content))

        for filename, expected_content in [(self.balance_detail_file, balance_detail_content)]:
            self.assertTrue(os.path.exists(filename))
            with open(filename, 'r') as file:
                content = file.read().rstrip()
                content = '\n'.join(sorted(content.split('\n')))
                self.assertEqual(expected_content, content)

    def tearDown(self):
        # restoring setting parameters
        Miner.objects.all().delete()
        Share.objects.all().delete()
        AggregateShare.objects.all().delete()
        for file in [self.balance_detail_file, self.shares_detail_file, self.shares_aggregate_file]:
            if os.path.exists(file):
                os.remove(file)


class GetMinerAddressTestCase(TestCase):
    """
    Test class for aggregation
    """

    def setUp(self):
        """
        creating a miners
        """
        self.miner = Miner.objects.create(public_key='miner')

    def test_miner_doesnt_have_address(self):
        """
        no address, return None
        """
        address = get_miner_payment_address(self.miner)
        self.assertEqual(address, None)

    def test_miner_has_several_withdraw_address_non_set(self):
        """
        several withdraw address, return the latest used one
        """
        selected = None
        for _ in range(5):
            selected = Address.objects.create(address_miner=self.miner, address=random_string(), category='withdraw')

        address = get_miner_payment_address(self.miner)
        self.assertEqual(address, selected.address)

    def test_miner_has_several_address_non_set(self):
        """
        several withdraw address, return the latest used one
        do not return addresses other than withdraw
        """
        selected = None
        for _ in range(5):
            selected = Address.objects.create(address_miner=self.miner, address=random_string(), category='withdraw')

        Address.objects.create(address_miner=self.miner, address=random_string(), category='lock')

        address = get_miner_payment_address(self.miner)
        self.assertEqual(address, selected.address)

    def test_miner_has_several_address_set_one(self):
        """
        several withdraw address
        do not return addresses other than withdraw
        miner has already selected one as payment address
        """
        for _ in range(5):
            Address.objects.create(address_miner=self.miner, address=random_string(), category='withdraw')

        Address.objects.create(address_miner=self.miner, address=random_string(), category='lock')

        self.miner.selected_address = Address.objects.filter(category='withdraw').order_by('last_used').first()
        self.miner.save()
        selected = self.miner.selected_address

        address = get_miner_payment_address(self.miner)
        self.assertEqual(address, selected.address)

    def tearDown(self):
        Miner.objects.all().delete()
        Address.objects.all().delete()
