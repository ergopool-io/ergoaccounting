### MODELS
we have 3 models<br>
* **Miners**
* **Share**
* **Balance**
  
#### Miner 
* `public_key`
* `nick_name`
* `created_at`
* `updated_at`
  
#### Share
* `share`
* `miner`
* `nonce`
* `status`
* `created_at`
* `updated_at`

#### Balance
* `miner`
* `share`
* `balance`
* `status`
* `created_at`
* `updated at`

_we recommend using post man for test purposes._

the main APIs are:
* `localhost:8000/shares`
* `localhost:8000/balances`
  
#### POST

for Share
```
{
    "share": "",
    "nonce":"",
    "status": null,
    "miner": null
}
```
the share status will be checked in order not to be duplicate.
the possible choices for share are
* `valid`
* `invalid`
* `solved`
* `repetitious`
only the `repetitious` status is assigned  by the accounting component, in case of duplicate share.

for‍‍‍‍‍ Balance‍
```
{
    "share": "",
    "balance":""
    "miner": null
}
```
the balance can have multiple status. the status is updated using API only when someone withdraw their from their account. 
**the API is only called for withdraw**.
only when the miner wishes to withdraw his/her money, the balance API is called, otherwise the API is in accessible for charging to viewing.
‍‍‍‍‍‍‍‍‍‍‍‍‍‍‍‍‍‍‍‍‍‍‍‍‍
_pay extra attention to the Foreignkeys and primary keys._
