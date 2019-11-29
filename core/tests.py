from django.test import TestCase, Client
from datetime import datetime, timedelta
import random
import string
from .views import *
from .utils import *


def random_string(length=10):
    """Generate a random string of fixed length """
    letters = string.ascii_lowercase + string.ascii_uppercase + string.digits
    return ''.join(random.choice(letters) for i in range(length))


'''
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
        self.client.post('/shares/', data, format='json')
        self.assertTrue(mocked_call_prop.isCalled())

    @patch('core.utils.prop')
    def test_prop_not_call(self, mocked_not_call_prop):
        mocked_not_call_prop.return_value = None
        core.utils.prop(None)
        data = {'share': '1',
                'miner': '1',
                'nonce': '1',
                'status': '2'}
        self.client.post('/shares/', data, format='json')
        self.assertFalse(mocked_not_call_prop.isCalled())
'''


class PropFunctionTest(TestCase):
    """
    Test class for prop function
    In all the test functions we assume that 'MAX_REWARD' is 35erg and 'TOTAL_REWARD' is 65erg.
    So in other situations the results may not be valid.
    """

    def setUp(self):
        """
        setUp function to create 5 miners for testing prop function
        :return:
        """
        # define a list of miner objects (it is used for bulk_create function)
        miners = list()
        # create 5 miners with nick_name as miner and public_key as '0', '1', '2', '3' and '4'
        for i in range(5):
            miners.append(Miner(nick_name='miner', public_key=str(i)))
        # create and save miner objects to test database
        Miner.objects.bulk_create(miners)

    def test_prop_function_with_0_solved_share(self):
        """
        In this scenario we test the functionality of prop function when there isn't any 'solved' share in the database.
        We have 5 miners and 10 shares which are not 'solved'.
        Then we call 'prop' function for one of the shares mentioned above and
        we expect it to not exist any balance object corresponding to that 'not solved' input share.
        :return:
        """
        # define a list of shares (it is used in bulk_create function)
        shares = list()
        # create 10 shares with miners which are created in setUp function
        for i in range(10):
            # each share is associated to a particular miner ( i % 5 )
            # the status of each share will be 2, 3 or 4
            shares.append(
                Share(share=str(i), miner=Miner.objects.get(public_key=str(i % 5)), nonce=0, status=(i % 3) + 2))
        # create share objects using shares list and save them to the test database
        Share.objects.bulk_create(shares)
        # call prop function for an invalid (not solved) share, 8th for example
        prop(shares[7])
        # use an assertIsNone to check the correctness of prop functionality
        # in this case we expect no balance associated to the input share
        self.assertIsNone(Balance.objects.filter(share=shares[7]).first())

    def test_prop_function_with_1_solved_share(self):
        """
        In this scenario we test the functionality of prop function
        when there is only one 'solved' share in the database.
        We have 5 miners and 16 shares which all of them are 'valid' except the last one.
        Then we call 'prop' function for the only 'solved' share mentioned above and
        We expect the amount of balances in following order based on our 5 miners
        16.25, 12.1875, 12.1875, 12.1875, 12.1875
        :return:
        """
        # define a list of shares (it is used in bulk_create function)
        shares = list()
        # create 16 shares with miners which are created in setUp function
        for i in range(16):
            # each share is associated to a particular miner ( i % 5 )
            shares.append(
                Share(share=str(i), miner=Miner.objects.get(public_key=str(i % 5)), nonce=0, status=2))
        # change only the status of last share to 'solved' (we want to check prop function in a case with only on
        # solved share)
        shares[15].status = 1
        # create share objects using shares list and save them to the test database
        Share.objects.bulk_create(shares)
        # call prop function for the last and the only 'solved' share
        prop(shares[15])
        # retrieve all Balance objects created after calling prop function
        balances = Balance.objects.filter(share=shares[15])
        # check the amount of balances with assertEqual
        self.assertEqual(balances[0].balance, 16.25)
        self.assertEqual(balances[1].balance, 12.1875)
        self.assertEqual(balances[2].balance, 12.1875)
        self.assertEqual(balances[3].balance, 12.1875)
        self.assertEqual(balances[4].balance, 12.1875)

    def test_prop_function_with_at_least_2_solved_shares(self):
        """
        In this scenario we test the functionality of prop function
        when there is at least two 'solved' share in the database
        and we call the function with a 'solved' share except the first 'solved' share.
        We have 5 miners and 10 shares.
        The second and the 8th share are 'solved' and
        the fifth share is 'invalid' and
        the 7th share which is 'repetitious' while
        the other shares are 'valid'.
        Then we call 'prop' function for the 9th share and
        we expect the amount of balances in following order based on our 5 miners:
        16.25, 32.5, 16.25
        :return:
        """
        # define a list of shares (it is used in bulk_create function)
        shares = list()
        # create 10 shares with miners which are created in setUp function
        for i in range(10):
            # each share is associated to a particular miner ( i % 5 )
            shares.append(
                Share(share=str(i), miner=Miner.objects.get(public_key=str(i % 5)), nonce=0, status=2))
        # change the status of the second and the 8th share to 'solved' for testing prop function
        shares[1].status = 1
        shares[7].status = 1
        # change the status of the 5th share to 'invalid'
        shares[4].status = 3
        # change the status of the 7th share to 'repetitious'
        shares[6].status = 4
        # create share objects using shares list and save them to the test database
        Share.objects.bulk_create(shares)
        # get the last 'solved' share
        last_solved_share = Share.objects.filter(status=1).order_by('-created_at')[0]
        # call prop function for the last 'solved' share
        prop(last_solved_share)
        # retrieve all Balance objects created after calling prop function
        balances = Balance.objects.filter(share=last_solved_share)
        # check the amount of balances using assertEqual
        self.assertEqual(balances[0].balance, 16.25)
        self.assertEqual(balances[1].balance, 32.5)
        self.assertEqual(balances[2].balance, 16.25)

    def test_prop_function_with_invalid_input_share(self):
        """
        In this scenario we test the functionality of prop function when
        the input share is invalid (it is 'valid', 'invalid' or 'repetitious').
        We have 5 miners and 10 shares.
        The first and the last shares are 'solved' and
        the other shares are not 'solved'.
        Then we call 'prop' function for one of the not 'solved' shares and
        we expect it to not exist any balance object corresponding to that not 'solved' input share
        :return:
        """
        # define a list of shares (it is used in bulk_create function)
        shares = list()
        # create 10 shares with miners which are created in setUp function
        for i in range(10):
            # each share is associated to a particular miner ( i % 5 )
            # the status of each share will be 2, 3 or 4
            shares.append(
                Share(share=str(i), miner=Miner.objects.get(public_key=str(i % 5)), nonce=0, status=(i % 3) + 2))
        # change the status of the first and the last shares to 'solved'
        shares[0].status = 1
        shares[9].status = 1
        # create share objects using shares list and save them to the test database
        Share.objects.bulk_create(shares)
        # call prop function for an invalid (not solved) share, 6th for example
        prop(shares[5])
        # use an assertIsNone to check the correctness of prop functionality
        # in this case we expect no balance associated to the input share
        self.assertIsNone(Balance.objects.filter(share=shares[5]).first())

    def test_prop_function_2_times_with_same_share(self):
        """
        In this scenario we test the functionality of prop function
        when we call it 2 times with a same input share.
        We have 5 miners and 23 shares.
        The first ,the 8th and the 20th shares are 'solved' and
        the fifth and the last share are 'invalid' and
        the 17th share which is 'repetitious' while
        the other shares are 'valid'.
        Then we call 'prop' function for the 2th share 2 times and
        we expect it to not exist repetitive balances.
        :return:
        """
        # define a list of shares (it is used in bulk_create function)
        shares = list()
        # create 23 shares with miners which are created in setUp function
        for i in range(23):
            # each share is associated to a particular miner ( i % 5 )
            shares.append(
                Share(share=str(i), miner=Miner.objects.get(public_key=str(i % 5)), nonce=0, status=2))
        # change the status of the first, the 8th and 20th share to 'solved'
        shares[0].status = 1
        shares[7].status = 1
        shares[19].status = 1
        # change the status of the 5th and the last share to 'invalid'
        shares[4].status = 3
        shares[22].status = 3
        # change the status of the 17th share to 'repetitious'
        shares[16].status = 4
        # create share objects using shares list and save them to the test database
        Share.objects.bulk_create(shares)
        # get the last solved share
        last_solved_share = shares[19]
        # call prop function for the last solved share for the first time
        prop(last_solved_share)
        # call prop function for the last solved share for the second time
        prop(last_solved_share)
        # retrieve all Balance objects created after calling prop function
        balances = Balance.objects.filter(share=last_solved_share)
        # check the number of Balance objects created after calling prop function using assertEqual
        self.assertEqual(balances.count(), 5)

    def test_prop_function_upper_bound(self):
        """
        In this scenario we want to test the functionality of 'prop' function while
        considering the upper bound 'MAX_REWARD' is necessary.
        We have 5 miners and 3 shares.
        The first and the last share are 'solved'.
        The middle share is 'valid'.
        We expect the reward to not be 65erg in this case.
        :return:
        """
        # define a list of shares (it is used in bulk_create function)
        shares = list()
        # create 3 shares with miners which are created in setUp function
        for i in range(3):
            # each share is associated to a particular miner ( i % 5 )
            shares.append(
                Share(share=str(i), miner=Miner.objects.get(public_key=str(i % 5)), nonce=0, status=1))
        # change the status of the middle share to 'valid'
        shares[0].status = 2
        # create share objects using shares list and save them to the test database
        Share.objects.bulk_create(shares)
        # get the last 'solved' share
        last_solved_share = Share.objects.filter(status=1).order_by('-created_at').first()
        # call prop function for the last solved share
        prop(last_solved_share)
        # retrieve all Balance objects created after calling prop function
        balances = Balance.objects.filter(share=last_solved_share)
        # check the amount of the balance to not be 65erg
        self.assertNotEqual(balances[0], 65.0)

    def test_prop_function_0_valid_share_between_2_solved_shares(self):
        """
        In this scenario we want to test the functionality of 'prop' function when
        is no 'valid' share between two 'solved' shares.
        We have 5 miners and 1000 shares.
        The first and the last share are 'solved' while
        the other shares are 'invalid' or 'repetitious'.
        Then we call the 'prop' function for the last 'solved' share and
        we expect that the number of Balance objects be 1 and the amount of the balance be 35erg (MAX_REWARD).
        :return:
        """
        # define a list of shares (it is used in bulk_create function)
        shares = list()
        # create 1000 shares with miners which are created in setUp function
        for i in range(1000):
            # each share is associated to a particular miner ( i % 5 ) and its status is 'invalid'
            shares.append(
                Share(share=str(i), miner=Miner.objects.get(public_key=str(i % 5)), nonce=0, status=(i % 2) + 3))
        # change the status of the first share and the last share to 'solved'
        shares[0].status = 1
        shares[999].status = 1
        # create share objects using shares list and save them to the test database
        Share.objects.bulk_create(shares)
        # get the last 'solved' share
        last_solved_share = Share.objects.filter(status=1).order_by('-created_at').first()
        # call prop function for the last 'solved' share
        prop(last_solved_share)
        # retrieve all Balance objects created after calling prop function
        balances = Balance.objects.filter(share=last_solved_share)
        # check the number of the Balance objects to be 1
        self.assertEqual(balances.count(), 1)
        # check the amount of the balance to be 35erg
        self.assertEqual(balances[0].balance, 35.0)

    def test_prop_function_0_share_between_2_solved_shares(self):
        """
        In this scenario we want to test the functionality of 'prop' function when
        is no share between two 'solved' shares.
        We have 5 miners and 10000 shares.
        The 53th and the 54th share are 'solved' while
        the other shares are not 'solved'.
        Then we call the 'prop' function for the last 'solved' share and
        we expect that the number of Balance objects be 1 and the amount of the balance be 35erg (MAX_REWARD).
        :return:
        """
        # define a list of shares (it is used in bulk_create function)
        shares = list()
        # create 100 shares with miners which are created in setUp function
        for i in range(100):
            # each share is associated to a particular miner ( i % 5 ) and its status is 'invalid'
            shares.append(
                Share(share=str(i), miner=Miner.objects.get(public_key=str(i % 5)), nonce=0, status=(i % 3) + 2))
        # change the status of the 53th share and the 54th share to 'solved'
        shares[52].status = 1
        shares[53].status = 1
        # create share objects using shares list and save them to the test database
        Share.objects.bulk_create(shares)
        # get the last 'solved' share
        last_solved_share = shares[53]
        # call prop function for the last 'solved' share
        prop(last_solved_share)
        # retrieve all Balance objects created after calling prop function
        balances = Balance.objects.filter(share=last_solved_share)
        # check the number of the Balance objects to be 1
        self.assertEqual(balances.count(), 1)
        # check the amount of the balance to be 35erg
        self.assertEqual(balances[0].balance, 35.0)

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
            Share.objects.create(share=random_string(), miner=miners[0], nonce=random.randint(0, 1000), status=1,
                                 created_at=self.now),
            Share.objects.create(share=random_string(), miner=miners[0], nonce=random.randint(0, 1000), status=2,
                                 created_at=self.now + timedelta(minutes=1)),
            Share.objects.create(share=random_string(), miner=miners[0], nonce=random.randint(0, 1000), status=2,
                                 created_at=self.now + timedelta(minutes=2)),
            Share.objects.create(share=random_string(), miner=miners[0], nonce=random.randint(0, 1000), status=3,
                                 created_at=self.now + timedelta(minutes=3)),
            Share.objects.create(share=random_string(), miner=miners[1], nonce=random.randint(0, 1000), status=2,
                                 created_at=self.now + timedelta(minutes=4)),
            Share.objects.create(share=random_string(), miner=miners[1], nonce=random.randint(0, 1000), status=2,
                                 created_at=self.now + timedelta(minutes=5)),
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
            'round_shares': 4,
            'timestamp': self.now.strftime('%Y-%m-%d %H:%M:%S'),
            'users': {
                'abc': {
                    "round_shares": 2,
                    "immature": 300.0,
                    "mature": 300.0,
                    "withdraw": 400.0
                },
                'xyz': {
                    "round_shares": 2,
                    "immature": 0,
                    "mature": 1100.0,
                    "withdraw": 0
                }
            }
        }
        """
        response = self.client.get('/dashboard/').json()
        self.assertDictEqual(response, {
            'round_shares': 4,
            'timestamp': self.now.strftime('%Y-%m-%d %H:%M:%S'),
            'users': {
                'abc': {
                    "round_shares": 2,
                    "immature": 300.0,
                    "mature": 300.0,
                    "withdraw": 400.0
                },
                'xyz': {
                    "round_shares": 2,
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
        response = self.client.get('/dashboard/abc').json()
        self.assertDictEqual(response, {
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
        })


class ConfigurationAPITest(TestCase):
    """
    Test class for Configuration API
    This class has 3 test function based on 3 following general situations:
    1) using http 'get' method to retrieve a list of existing configurations
    2) using http 'post' method to create a new configuration
    3) using http 'post' method to update an existing configuration
    """

    def setUp(self):
        """
        setUp function for 'ConfigurationAPITest' class do nothing
        :return:
        """
        pass

    def test_Configuration_API_get_method_list(self):
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
        keys = [key for (key, temp) in KEY_CHOICES]
        # define expected response as an empty list
        expected_response = []
        # define an 'id' variable for expected response
        conf_id = 1
        # create a json like dictionary for any key in keys
        for key in keys:
            Configuration.objects.create(key=key, value=1)
            expected_response.append({'id': conf_id, 'key': key, 'value': 1.0})
            conf_id += 1
        # send a http 'get' request to the configuration endpoint
        response = self.client.get('/conf/')
        # check the status of the response
        self.assertEqual(response.status_code, 200)
        # check the content of the response
        self.assertEqual(response.json(), expected_response)

    def test_Configuration_API_post_method_create(self):
        """
        In this scenario we want to test the functionality of Configuration API when
        it is called by a http 'post' method to create a new configuration
        For this purpose we send a http 'post' method to create a new configuration with a non-existing key in database.
        We expect that the status code of response be '201' and
        the new configuration object exists in database with a value as below.
        :return:
        """
        # retrieve all possible keys for KEY_CHOICES
        keys = [key for (key, temp) in KEY_CHOICES]
        # send http 'post' request to the configuration endpoint and validate the result
        for key in keys:
            # send http 'post' request to the endpoint
            response = self.client.post('/conf/', {'key': key, 'value': 1})
            # check the status of the response
            self.assertEqual(response.status_code, 201)
            # retrieve the new created configuration from database
            configuration = Configuration.objects.get(key=key)
            # check whether the above object is created and saved to database or not
            self.assertIsNotNone(configuration)
            # check the value of the new created object
            self.assertEqual(configuration.value, 1)

    def test_Configuration_API_post_method_update(self):
        """
        In this scenario we want to test the functionality of Configuration API when
        it is called by a http 'post' method to update an existing configuration.
        For this purpose we send a http 'post' request for an existing configuration object in database.
        We expect that the status code of response be '201' and
        the new configuration object be updated in database with a new value as below.
        :return:
        """
        # retrieve all possible keys for KEY_CHOICES
        keys = [key for (key, temp) in KEY_CHOICES]
        # send http 'post' request to the configuration endpoint and validate the result
        for key in keys:
            # create a configuration object to check the functionality of 'post' method
            Configuration.objects.create(key=key, value=1)
            # send http 'post' request to the endpoint
            response = self.client.post('/conf/', {'key': key, 'value': 2})
            # check the status of the response
            self.assertEqual(response.status_code, 201)
            # retrieve the new created configuration from database
            configurations = Configuration.objects.filter(key=key)
            # check whether the above object is created and saved to database or not
            self.assertEqual(configurations.count(), 1)
            # check the value of the new created object
            self.assertEqual(configurations.first().value, 2)

    def tearDown(self):
        """
        tearDown function to delete all configuration objects
        :return:
        """
        # delete all configuration objects
        Configuration.objects.all().delete()
