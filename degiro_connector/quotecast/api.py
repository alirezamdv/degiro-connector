# IMPORTATION STANDARD
import logging
import pkgutil
from degiro_connector.core.abstracts.abstract_action import AbstractAction
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# IMPORTATION THIRD PARTY

# IMPORTATION INTERNAL
import degiro_connector.core.constants.timeouts as timeouts
from degiro_connector.core.helpers.lazy_loader import InitArgs, LazyLoader, Pair
from degiro_connector.core.models.model_connection import ModelConnection
from degiro_connector.core.models.model_session import ModelSession

from degiro_connector.quotecast.models.quotecast_pb2 import Quotecast
from degiro_connector.quotecast.models.quotecast_parser import QuotecastParser


class API:
    PKG_PATH = "degiro_connector.quotecast.actions"
    CLS_PREFIX = "Action"
    MOD_PREFIX = "action_"
    ROOT_PATH = Path(__file__).absolute().parent.parent.parent.resolve()

    @classmethod
    def build_action_list(cls) -> List[str]:
        # SETUP PATH
        path = cls.PKG_PATH
        path = str(Path(cls.ROOT_PATH, *path.split(".")).resolve())

        # BUILD MODULE LIST
        action_list = list()
        for module in pkgutil.iter_modules([path]):
            if (
                not module.ispkg
                and module.name[: len(cls.MOD_PREFIX)] == cls.MOD_PREFIX
            ):
                action_list.append(module.name[len(cls.MOD_PREFIX) :])

        return action_list

    @property
    def action_list(self) -> List[str]:
        return self._action_list

    @property
    def connection_storage(self) -> ModelConnection:
        return self._connection_storage

    @property
    def credentials(self) -> Dict[str, Any]:
        return self._credentials

    @property
    def session_storage(self) -> ModelSession:
        return self._session_storage

    def load(
        self,
        action: str,
        init_args: InitArgs = None,
    ) -> Optional[object]:
        logger = self._logger
        action_list = self._action_list

        if action not in action_list:
            logger.info("Not in action_list")
            logger.info("action : %s", action)
            logger.info("action_list : %s", action_list)
            return None

        # SETUP CLASS NAME
        cap_words_action = action.replace("_", " ").title().replace(" ", "")
        class_name = self.CLS_PREFIX + cap_words_action

        # SETUP PATHS
        module_path = self.PKG_PATH + "." + self.MOD_PREFIX + action

        # SETUP PAIR
        pair = Pair(
            module_path=module_path,
            class_name=class_name,
        )

        return LazyLoader.load_pair(pair=pair, init_args=init_args)

    def __init__(
        self,
        user_token: int,
        connection_storage: ModelConnection = None,
        logger: logging.Logger = None,
        preload: bool = True,
        session_storage: ModelSession = None,
    ):
        self._credentials = {"user_token": user_token}
        self._connection_storage = connection_storage or ModelConnection(
            timeout=timeouts.QUOTECAST_TIMEOUT,
        )
        self._logger = logger or logging.getLogger(self.__module__)
        self._session_storage = session_storage or ModelSession(
            hooks=self._connection_storage.build_hooks(),
            ssl_check=False,
        )
        self._action_list = self.build_action_list()

        if preload:
            self.setup_all_actions()

    def setup_all_actions(self):
        action_list = self._action_list
        for action in action_list:
            self.setup_one_action(action=action)

    def setup_one_action(self, action: str):
        logger = self._logger
        init_args = InitArgs(
            credentials=self._credentials,
            connection_storage=self._connection_storage,
            session_storage=self._session_storage,
        )
        action_instance = self.load(
            action=action,
            init_args=init_args,
        )
        if not isinstance(action_instance, AbstractAction):
            raise TypeError(
                "Not a `AbstractAction` : %s / %s " % (action, action_instance)
            )

        logger.debug("setup_one_action : %s", action)
        setattr(self, action, action_instance)

    def __getattr__(self, item):
        logger = self._logger
        logger.debug("CALLING __GETATTR__, on item : %s", item)
        if item in self._action_list:
            action = item
            self.setup_one_action(action=action)

            return getattr(self, action)

    def fetch_metrics(
        self,
        request: Quotecast.Request,
    ) -> Dict[
        Union[str, int], Dict[str, Union[str, int]]  # VWD_ID  # METRICS : NAME / VALUE
    ]:
        """Fetch metrics from a request.
        If you seek realtime it's better to use "fetch_data".
        Since "fetch_data" consumes less ressources.
        Args:
            request (QuotecastAPI.Request):
                List of subscriptions & unsubscriptions to do.
        Returns:
            Dict[Union[str, int], Dict[str, Union[str, int]]]:
                Dict containing all the metrics grouped by "vwd_id".
        """

        logger = self._logger

        connection_attempts = 0
        ticker_dict = dict()
        while connection_attempts < 2:
            try:
                self.subscribe(request=request)
                quotecast = self.fetch_data()
                quotecast_parser = QuotecastParser(forward_fill=True)
                quotecast_parser.put_quotecast(quotecast=quotecast)
                ticker_dict = quotecast_parser.ticker_dict
                break
            except (ConnectionError, BrokenPipeError, TimeoutError) as e:
                logger.info(e)
                self.connect()
                connection_attempts += 1
            except Exception as e:
                logger.fatal(e)
                break

        return ticker_dict
