# -*- coding: utf-8 -*-
import logging
from typing import Any, Dict, List, Optional, Union

from graphenecommon.chain import AbstractGrapheneChain

from vizapi.noderpc import NodeRPC
from vizbase import operations
from vizbase.chains import PRECISIONS

from .account import Account
from .amount import Amount
from .transactionbuilder import ProposalBuilder, TransactionBuilder
from .wallet import Wallet

# from .utils import formatTime

log = logging.getLogger(__name__)


class Client(AbstractGrapheneChain):
    """
    Blockchain network client.

    :param str node: Node to connect to
    :param str rpcuser: RPC user *(optional)*
    :param str rpcpassword: RPC password *(optional)*
    :param bool nobroadcast: Do **not** broadcast a transaction!
        *(optional)*
    :param bool debug: Enable Debugging *(optional)*
    :param array,dict,string keys: Predefine the wif keys to shortcut the
        wallet database *(optional)*
    :param bool offline: Boolean to prevent connecting to network (defaults
        to ``False``) *(optional)*
    :param str proposer: Propose a transaction using this proposer
        *(optional)*
    :param int proposal_expiration: Expiration time (in seconds) for the
        proposal *(optional)*
    :param int proposal_review: Review period (in seconds) for the proposal
        *(optional)*
    :param int expiration: Delay in seconds until transactions are supposed
        to expire *(optional)*
    :param bool blocking: Wait for broadcasted transactions to be included
        in a block and return full transaction. Blocking is checked inside
        :py:meth:`~graphenecommon.transactionbuilder.TransactionBuilder.broadcast`
        *(Default: False)*, *(optional)*
    :param bool bundle: Do not broadcast transactions right away, but allow
        to bundle operations *(optional)*

    Three wallet operation modes are possible:

    * **Wallet Database**: Here, the libs load the keys from the
      locally stored wallet SQLite database (see ``storage.py``).
      To use this mode, simply call ``Client()`` without the
      ``keys`` parameter
    * **Providing Keys**: Here, you can provide the keys for
      your accounts manually. All you need to do is add the wif
      keys for the accounts you want to use as a simple array
      using the ``keys`` parameter to ``Client()``.
    * **Force keys**: This more is for advanced users and
      requires that you know what you are doing. Here, the
      ``keys`` parameter is a dictionary that overwrite the
      ``active``, ``master``, or ``memo`` keys for
      any account. This mode is only used for *foreign*
      signatures!

    The purpose of this class it to simplify interaction with
    blockchain by providing high-level methods instead of forcing user to use RPC methods directly.

    The idea is to have a class that allows to do this:

    .. code-block:: python

        from viz import Client
        viz = Client()
        print(viz.info())
    """

    def define_classes(self):
        from .blockchainobject import BlockchainObject

        self.wallet_class = Wallet
        self.account_class = Account
        self.rpc_class = NodeRPC
        self.default_key_store_app_name = "viz"
        self.proposalbuilder_class = ProposalBuilder
        self.transactionbuilder_class = TransactionBuilder
        self.blockchainobject_class = BlockchainObject

    def transfer(
        self, to: str, amount: float, asset: str, memo: str = "", account: Optional[str] = None, **kwargs: Any
    ) -> dict:
        """
        Transfer an asset to another account.

        :param str to: Recipient
        :param float amount: Amount to transfer
        :param str asset: Asset to transfer
        :param str memo: (optional) Memo, may begin with `#` for encrypted
            messaging
        :param str account: (optional) the source account for the transfer
            if not ``default_account``
        """
        if not account:
            if "default_account" in self.config:
                account = self.config["default_account"]
        if not account:
            raise ValueError("You need to provide an account")

        _amount = Amount("{} {}".format(amount, asset))

        if memo and memo[0] == "#":
            from .memo import Memo

            memo_obj = Memo(from_account=account, to_account=to, blockchain_instance=self)
            memo = memo_obj.encrypt(memo)

        op = operations.Transfer(**{"from": account, "to": to, "amount": "{}".format(str(_amount)), "memo": memo})

        return self.finalizeOp(op, account, "active", **kwargs)

    def decode_memo(self, enc_memo: str) -> str:
        """Try to decode an encrypted memo."""
        from .memo import Memo

        memo_obj = Memo()
        return memo_obj.decrypt(enc_memo)

    def award(
        self,
        receiver: str,
        energy: float,
        memo: str = "",
        beneficiaries: Optional[List[Dict[str, Union[str, int]]]] = None,
        account: str = None,
        **kwargs: Any
    ) -> dict:
        """
        Award someone.

        :param str receiver: account name of award receiver
        :param float energy: energy as 0-100%
        :param str memo: optional comment
        :param list beneficiaries: list of dicts, example [{'account': 'vvk', 'weight': 50}]
        :param str account: initiator account name
        """
        if not account:
            if "default_account" in self.config:
                account = self.config["default_account"]
        if not account:
            raise ValueError("You need to provide an account")

        if beneficiaries is None:
            beneficiaries = []

        op = operations.Award(
            **{
                "initiator": account,
                "receiver": receiver,
                "energy": int(energy * self.rpc.config['CHAIN_1_PERCENT']),
                "custom_sequence": kwargs.get("custom_sequence", 0),
                "memo": memo,
                "beneficiaries": beneficiaries,
            }
        )

        return self.finalizeOp(op, account, "regular")

    def custom(
        self,
        id_: str,
        json: Union[Dict, List],
        required_active_auths: Optional[List[str]] = None,
        required_regular_auths: Optional[List[str]] = None,
    ) -> dict:
        """
        Create a custom operation.

        :param str id_: identifier for the custom (max length 32 bytes)
        :param dict,list json: the json data to put into the custom operation
        :param list required_active_auths: (optional) require signatures from these active auths to make this operation
            valid
        :param list required_regular_auths: (optional) require signatures from these regular auths
        """
        if required_active_auths is None:
            required_active_auths = []
        if required_regular_auths is None:
            required_regular_auths = []

        if not isinstance(required_active_auths, list) or not isinstance(required_regular_auths, list):
            raise ValueError("Expected list for required_active_auths or required_regular_auths")

        account = None
        required_key_type = "regular"

        if len(required_active_auths):
            account = required_active_auths[0]
            required_key_type = "active"
        elif len(required_regular_auths):
            account = required_regular_auths[0]
        else:
            raise ValueError("At least one account needs to be specified")

        op = operations.Custom(
            **{
                "json": json,
                "required_active_auths": required_active_auths,
                "required_regular_auths": required_regular_auths,
                "id": id_,
            }
        )
        return self.finalizeOp(op, account, required_key_type)

    def withdraw_vesting(self, amount: float, account: str = None) -> dict:
        """
        Withdraw SHARES from the vesting account.

        :param float amount: number of SHARES to withdraw over a period
        :param str account: (optional) the source account for the transfer if not ``default_account``
        """
        if not account:
            if "default_account" in self.config:
                account = self.config["default_account"]
        if not account:
            raise ValueError("You need to provide an account")

        op = operations.Withdraw_vesting(
            **{
                "account": account,
                "vesting_shares": "{:.{prec}f} {asset}".format(
                    float(amount),
                    prec=PRECISIONS.get(self.rpc.chain_params["shares_symbol"]),
                    asset=self.rpc.chain_params["shares_symbol"],
                ),
            }
        )

        return self.finalizeOp(op, account, "active")

    def transfer_to_vesting(self, amount: float, to: str = None, account: str = None) -> dict:
        """
        Vest free VIZ into vesting.

        :param float amount: number of VIZ to vest
        :param str to: (optional) the source account for the transfer if not ``default_account``
        :param str account: (optional) the source account for the transfer if not ``default_account``
        """
        if not account:
            if "default_account" in self.config:
                account = self.config["default_account"]
        if not account:
            raise ValueError("You need to provide an account")

        if not to:
            to = account  # powerup on the same account

        op = operations.Transfer_to_vesting(
            **{
                "from": account,
                "to": to,
                "amount": "{:.{prec}f} {asset}".format(
                    float(amount),
                    prec=PRECISIONS.get(self.rpc.chain_params["core_symbol"]),
                    asset=self.rpc.chain_params["core_symbol"],
                ),
            }
        )

        return self.finalizeOp(op, account, "active")

    def set_withdraw_vesting_route(
        self, to: str, percentage: float = 100, account: str = None, auto_vest: bool = False
    ) -> dict:
        """
        Set up a vesting withdraw route. When vesting shares are withdrawn, they will be routed to these accounts based
        on the specified weights.

        To obtain existing withdraw routes, use :py:meth:`get_withdraw_vesting_routes`

        .. code-block:: python

            a = Account('vvk', blockchain_instance=viz)
            pprint(a.get_withdraw_routes())

        :param str to: Recipient of the vesting withdrawal
        :param float percentage: The percent of the withdraw to go
            to the 'to' account.
        :param str account: (optional) the vesting account
        :param bool auto_vest: Set to true if the from account
            should receive the SHARES as SHARES, or false if it should
            receive them as CORE. (defaults to ``False``)
        """
        if not account:
            if "default_account" in self.config:
                account = self.config["default_account"]
        if not account:
            raise ValueError("You need to provide an account")

        op = operations.Set_withdraw_vesting_route(
            **{
                "from_account": account,
                "to_account": to,
                "percent": int(percentage * self.rpc.config['CHAIN_1_PERCENT']),
                "auto_vest": auto_vest,
            }
        )

        return self.finalizeOp(op, account, "active")

    def get_withdraw_vesting_routes(self, account: str, **kwargs: str) -> dict:
        """
        Get vesting withdraw route for an account.

        This is a shortcut for :py:meth:`viz.account.Account.get_withdraw_routes`.

        :param str account: account name
        :return: list with routes
        """
        _account = Account(account, blockchain_instance=self)

        return _account.get_withdraw_routes(**kwargs)

    # TODO: Methods to implement:
    # - create_account
    # - delegate_vesting_shares
    # - witness_update
    # - chain_properties_update
    # - allow / disallow
    # - update_memo_key
    # - approve_witness / disapprove_witness
    # - update_account_profile
    # - account_metadata
    # - proposal_create / proposal_update / proposal_delete
    # - witness_proxy
    # - recover-related methods
    # - escrow-related methods
    # - worker create / cancel / vote
    # - invite-related: create_invite, claim_invite_balance, invite_registration
    # - paid subscrives related: set_paid_subscription / paid_subscribe
