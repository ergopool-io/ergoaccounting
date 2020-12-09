# ErgoPool accounting
This project is a api server for [ergopool.io](https://ergopool.io) now ergopool is closed due to incoming hardfork of Ergo. 
Ergopool is an impotent semi-decentralized mining pool built to empower the most decentralized blockchain ever existed.

In ergopool microservice architecture, ergoaccounting is behind of [ergoapi](https://github.com/ergopool-io/ergoapi) service.
## Setup
### Prerequisite
  * python:3.7
  * django>=2.2,<2.3
### Getting Started

The best solution for starting this service is, build [Dockerfile](https://github.com/ergopool-io/ergoaccounting/blob/master/Dockerfile) and use it.

First clone the repository from Github and switch to the new directory:
```
$ git clone https://github.com/ergopool-io/ergoaccounting.git
$ cd ergoaccounting
```

Install project dependencies:
```
$ pip3 install -r requirements.txt
```

For config app in development mode use [production.py.sample](https://github.com/ergopool-io/ergoaccounting/blob/master/ErgoAccounting/production.py.sample) and rename this file to `production.py` and for production mode use this file [production.py](https://github.com/ergopool-io/ergoaccounting/blob/master/config/production.py) and after config default value or set enviroment for parameters move this file to [this path](https://github.com/ergopool-io/ergoaccounting/blob/master/ErgoAccounting/).

Then simply apply the migrations:
```
$ python manage.py migrate
```

Note: for running ergoaccounting service you need to run rabbitmq or redis for celery task, also you need to set up an [Ergo node](https://github.com/ergoplatform/ergo.git) and set url them to the config file `production.py`.

You can now run the development server :
```
$ python manage.py runserver
```

in this service we are accounting both valid shares and invalid shares. invalid shares will result in some penalties for the user (this is best approch but not now).

users are identified by their erg address, and their workers are identified by a ip for their [proxy](https://github.com/ergopool-io/proxy).

so the user may have several workers (proxies) working for one address.

so, we define some time windows, starting from the last block mined in the pool and finishing by a new block mined in the pool.

during this window, any shares will be accounted for the user. when the window is closed (a new block mined) the window is closed and a new window is started.

the accounting system has some delay for accouting to be sure that the block is acctually accepted by the network and to avoid paying for orphan blocks.

ergopool support PROP, PPS, PPLNS algorithm for sharing reward that can set in reward setting by owner of ergopool.