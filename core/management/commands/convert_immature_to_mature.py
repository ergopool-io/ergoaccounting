import os
import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from core.models import Balance, Share, Configuration


class Command(BaseCommand):
    help = 'updating immature balances to mature balance'

    NODE_URL = getattr(settings, "NODE_URL", "http://vorujak:9052/")
    url = os.path.join(NODE_URL, "wallet/transactionById")

    def handle(self, *args, **kwargs):
        shares = Share.objects.filter(balance__status=1)
        for share in shares:
            PARAMS = {"id": share.transaction_id}
            transaction = requests.get(url, PARAMS).json()
            number_of_confirmations = transaction["numConfirmations"]
            height = transaction["inclusionHeight"]
            if number_of_confirmations > Configuration.objects.CONFIRMATION_LENGTH:
                Balance.objects.filter(share=share).update(status=2)
                share.block_height = height
                share.save()

