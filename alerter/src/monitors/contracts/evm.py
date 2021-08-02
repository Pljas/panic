import json
import logging
from datetime import timedelta
from http.client import IncompleteRead
from typing import List, Dict, Optional, Tuple

from requests.exceptions import (ConnectionError as ReqConnectionError,
                                 ReadTimeout, ChunkedEncodingError,
                                 MissingSchema, InvalidSchema, InvalidURL)
from urllib3.exceptions import ProtocolError
from web3 import Web3

from src.configs.nodes.chainlink import ChainlinkNodeConfig
from src.message_broker.rabbitmq import RabbitMQApi
from src.monitors.monitor import Monitor
from src.utils.constants.abis import V3, V4
from src.utils.constants.data import WEI_WATCHERS_URL_TEMPLATE
from src.utils.data import get_json, get_prometheus_metrics_data
from src.utils.exceptions import (ComponentNotGivenEnoughDataSourcesException,
                                  MetricNotFoundException)
from src.utils.timing import TimedTaskLimiter

_PROMETHEUS_RETRIEVAL_TIME_PERIOD = 86400
_WEI_WATCHERS_RETRIEVAL_TIME_PERIOD = 86400


class EVMContractsMonitor(Monitor):
    """
    The EVMContractsMonitor is able to monitor contracts of an EVM based chain.
    For now, only chainlink chains are supported.
    """

    def __init__(self, monitor_name: str, chain_name: str, evm_nodes: List[str],
                 node_configs: List[ChainlinkNodeConfig],
                 logger: logging.Logger, monitor_period: int,
                 rabbitmq: RabbitMQApi) -> None:
        # An exception is raised if the monitor is not given enough data
        # sources. The callee must also make sure that the given node_configs
        # have valid prometheus urls, and that prometheus is enabled.
        if len(evm_nodes) == 0 or len(node_configs) == 0:
            field = 'data_sources' if len(
                evm_nodes) == 0 else 'node_configs'
            raise ComponentNotGivenEnoughDataSourcesException(
                monitor_name, field)

        super().__init__(monitor_name, logger, monitor_period, rabbitmq)
        self._node_configs = node_configs

        # Construct the Web3 interfaces
        self._evm_node_w3_interface = {}
        for evm_node_url in evm_nodes:
            self._evm_node_w3_interface[evm_node_url] = Web3(Web3.HTTPProvider(
                evm_node_url, request_kwargs={'timeout': 2}))

        # Construct the wei-watchers url. This url will be used to get all
        # chain contracts. Note, for ethereum no chain is supplied to the url.
        url_chain_name = '' if chain_name == 'ethereum' else chain_name
        self._contracts_url = WEI_WATCHERS_URL_TEMPLATE.format(url_chain_name)

        # This dict stores the eth address of a chainlink node indexed by the
        # node id. The eth address is obtained from prometheus.
        self._node_eth_address = {}

        # This list stores a list of chain contracts data obtained from the wei
        # watchers link
        self._contracts_data = []

        # This dict stores a list of contract addresses that each node
        # participates on, indexed by the node id. The contracts addresses are
        # also filtered out according to their version.
        self._node_contracts = {}

        # Data retrieval limiters
        self._wei_watchers_retrieval_limiter = TimedTaskLimiter(
            timedelta(seconds=float(_WEI_WATCHERS_RETRIEVAL_TIME_PERIOD)))
        self._eth_address_retrieval_limiter = TimedTaskLimiter(
            timedelta(seconds=float(_PROMETHEUS_RETRIEVAL_TIME_PERIOD)))

    @property
    def node_configs(self) -> List[ChainlinkNodeConfig]:
        return self._node_configs

    @property
    def evm_node_w3_interface(self) -> Dict[str, Web3]:
        return self._evm_node_w3_interface

    @property
    def contracts_url(self) -> str:
        return self._contracts_url

    @property
    def node_eth_address(self) -> Dict[str, str]:
        return self._node_eth_address

    @property
    def contracts_data(self) -> List[Dict]:
        return self._contracts_data

    @property
    def node_contracts(self) -> Dict:
        return self._node_contracts

    @property
    def wei_watchers_retrieval_limiter(self) -> TimedTaskLimiter:
        return self._wei_watchers_retrieval_limiter

    @property
    def eth_address_retrieval_limiter(self) -> TimedTaskLimiter:
        return self._eth_address_retrieval_limiter

    def _get_chain_contracts(self) -> Dict:
        """
        This functions retrieves all the chain contracts along with some data.
        :return: A list of chain contracts together with data.
        """
        return get_json(self._contracts_url, self.logger, None, True)

    def _store_chain_contracts(self, contracts_data: List[Dict]) -> None:
        """
        This function stores the contracts data in the state
        :param contracts_data: The retrieved contracts data
        :return: None
        """
        self._contracts_data = contracts_data

    def _get_nodes_eth_address(self) -> Tuple[Dict, bool]:
        """
        This function attempts to get all the Ethereum addresses associated with
        each node from the prometheus endpoints. For each node it attempts to
        connect with the online source to get the eth address, however if a
        recognizable error occurs, the node is not added to the output dict but
        the second element in the tuple is set to True indicating that an error
        occurred during the process.
        :return: A tuple with the following structure:
                ({ node_id: node_eth_address }, bool)
        """
        metrics_to_retrieve = {
            'eth_balance': 'strict',
        }
        node_eth_address = {}
        error_occurred = False
        for node_config in self.node_configs:
            for prom_url in node_config.node_prometheus_urls:
                try:
                    metrics = get_prometheus_metrics_data(
                        prom_url, metrics_to_retrieve, self.logger,
                        verify=False)
                    for _, data_subset in enumerate(metrics['eth_balance']):
                        if "account" in json.loads(data_subset):
                            eth_address = json.loads(data_subset)['account']
                            node_eth_address[node_config.node_id] = eth_address
                            break
                except (ReqConnectionError, ReadTimeout, InvalidURL,
                        InvalidSchema, MissingSchema, IncompleteRead,
                        ChunkedEncodingError, ProtocolError) as e:
                    # If these errors are raised it may still be that another
                    # source can be accessed
                    self.logger.error("Error when trying to access %s",
                                      prom_url)
                    self.logger.exception(e)
                    error_occurred = True
                except MetricNotFoundException as e:
                    # If these errors are raised then we can't get valid data
                    # from any node, as only 1 node is online at the same time.
                    self.logger.error("Error when trying to access %s",
                                      prom_url)
                    self.logger.exception(e)
                    error_occurred = True
                    break

        return node_eth_address, error_occurred

    def _store_nodes_eth_addresses_contracts(self,
                                             node_eth_address: Dict) -> None:
        """
        This function stores the node's associated ethereum addresses obtained
        from prometheus in the state
        :param node_eth_address: A dict associating a node's ID to it's ethereum
                               : address obtained from prometheus
        :return: None
        """
        self._node_eth_address = node_eth_address

    def _select_node(self) -> Optional[str]:
        """
        This function returns the url of the selected node. A node is selected
        if the HttpProvider is connected and the node is not syncing.
        :return: The url of the selected node.
               : None if no node is selected.
        """
        for node_url, w3_interface in self._evm_node_w3_interface.items():
            try:
                if w3_interface.isConnected() and not w3_interface.eth.syncing:
                    return node_url
            except (ReqConnectionError, ReadTimeout, IncompleteRead,
                    ChunkedEncodingError, ProtocolError, InvalidURL,
                    InvalidSchema, MissingSchema) as e:
                self.logger.error("Error when trying to access %s", node_url)
                self.logger.exception(e)

        return None

    def _filter_contracts_by_node(self, selected_node: str) -> Dict:
        """
        This function checks which contracts a node participates on.
        :param selected_node: The evm node selected to retrieve the data from
        :return: A dict indexed by the node_id were each value is another dict
               : containing a list of v3 and v4 contracts the node participates
               : on
        """
        w3_interface = self.evm_node_w3_interface[selected_node]
        node_contracts = {}
        for node_id, eth_address in self._node_eth_address.items():
            transformed_eth_address = w3_interface.toChecksumAddress(
                eth_address)
            v3_participating_contracts = []
            v4_participating_contracts = []
            for contract_data in self._contracts_data:
                contract_address = contract_data['contractAddress']
                contract_version = contract_data['contractVersion']
                if contract_version == 3:
                    contract = w3_interface.eth.contract(
                        address=contract_address, abi=V3)
                    oracles = contract.functions.getOracles().call()
                    if transformed_eth_address in oracles:
                        v3_participating_contracts.append(contract_address)
                elif contract_version == 4:
                    contract = w3_interface.eth.contract(
                        address=contract_address, abi=V4)
                    transmitters = contract.functions.transmitters().call()
                    if transformed_eth_address in transmitters:
                        v4_participating_contracts.append(contract_address)

            node_contracts[node_id] = {}
            node_contracts['v3'] = v3_participating_contracts
            node_contracts['v4'] = v4_participating_contracts

        return node_contracts

    def _store_node_contracts(self, node_contracts: Dict) -> None:
        """
        This function stores the retrieved node_contracts inside the state.
        :param node_contracts: The retrieved node_contracts
        :return: None
        """
        self._node_contracts = node_contracts

    def _get_v3_data(self, w3_interface: Web3, node_eth_address: str,
                     node_id: str) -> Dict:
        """
        This function attempts to retrieve the v3 contract metrics for a node
        using an evm node as data source.
        :param w3_interface: The web3 interface used to get the data
        :param node_eth_address: The ethereum address of the node the metrics
                               : are associated with.
        :param node_id: The id of the node the metrics are associated with.
        :return: A dict with the following structure:
        {
            <v3_contract_address>: {
                'contractVersion': 3,
                'latestRound': int,
                'latestAnswer': int,
                'latestTimestamp': float,
                'nodeLatestAnswer': int,
                'withdrawablePayment': int
            }
        }
        """

        # If this is the case, then the node has not associated contracts stored
        if node_id not in self.node_contracts:
            return {}

        data = {}
        v3_contracts = self.node_contracts[node_id]['v3']
        for contract_address in v3_contracts:
            contract = w3_interface.eth.contract(address=contract_address,
                                                 abi=V3)
            transformed_eth_address = w3_interface.toChecksumAddress(
                node_eth_address)
            latest_round = contract.functions.latestRound().call()
            data[contract_address] = {
                'contractVersion': 3,
                'latestRound': latest_round,
                'latestAnswer': contract.functions.latestAnswer().call(),
                'latestTimestamp': contract.functions.latestTimestamp().call(),
                'nodeLatestAnswer': contract.functions.oracleRoundState().call(
                    transformed_eth_address, latest_round),
                'withdrawablePayment':
                    contract.functions.withdrawablePayment().call()
            }

        return data

    def _get_v4_data(self, w3_inteface: Web3, node_eth_address: str,
                     node_id: str) -> Dict:
        # TODO: Pydocs
        pass

    def _get_data(self, w3_interface: Web3, node_eth_address: str,
                  node_id: str) -> Dict:
        """
        This function retrieves the contracts' v3 and v4 metrics data for a
        single node using an evm node as data source.
        :param w3_interface: The web3 interface associated with the evm node
                           : used as data source
        :param node_eth_address: The Ethereum address of the node
        :param node_id: The identifier of the node
        :return: A dict containing all contract metrics
        """
        v3_data = self._get_v3_data(w3_interface, node_eth_address, node_id)
        v4_data = self._get_v4_data(w3_interface, node_eth_address, node_id)
        return {**v3_data, **v4_data}

    # TODO: Must cater for exceptions in all retrieval fns
    # TODO: When getting contracts and prom metrics, if the state is still
    #     : empty perform the retrieval again, anzi if empty don't set the
    #     : limiter did work. or do, retrieve, save, limiter.did_work
    # TODO: When formulating the data we need to check if a node has eth address
    #     : retrieved, if not we retrieve the eth addresses again next round.
    # TODO: Contracts filtering is also done every 24 hours
    # TODO: If weiwatchers retrieval successful, set it's limiter to did task.
    #     : If eth address retrieval successful for all set limiter to did task
    #     : otherwise do not set to did task and do prom address retrieval again
    #     : in next monitoring round
    #     : Do filtering if one of the above functions is called.
    # TODO: If contracts retrieval fails, stop and re-try to always have the
    #     : latest contracts
    # TODO: Select a node, check if None, if yes do nothing as it means no node
    #     : is available and raise error in logs, or possibly an error alert
    #     : saying no data source is available.

    #
    # def _display_data(self, data: Dict) -> str:
    #     # This function assumes that the data has been obtained and processed
    #     # successfully by the node monitor
    #     return "current_height={}".format(data['current_height'])
    #
    #
    # def _process_error(self, error: PANICException) -> Dict:
    #     processed_data = {
    #         'error': {
    #             'meta_data': {
    #                 'monitor_name': self.monitor_name,
    #                 'node_name': self.node_config.node_name,
    #                 'node_id': self.node_config.node_id,
    #                 'node_parent_id': self.node_config.parent_id,
    #                 'time': datetime.now().timestamp()
    #             },
    #             'message': error.message,
    #             'code': error.code,
    #         }
    #     }
    #
    #     return processed_data
    #
    # def _process_retrieved_data(self, data: Dict) -> Dict:
    #     # Add some meta-data to the processed data
    #     processed_data = {
    #         'result': {
    #             'meta_data': {
    #                 'monitor_name': self.monitor_name,
    #                 'node_name': self.node_config.node_name,
    #                 'node_id': self.node_config.node_id,
    #                 'node_parent_id': self.node_config.parent_id,
    #                 'time': datetime.now().timestamp()
    #             },
    #             'data': copy.deepcopy(data),
    #         }
    #     }
    #
    #     return processed_data
    #
    # def _send_data(self, data: Dict) -> None:
    #     self.rabbitmq.basic_publish_confirm(
    #         exchange=RAW_DATA_EXCHANGE,
    #         routing_key=EVM_NODE_RAW_DATA_ROUTING_KEY, body=data,
    #         is_body_dict=True, properties=pika.BasicProperties(delivery_mode=2),
    #         mandatory=True)
    #     self.logger.debug("Sent data to '%s' exchange", RAW_DATA_EXCHANGE)
    #
    # def _monitor(self) -> None:
    #     data_retrieval_exception = None
    #     data = None
    #     data_retrieval_failed = True
    #     try:
    #         data = self._get_data()
    #         data_retrieval_failed = False
    #     except (ReqConnectionError, ReadTimeout):
    #         data_retrieval_exception = NodeIsDownException(
    #             self.node_config.node_name)
    #         self.logger.error("Error when retrieving data from %s",
    #                           self.node_config.node_http_url)
    #         self.logger.exception(data_retrieval_exception)
    #     except (IncompleteRead, ChunkedEncodingError, ProtocolError):
    #         data_retrieval_exception = DataReadingException(
    #             self.monitor_name, self.node_config.node_name)
    #         self.logger.error("Error when retrieving data from %s",
    #                           self.node_config.node_http_url)
    #         self.logger.exception(data_retrieval_exception)
    #     except (InvalidURL, InvalidSchema, MissingSchema):
    #         data_retrieval_exception = InvalidUrlException(
    #             self.node_config.node_http_url)
    #         self.logger.error("Error when retrieving data from %s",
    #                           self.node_config.node_http_url)
    #         self.logger.exception(data_retrieval_exception)
    #
    #     try:
    #         processed_data = self._process_data(data_retrieval_failed,
    #                                             [data_retrieval_exception],
    #                                             [data])
    #     except Exception as error:
    #         self.logger.error("Error when processing data obtained from %s",
    #                           self.node_config.node_http_url)
    #         self.logger.exception(error)
    #         # Do not send data if we experienced processing errors
    #         return
    #
    #     self._send_data(processed_data)
    #
    #     if not data_retrieval_failed:
    #         # Only output the gathered data if there was no error
    #         self.logger.info(self._display_data(
    #             processed_data['result']['data']))
    #
    #     # Send a heartbeat only if the entire round was successful
    #     heartbeat = {
    #         'component_name': self.monitor_name,
    #         'is_alive': True,
    #         'timestamp': datetime.now().timestamp()
    #     }
    #     self._send_heartbeat(heartbeat)

# TODO: Add chain_name and list of evm nodes. Aggregate list of evm urls
#     : in manager. Check if equal.
# TODO: Manager should not start contracts monitor if list of evm nodes
#     : empty or list of chainlink node configs empty. For every node config
#     : we must also check that prometheus is enabled, and the list of
#     : http sources is non empty.
