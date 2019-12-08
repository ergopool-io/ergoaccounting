import os
import requests
import json
from django.core.management.base import BaseCommand
from django.conf import settings
import logging

from core.models import Balance, Share, Configuration


class Command(BaseCommand):
    """
    command class for 'convert_immature_to_mature' command
    """
    help = 'updating immature balances to mature balance'

    def handle(self, *args, **kwargs):
        """
        handle function to define the logic and the process of the management command
        In this command we send a 'get' http method to 'transcriptById' endpoint
        and retrieve the 'number_of_confirmation' and 'height' from the response.
        For this purpose first we retrieve all shares which have immature balances and
        then for each share we check if the 'number_of_confirmation' is greater than 'CONFIRMATION_LENGTH',
        we change the status of related shares from 'immature' to 'mature'.
        After that we update the 'block_height' of the share.
        :return:
        """
        # Node URL
        NODE_URL = getattr(settings, "NODE_URL", "http://vorujak:9052/")
        # 'transcript by id' endpoint url
        url = os.path.join(NODE_URL, "wallet/transactionById")
        # retrieve api_key for node authorization
        API_KEY = getattr(settings, "API_KEY")
        # retrieve all shares which have 'immature' balances
        shares = Share.objects.filter(balance__status=1)
        # iterate on shares
        for share in shares:
            # construct required parameters for the endpoint
            params = {"id": share.transaction_id}
            # construct header for the endpoint
            headers = {'Authorization': 'api_key ' + API_KEY}
            # create a logging object
            logger = logging.getLogger()
            try:
                # send a get request to the endpoint and save the json response
                transaction = requests.get(url, params, headers=headers)
            except requests.exceptions.RequestException as e:
                # write a related log
                logger.error('Request Error: ' + str(e))
                continue
            # check whether the status code of the response is ok
            if transaction.status_code == 200:
                try:
                    # retrieve the json format of response
                    transaction_json = transaction.json()
                    # retrieve number of confirmation of the block
                    number_of_confirmations = transaction_json.get("numConfirmations", None)
                    # retrieve height of the block
                    height = transaction_json["inclusionHeight"]
                except json.decoder.JSONDecodeError as e:
                    # write a related log
                    logger.error('Json Decode Error: ' + str(e))
                    continue
                # check whether the 'number_of_confirmation' is greater than the configuration 'CONFIRMATION_LENGTH'
                if number_of_confirmations > Configuration.objects.CONFIRMATION_LENGTH:
                    # update the status of corresponding balances from immature to mature
                    Balance.objects.filter(share=share).update(status=2)
                    # update the block_height of the share
                    share.block_height = height
                    # saving the share to teh database
                    share.save()
            # check whether the status_code is not 200
            elif transaction.status_code == 404:
                # write a related log
                logger.error("Error: Forbidden")
                return
            elif transaction.status_code == 404:
                # write a related log
                logger.error("Transaction with specified id not found in wallet.")
                # to do
            elif transaction.status_code == 500:
                # write a related log
                logger.error("Internal Server Error")
                return
