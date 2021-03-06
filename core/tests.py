import json
import os
import random
import string
import uuid
from datetime import timedelta, datetime
from pydoc import locate
from urllib.parse import urlparse, urljoin

from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Sum, Max
from django.test import TestCase, Client, TransactionTestCase, override_settings
from django.test.client import RequestFactory
from django.utils import timezone
from django.utils.timezone import get_current_timezone
from django_otp.plugins.otp_totp.models import TOTPDevice
from mock import patch, call, mock_open
from rest_framework import status
from rest_framework.test import APIClient

from core.models import CONFIGURATION_KEY_CHOICE, AggregateShare, Share, Balance, Miner, Configuration, \
    CONFIGURATION_DEFAULT_KEY_VALUE, CONFIGURATION_KEY_TO_TYPE, \
    Address, MinerIP, ExtraInfo, TokenAuth as Token, HashRate, Transaction
from core.tasks import immature_to_mature, periodic_withdrawal, aggregate, handle_withdraw, \
    get_ergo_price, periodic_verify_blocks, periodic_calculate_hash_rate, handle_transactions
from core.utils import RewardAlgorithm, get_miner_payment_address
from core.views import TOTPDeviceViewSet


def random_string(length=10):
    """Generate a random string of fixed length """
    letters = string.ascii_lowercase + string.ascii_uppercase + string.digits
    return ''.join(random.choice(letters) for _ in range(length))


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
                'status': 'invalid',
                'parent_id': random_string(),
                'next_ids': [],
                'difficulty': 123456}
        self.client.post('/shares/', data, format='json')
        self.assertTrue(mocked_call_prop.isCalled())

    @patch('core.utils.RewardAlgorithm.get_instance')
    def test_prop_not_call(self, mocked_not_call_prop):
        mocked_not_call_prop.return_value = None
        data = {'share': '1',
                'miner': '1',
                'nonce': '1',
                'status': 'invalid',
                'parent_id': 'test',
                'next_ids': [],
                'path': '-1',
                'difficulty': 123456}
        data.update(self.addresses)
        self.client.post('/shares/', data, format='json')
        self.assertFalse(mocked_not_call_prop.called)
        self.assertEqual(Address.objects.filter(address_miner__public_key='1', address=self.addresses['miner_address'],
                                                category='miner').count(), 0)
        self.assertEqual(Address.objects.filter(address_miner__public_key='1', address=self.addresses['lock_address'],
                                                category='lock').count(), 0)
        self.assertEqual(
            Address.objects.filter(address_miner__public_key='1', address=self.addresses['withdraw_address'],
                                   category='withdraw').count(), 0)

    def test_solved_share_without_transaction_id(self):
        """
        test if a solution submitted without transaction id no solution must store in database
        :return:
        """
        share = uuid.uuid4().hex
        data = {'share': share,
                'miner': '1',
                'nonce': '1',
                'status': 'solved',
                'pow_identity': "test",
                'parent_id': 'test',
                'next_ids': [],
                'client_ip': '127.0.0.5',
                'path': '-1',
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
                'status': 'solved',
                'pow_identity': "test",
                'parent_id': 'test',
                'next_ids': [],
                'client_ip': '127.0.0.5',
                'path': '-1',
                'difficulty': 123456}
        data.update(self.addresses)
        self.client.post('/shares/', data, format='json')
        self.assertFalse(Share.objects.filter(share=share).exists())

    def test_solved_share_without_parent_id(self):
        """
        test if a solution submitted without parent_id no solution must store in database
        :return:
        """
        share = uuid.uuid4().hex
        data = {'share': share,
                'miner': '1',
                'nonce': '1',
                "transaction_id": "this is a transaction id",
                'status': 'valid',
                "block_height": 40404,
                'next_ids': [],
                'client_ip': '127.0.0.5',
                'path': '-1',
                'difficulty': 123456}
        data.update(self.addresses)
        self.client.post('/shares/', data, format='json')
        self.assertFalse(Share.objects.filter(share=share).exists())

    def test_solved_share_without_path(self):
        """
        test if a solution submitted without path no solution must store in database
        :return:
        """
        share = uuid.uuid4().hex
        data = {'share': share,
                'miner': '1',
                'nonce': '1',
                "transaction_id": "this is a transaction id",
                'status': 'valid',
                "block_height": 40404,
                'parent_id': 'test',
                'next_ids': [],
                'client_ip': '127.0.0.5',
                'difficulty': 123456}
        data.update(self.addresses)
        self.client.post('/shares/', data, format='json')
        self.assertFalse(Share.objects.filter(share=share).exists())

    def test_solved_share_without_pow(self):
        """
        test if a solution submitted must store in database
        :return:
        """
        share = uuid.uuid4().hex
        data = {"share": share,
                'miner': '1',
                'nonce': '1',
                "transaction_id": "this is a transaction id",
                "block_height": 40404,
                'status': 'solved',
                'parent_id': 'test',
                'next_ids': ['test'],
                'client_ip': '127.0.0.1',
                'path': '-1',
                'difficulty': 123456}
        data.update(self.addresses)
        self.client.post('/shares/', data, format='json')
        self.assertFalse(Share.objects.filter(share=share).exists())

    def test_solved_share(self):
        """
        test if a solution submitted must store in database and save last ip in field ip
        :return:
        """
        share = uuid.uuid4().hex
        data = {"share": share,
                "miner": "1",
                "nonce": "1",
                "transaction_id": "this is a transaction id",
                "block_height": 40404,
                "status": "solved",
                "pow_identity": "test",
                "parent_id": "test",
                "next_ids": ["test"],
                "client_ip": "127.0.0.5",
                "path": "-1",
                "difficulty": 123456,
                "withdraw_address": "test",
                "miner_address": "test",
                "lock_address": "test"
                }
        data.update(self.addresses)
        self.client.post('/shares/', data, format='json')

        data = {"share": share + 'bhkk',
                'miner': '1',
                'nonce': '1',
                "transaction_id": "gffdthis is a transaction id",
                "block_height": 404054,
                'status': 'solved',
                'pow_identity': "test",
                'parent_id': 'test',
                'next_ids': ['test'],
                'client_ip': '127.0.0.1',
                'path': '-1',
                'difficulty': 123456}
        data.update(self.addresses)
        self.client.post('/shares/', data, format='json')

        self.assertTrue(Share.objects.filter(share=share).exists())
        self.assertTrue(Share.objects.filter(parent_id='test').exists())
        self.assertTrue(MinerIP.objects.filter(ip='127.0.0.1').exists())

    def test_valid_share_without_block_height(self):
        """
        test if a valid share submitted without block height no solution must store in database
        :return:
        """
        share = uuid.uuid4().hex
        data = {'share': share,
                'miner': '1',
                'nonce': '1',
                'status': 'valid',
                'parent_id': 'test',
                'next_ids': [],
                'client_ip': '127.0.0.5',
                'path': '-1',
                'difficulty': 123456}
        data.update(self.addresses)
        self.client.post('/shares/', data, format='json')
        self.assertFalse(Share.objects.filter(share=share).exists())

    def test_miner_ip_exist(self):
        """
        test if a ip of miner exist should be update timestamp to updated_at
        :return:
        """
        share = uuid.uuid4().hex
        miner = Miner.objects.get(public_key="2")
        client = MinerIP.objects.create(miner=miner, ip='127.0.0.1')
        data = {"share": share,
                'miner': '2',
                'nonce': '1',
                "transaction_id": "this is a transaction id",
                "block_height": 40404,
                'status': 'solved',
                'pow_identity': "test",
                'parent_id': 'test',
                'next_ids': ['test'],
                'client_ip': '127.0.0.1',
                'path': '-1',
                'difficulty': 123456}
        data.update(self.addresses)
        self.client.post('/shares/', data, format='json')
        client_update = MinerIP.objects.filter(miner=miner)[0].updated_at
        self.assertGreater(client_update, client.updated_at)

    def test_miner_exist(self):
        """
        test if a miner exist should be create a new object from MinerIP not override
        :return:
        """
        share = uuid.uuid4().hex
        miner = Miner.objects.get(public_key="2")
        MinerIP.objects.create(miner=miner, ip='127.0.0.1')
        data = {"share": share,
                'miner': '2',
                'nonce': '1',
                "transaction_id": "this is a transaction id",
                "block_height": 40404,
                'status': 'solved',
                'pow_identity': "test",
                'parent_id': 'test',
                'next_ids': ['test'],
                'client_ip': '127.0.0.2',
                'path': '-1',
                'difficulty': 123456}
        data.update(self.addresses)
        self.client.post('/shares/', data, format='json')
        self.assertEqual(MinerIP.objects.filter(miner=miner).count(), 2)

    def test_validate_unsolved_share_update_last_used(self):
        """
        test if a non-solution submitted share must store with None in transaction_id
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
                'parent_id': 'test',
                'next_ids': [],
                'client_ip': '127.0.0.1',
                'path': '-1',
                'status': 'valid',
                'difficulty': 123456,
                "pow_identity": "test"}
        data.update(self.addresses)
        self.client.post('/shares/', data, format='json')
        self.assertEqual(Share.objects.filter(share=share).count(), 1)
        transaction = Share.objects.filter(share=share).first()
        self.assertIsNone(transaction.transaction_id)
        self.assertEqual(Address.objects.filter(address_miner__public_key='2', address=self.addresses['miner_address'],
                                                category='miner').count(), 1)
        self.assertEqual(Address.objects.filter(address_miner__public_key='2', address=self.addresses['lock_address'],
                                                category='lock').count(), 1)
        self.assertEqual(
            Address.objects.filter(address_miner__public_key='2', address=self.addresses['withdraw_address'],
                                   category='withdraw').count(), 1)
        self.assertTrue(Address.objects.filter(address_miner__public_key='2', address=self.addresses['miner_address'],
                                               category='miner').first().last_used > miner_last_used)
        self.assertEqual(Address.objects.filter(address_miner__public_key='2', address=self.addresses['lock_address'],
                                                category='lock').first().last_used, lock_last_used)
        self.assertEqual(
            Address.objects.filter(address_miner__public_key='2', address=self.addresses['withdraw_address'],
                                   category='withdraw').first().last_used, withdraw_last_used)

    def test_validate_invalid_share_do_not_update_last_used(self):
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
                'client_ip': '127.0.0.1',
                'status': 'invalid'
                }
        data.update(self.addresses)
        self.client.post('/shares/', data, format='json')
        self.assertEqual(Address.objects.filter(address_miner__public_key='2', address=self.addresses['miner_address'],
                                                category='miner').count(), 1)
        self.assertEqual(Address.objects.filter(address_miner__public_key='2', address=self.addresses['lock_address'],
                                                category='lock').count(), 1)
        self.assertEqual(
            Address.objects.filter(address_miner__public_key='2', address=self.addresses['withdraw_address'],
                                   category='withdraw').count(), 1)
        self.assertTrue(Address.objects.filter(address_miner__public_key='2', address=self.addresses['miner_address'],
                                               category='miner').first().last_used == miner_last_used)
        self.assertTrue(Address.objects.filter(address_miner__public_key='2', address=self.addresses['lock_address'],
                                               category='lock').first().last_used == lock_last_used)
        self.assertTrue(
            Address.objects.filter(address_miner__public_key='2', address=self.addresses['withdraw_address'],
                                   category='withdraw').first().last_used == withdraw_last_used)

    def tearDown(self):
        Address.objects.all().delete()
        Miner.objects.all().delete()
        Share.objects.all().delete()
        Balance.objects.all().delete()
        Configuration.objects.all().delete()


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

    def test_prop_called_multiple_with_different_shares(self):
        """
        in this case we call prop function 5 times. after first call, miners shares changes
        so in second call balances must be changed
        :return:
        """
        Configuration.objects.create(key='MAX_REWARD', value=int(65e9))
        share = self.shares[34]
        self.prop(share)
        balances = self.get_share_balance(share)
        self.assertEqual(balances, {'0': int(19.5e9), '1': int(26.0e9), '2': int(19.5e9)})

        cur = Share.objects.create(miner=Miner.objects.get(public_key='1'), status='valid', difficulty=10000)
        cur.created_at = share.created_at - timedelta(seconds=1)
        cur.save()
        self.prop(share)
        cur_balances = self.get_share_balance(share)
        self.assertEqual(cur_balances, {'0': int(9.75e9), '1': int(45.5e9), '2': int(9.75e9)})
        for miner_id in cur_balances:
            balance = Balance.objects.filter(miner__public_key=miner_id,
                                             balance=cur_balances[miner_id] - balances[miner_id],
                                             status='immature', share=share)
            self.assertEqual(balance.count(), 1)

    def test_prop_with_first_solved_share_with_fee(self):
        """
        in this scenario we call prop function with first solved share in database.
        we generate 15 share 7 are invalid 7 are valid and one is solved

        :return:
        """
        reward = RewardAlgorithm.get_instance().get_reward_to_share()
        Configuration.objects.filter(key='FEE_FACTOR').update(value=str(10e9 / reward))
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
        Configuration.objects.filter(key='FEE_FACTOR').delete()
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
        Balance.objects.all().delete()
        Share.objects.all().delete()
        Miner.objects.all().delete()


class UserApiTestCase(TestCase):
    def setUp(self) -> None:
        Configuration.objects.create(key='MAX_WITHDRAW_THRESHOLD', value=str(int(100e9)))
        Configuration.objects.create(key='MIN_WITHDRAW_THRESHOLD', value=str(int(1e9)))

        # creating 10 miners
        pks = [random_string().lower() for _ in range(10)]
        for pk in pks:
            Miner.objects.create(public_key=pk)

        self.miners = list(Miner.objects.all())
        # by default every miner has 80 erg balance
        for miner in Miner.objects.all():
            Balance.objects.create(miner=miner, balance=int(100e9), status="mature")
            Balance.objects.create(miner=miner, balance=int(-20e9), status="withdraw")

        self.balances = list(Balance.objects.all())

        self.factory = RequestFactory()
        User.objects.create_user(username='test', password='test')

        self.client = APIClient()
        self.client.login(username='test', password='test')

        # Create two miner; abc and xyz
        cur_miners = [
            Miner.objects.create(public_key='abc', nick_name='ABC'),
            Miner.objects.create(public_key='xyz', nick_name='XYZ')
        ]

        # Set current time
        self.now = datetime.now()

        # Create shares
        shares = [
            Share.objects.create(share=random_string(), miner=cur_miners[0], status="solved",
                                 created_at=self.now, difficulty=1000),
            Share.objects.create(share=random_string(), miner=cur_miners[0], status="valid",
                                 created_at=self.now + timedelta(minutes=1), difficulty=98761234),
            Share.objects.create(share=random_string(), miner=cur_miners[0], status="valid",
                                 created_at=self.now + timedelta(minutes=2), difficulty=54329876),
            Share.objects.create(share=random_string(), miner=cur_miners[0], status="invalid",
                                 created_at=self.now + timedelta(minutes=3), difficulty=1000),
            Share.objects.create(share=random_string(), miner=cur_miners[1], status="valid",
                                 created_at=self.now + timedelta(minutes=4), difficulty=1234504321),
            Share.objects.create(share=random_string(), miner=cur_miners[1], status="valid",
                                 created_at=self.now + timedelta(minutes=5), difficulty=67890987),
        ]

        # base time for actions hash_rate and share
        time = datetime(2020, 1, 1, 8, 0, 20, 395985, tzinfo=timezone.utc)
        # create miner for actions hash_rate, share, income
        self.miner_actions = Miner.objects.create(public_key='hash', nick_name='hash')
        # Create shares for actions hash_rate, share, income
        shares_actions = [
            Share.objects.create(share=random_string(), miner=self.miner_actions, status="solved",
                                 difficulty=1000, block_height=1006),
            Share.objects.create(share=random_string(), miner=self.miner_actions, status="solved",
                                 difficulty=98761234, block_height=1005),
            Share.objects.create(share=random_string(), miner=self.miner_actions, status="valid",
                                 difficulty=54329876, block_height=1004),
            Share.objects.create(share=random_string(), miner=self.miner_actions, status="invalid",
                                 difficulty=1000, block_height=1003),
            Share.objects.create(share=random_string(), miner=self.miner_actions, status="solved",
                                 difficulty=1234504321, block_height=1002),
            Share.objects.create(share=random_string(), miner=self.miner_actions, status="solved",
                                 difficulty=67890987, block_height=1001),
        ]
        # Set timestamp for create_at shares
        for i, share in enumerate(shares_actions):
            if i == 1:
                share.created_at = time - timedelta(hours=6)
            else:
                share.created_at = time + timedelta(minutes=i)
            share.save()
        # Create balances for action income
        Balance.objects.create(miner=self.miner_actions, share=shares_actions[0], balance=100, status="immature")
        Balance.objects.create(miner=self.miner_actions, share=shares_actions[1], balance=200, status="immature")
        Balance.objects.create(miner=self.miner_actions, share=shares_actions[1], balance=300, status="mature")
        Balance.objects.create(miner=self.miner_actions, share=shares_actions[2], balance=300, status="mature")
        Balance.objects.create(miner=self.miner_actions, share=shares_actions[4], balance=500, status="mature")
        Balance.objects.create(miner=self.miner_actions, share=shares_actions[5], balance=600, status="mature")

        balance_actions = [
            Balance.objects.create(miner=self.miner_actions, balance=-400, tx_id="1234", status="withdraw",
                                   max_height=1234),
            Balance.objects.create(miner=self.miner_actions, balance=-600, tx_id="765", status="withdraw",
                                   max_height=1235),
            Balance.objects.create(miner=self.miner_actions, balance=-200, tx_id="876", status="withdraw",
                                   max_height=1236),
        ]
        # Set timestamp for create_at shares
        for i, balance in enumerate(balance_actions):
            if i == 1:
                balance.created_at = time - timedelta(days=4)
            else:
                balance.created_at = time - timedelta(hours=i)
            balance.save()

        # Create balances
        Balance.objects.create(miner=cur_miners[0], share=shares[0], balance=100, status="immature")
        Balance.objects.create(miner=cur_miners[0], share=shares[1], balance=200, status="immature")
        Balance.objects.create(miner=cur_miners[0], share=shares[2], balance=300, status="mature")
        Balance.objects.create(miner=cur_miners[0], balance=-400, status="withdraw")
        Balance.objects.create(miner=cur_miners[1], share=shares[4], balance=500, status="mature")
        Balance.objects.create(miner=cur_miners[1], share=shares[5], balance=600, status="mature")

    def get_threshold_url(self, pk):
        return urljoin('/user/', pk) + '/'

    def get_withdraw_url(self, pk):
        return urljoin(urljoin('/user/', pk) + '/', 'withdraw') + '/'

    def get_hash_rate_url(self, pk):
        return urljoin(urljoin('/user/', pk) + '/', 'hash_rate') + '/'

    def get_share_url(self, pk):
        return urljoin(urljoin('/user/', pk) + '/', 'share') + '/'

    def get_income_url(self, pk):
        return urljoin(urljoin('/user/', pk) + '/', 'income') + '/'

    def get_payout_url(self, pk):
        return urljoin(urljoin('/user/', pk) + '/', 'payout') + '/'

    def mocked_time(*args, **kwargs):
        return datetime(2020, 1, 1, 8, 59, 20, 395985, tzinfo=timezone.utc)

    @override_settings(DEFAULT_START_PAYOUT=1577577600)
    @patch('django.utils.timezone.now', side_effect=mocked_time)
    def test_payout_default_value(self, mock_time):
        """
        In this case checking ordering according to date and payout for miner hash with default value
        :param mock_time:
        :return:
        """
        response = self.client.get(self.get_payout_url('hash')).json()
        with open("core/data_testing/user_payout_default_value.json", "r") as read_file:
            file = json.load(read_file)
        self.assertEqual(file, response)

    @override_settings(DEFAULT_START_PAYOUT=1577577600)
    @patch('django.utils.timezone.now', side_effect=mocked_time)
    def test_payout_with_filter(self, mock_time):
        """
        In this case checking ordering according to amount and payout for miner hash with filter start and stop
        :param mock_time:
        :return:
        """
        data = {
            'start': 1577520020,
            'stop': 1577869160,
            'ordering': '-amount'
        }
        response = self.client.get(self.get_payout_url('hash'), data=data).json()
        with open("core/data_testing/user_payout_with_filter.json", "r") as read_file:
            file = json.load(read_file)
        self.assertEqual(file, response)

    def test_income(self):
        """
        We expect to get list income of the user abc
        :return:
        """
        response = self.client.get(self.get_income_url('hash')).json()
        with open("core/data_testing/user_income.json", "r") as read_file:
            file = json.load(read_file)
        self.assertEqual(file, response)

    @patch('django.utils.timezone.now', side_effect=mocked_time)
    def test_share_default_value(self, mock_time):
        """
        In this scenario we expect with call action share for a user get number of valid and invalid between
        timezone.now().timestamp() - DEFAULT_STOP_TIME_STAMP_DIAGRAM and timezone.now().timestamp()
         in half-hour intervals
        :return:
        """
        response = self.client.get(self.get_share_url('hash')).json()
        with open("core/data_testing/user_share_default_value.json", "r") as read_file:
            file = json.load(read_file)
        self.assertEqual(file, response)

    @patch('django.utils.timezone.now', side_effect=mocked_time)
    def test_share_with_filter(self, mock_time):
        """
        In this scenario we expect with call action share for a user, get number of valid and invalid shares between
         start and stop filter query in half-hour intervals
        :return:
        """
        data = {
            "start": 1577858420,
            "stop": 1577869220
        }
        response = self.client.get(self.get_share_url('hash'), data).json()
        with open("core/data_testing/user_share_with_filter.json", "r") as read_file:
            file = json.load(read_file)
        self.assertEqual(file, response)

    @patch('django.utils.timezone.now', side_effect=mocked_time)
    def test_hash_rate_default_value(self, mock_time):
        """
        In this scenario we expect call action hash_rate for a user and get average and current hash_rate between
         timezone.now().timestamp() - DEFAULT_STOP_TIME_STAMP_DIAGRAM and timezone.now().timestamp()
         in half-hour intervals
        :return:
        """
        response = self.client.get(self.get_hash_rate_url('hash')).json()
        with open("core/data_testing/user_hash_rate_default_value.json", "r") as read_file:
            file = json.load(read_file)
        self.assertEqual(file, response)

    @patch('django.utils.timezone.now', side_effect=mocked_time)
    def test_hash_rate_with_filter(self, mock_time):
        """
        In this scenario we expect call action hash_rate for a user and get average and current hash_rate between
         start and stop filter query in half-hour intervals
        :return:
        """
        data = {
            "start": 1577858420,
            "stop": 1577869220
        }
        response = self.client.get(self.get_hash_rate_url('hash'), data).json()
        with open("core/data_testing/user_hash_rate_with_filter.json", "r") as read_file:
            file = json.load(read_file)
        self.assertEqual(file, response)

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

        res = Client().patch(self.get_threshold_url(miner.public_key), data, content_type='application/json')

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

    def test_get_all(self):
        """
        Purpose: Check if User Api view returns the correct info for all miners.
        Prerequisites: Nothing
        Scenario: Sends a request to /user/ and checks if response is correct
        Test Conditions:
        * status is 200
        * Content-Type is application/json
        * Content is :
        {
            'round_valid_shares': 4,
            'round_invalid_shares': 1,
            'timestamp': self.now.strftime('%Y-%m-%d %H:%M:%S'),
            "hash_rate": {
                "current": 808604,
                "avg": 16845
            },
            'users': {
                'abc': {
                    "round_valid_shares": 2,
                    "round_invalid_shares": 1,
                    "immature": 300,
                    "mature": 300,
                    "withdraw": 400,
                    "hash_rate": {
                        "current": 85051,
                        "avg": 1771
                    },
                },
                'xyz': {
                    "round_valid_shares": 2,
                    "round_invalid_shares": 0,
                    "immature": 0,
                    "mature": 1100,
                    "withdraw": 0,
                    "hash_rate": {
                        "current": 723552,
                        "avg": 15074
                    },
                }
            }
        }
        """

        self.miner_actions.delete()

        for miner in self.miners:
            miner.delete()

        for balance in self.balances:
            balance.delete()

        response = self.client.get('/user/').json()
        with open("core/data_testing/user_api_all.json", "r") as read_file:
            file = json.load(read_file)
        file['timestamp'] = self.now.strftime("%Y-%m-%d %H:%M:%S")
        self.assertDictEqual(response, file)

    def test_get_specified_pk(self):
        """
        Purpose: Check if user view returns the correct info for the specified miner (abc)
        Prerequisites: Nothing
        Scenario: Sends a request to /user/abc and checks if response is correct for miner 'abc'
        Test Conditions:
        * status is 200
        * Content-Type is application/json
        * Content is :
        {
            'round_valid_shares': 4,
            'round_invalid_shares': 1,
            'timestamp': self.now.strftime('%Y-%m-%d %H:%M:%S'),
            "hash_rate": {
                "current": 808604,
                "avg": 16845
            },
            'users': {
                'abc': {
                    "round_valid_shares": 2,
                    "round_invalid_shares": 1,
                    "immature": 300,
                    "mature": 300,
                    "withdraw": 400,
                    "hash_rate": {
                        "current": 85051,
                        "avg": 1771
                    }
                }
            }
        }
        """
        content = self.client.get('/user/abc/')
        response = content.json()
        with open("core/data_testing/user_api_specified_pk.json", "r") as read_file:
            file = json.load(read_file)
        file['timestamp'] = self.now.strftime("%Y-%m-%d %H:%M:%S")
        self.assertDictEqual(response, file)

    def tearDown(self) -> None:
        Miner.objects.all().delete()
        Balance.objects.all().delete()
        Share.objects.all().delete()
        Configuration.objects.all().delete()


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
        User.objects.create_user(username='test', password='test')
        self.client = APIClient()
        self.client.login(username='test', password='test')
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

    def test_configuration_batch_create(self):
        """
        create or update configuration using batch configs
        """
        keys = [key for (key, temp) in CONFIGURATION_KEY_CHOICE]
        Configuration.objects.create(key=keys[0], value="dummy_value")
        batch = {}
        for ind, key in enumerate(keys):
            batch[key] = str(ind)

        self.client.post('/conf/batch_create/', batch)

        for ind, key in enumerate(keys):
            self.assertEqual(Configuration.objects.filter(key=key).count(), 1)
            conf = Configuration.objects.filter(key=key).first()
            self.assertEqual(conf.value, str(ind))

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
        miners = [Miner.objects.create(public_key=str(i)) for i in range(3)]
        # create shares list
        shares = [Share.objects.create(
            share=str(i),
            miner=miners[int(i / 2) % 3],
            status="solved" if i in [14, 44, 45] else "valid" if i % 2 == 0 else "invalid",
            block_height=10,
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
        return dict(Balance.objects.filter(share=sh, status='immature').values_list('miner__public_key').annotate(
            Sum('balance')))

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

    def test_pplns_balance_height(self):
        """
        in this case we have 8 shares and pplns must work with this amount of shares
        block_height of miner 1 share is 100, so balances created for this miner must match
        """
        share = self.shares[14]
        for s in self.shares[:14]:
            if s.status == 'valid' and s.miner.public_key == '0':
                s.block_height = 100
                s.save()
                break
        self.PPLNS(share)
        balances = self.get_share_balance(share)
        self.assertEqual(balances, {'0': int(24.375e9), '1': int(24.375e9), '2': int(16.25e9)})
        self.assertEqual(Balance.objects.get(miner__public_key='0').min_height, 10)
        self.assertEqual(Balance.objects.get(miner__public_key='0').max_height, 100)

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

    def test_pplns_called_multiple_with_different_shares(self):
        """
        in this case we call prop function 5 times. after first call, miners shares changes
        so in second call balances must be changed
        :return:
        """
        Configuration.objects.create(key='MAX_REWARD', value=int(65e9))
        share = self.shares[44]
        self.PPLNS(share)
        balances = self.get_share_balance(share)
        self.assertEqual(balances, {'0': int(19.5e9), '1': int(26.0e9), '2': int(19.5e9)})

        cur = Share.objects.create(miner=Miner.objects.get(public_key='1'), status='valid', difficulty=10000)
        cur.created_at = share.created_at - timedelta(seconds=1)
        cur.save()
        Configuration.objects.filter(key="PPLNS_N").update(value='11')
        self.PPLNS(share)
        cur_balances = self.get_share_balance(share)
        self.assertEqual(cur_balances, {'0': int(9.75e9), '1': int(45.5e9), '2': int(9.75e9)})
        for miner_id in cur_balances:
            balance = Balance.objects.filter(miner__public_key=miner_id,
                                             balance=cur_balances[miner_id] - balances[miner_id],
                                             status='immature', share=share)
            self.assertEqual(balance.count(), 1)

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


class PPSFunctionTest(TestCase):
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
        Configuration.objects.create(key='REWARD_ALGORITHM', value='PPS')
        Configuration.objects.create(key='TOTAL_REWARD', value=str(int(67.5e9)))
        Configuration.objects.create(key='FEE_FACTOR', value='0')
        Configuration.objects.create(key='REWARD_FACTOR', value=str(65 / 67.5))
        Configuration.objects.create(key='POOL_BASE_FACTOR', value=str(1000))
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
        self.pps = RewardAlgorithm.get_instance().perform_logic

    def test_pps_valid(self):
        """
        test pps function to generate a balance for any share in system
        :return: nothing
        """
        # call prop function for an invalid (not solved) share, 8th for example
        share = self.shares[12]
        self.pps(share)
        balances = Balance.objects.filter(share=share)
        self.assertEqual(balances.count(), 1)
        balance = balances.first()
        self.assertEqual(balance.balance, 65 * 1e6)

    def test_pps_solved(self):
        """
        test pps function to generate a balance for any share in system
        :return: nothing
        """
        # call prop function for an invalid (not solved) share, 8th for example
        share = self.shares[14]
        self.pps(share)
        balances = Balance.objects.filter(share=share)
        self.assertEqual(balances.count(), 1)
        balance = balances.first()
        self.assertEqual(balance.balance, 65 * 1e6)

    def test_pps_invalid(self):
        """
        test pps function to generate a balance for any share in system
        :return: nothing
        """
        # call prop function for an invalid (not solved) share, 8th for example
        share = self.shares[13]
        self.pps(share)
        balances = Balance.objects.filter(share=share).count()
        self.assertEqual(balances, 0)

    def tearDown(self):
        """
        tearDown function to delete miners created in setUp function
        :return:
        """
        Configuration.objects.all().delete()
        Balance.objects.all().delete()
        Share.objects.all().delete()
        Miner.objects.all().delete()


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

        with open("core/data_testing/test_get_blocks.json", "r") as read_file:
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

    def tearDown(self) -> None:
        Configuration.objects.all().delete()
        Miner.objects.all().delete()
        Share.objects.all().delete()


def mocked_node_request_transaction_generate_test(*args, **kwargs):
    """
    mock requests with method post
    """
    url = args[0]

    if url == 'wallet/boxes/unspent':
        with open("core/data_testing/test_boxes.json", "r") as read_file:
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

    if url == 'transactions':
        return {
            'status': 'success'
        }

    if url == 'wallet/transaction/generate':
        tx = json.loads(open("core/data_testing/sample_tx.json", "r").read())
        req = kwargs['data']
        tx['inputs'] = [{'boxId': x} for x in req['inputsRaw']]
        tx['id'] = ''.join(req['inputsRaw'])

        return {
            'status': 'success',
            'response': tx
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
        also created balances must have default heights
        """
        # setting configuration
        Configuration.objects.create(key='MAX_NUMBER_OF_OUTPUTS', value='4')

        # creating 10 miners
        pks = [random_string() for i in range(10)]
        for pk in pks:
            Miner.objects.create(public_key=pk)

        # create output for each miner
        self.outputs = [(pk, int((i + 1) * 1e10)) for i, pk in enumerate(pks)]
        self.pending_balances = [
            Balance(miner=Miner.objects.get(public_key=x[0]), balance=-x[1], actual_payment=x[1],
                    status="pending_withdrawal",
                    min_height=1, max_height=100) for x in
            self.outputs]
        for pk, _ in self.outputs:
            Address.objects.create(address_miner=Miner.objects.get(public_key=pk), category='miner', address=pk)

    def test_generate_three_transactions_max_num_output_4(self, mocked_request):
        """
        calling the function with all outputs and MAX_NUMBER_OF_OUTPUT = 4
        must create 3 transactions and required balances
        """
        for i, _ in enumerate(self.pending_balances):
            self.pending_balances[i].save()

        self.assertEqual(Transaction.objects.count(), 0)
        handle_withdraw()

        req = [(['a', 'b', 'c', 'd'], 4), (['e', 'f', 'g'], 4), (['h', 'i'], 2)]
        self.assertEqual(Transaction.objects.count(), len(req))
        for i, tx in enumerate(Transaction.objects.all()):
            self.assertEqual(tx.inputs, ','.join(req[i][0]))
            self.assertEqual(Balance.objects.filter(tx=tx).count(), req[i][1])

    def test_generate_one_transactions_max_num_output_4(self, mocked_request):
        """
        calling the function with 4 outputs and MAX_NUMBER_OF_OUTPUT = 4
        must create 1 transactions and required balances
        """
        pending = self.pending_balances[0:4]
        for i, _ in enumerate(pending):
            self.pending_balances[i].save()

        self.assertEqual(Transaction.objects.count(), 0)
        handle_withdraw()

        req = [(['a', 'b', 'c', 'd'], 4)]
        self.assertEqual(Transaction.objects.count(), len(req))
        for i, tx in enumerate(Transaction.objects.all()):
            self.assertEqual(tx.inputs, ','.join(req[i][0]))
            self.assertEqual(Balance.objects.filter(tx=tx).count(), req[i][1])

    def test_generate_three_transactions_max_num_output_20(self, mocked_request):
        """
        calling the function with all outputs and MAX_NUMBER_OF_OUTPUT = 20
        must create 1 transactions and required balances
        """
        pending = self.pending_balances
        for i, _ in enumerate(pending):
            self.pending_balances[i].save()

        self.assertEqual(Transaction.objects.count(), 0)
        Configuration.objects.create(key='MAX_NUMBER_OF_OUTPUTS', value='20')
        handle_withdraw()

        req = [([a for a in 'abcdefghi'], 10)]
        self.assertEqual(Transaction.objects.count(), len(req))
        for i, tx in enumerate(Transaction.objects.all()):
            self.assertEqual(tx.inputs, ','.join(req[i][0]))
            self.assertEqual(Balance.objects.filter(tx=tx).count(), req[i][1])

    def tearDown(self):
        """
        tearDown function to clean up objects created in setUp function
        :return:
        """
        Configuration.objects.all().delete()
        Miner.objects.all().delete()
        Share.objects.all().delete()
        Balance.objects.all().delete()
        # delete all miners objects. all related objects are deleted


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
            Balance.objects.create(miner=miner, balance=int(100e9), status="mature", min_height=1, max_height=10)
            Balance.objects.create(miner=miner, balance=int(-20e9), status="withdraw", min_height=1, max_height=10)

        self.outputs = [(pk, int(80e9)) for pk in pks]

    def test_all_miners_below_defualt_threshold(self):
        """
        all miners balances are below default threshold
        """
        periodic_withdrawal()
        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 0)

    def test_all_miners_except_one_below_default_threshold(self):
        """
        all miners balances are below default threshold but one
        """
        Balance.objects.create(miner=self.miners[0], balance=int(100e9), status="mature")
        max_id = Balance.objects.all().aggregate(Max('pk'))['pk__max']
        periodic_withdrawal()

        self.assertEqual(
            Balance.objects.filter(miner=self.miners[0], balance=int(-180e9), status="pending_withdrawal").count(), 1)

    def test_all_miner_below_default_threshold_one_explicit_threshold(self):
        """
        all miners balances are below default threshold
        one miner has explicit threshold, his balance is above this threshold
        """
        miner = self.miners[0]
        miner.periodic_withdrawal_amount = int(20e9)
        miner.save()
        max_id = Balance.objects.all().aggregate(Max('pk'))['pk__max']
        periodic_withdrawal()

        self.assertEqual(Balance.objects.filter(miner=miner, balance=int(-80e9),
                                                status="pending_withdrawal").count(), 1)
        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 1)

    def test_all_miner_below_default_threshold_two_explicit_threshold(self):
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
        pks = sorted([m.public_key for m in [miner1, miner2]])
        outputs = [(pk, int(80e9), max_id + 1 + i) for i, pk in enumerate(pks)]
        for miner in [miner1, miner2]:
            self.assertEqual(
                Balance.objects.filter(miner=miner, balance=int(-80e9), status="pending_withdrawal").count(), 1)
        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 2)

    def test_all_miners_but_one_below_default_threshold_two_explicit_threshold_one_not_above(self):
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

        self.assertEqual(Balance.objects.filter(miner=miner1, balance=int(-80e9), status="pending_withdrawal").count(),
                         1)
        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 1)

    def test_all_miners_but_one_below_default_one_above_default_below_explicit(self):
        """
        all miners balances are below default threshold but one
        two miners have explicit threshold, balance of one of them is below the explicit conf
        """
        miner1 = self.miners[0]
        Balance.objects.create(miner=miner1, balance=int(30e9), status="mature")
        miner1.periodic_withdrawal_amount = int(120e9)
        miner1.save()
        periodic_withdrawal()

        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 0)

    def test_all_miners_above_default_but_one(self):
        """
        all miners balances are above default threshold but one
        """
        for miner in self.miners:
            Balance.objects.create(miner=miner, balance=int(30e9), status="mature")
        miner1 = self.miners[0]
        Balance.objects.create(miner=miner1, balance=int(-80e9), status="mature")
        max_id = Balance.objects.all().aggregate(Max('pk'))['pk__max']
        pks = sorted([m.public_key for m in self.miners[1:]])
        outputs = [(pk, int(110e9), max_id + 1 + i) for i, pk in enumerate(pks)]
        periodic_withdrawal()

        for miner in self.miners[1:]:
            self.assertEqual(
                Balance.objects.filter(miner=miner, balance=int(-110e9), status="pending_withdrawal",
                                       min_height=1, max_height=10).count(), 1)
        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), len(self.miners) - 1)

    def test_all_miners_above_default_diff_height(self):
        """
        all miners balances are above default threshold, pending_withdrawal balances must have valid height
        """
        for i, miner in enumerate(self.miners[:5]):
            Balance.objects.create(miner=miner, balance=int(30e9), status="mature", max_height=10 + i)

        for i, miner in enumerate(self.miners[5:]):
            Balance.objects.create(miner=miner, balance=int(30e9), status="mature", min_height=0, max_height=10 + i)
        miner1 = self.miners[0]
        Balance.objects.create(miner=miner1, balance=int(-80e9), status="mature")
        max_id = Balance.objects.all().aggregate(Max('pk'))['pk__max']
        pks = sorted([m.public_key for m in self.miners[1:]])
        outputs = [(pk, int(110e9), max_id + 1 + i) for i, pk in enumerate(pks)]
        periodic_withdrawal()

        for i, miner in enumerate(self.miners[1:5]):
            self.assertEqual(
                Balance.objects.filter(miner=miner, balance=int(-110e9), status="pending_withdrawal",
                                       min_height=1, max_height=11 + i).count(), 1)

        for i, miner in enumerate(self.miners[5:]):
            self.assertEqual(
                Balance.objects.filter(miner=miner, balance=int(-110e9), status="pending_withdrawal",
                                       min_height=0, max_height=10 + i).count(), 1)

        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), len(self.miners) - 1)

    def test_all_miners_above_default_but_one_no_balance(self):
        """
        all miners balances are above default threshold but one
        one doesn't have any balance
        """
        for miner in self.miners:
            Balance.objects.create(miner=miner, balance=int(30e9), status="mature")
        miner1 = self.miners[0]
        Balance.objects.filter(miner=miner1).delete()
        max_id = Balance.objects.all().aggregate(Max('pk'))['pk__max']
        pks = sorted([m.public_key for m in self.miners[1:]])
        outputs = [(pk, int(110e9), max_id + 1 + i) for i, pk in enumerate(pks)]
        outputs = sorted(outputs)
        periodic_withdrawal()

        for miner in self.miners[1:]:
            self.assertEqual(
                Balance.objects.filter(miner=miner, balance=int(-110e9), status="pending_withdrawal").count(), 1)
        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), len(self.miners) - 1)

    def test_no_balance(self):
        """
        no balance, empty output
        """
        Balance.objects.all().delete()
        periodic_withdrawal()
        self.assertEqual(Balance.objects.filter(status="pending_withdrawal").count(), 0)

    def tearDown(self):
        """
        tearDown function to clean up objects created in setUp function
        :return:
        """
        Configuration.objects.all().delete()
        Miner.objects.all().delete()
        Share.objects.all().delete()
        Balance.objects.all().delete()
        # delete all miners objects. all related objects are deleted


class ImmatureToMatureTestCase(TestCase):
    """
    Test class for immature_to_mature function
    """
    CURRENT_HEIGHT = 20000

    def mocked_reward_algorithm_do_nothing(*args, **kwargs):
        pass

    def mocked_reward_algorithm(*args, **kwargs):
        share = args[0]
        miners = Miner.objects.all()
        for miner in miners[:5]:
            Balance.objects.create(miner=miner, share=share, status='immature', balance=-10)

        for miner in miners[5:]:
            Balance.objects.create(miner=miner, share=share, status='immature', balance=10)

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
            num_confirmation = int(params['id'].split('_')[-1])
            height = int(params['id'].split('_')[-2])
            return {
                'response': {
                    'numConfirmations': num_confirmation,
                    'inclusionHeight': height
                },
                'status': 'success'
            }

        if 'chainslice' in url.lower():
            headers = json.loads(open('core/data_testing/headers.json').read())
            return {
                'status': 'success',
                'response': headers
            }

        if 'blocks' in url.lower():
            headers = json.loads(open('core/data_testing/sibling_header.json').read())
            return {
                'status': 'success',
                'response': {
                    'header': headers
                }
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
        default_hash = '0fd923ca5e7218c4ba3c3801c26a617ecdbfdaebb9c76ce2eca166e7855efbb8'
        for i in range(5):
            # not important shares
            num_confirmation = CONFIRMATION_LENGTH + 10
            block_height = self.CURRENT_HEIGHT - num_confirmation
            tx_id = '_'.join([random_string(), str(block_height), str(num_confirmation)])
            Share.objects.create(miner=self.miners[0], transaction_id=tx_id, difficulty=1,
                                 block_height=block_height, status='valid', parent_id='1',
                                 pow_identity=default_hash)

            # confirmed shares
            num_confirmation = CONFIRMATION_LENGTH + 10
            block_height = self.CURRENT_HEIGHT - num_confirmation
            tx_id = '_'.join([random_string(), str(block_height), str(num_confirmation)])
            Share.objects.create(miner=self.miners[0], transaction_id=tx_id, difficulty=1,
                                 block_height=block_height, status='solved', parent_id='1',
                                 pow_identity=default_hash)

            # confirmed just now
            num_confirmation = CONFIRMATION_LENGTH
            block_height = self.CURRENT_HEIGHT - num_confirmation
            tx_id = '_'.join([random_string(), str(block_height), str(num_confirmation)])
            Share.objects.create(miner=self.miners[0], transaction_id=tx_id, difficulty=1,
                                 block_height=block_height, status='solved', parent_id='1',
                                 pow_identity=default_hash)

            # unconfirmed shares
            num_confirmation = CONFIRMATION_LENGTH - 10
            block_height = self.CURRENT_HEIGHT - num_confirmation
            tx_id = '_'.join([random_string(), str(block_height), str(num_confirmation)])
            Share.objects.create(miner=self.miners[0], transaction_id=tx_id, difficulty=1,
                                 block_height=block_height, status='solved', parent_id='1',
                                 pow_identity=default_hash)

        # by default all shares have immature balances for each miner
        for share in Share.objects.filter(status='solved'):
            for miner in self.miners:
                Balance.objects.create(share=share, miner=miner, balance=int(100e9), status='immature')
                Balance.objects.create(share=share, miner=miner, balance=int(100e9), status='mature')
                Balance.objects.create(miner=miner, balance=int(-20e9), status='withdraw')

    @patch('core.tasks.node_request', side_effect=mocked_node_request)
    @patch('core.tasks.RewardAlgorithm.perform_logic', side_effect=mocked_reward_algorithm_do_nothing)
    def test_20_shares_possible_20_confirmed(self, mocked_node_request, mock):
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
        for balance_id in balances_to_status.keys():
            balance = Balance.objects.get(id=balance_id)
            if balance.share is None or balance.share.id not in confirmed_shares:
                self.assertEqual(balance.status, balances_to_status[balance.id])

            else:
                if balances_to_status[balance.id] == "immature":
                    self.assertEqual(balance.status, "mature")

                else:
                    self.assertEqual(balance.status, balances_to_status[balance.id])

    @patch('core.tasks.node_request', side_effect=mocked_node_request)
    @patch('core.tasks.RewardAlgorithm.perform_logic', side_effect=mocked_reward_algorithm_do_nothing)
    def test_20_shares_pps(self, mocked_node_request, mock):
        """
        must avoid checking transaction
        """
        Configuration.objects.create(key='REWARD_ALGORITHM', value='PPS')
        current_height = ImmatureToMatureTestCase.CURRENT_HEIGHT
        CONFIRMATION_LENGTH = Configuration.objects.CONFIRMATION_LENGTH
        confirmed_shares = [x.id for x in Share.objects.filter(balance__status='immature',
                                                               block_height__lte=(current_height - CONFIRMATION_LENGTH)).distinct()]
        balances_to_status = {
            balance.id: balance.status for balance in Balance.objects.all()
        }

        immature_to_mature()
        for balance_id in balances_to_status.keys():
            balance = Balance.objects.get(id=balance_id)
            if balance.share is None or balance.share.id not in confirmed_shares:
                self.assertEqual(balance.status, balances_to_status[balance.id])
            else:
                if balances_to_status[balance.id] == "immature":
                    self.assertEqual(balance.status, "mature")
                else:
                    self.assertEqual(balance.status, balances_to_status[balance.id])

    @patch('core.tasks.node_request', side_effect=mocked_node_request)
    @patch('core.tasks.RewardAlgorithm.perform_logic', side_effect=mocked_reward_algorithm_do_nothing)
    def test_some_shares_next_ids_present(self, mocked_node_request, logic):
        """
        20 shares have immature balances and their block_height is less than the threshold
        15 of these shares are confirmed
        some confirmed share has issues because its next ids are present in blockchain
        """
        current_height = ImmatureToMatureTestCase.CURRENT_HEIGHT
        CONFIRMATION_LENGTH = Configuration.objects.CONFIRMATION_LENGTH
        cur_unconfirmed = Share.objects.filter(balance__status='immature',
                                               block_height=(current_height - CONFIRMATION_LENGTH),
                                               status='solved').distinct()[:5]
        for share in cur_unconfirmed:
            num_confirmed = int(share.transaction_id.split('_')[-1])
            share.transaction_id = '_'.join([random_string(), str(share.block_height), str(num_confirmed - 1)])
            share.save()

        cur_unconfirmed = [x.id for x in cur_unconfirmed]

        confirmed_shares = [x.id for x in Share.objects.filter(balance__status='immature',
                                                               block_height__lte=(current_height - CONFIRMATION_LENGTH),
                                                               status='solved').distinct() if
                            x.id not in cur_unconfirmed]
        conf = Share.objects.get(id=confirmed_shares[0])
        conf.next_ids = ['1']
        conf.save()
        val = Share.objects.filter(status='valid').first()
        val.next_ids = ['1']
        val.save()
        conf_balances = [b.id for b in Balance.objects.filter(share=conf, status='immature')]

        balances_to_status = {
            balance.id: balance.status for balance in Balance.objects.all()
        }

        total_bal_count = Balance.objects.all().count()
        immature_to_mature()
        for id in conf_balances:
            b = Balance.objects.get(id=id)
            self.assertEqual(Balance.objects.filter(miner=b.miner, status='mature',
                                                    balance=-b.balance, share=conf).count(), 1)

        self.assertEqual(Balance.objects.all().count(), total_bal_count + len(conf_balances))

        conf = Share.objects.get(id=conf.id)
        self.assertTrue(conf.is_orphaned)
        val = Share.objects.get(id=val.id)
        self.assertTrue(val.is_orphaned)

        for balance_id in balances_to_status.keys():
            balance = Balance.objects.get(id=balance_id)
            if balance.share is None or balance.share.id not in confirmed_shares:
                self.assertEqual(balance.status, balances_to_status[balance.id])

            else:
                if balances_to_status[balance.id] == "immature":
                    self.assertEqual(balance.status, "mature")

                else:
                    self.assertEqual(balance.status, balances_to_status[balance.id])

    @patch('core.tasks.node_request', side_effect=mocked_node_request)
    @patch('core.tasks.RewardAlgorithm.perform_logic', side_effect=mocked_reward_algorithm_do_nothing)
    def test_reward_algorithm_called_for_confirmed(self, logic, node_request):
        """
        20 shares have immature balances and their block_height is less than the threshold
        15 of these shares are confirmed
        reward algorithm must be called for ok and confirmed solved shares
        """
        current_height = ImmatureToMatureTestCase.CURRENT_HEIGHT
        CONFIRMATION_LENGTH = Configuration.objects.CONFIRMATION_LENGTH
        cur_unconfirmed = Share.objects.filter(balance__status='immature',
                                               block_height=(current_height - CONFIRMATION_LENGTH),
                                               status='solved').distinct()[:5]
        for share in cur_unconfirmed:
            num_confirmed = int(share.transaction_id.split('_')[-1])
            share.transaction_id = '_'.join([random_string(), str(share.block_height), str(num_confirmed - 1)])
            share.save()

        cur_unconfirmed = [x.id for x in cur_unconfirmed]

        confirmed_shares_id = [x.id for x in Share.objects.filter(balance__status='immature',
                                                                  block_height__lte=(
                                                                          current_height - CONFIRMATION_LENGTH),
                                                                  status='solved').distinct() if
                               x.id not in cur_unconfirmed]

        confirmed_shares = [x for x in Share.objects.filter(balance__status='immature',
                                                            block_height__lte=(current_height - CONFIRMATION_LENGTH),
                                                            status='solved').distinct() if
                            x.id not in cur_unconfirmed]
        conf = Share.objects.get(id=confirmed_shares_id[0])
        conf.next_ids = ['1']
        conf.save()
        conf_balances = [b.id for b in Balance.objects.filter(share=conf, status='immature')]

        balances_to_status = {
            balance.id: balance.status for balance in Balance.objects.all()
        }

        total_bal_count = Balance.objects.all().count()
        immature_to_mature()
        for id in conf_balances:
            b = Balance.objects.get(id=id)
            self.assertEqual(Balance.objects.filter(miner=b.miner, status='mature',
                                                    balance=-b.balance, share=conf).count(), 1)

        self.assertEqual(Balance.objects.all().count(), total_bal_count + len(conf_balances))

        conf = Share.objects.get(id=conf.id)
        self.assertTrue(conf.is_orphaned)

        logic.assert_has_calls([call(share) for share in confirmed_shares if share.id != conf.id])

        for balance_id in balances_to_status.keys():
            balance = Balance.objects.get(id=balance_id)
            if balance.share is None or balance.share.id not in confirmed_shares_id:
                self.assertEqual(balance.status, balances_to_status[balance.id])

            else:
                if balances_to_status[balance.id] == "immature":
                    self.assertEqual(balance.status, "mature")

                else:
                    self.assertEqual(balance.status, balances_to_status[balance.id])

    @patch('core.tasks.node_request', side_effect=mocked_node_request)
    @patch('core.tasks.RewardAlgorithm.perform_logic', side_effect=mocked_reward_algorithm)
    def test_reward_algorithm_results_must_be_mature(self, logic, node_request):
        """
        20 shares have immature balances and their block_height is less than the threshold
        15 of these shares are confirmed
        balances created in reward algorithm must be converted to mature too
        """
        current_height = ImmatureToMatureTestCase.CURRENT_HEIGHT
        CONFIRMATION_LENGTH = Configuration.objects.CONFIRMATION_LENGTH
        cur_unconfirmed = Share.objects.filter(balance__status='immature',
                                               block_height=(current_height - CONFIRMATION_LENGTH),
                                               status='solved').distinct()[:5]
        for share in cur_unconfirmed:
            num_confirmed = int(share.transaction_id.split('_')[-1])
            share.transaction_id = '_'.join([random_string(), str(share.block_height), str(num_confirmed - 1)])
            share.save()

        cur_unconfirmed = [x.id for x in cur_unconfirmed]

        confirmed_shares_id = [x.id for x in Share.objects.filter(balance__status='immature',
                                                                  block_height__lte=(
                                                                          current_height - CONFIRMATION_LENGTH),
                                                                  status='solved').distinct() if
                               x.id not in cur_unconfirmed]

        confirmed_shares = [x for x in Share.objects.filter(balance__status='immature',
                                                            block_height__lte=(current_height - CONFIRMATION_LENGTH),
                                                            status='solved').distinct() if
                            x.id not in cur_unconfirmed]
        balances_to_status = {
            balance.id: balance.status for balance in Balance.objects.all()
        }

        immature_to_mature()

        logic.assert_has_calls([call(share) for share in confirmed_shares if share.id])

        for share in confirmed_shares:
            miners = Miner.objects.all()
            for miner in miners[:5]:
                bal = Balance.objects.filter(miner=miner, share=share, balance=-10)
                self.assertEqual(bal.count(), 1)
                self.assertEqual(bal.first().status, 'mature')
                self.assertTrue(bal.first().is_orphaned)

            for miner in miners[5:]:
                bal = Balance.objects.filter(miner=miner, share=share, balance=10)
                self.assertEqual(bal.count(), 1)
                self.assertEqual(bal.first().status, 'mature')
                self.assertTrue(not bal.first().is_orphaned)

        for balance_id in balances_to_status.keys():
            balance = Balance.objects.get(id=balance_id)
            if balance.share is None or balance.share.id not in confirmed_shares_id:
                self.assertEqual(balance.status, balances_to_status[balance.id])

            else:
                if balances_to_status[balance.id] == "immature":
                    self.assertEqual(balance.status, "mature")

                else:
                    self.assertEqual(balance.status, balances_to_status[balance.id])

    @patch('core.tasks.node_request', side_effect=mocked_node_request)
    @patch('core.tasks.RewardAlgorithm.perform_logic', side_effect=mocked_reward_algorithm_do_nothing)
    def test_some_shares_parent_id_not_present(self, mocked_node_request, logic):
        """
        20 shares have immature balances and their block_height is less than the threshold
        15 of these shares are confirmed
        some confirmed share has issues because its parent id is not present in the blockchain
        """
        current_height = ImmatureToMatureTestCase.CURRENT_HEIGHT
        CONFIRMATION_LENGTH = Configuration.objects.CONFIRMATION_LENGTH
        cur_unconfirmed = Share.objects.filter(balance__status='immature',
                                               block_height=(current_height - CONFIRMATION_LENGTH),
                                               status='solved').distinct()[:5]
        for share in cur_unconfirmed:
            num_confirmed = int(share.transaction_id.split('_')[-1])
            share.transaction_id = '_'.join([random_string(), str(share.block_height), str(num_confirmed - 1)])
            share.save()

        cur_unconfirmed = [x.id for x in cur_unconfirmed]

        confirmed_shares = [x.id for x in Share.objects.filter(balance__status='immature',
                                                               block_height__lte=(current_height - CONFIRMATION_LENGTH),
                                                               status='solved').distinct() if
                            x.id not in cur_unconfirmed]
        conf = Share.objects.get(id=confirmed_shares[0])
        conf.parent_id = '1000'
        conf.save()
        val = Share.objects.filter(status='valid').first()
        val.parent_id = '1000'
        val.save()
        conf_balances = [b.id for b in Balance.objects.filter(share=conf, status='immature')]

        balances_to_status = {
            balance.id: balance.status for balance in Balance.objects.all()
        }

        total_bal_count = Balance.objects.all().count()
        immature_to_mature()
        for id in conf_balances:
            b = Balance.objects.get(id=id)
            self.assertEqual(Balance.objects.filter(miner=b.miner, status='mature',
                                                    balance=-b.balance, share=conf).count(), 1)

        self.assertEqual(Balance.objects.all().count(), total_bal_count + len(conf_balances))

        conf = Share.objects.get(id=conf.id)
        self.assertTrue(conf.is_orphaned)
        val = Share.objects.get(id=val.id)
        self.assertTrue(val.is_orphaned)

        for balance_id in balances_to_status.keys():
            balance = Balance.objects.get(id=balance_id)
            if balance.share is None or balance.share.id not in confirmed_shares:
                self.assertEqual(balance.status, balances_to_status[balance.id])

            else:
                if balances_to_status[balance.id] == "immature":
                    self.assertEqual(balance.status, "mature")

                else:
                    self.assertEqual(balance.status, balances_to_status[balance.id])

    @patch('core.tasks.node_request', side_effect=mocked_node_request)
    @patch('core.tasks.RewardAlgorithm.perform_logic', side_effect=mocked_reward_algorithm_do_nothing)
    def test_some_shares_incorrect_pow(self, mocked_node_request, logic):
        """
        20 shares have immature balances and their block_height is less than the threshold
        15 of these shares are confirmed
        some solved confirmed share has issues because their pow does not match with pow in the blockchain
        """
        current_height = ImmatureToMatureTestCase.CURRENT_HEIGHT
        CONFIRMATION_LENGTH = Configuration.objects.CONFIRMATION_LENGTH
        cur_unconfirmed = Share.objects.filter(balance__status='immature',
                                               block_height=(current_height - CONFIRMATION_LENGTH),
                                               status='solved').distinct()[:5]
        for share in cur_unconfirmed:
            num_confirmed = int(share.transaction_id.split('_')[-1])
            share.transaction_id = '_'.join([random_string(), str(share.block_height), str(num_confirmed - 1)])
            share.save()

        cur_unconfirmed = [x.id for x in cur_unconfirmed]

        confirmed_shares = [x.id for x in Share.objects.filter(balance__status='immature',
                                                               block_height__lte=(current_height - CONFIRMATION_LENGTH),
                                                               status='solved').distinct() if
                            x.id not in cur_unconfirmed]
        conf = Share.objects.get(id=confirmed_shares[0])
        conf.pow_identity = 'wrong_hash'
        conf.save()
        conf_balances = [b.id for b in Balance.objects.filter(share=conf, status='immature')]

        balances_to_status = {
            balance.id: balance.status for balance in Balance.objects.all()
        }

        total_bal_count = Balance.objects.all().count()
        immature_to_mature()
        for id in conf_balances:
            b = Balance.objects.get(id=id)
            self.assertEqual(Balance.objects.filter(miner=b.miner, status='mature',
                                                    balance=-b.balance, share=conf).count(), 1)

        self.assertEqual(Balance.objects.all().count(), total_bal_count + len(conf_balances))

        conf = Share.objects.get(id=conf.id)
        self.assertTrue(conf.is_orphaned)

        for balance_id in balances_to_status.keys():
            balance = Balance.objects.get(id=balance_id)
            if balance.share is None or balance.share.id not in confirmed_shares:
                self.assertEqual(balance.status, balances_to_status[balance.id])

            else:
                if balances_to_status[balance.id] == "immature":
                    self.assertEqual(balance.status, "mature")

                else:
                    self.assertEqual(balance.status, balances_to_status[balance.id])

    @patch('core.tasks.node_request', side_effect=mocked_node_request)
    @patch('core.tasks.RewardAlgorithm.perform_logic', side_effect=mocked_reward_algorithm_do_nothing)
    def test_some_shares_incorrect_tx_height(self, mocked_node_request, logic):
        """
        20 shares have immature balances and their block_height is less than the threshold
        15 of these shares are confirmed
        some solved confirmed share has issues because their tx height does not match with share height
        """
        current_height = ImmatureToMatureTestCase.CURRENT_HEIGHT
        CONFIRMATION_LENGTH = Configuration.objects.CONFIRMATION_LENGTH
        cur_unconfirmed = Share.objects.filter(balance__status='immature',
                                               block_height=(current_height - CONFIRMATION_LENGTH),
                                               status='solved').distinct()[:5]
        for share in cur_unconfirmed:
            num_confirmed = int(share.transaction_id.split('_')[-1])
            share.transaction_id = '_'.join([random_string(), str(share.block_height), str(num_confirmed - 1)])
            share.save()

        cur_unconfirmed = [x.id for x in cur_unconfirmed]

        confirmed_shares = [x.id for x in Share.objects.filter(balance__status='immature',
                                                               block_height__lte=(current_height - CONFIRMATION_LENGTH),
                                                               status='solved').distinct() if
                            x.id not in cur_unconfirmed]
        conf = Share.objects.get(id=confirmed_shares[0])
        conf.block_height = 10
        conf.save()
        conf_balances = [b.id for b in Balance.objects.filter(share=conf, status='immature')]

        balances_to_status = {
            balance.id: balance.status for balance in Balance.objects.all()
        }

        total_bal_count = Balance.objects.all().count()
        immature_to_mature()
        for id in conf_balances:
            b = Balance.objects.get(id=id)
            self.assertEqual(Balance.objects.filter(miner=b.miner, status='mature',
                                                    balance=-b.balance, share=conf).count(), 1)

        self.assertEqual(Balance.objects.all().count(), total_bal_count + len(conf_balances))

        conf = Share.objects.get(id=conf.id)
        self.assertTrue(conf.is_orphaned)

        for balance_id in balances_to_status.keys():
            balance = Balance.objects.get(id=balance_id)
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
            share.block_height += 100
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
                                               settings.SHARE_DETAIL_FOLDER, date) + '.csv'
        self.shares_aggregate_file = os.path.join(settings.AGGREGATE_ROOT_FOLDER,
                                                  settings.SHARE_AGGREGATE_FOLDER, date) + '.csv'
        self.balance_detail_file = os.path.join(settings.AGGREGATE_ROOT_FOLDER,
                                                settings.BALANCE_DETAIL_FOLDER, date) + '.csv'

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

        share = self.solved[:-settings.KEEP_SHARES_WITH_DETAIL_NUM][-1]
        shares = Share.objects.filter(status__in=['valid', 'invalid', 'repetitious'], created_at__lte=share.created_at)
        share_detail_content = shares.to_csv().decode('utf-8')
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

        self.assertTrue(os.path.exists(self.shares_detail_file))
        with open(self.shares_detail_file, 'r') as file:
            content = sorted(file.read().split('\n'))
            self.assertEqual(sorted(share_detail_content.split('\n')), content)

        self.assertTrue(os.path.exists(self.shares_aggregate_file))
        with open(self.shares_aggregate_file, 'r') as file:
            content = file.read().rstrip()
            content = content.split('\n')
            self.assertEqual(len(content), 11)

    def test_share_6_with_detail_other_aggregated(self, mocked_time):
        """
        some aggregated must be removed, some details must be aggregated
        """
        mocked_time.now.return_value = datetime.strptime('2020-01-27 12:19:46.196633',
                                                         '%Y-%m-%d %H:%M:%S.%f')

        shares = Share.objects.filter(created_at=self.solved[4].created_at - timedelta(seconds=1))
        share_detail_content = shares.to_csv().decode('utf-8')

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
        share_aggregate_content = AggregateShare.objects.filter(solved_share__in=self.solved[:2]). \
            to_csv().decode('utf-8')

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

        for filename, expected_content in [(self.shares_aggregate_file, share_aggregate_content),
                                           (self.shares_detail_file, share_detail_content)]:
            self.assertTrue(os.path.exists(filename))
            with open(filename, 'r') as file:
                content = sorted(file.read().split('\n'))
                self.assertEqual(sorted(expected_content.split('\n')), content)

    def test_share_6_with_detail_other_aggregated_some_miners_not_exist_in_round(self, mocked_time):
        """
        some aggregated must be removed, some details must be aggregated
        some miners are not in the round to be aggregate, no aggregate object must be created for that miner
        """
        mocked_time.now.return_value = datetime.strptime('2020-01-27 12:19:46.196633',
                                                         '%Y-%m-%d %H:%M:%S.%f')
        # first miner is not present in 5th round, so nothing must be aggregated for him
        Share.objects.filter(created_at=self.solved[4].created_at - timedelta(seconds=1),
                             miner=Miner.objects.all()[0]).delete()

        share_detail_content = Share.objects.filter(created_at=self.solved[4].created_at - timedelta(seconds=1)). \
            to_csv().decode('utf-8')

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

        share_aggregate_content = AggregateShare.objects.filter(solved_share__in=self.solved[:2]). \
            to_csv().decode('utf-8')

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

        for filename, expected_content in [(self.shares_aggregate_file, share_aggregate_content),
                                           (self.shares_detail_file, share_detail_content)]:
            self.assertTrue(os.path.exists(filename))
            with open(filename, 'r') as file:
                content = sorted(file.read().split('\n'))
                self.assertEqual(sorted(expected_content.split('\n')), content)

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
        balances = Balance.objects.filter(created_at__lte=self.solved[1].created_at)
        balance_detail_content = balances.to_csv()
        balance_detail_content = balance_detail_content.decode('utf-8')

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

        for filename, expected_content in [(self.balance_detail_file, balance_detail_content)]:
            self.assertTrue(os.path.exists(filename))
            with open(filename, 'r')as file:
                content = sorted(file.read().split('\n'))
                self.assertEqual(sorted(expected_content.split('\n')), content)

    def test_balance_all_with_detail_some_without_share(self, mocked_time):
        """
        all balances are with details
        some balances don't have share filed
        """
        mocked_time.now.return_value = datetime.strptime('2020-01-27 12:19:46.196633',
                                                         '%Y-%m-%d %H:%M:%S.%f')

        b = Balance.objects.create(miner=Miner.objects.all()[0], balance=int(100e9), status="mature")
        Balance.objects.filter(id=b.id).update(created_at=self.solved[1].created_at - timedelta(seconds=1))
        b = Balance.objects.create(miner=Miner.objects.all()[0], balance=int(-50e9), status="withdraw")
        Balance.objects.filter(id=b.id).update(created_at=self.solved[1].created_at - timedelta(seconds=1))

        balance_detail_content = Balance.objects.filter(created_at__lte=self.solved[1].created_at). \
            to_csv().decode('utf-8')

        aggregate()

        for miner in Miner.objects.all()[1:]:
            self.assertEqual(Balance.objects.filter(miner=miner, status="mature", balance=int(60e9)).count(), 1)
            self.assertEqual(Balance.objects.filter(miner=miner, status="withdraw", balance=int(-20e9)).count(), 1)

        self.assertEqual(
            Balance.objects.filter(miner=Miner.objects.all()[0], status="mature", balance=int(160e9)).count(), 1)
        self.assertEqual(
            Balance.objects.filter(miner=Miner.objects.all()[0], status="withdraw", balance=int(-70e9)).count(), 1)

        for solved in self.solved[2:]:
            for miner in Miner.objects.all():
                self.assertEqual(Balance.objects.filter(share=solved, miner=miner, status="mature",
                                                        balance=int(30e9)).count(), 1)
                self.assertEqual(Balance.objects.filter(share=solved, miner=miner, status="withdraw",
                                                        balance=int(-10e9)).count(), 1)

        for filename, expected_content in [(self.balance_detail_file, balance_detail_content)]:
            self.assertTrue(os.path.exists(filename))
            with open(filename, 'r') as file:
                content = sorted(file.read().split('\n'))
                self.assertEqual(sorted(expected_content.split('\n')), content)

    @override_settings(KEEP_BALANCE_WITH_DETAIL_NUM=0)
    def test_balance_all_with_detail_no_detail_remain(self, mocked_time):
        """
        no detail should remain, all should be aggregated
        """
        mocked_time.now.return_value = datetime.strptime('2020-01-27 12:19:46.196633',
                                                         '%Y-%m-%d %H:%M:%S.%f')
        balance_detail_content = []
        settings.KEEP_BALANCE_WITH_DETAIL_NUM = 0

        balance_detail_content = Balance.objects.all().to_csv().decode('utf-8')

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

        for filename, expected_content in [(self.balance_detail_file, balance_detail_content)]:
            self.assertTrue(os.path.exists(filename))
            with open(filename, 'r') as file:
                content = sorted(file.read().split('\n'))
                self.assertEqual(sorted(expected_content.split('\n')), content)

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

        balance_detail_content = Balance.objects.filter(created_at__lte=self.solved[1].created_at,
                                                        status__in=["mature", "withdraw"]).to_csv().decode('utf-8')
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

        for filename, expected_content in [(self.balance_detail_file, balance_detail_content)]:
            self.assertTrue(os.path.exists(filename))
            with open(filename, 'r') as file:
                content = sorted(file.read().split('\n'))
                self.assertEqual(sorted(expected_content.split('\n')), content)

    def tearDown(self):
        Configuration.objects.all().delete()
        Miner.objects.all().delete()
        Share.objects.all().delete()
        Balance.objects.all().delete()
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
        Configuration.objects.all().delete()
        Miner.objects.all().delete()
        Address.objects.all().delete()
        Share.objects.all().delete()
        AggregateShare.objects.all().delete()
        Balance.objects.all().delete()


class GetMinerAddressTestCase(TestCase):
    """
    Test class for ergo price creation and get
    """

    def mock_get_price(*args, **kwargs):
        return {'ergo': {'btc': 10.1, 'usd': 11.1}}

    def setUp(self):
        pass

    @patch('core.tasks.CoinGeckoAPI.get_price', side_effect=mock_get_price)
    def test_create_prices(self, mock):
        """
        must create prices in DB if not exist
        """
        get_ergo_price()
        self.assertEqual(ExtraInfo.objects.filter(key='ERGO_PRICE_BTC', value='10.1').count(), 1)
        self.assertEqual(ExtraInfo.objects.filter(key='ERGO_PRICE_USD', value='11.1').count(), 1)

    @patch('core.tasks.CoinGeckoAPI.get_price', side_effect=mock_get_price)
    def test_update_prices(self, mock):
        """
        must update price if they exist
        """
        ExtraInfo.objects.create(key='ERGO_PRICE_BTC', value='1.1')
        get_ergo_price()
        self.assertEqual(ExtraInfo.objects.filter(key='ERGO_PRICE_BTC', value='10.1').count(), 1)
        self.assertEqual(ExtraInfo.objects.filter(key='ERGO_PRICE_USD', value='11.1').count(), 1)

    def tearDown(self):
        Configuration.objects.all().delete()
        ExtraInfo.objects.all().delete()


class PeriodicVerifyBlocks(TestCase):
    """
    For test task periodic verify blocks
    """
    CURRENT_HEIGHT = 11

    def mocked_node_request(*args, **kwargs):
        """
        mock requests with method post
        """
        url = args[0]

        if url == 'info':
            return {
                'response': {'fullHeight': PeriodicVerifyBlocks.CURRENT_HEIGHT},
                'status': 'success'
            }

        if 'wallet/transactionById' in url:
            params = kwargs['params']['id']
            if params == '6':
                return {
                    'response': ['Error'],
                    'status': 'External Error'
                }
            if params == '7':
                return {
                    'status': 'not-found'
                }
            if params == '8':
                return {
                    'response': {'inclusionHeight': int(params) + 1},
                    'status': 'success'
                }
            return {
                'response': {'inclusionHeight': int(params)},
                'status': 'success'
            }

        return {
            'response': None,
            'status': 'error'
        }

    def setUp(self):
        """
        Create 1 miner and 10 shares with specific transaction_id and block_height
        :return:
        """
        miner = Miner.objects.create(public_key='1')
        for x in range(10):
            Share.objects.create(miner=miner, transaction_id=str(x), difficulty=1, block_height=str(x),
                                 status='solved', parent_id='1')

    @patch('core.tasks.node_request', side_effect=mocked_node_request)
    def test_verify_blocks(self, mock_node):
        """
        run task verify blocks and check flag transaction_valid expect transaction_valid for shares with
        transaction_id 8, 7 is False because height not true and not-found transaction in block-chain,
         transaction_id 6 flag is None because node don't send response for this share,
          transaction_id 9 is None because not in range check transaction.
        :return:
        """
        periodic_verify_blocks()
        shares = Share.objects.all().order_by('transaction_id')
        self.assertIsNone(shares[9].transaction_valid)
        self.assertFalse(shares[8].transaction_valid)
        self.assertFalse(shares[7].transaction_valid)
        self.assertIsNone(shares[6].transaction_valid)
        for x in range(5, -1, -1):
            self.assertTrue(shares[x].transaction_valid)

    def tearDown(self):
        """
        tearDown function to clean up objects created in setUp function
        :return:
        """
        Configuration.objects.all().delete()
        Miner.objects.all().delete()
        Share.objects.all().delete()
        Balance.objects.all().delete()


class AdministratorUserTestCase(TestCase):
    """
    test route administrator/users
    result of every miner similar this
    {
        "user": public_key,
        "hash_rate": int,
        "valid_shares": int,
        "invalid_shares": int,
        "last_ip": last ip of miner,
        "status": active or inactive
    }
    """

    def setUp(self):
        """
        Create 4 miners and set miner ip for them so call 10 shares for every miners and set authenticate.
        :return:
        """
        for i in range(1, 5):
            Miner.objects.create(public_key=i, ip='127.0.0.{}'.format(i))

        miner = Miner.objects.all()

        for x in range(10):
            Share.objects.create(miner=miner[0], transaction_id=str(x), difficulty=10000, block_height=str(x),
                                 status='solved', parent_id='1')
            Share.objects.create(miner=miner[1], transaction_id=str(x), difficulty=10000, block_height=str(x),
                                 status='invalid', parent_id='1')
            Share.objects.create(miner=miner[2], transaction_id=str(x), difficulty=10000, block_height=str(x),
                                 status='repetitious', parent_id='1')
            Share.objects.create(miner=miner[3], transaction_id=str(x), difficulty=20000, block_height=str(x),
                                 status='valid', parent_id='1')
        # set session authenticate
        self.factory = RequestFactory()
        User.objects.create_user(username='test', password='test')
        self.client = APIClient()
        self.client.login(username='test', password='test')

    def test_call_api_normal(self):
        """
        We expect with call route /administrator/users/ get all miners.
        """
        # Call route /administrator/users/
        response = self.client.get('/administrator/users/').json()
        # Expected output
        with open("core/data_testing/administrator_user_normal.json", "r") as read_file:
            file = json.load(read_file)

        self.assertEqual(response, file)

    def test_call_api_query_1(self):
        """
        We expect with call route /administrator/users/ get miners that has last_ip with range 127.0.0.2 - 127.0.0.10
         and sorted according to user.
        """
        # Call route /administrator/users/
        data = {
            'last_ip_min': '127.0.0.2',
            'last_ip_max': '127.0.0.10',
            'ordering': '-last_ip'
        }
        response = self.client.get('/administrator/users/', data, content_type='application/json').json()
        # Expected output
        with open("core/data_testing/administrator_user_query_1.json", "r") as read_file:
            file = json.load(read_file)

        self.assertEqual(response, file)

    def test_call_api_query_2(self):
        """
        We expect with call route /administrator/users/ get miners that has hash_rate with range 50 - 150
         and lat_ip bigger than 127.0.0.2
        """
        # Call route /administrator/users/
        data = {
            'hash_rate_min': '50',
            'hash_rate_max': '150',
            'last_ip_min': '127.0.0.2'
        }
        response = self.client.get('/administrator/users/', data, content_type='application/json').json()
        # Expected output
        with open("core/data_testing/administrator_user_query_2.json", "r") as read_file:
            file = json.load(read_file)

        self.assertEqual(response, file)

    def test_call_api_query_3(self):
        """
        We expect with call route /administrator/users/ get exception because ip is invalid
        """
        # Call route /administrator/users/
        data = {
            'last_ip_max': '127.0.0.1116'
        }
        response = self.client.get('/administrator/users/', data, content_type='application/json').json()

        self.assertEqual(response, ['Filter range for last_ip is invalid.'])

    def test_get_today_txs(self):
        today = timezone.now() - timedelta(hours=1)
        yesterday = today - timedelta(days=1, hours=1)
        tz = get_current_timezone()
        today = timezone.datetime.fromtimestamp(today.timestamp(), tz=tz)
        yesterday = timezone.datetime.fromtimestamp(yesterday.timestamp(), tz=tz)
        miners = Miner.objects.all()
        tx1 = Transaction.objects.create(tx_id='id', tx_body='{}', is_confirmed=False)
        tx1.created_at = today
        tx1.save()
        tx2 = Transaction.objects.create(tx_id='id2', tx_body='{}', is_confirmed=True)
        tx2.created_at = yesterday
        tx2.save()
        for i in range(0, 2):
            Balance.objects.create(tx=tx1, miner=miners[i], status='pending_withdrawal', actual_payment=int(1e9))
        for i in range(2, 4):
            Balance.objects.create(tx=tx2, miner=miners[i], status='pending_withdrawal', actual_payment=int(1.5e9))
        response = self.client.get('/administrator/users/payments/', content_type='application/json').json()
        self.assertEqual(len(response), 1)
        self.assertEqual(response[0]['tx_id'], 'id')
        for miner in miners[0:2]:
            self.assertTrue({'pk': miner.public_key, 'paid': int(1e9)} in response[0]['payments'])

    def test_get_txs_with_params(self):
        today = timezone.now() - timedelta(hours=1)
        yesterday = today - timedelta(days=1, hours=1)
        tz = get_current_timezone()
        today = timezone.datetime.fromtimestamp(today.timestamp(), tz=tz)
        yesterday = timezone.datetime.fromtimestamp(yesterday.timestamp(), tz=tz)
        miners = Miner.objects.all()
        tx1 = Transaction.objects.create(tx_id='id', tx_body='{}', is_confirmed=False)
        tx1.created_at = today
        tx1.save()
        tx2 = Transaction.objects.create(tx_id='id2', tx_body='{}', is_confirmed=True)
        tx2.created_at = yesterday
        tx2.save()
        for i in range(0, 2):
            Balance.objects.create(tx=tx1, miner=miners[i], status='pending_withdrawal', actual_payment=int(1e9))
        for i in range(2, 4):
            Balance.objects.create(tx=tx2, miner=miners[i], status='pending_withdrawal', actual_payment=int(1.5e9))
        data = {'from': (yesterday - timedelta(hours=5)).timestamp(), 'to': (today + timedelta(hours=5)).timestamp()}
        response = self.client.get('/administrator/users/payments/', data, content_type='application/json').json()
        self.assertEqual(len(response), 2)
        for miner in miners[0:2]:
            self.assertTrue({'pk': miner.public_key, 'paid': int(1e9)} in response[0]['payments'])
        for miner in miners[2:4]:
            self.assertTrue({'pk': miner.public_key, 'paid': int(1.5e9)} in response[1]['payments'])


time_now = [timezone.now()]


class LoginTestCase(TransactionTestCase):
    reset_sequences = True
    TIME = time_now
    DEVICE_CONFIG = getattr(settings, "DEVICE_CONFIG")
    DEFAULT_TOKEN_EXPIRE = getattr(settings, 'DEFAULT_TOKEN_EXPIRE')

    def mocked_verify_recaptcha(*args, **kwargs):
        return {'success': True}

    def mocked_verify_token(*args, **kwargs):
        if args[0] == '1234':
            return True
        if args[0] == '4321':
            return False

    def mocked_time(*args, **kwargs):
        return time_now[0]

    @patch('core.utils.verify_recaptcha', side_effect=mocked_verify_recaptcha)
    def test_valid_first_login(self, mock_verify_recaptcha):
        """
        In this scenario check first login for, getting token with out otp_token.
        :return:
        """
        # Create User
        self.factory = RequestFactory()
        user = User.objects.create_user(username='test', password='test')
        # Call route /login/
        response = self.client.post('/login/', data={
            'username': 'test',
            'password': 'test',
            'recaptcha_code': 'abcd'
        }).json()
        # Check generate token
        token = Token.objects.filter(user=user).first()
        self.assertEqual(token.key, response['token'])

    @patch('django.utils.timezone.now', side_effect=mocked_time)
    @patch('core.utils.verify_recaptcha', side_effect=mocked_verify_recaptcha)
    def test_valid_second_login_expired_token(self, mock_verify_recaptcha, mock_time):
        """
        In this scenario we expect after expire token with login user delete last token and create new token for user.
        :param mock_verify_recaptcha:
        :param mock_time:
        :return:
        """
        # Create User
        self.factory = RequestFactory()
        user = User.objects.create_user(username='test', password='test')
        # Create token for above user
        token = Token.objects.create(user=user)
        token = token.key
        # Forward time to size DEFAULT_TOKEN_EXPIRE['PER_USE'] ( The token has now expired )
        self.TIME[0] = timezone.now() + timedelta(seconds=self.DEFAULT_TOKEN_EXPIRE['PER_USE'])
        # Call route /login/
        response = self.client.post('/login/', data={
            'username': 'test',
            'password': 'test',
            'recaptcha_code': 'abcd'
        }).json()
        self.assertNotEqual(token, response['token'])

    @patch('core.utils.verify_recaptcha', side_effect=mocked_verify_recaptcha)
    def test_login_with_OTP_device_empty_otp_toekn(self, mock_verify_recaptcha):
        """
        if a user have OTP-Device should be enter otp-token
        :return:
        """
        # Create User
        self.factory = RequestFactory()
        user = User.objects.create_user(username='test', password='test')
        # create device for this user
        device_config = self.DEVICE_CONFIG.copy()
        device_config.update({'user': user, 'name': user.username, 'confirmed': True})
        TOTPDevice.objects.create(**device_config)
        # Call route /login/ for the time being device created for user should be enter OTP-token
        response = self.client.post('/login/', data={
            'username': 'test',
            'password': 'test',
            'recaptcha_code': 'abcd'
        }).json()
        self.assertEqual(response, {
            'non_field_errors': ['For this user, Two-Step verification is active so OTP Token is required.']
        })

    @patch('django_otp.plugins.otp_totp.models.TOTPDevice.verify_token', side_effect=mocked_verify_token)
    @patch('core.utils.verify_recaptcha', side_effect=mocked_verify_recaptcha)
    def test_login_with_OTP_device_valid(self, mock_verify_recaptcha, mock_TOTP_verify):
        """
        OTP-Token is valid should be return a token in response
        :return:
        """
        # Create User
        self.factory = RequestFactory()
        user = User.objects.create_user(username='test', password='test')
        # create device for this user
        device_config = self.DEVICE_CONFIG.copy()
        device_config.update({'user': user, 'name': user.username, 'confirmed': True})
        TOTPDevice.objects.create(**device_config)
        # Call route /login/ for the time being device created for user should be enter OTP-token
        response = self.client.post('/login/', data={
            'username': 'test',
            'password': 'test',
            'recaptcha_code': 'abcd',
            'otp_token': '1234'
        }).json()
        token = Token.objects.filter(user=user).first()
        self.assertEqual(token.key, response['token'])

    @patch('django_otp.plugins.otp_totp.models.TOTPDevice.verify_token', side_effect=mocked_verify_token)
    @patch('core.utils.verify_recaptcha', side_effect=mocked_verify_recaptcha)
    def test_login_with_OTP_device_invalid(self, mock_verify_recaptcha, mock_TOTP_verify):
        """
        In this scenario checking OTP-Token, that is invalid.
        :return:
        """
        # Create User
        self.factory = RequestFactory()
        user = User.objects.create_user(username='test', password='test')
        # create device for this user
        device_config = self.DEVICE_CONFIG.copy()
        device_config.update({'user': user, 'name': user.username, 'confirmed': True})
        TOTPDevice.objects.create(**device_config)
        # checking OTP-Token that is invalid.
        response = self.client.post('/login/',
                                    data={
                                        'username': 'test',
                                        'password': 'test',
                                        'recaptcha_code': 'abcd',
                                        'otp_token': '4321'
                                    }).json()
        self.assertEqual(response, {'non_field_errors': ['OTP Token is invalid.']})

    @patch('django.utils.timezone.now', side_effect=mocked_time)
    def test_login_with_expire_token_per_use(self, mock):
        """
        In this scenario checking expired token after passing DEFAULT_TOKEN_EXPIRE from last use user this token.
        :param mock:
        :return:
        """
        # Create User
        self.factory = RequestFactory()
        user = User.objects.create_user(username='test', password='test')
        # Create token for above user
        token = Token.objects.create(user=user)
        # Set token for send request
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Token ' + token.key)
        # Call a request that need Token authenticate
        response = client.post('/totp/')
        self.assertEqual(response.status_code, 201)
        # Take time forward to one day later
        self.TIME[0] = timezone.now() + timedelta(seconds=self.DEFAULT_TOKEN_EXPIRE['PER_USE'])
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Token ' + token.key)
        response = client.post('/totp/')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {'detail': 'Expired token.'})

    @patch('django.utils.timezone.now', side_effect=mocked_time)
    def test_login_with_expire_token_TOTAL(self, mock):
        """
        In this scenario we want checking expired token after passing DEFAULT_TOKEN_EXPIRE['TOTAL'] from created token.
        :param mock:
        :return:
        """
        # Create User
        self.factory = RequestFactory()
        user = User.objects.create_user(username='test', password='test')
        # Create token for above user
        token = Token.objects.create(user=user)
        # Set token for send request
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Token ' + token.key)
        # Call a request that need Token authenticate
        response = client.post('/totp/')
        self.assertEqual(response.status_code, 201)
        # We take the time forward as much as DEFAULT_TOKEN_EXPIRE['TOTAL']
        self.TIME[0] = timezone.now() + timedelta(seconds=self.DEFAULT_TOKEN_EXPIRE['TOTAL'])
        # Update last_use token to half a day after now time
        token.last_use = timezone.now() + timedelta(seconds=(self.DEFAULT_TOKEN_EXPIRE['TOTAL'] - 9.5 * 24 * 60 * 60))
        token.save()
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Token ' + token.key)
        response = client.post('/totp/')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {'detail': 'Expired token.'})


class TOTPTestCase(TransactionTestCase):
    reset_sequences = True
    DEVICE_CONFIG = getattr(settings, "DEVICE_CONFIG")

    def test_QR_first_device(self):
        """
        In this scenario checking route /totp/ for create TOTP-device in first time,
        after that checking QR-Code generated of this route equal with QR-Code of device
        :return:
        """
        # Create User
        self.factory = RequestFactory()
        user = User.objects.create_user(username='test', password='test')
        # create token for this user
        token, created = Token.objects.get_or_create(user=user)
        # Create TOTP-Device with route /totp/
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Token ' + token.key)
        response = client.post('/totp/').json()
        # Check create device for this user
        device = TOTPDevice.objects.filter(user=user).first()
        self.assertIsNotNone(device)
        qrcode_1 = TOTPDeviceViewSet.get_qr_code(device.config_url)
        # checking QR-Code for this device equals to the response of this route or no
        self.assertEqual(qrcode_1, response['qrcode'])

    def test_second_device(self):
        """
         In this scenario checking with call route /totp/ for user that have device should be
         generate a new device instead of last device, with create a TOTP-Device for user.
        :return:
        """
        # Create User
        self.factory = RequestFactory()
        user = User.objects.create_user(username='test', password='test')
        # create token for this user
        token, created = Token.objects.get_or_create(user=user)
        # create device for this user
        device_config = self.DEVICE_CONFIG.copy()
        device_config.update({'user': user, 'name': user.username, 'confirmed': True})
        device = TOTPDevice.objects.create(**device_config)
        # Create TOTP-Device with route /totp/
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Token ' + token.key)
        # Check reload new secret key for this device when device exist.
        response = client.post('/totp/').json()
        qrcode = TOTPDeviceViewSet.get_qr_code(device.config_url)
        self.assertNotEqual(qrcode, response['qrcode'])


class UIDataTestCase(TransactionTestCase):
    reset_sequences = True
    DEFAULT_UI_PREFIX_DIRECTORY = getattr(settings, 'DEFAULT_UI_PREFIX_DIRECTORY')

    def setUp(self):
        # Create User
        self.factory = RequestFactory()
        user = User.objects.create_user(username='x', password='y')
        # Create token for above user
        token = Token.objects.create(user=user)
        self.token = token

    @patch("builtins.open", new_callable=mock_open)
    def test_patch_get(self, mock_file):
        self.client.get('/ui/test/about/', **{'HTTP_source-ip': '127.0.0.1'}).json()
        mock_file.assert_called_with(os.path.join(self.DEFAULT_UI_PREFIX_DIRECTORY, 'test/about'), 'r')

    @patch("os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    def test_patch_post(self, mock_file, mock_make_dir):
        # Set token for send request
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        client.post(path='/ui/test/about/', data=json.dumps({
            "data": {
                "test": "test"
            }
        }), content_type='application/json', **{'HTTP_source-ip': '127.0.0.1'})
        mock_file.assert_called_with(os.path.join(self.DEFAULT_UI_PREFIX_DIRECTORY, 'test/about'), 'w')
        mock_make_dir.assert_called_with(os.path.join(self.DEFAULT_UI_PREFIX_DIRECTORY, 'test'), mode=0o750,
                                         exist_ok=True)


class TestSupport(TestCase):
    """
    Test scenario get support information and check recaptcha code and send with email to admin system
    """
    RECAPTCHA_SITE_KEY = getattr(settings, 'RECAPTCHA_SITE_KEY')
    SENDER_EMAIL_ADDRESS = getattr(settings, 'SENDER_EMAIL_ADDRESS')
    RECEIVERS_EMAIL_ADDRESS = getattr(settings, 'RECEIVERS_EMAIL_ADDRESS')

    def mock_send_mail(*args, **kwargs):
        raise TypeError

    def test_send_email_support_get(self):
        """
        in this test should be get RECAPTCHA_SITE_KEY
        :return:
        """
        response = self.client.get('/support/').json()
        self.assertEqual(response.get('site_key'), self.RECAPTCHA_SITE_KEY)

    @patch('core.utils.verify_recaptcha', return_value={'success': True})
    @patch('core.tasks.send_support_email.delay')
    def test_send_email_support_post(self, mock_mail, mock_recaptcha):
        """
        In this test case should be send information of form support and get message ok with status_code 200
        :param mock_mail:
        :param mock_recaptcha:
        :return:
        """
        data = {
            "recaptcha_code": "test",
            "name": "Alex Chepurnoy",
            "email": "test@ergopool.io",
            "subject": "Problem Config Config proxy",
            "message": "Please, Help."
        }
        response = self.client.post('/support/', data=data, content_type="application/json")
        message = "Name: %s\nEmail: %s\nMessage: %s" % (data.get('name'), data.get('email'), data.get('message'))
        mock_mail.assert_has_calls([call(data.get('subject'), message)])
        self.assertEqual(response.json().get('status'), ['ok'])
        self.assertEqual(response.status_code, 200)


class TestPeriodicCalculateHashRate(TestCase):
    """
    Test periodic task for calculate hash_rate and save in data_base
    """

    def mocked_node_request(*args, **kwargs):
        """
        mock requests with method post
        """
        url = args[0]

        if url == 'info':
            return {
                'response': {'fullHeight': 14975},
                'status': 'success'
            }
        if url == 'blocks/chainSlice':
            params = kwargs['params']
            blocks = json.loads(open('core/data_testing/periodic_calculate_hash_rate_chain_slice.json').read())
            output = []
            for block in blocks:
                if params['fromHeight'] < block['height'] <= params['toHeight']:
                    output.append(block)
            return {
                'status': 'success',
                'response': output
            }

        return {
            'response': None,
            'status': 'error'
        }

    def mocked_time(*args, **kwargs):
        return datetime(2020, 6, 23, 7, 46, 0, 395985, tzinfo=timezone.utc)

    def setUp(self):
        # create miners lists
        miners = [Miner.objects.create(nick_name="miner %d" % i, public_key=str(i)) for i in range(3)]
        # create shares list
        [Share.objects.create(share=str(i), miner=miners[i % 3],
                              status="solved" if i in [14, 34, 35] else "valid" if i % 2 == 0 else "invalid",
                              difficulty=1000 * i + 1) for i in range(36)]

    @override_settings(LIMIT_NUMBER_BLOCK=2)
    @override_settings(PERIOD_DIAGRAM=15 * 60)
    @patch('django.utils.timezone.now', side_effect=mocked_time)
    @patch('core.tasks.node_request', side_effect=mocked_node_request)
    def test_task(self, mock_node, mock_time):
        """
        Except for this test case calculate hash_rate of network and pool in PERIOD_DIAGRAM and save them in database
        :param mock_node:
        :param mock_time:
        :return:
        """
        periodic_calculate_hash_rate()
        hash_rate = HashRate.objects.last()
        self.assertEqual(hash_rate.pool, 378.0)
        self.assertEqual(hash_rate.network, 576.0)


class HandleTransactionTestCase(TestCase):
    """
    Test class for handle transaction task
    """

    def mocked_node_request(*args, **kwargs):
        """
        mock requests with method post
        """
        url = args[0]

        if 'transactionById' in url:
            conf = int(url.split('=')[-1])
            if conf >= 0:
                return {
                    'status': 'success',
                    'response': {'numConfirmations': conf}
                }
            else:
                return {
                    'status': 'error',
                }

        if url == 'transaction':
            return {
                'status': 'success'
            }

        return {
            'response': None,
            'status': 'error'
        }

    def setUp(self):
        """
        1 tx
        2 balance associated with that tx
        :return:
        """
        self.tx = Transaction.objects.create(tx_id='tx_id', tx_body='{}')
        miner = Miner.objects.create(public_key='pk')
        for i in range(2):
            Balance.objects.create(tx=self.tx, miner=miner, status='pending_withdrawal')

    @patch('core.tasks.node_request', side_effect=mocked_node_request)
    def test_send_email_support_post(self, node_request):
        """
        not mined, broadcast
        """
        self.tx.tx_id = '-1'
        self.tx.save()
        handle_transactions()
        for b in Balance.objects.all():
            self.assertEqual(b.status, 'pending_withdrawal')
        self.assertEqual(Transaction.objects.first().is_confirmed, False)
        node_request.assert_has_calls([call('transactions', data={}, request_type='post')])

    @patch('core.tasks.node_request', side_effect=mocked_node_request)
    def test_send_email_support_post(self, node_request):
        """
        mined, not confirmed, do nothing!
        """
        self.tx.tx_id = '5'
        self.tx.save()
        handle_transactions()
        for b in Balance.objects.all():
            self.assertEqual(b.status, 'pending_withdrawal')
        self.assertEqual(Transaction.objects.first().is_confirmed, False)

    @patch('core.tasks.node_request', side_effect=mocked_node_request)
    def test_send_email_support_post(self, node_request):
        """
        mined, confirmed. update statuses
        """
        self.tx.tx_id = '12'
        self.tx.save()
        handle_transactions()
        for b in Balance.objects.all():
            self.assertEqual(b.status, 'withdraw')
        self.assertEqual(Transaction.objects.first().is_confirmed, True)


class PaymentViewTestCase(TestCase):
    """
    tests payment view
    """

    def setUp(self):
        self.client = Client()
        Configuration.objects.create(key='DEFAULT_WITHDRAW_THRESHOLD', value=str(int(1e8)))
        for i in range(3):
            Miner.objects.create(public_key=str(i))

    def test_get_current_balances(self):
        """
        will return miner's balances
        """
        for miner in Miner.objects.all():
            Balance.objects.create(miner=miner, balance=int(1e9),
                                   min_height=1, max_height=10, status='mature')
            Balance.objects.create(miner=miner, balance=int(1e9),
                                   min_height=1, max_height=10, status='immature')
        expected = []
        for b in Balance.objects.filter(status='mature'):
            expected.append({
                'miner_id': b.miner.id,
                'miner_pk': b.miner.public_key,
                'balance': b.balance,
                'actual_payment': b.balance,
                'min_height': b.min_height,
                'max_height': b.max_height
            })
        response = self.client.get('/payment/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)

    def test_payment(self):
        """
        post for payment, will create pending_withdrawal balances
        """
        expected = []
        for b in Miner.objects.all():
            expected.append({
                'miner_id': b.id,
                'balance': int(1e9),
                'actual_payment': int(2e9),
                'min_height': 1,
                'max_height': 10
            })
        response = self.client.post('/payment/', data=expected, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        for i in expected:
            self.assertEqual(Balance.objects.filter(miner_id=i['miner_id'], balance=-int(1e9),
                                                    actual_payment=int(2e9), min_height=1,
                                                    max_height=10, status='pending_withdrawal').count(), 1)
