import random
import string
import uuid
from django.test import TestCase, Client, TransactionTestCase
from django.utils import timezone
from mock import patch
from core.models import Miner, Share
import core.utils
from .views import *
from datetime import datetime, timedelta
from ErgoAccounting.settings import ERGO_EXPLORER_ADDRESS
import json
import os


def random_string(length=10):
    """Generate a random string of fixed length """
    letters = string.ascii_lowercase + string.ascii_uppercase + string.digits
    return ''.join(random.choice(letters) for i in range(length))


class ShareTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        Miner.objects.create(public_key="2", nick_name="Parsa")

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
        self.client.post('/shares/', data, format='json')
        self.assertTrue(Share.objects.filter(share=share).exists())

    def test_validad_unsolved_share(self):
        """
        test if a non-solution submitted share must store with None in transaction_id and block_height
        :return:
        """
        share = uuid.uuid4().hex
        data = {'share': share,
                'miner': '1',
                'nonce': '1',
                "transaction_id": "this is a transaction id",
                "block_height": 40404,
                'status': 'valid',
                'difficulty': 123456}
        self.client.post('/shares/', data, format='json')
        self.assertEqual(Share.objects.filter(share=share).count(), 1)
        transaction = Share.objects.filter(share=share).first()
        self.assertIsNone(transaction.transaction_id)
        self.assertIsNone(transaction.block_height)


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
        return dict(Balance.objects.filter(share=sh).values_list('miner__public_key').annotate(models.Sum('balance')))

    def test_prop_with_first_solved_share(self):
        """
        in this scenario we call prop function with first solved share in database.
        we generate 15 share 7 are invalid 7 are valid and one is solved

        :return:
        """
        share = self.shares[14]
        self.prop(share)
        balances = self.get_share_balance(share)
        self.assertEqual(balances, {'0': 24.375, '1': 16.25, '2': 24.375})

    def test_prop_between_two_solved_shares(self):
        """
        this function check when we have two solved share and some valid share between them.
        in this case we have 9 valid share 9 invalid share and one solved share.
        :return:
        """
        share = self.shares[34]
        self.prop(share)
        balances = self.get_share_balance(share)
        self.assertEqual(balances, {'0': 19.5, '1': 26.0, '2': 19.5})

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
            self.assertEqual(balances, {'0': 19.5, '1': 26.0, '2': 19.5})

    def test_prop_with_first_solved_share_with_fee(self):
        """
        in this scenario we call prop function with first solved share in database.
        we generate 15 share 7 are invalid 7 are valid and one is solved

        :return:
        """
        Configuration.objects.create(key='FEE', value='10')
        share = self.shares[14]
        self.prop(share)
        balances = self.get_share_balance(share)
        self.assertEqual(balances, {'0': 20.625, '1': 13.75, '2': 20.625})

    def test_prop_between_two_solved_shares_with_fee(self):
        """
        this function check when we have two solved share and some valid share between them.
        in this case we have 9 valid share 9 invalid share and one solved share.
        :return:
        """
        Configuration.objects.create(key='FEE', value='10')
        share = self.shares[34]
        self.prop(share)
        balances = self.get_share_balance(share)
        self.assertEqual(balances, {'0': 16.5, '1': 22.0, '2': 16.5})

    def test_prop_with_with_no_valid_share_with_fee(self):
        """
        in this case we test when no valid share between solved shares
        in this case we only have one share and reward must be minimum of MAX_REWARD and TOTAL_REWARD
        :return:
        """
        Configuration.objects.create(key='FEE', value='10')
        share = self.shares[35]
        self.prop(share)
        balances = self.get_share_balance(share)
        reward_value = min(Configuration.objects.MAX_REWARD, Configuration.objects.TOTAL_REWARD - Configuration.objects.FEE)
        self.assertEqual(balances, {'2': float(reward_value)})

    def test_prop_called_multiple_with_fee(self):
        """
        in this case we call prop function 5 times. after each call balance for each miner must be same as expected
        :return:
        """
        Configuration.objects.create(key='FEE', value='10')
        share = self.shares[34]
        for i in range(5):
            self.prop(share)
            balances = self.get_share_balance(share)
            self.assertEqual(balances, {'0': 16.5, '1': 22.0, '2': 16.5})

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
            Balance.objects.create(miner=miners[0], share=shares[0], balance=100, status=1),
            Balance.objects.create(miner=miners[0], share=shares[1], balance=200, status=1),
            Balance.objects.create(miner=miners[0], share=shares[2], balance=300, status=2),
            Balance.objects.create(miner=miners[0], share=shares[3], balance=400, status=3),
            Balance.objects.create(miner=miners[1], share=shares[4], balance=500, status=2),
            Balance.objects.create(miner=miners[1], share=shares[5], balance=600, status=2),
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
        expected_response = []
        # create a json like dictionary for any key in keys
        for key in keys:
            Configuration.objects.create(key=key, value='1')
            expected_response.append({'key': key, 'value': '1'})
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
        self.PPLNS = RewardAlgorithm.get_instance().perform_logic
        # create miners lists
        miners = [Miner.objects.create(nick_name="miner %d" % i, public_key=str(i)) for i in range(3)]
        # create shares list
        shares = [Share.objects.create(
            share=str(i),
            miner=miners[int(i / 2) % 3],
            status="solved" if i in [14, 44, 45] else "valid" if i % 2 == 0 else "invalid",
            difficulty=1000
        )for i in range(46)]
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
        return dict(Balance.objects.filter(share=sh).values_list('miner__public_key').annotate(models.Sum('balance')))

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
        self.assertEqual(balances, {'0': 24.375, '1': 24.375, '2': 16.25})

    def test_pplns_with_more_than_n_shares(self):
        """
        this function check when we have two solved share and some valid share between them.
        in this case we have 9 valid share 9 invalid share and one solved share.
        :return:
        """
        share = self.shares[44]
        self.PPLNS(share)
        balances = self.get_share_balance(share)
        self.assertEqual(balances, {'0': 19.5, '1': 26.0, '2': 19.5})

    def test_pplns_multiple(self):
        """
        in this case we call pplns function 5 times. after each call balance for each miner must be same as expected
        :return:
        """
        share = self.shares[44]
        for i in range(5):
            self.PPLNS(share)
            balances = self.get_share_balance(share)
            self.assertEqual(balances, {'0': 19.5, '1': 26.0, '2': 19.5})

    def test_pplns_with_lower_amount_of_shares_with_fee(self):
        """
        in this case we have 8 shares and pplns must work with this amount of shares with fee: 10
        :return:
        """
        share = self.shares[14]
        Configuration.objects.create(key='FEE', value='10')
        self.PPLNS(share)
        balances = self.get_share_balance(share)
        self.assertEqual(balances, {'0': 20.625, '1': 20.625, '2': 13.75})

    def test_pplns_with_more_than_n_shares_with_fee(self):
        """
        this function check when we have two solved share and some valid share between them.
        in this case we have 9 valid share 9 invalid share and one solved share.
        :return:
        """
        share = self.shares[44]
        Configuration.objects.create(key='FEE', value='10')
        self.PPLNS(share)
        balances = self.get_share_balance(share)
        self.assertEqual(balances, {'0': 16.5, '1': 22.0, '2': 16.5})

    def test_pplns_multiple_with_fee(self):
        """
        in this case we call pplns function 5 times. after each call balance for each miner must be same as expected
        :return:
        """
        share = self.shares[44]
        Configuration.objects.create(key='FEE', value='10')
        for i in range(5):
            self.PPLNS(share)
            balances = self.get_share_balance(share)
            self.assertEqual(balances, {'0': 16.5, '1': 22.0, '2': 16.5})

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

        Miner.objects.create(nick_name="moein", public_key="12345678976543", created_at=datetime(2019, 12, 22, 8, 33, 45, 395985),
                             updated_at=datetime(2019, 12, 22, 8, 33, 45, 395985))
        Miner.objects.create(nick_name="amir", public_key="869675768342", created_at=datetime(2019, 12, 23, 8, 33, 45, 395985),
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

    def mocked_get_request(*args, **kwargs):
        """
        mock requests with method get for urls 'blocks'
        """
        class MockResponse:
            def __init__(self, json_data):
                self.json_data = json_data

            def json(self):
                return self.json_data
        if args[0] == ERGO_EXPLORER_ADDRESS + "/blocks/?offset=1&limit=4":
            with open("core/data_mock_testing/test_get_offset_limit.json", "r") as read_file:
                response = json.load(read_file)
            return MockResponse(response)
        if "/blocks/?sortBy=height&sortDirection=asc" in args[0]:
            with open("core/data_mock_testing/test_get_sortBy_sortDirection.json", "r") as read_file:
                response = json.load(read_file)
            return MockResponse(response)
        if "/blocks/?endDate=1579811399999&startDate=1577824200000" in args[0]:
            with open("core/data_mock_testing/test_get_period_time.json", "r") as read_file:
                response = json.load(read_file)
            return MockResponse(response)

        return MockResponse(None)

    @patch("requests.get", side_effect=mocked_get_request)
    def test_get_offset_limit(self, mock):
        """
        Send a http 'get' request for get blocks with => offset = 1 and limit = 4 in this test, we must get 4 blocks and
         set the inPool  flag to True if it has been mined by the miner in the pool
        """

        # Send a http 'get' request for get blocks with limits => offset = 1 and limit = 4
        response = self.client.get('/blocks/?offset=1&limit=4')
        # check the status of the response
        self.assertEqual(response.status_code, 200)
        response = response.json()
        # check the content of the response
        # For check flag ' inPool'
        blocks_pool = [3, 2]
        blocks_pool_result = []
        # For Check true block heights
        heights = [4, 3, 2, 1]
        heights_result = []
        for res in response['results']['items']:
            heights_result.append(res['height'])
            if res['inPool']:
                blocks_pool_result.append(res['height'])

        self.assertEqual(heights_result, heights)
        self.assertEqual(blocks_pool_result, blocks_pool)

    @patch("requests.get", side_effect=mocked_get_request)
    def test_get_sort_by_direction(self, mock):
        """
        Send a http 'get' request for get blocks with sort according to height and direction asc.
        """

        # Send a http 'get' request for get blocks with sort according to height and Direction asc
        response = self.client.get('/blocks/?sortBy=height&sortDirection=asc')
        # check the status of the response
        self.assertEqual(response.status_code, 200)
        response = response.json()
        # check the content of the response
        # For check flag ' inPool'
        blocks_pool = [2, 3]
        blocks_pool_result = []
        # For Check true block heights
        heights = [1, 2, 3, 4]
        heights_result = []
        for res in response['results']['items']:
            heights_result.append(res['height'])
            if res['inPool']:
                blocks_pool_result.append(res['height'])

        self.assertEqual(heights_result, heights)
        self.assertEqual(blocks_pool_result, blocks_pool)

    @patch("requests.get", side_effect=mocked_get_request)
    def test_get_period_time(self, mock):
        """
        Send a http 'get' request for get blocks in period time. in this test we send endDate=1579811399999 and
         startDate=1577824200000 and we want to get blocks between this times.
        """
        # send a http 'get' request for get blocks in period time.
        response = self.client.get('/blocks/?endDate=1579811399999&startDate=1577824200000')
        # check the status of the response
        self.assertEqual(response.status_code, 200)
        response = response.json()
        # check the content of the response
        # For check flag ' inPool'
        blocks_pool = [3, 2]
        blocks_pool_result = []
        # For Check true block heights
        heights = [4, 3, 2, 1]
        heights_result = []
        for res in response['results']['items']:
            heights_result.append(res['height'])
            if res['inPool']:
                blocks_pool_result.append(res['height'])

        self.assertEqual(heights_result, heights)
        self.assertEqual(blocks_pool_result, blocks_pool)


