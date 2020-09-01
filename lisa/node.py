from __future__ import annotations

import pathlib
import random
from collections import UserDict
from typing import TYPE_CHECKING, Iterable, List, Optional, TypeVar, Union, cast

from lisa import schema
from lisa.executable import Tools
from lisa.tools import Echo, Uname
from lisa.tools.uname import LinuxInfo
from lisa.util import ContextMixin, LisaException, constants, fields_to_dict
from lisa.util.logger import get_logger
from lisa.util.process import ExecutableResult, Process
from lisa.util.shell import ConnectionInfo, LocalShell, Shell, SshShell

T = TypeVar("T")


class Node(ContextMixin):
    def __init__(
        self,
        index: int,
        is_remote: bool = True,
        requirement: Optional[schema.NodeSpace] = None,
        is_default: bool = False,
    ) -> None:
        self.is_default = is_default
        self.is_remote = is_remote
        self.requirement = requirement
        self.name: str = ""
        self.index = index

        self.shell: Shell = LocalShell()

        self.info: LinuxInfo = LinuxInfo()
        self.tools = Tools(self)
        self.working_path: pathlib.PurePath = pathlib.PurePath()

        self._connection_info: Optional[ConnectionInfo] = None
        self._is_initialized: bool = False
        self._is_linux: bool = True
        self._log = get_logger("node", str(self.index))

    @staticmethod
    def create(
        index: int,
        requirement: Optional[schema.NodeSpace] = None,
        node_type: str = constants.ENVIRONMENTS_NODES_REMOTE,
        is_default: bool = False,
    ) -> Node:
        if node_type == constants.ENVIRONMENTS_NODES_REMOTE:
            is_remote = True
        elif node_type == constants.ENVIRONMENTS_NODES_LOCAL:
            is_remote = False
        else:
            raise LisaException(f"unsupported node_type '{node_type}'")
        node = Node(
            index, requirement=requirement, is_remote=is_remote, is_default=is_default
        )
        node._log.debug(f"created, type: '{node_type}', isDefault: {is_default}")
        return node

    def set_connection_info(
        self,
        address: str = "",
        port: int = 22,
        public_address: str = "",
        public_port: int = 22,
        username: str = "root",
        password: str = "",
        private_key_file: str = "",
    ) -> None:
        if self._connection_info is not None:
            raise LisaException(
                "node is set connection information already, cannot set again"
            )

        self._connection_info = ConnectionInfo(
            public_address, public_port, username, password, private_key_file,
        )
        self.shell = SshShell(self._connection_info)
        self.internal_address = address
        self.internal_port = port

    def execute(
        self,
        cmd: str,
        shell: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> ExecutableResult:
        process = self.execute_async(
            cmd,
            shell=shell,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            cwd=cwd,
        )
        return process.wait_result()

    def execute_async(
        self,
        cmd: str,
        shell: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> Process:
        self._initialize()
        return self._execute(
            cmd,
            shell=shell,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            cwd=cwd,
        )

    @property
    def is_linux(self) -> bool:
        self._initialize()
        return self._is_linux

    def close(self) -> None:
        self.shell.close()

    def _initialize(self) -> None:
        if not self._is_initialized:
            # prevent loop calls, set _isInitialized to True first
            self._is_initialized = True
            self._log.debug(f"initializing node {self.name}")
            try:
                self.shell.initialize()
                uname = self.tools[Uname]
                self.info = uname.get_linux_information(no_error_log=True)
                if (not self.info.kernel_release) or (
                    "Linux" not in self.info.operating_system
                ):
                    self._is_linux = False
                if self._is_linux:
                    self._log.info(
                        f"initialized Linux node '{self.name}', "
                        f"kernelRelease: {self.info.kernel_release}, "
                        f"kernelVersion: {self.info.kernel_version}"
                        f"hardwarePlatform: {self.info.hardware_platform}"
                    )
                else:
                    self._log.info(f"initialized Windows node '{self.name}', ")

                # set working path
                if self.is_remote:
                    assert self.shell
                    assert (
                        self._connection_info
                    ), "call setConnectionInfo before use remote node"

                    if self.is_linux:
                        remote_root_path = pathlib.Path("$HOME")
                    else:
                        remote_root_path = pathlib.Path("%TEMP%")
                    working_path = remote_root_path.joinpath(
                        constants.PATH_REMOTE_ROOT, constants.RUN_LOGIC_PATH
                    ).as_posix()

                    # expand environment variables in path
                    echo = self.tools[Echo]
                    result = echo.run(working_path, shell=True)

                    # PurePath is more reasonable here, but spurplus doesn't support it.
                    if self.is_linux:
                        self.working_path = pathlib.PurePosixPath(result.stdout)
                    else:
                        self.working_path = pathlib.PureWindowsPath(result.stdout)
                else:
                    self.working_path = constants.RUN_LOCAL_PATH
                self.shell.mkdir(self.working_path, parents=True, exist_ok=True)
                self._log.debug(f"working path is: '{self.working_path}'")
            except Exception as identifier:
                # initialize failed, and make sure it reverses to not initialized state
                self._is_initialized = False
                raise identifier

    def _execute(
        self,
        cmd: str,
        shell: bool = False,
        no_error_log: bool = False,
        no_info_log: bool = False,
        cwd: Optional[pathlib.PurePath] = None,
    ) -> Process:
        cmd_id = str(random.randint(0, 10000))
        process = Process(
            cmd_id, self.shell, parent_logger=self._log, is_linux=self.is_linux
        )
        process.start(
            cmd,
            shell=shell,
            no_error_log=no_error_log,
            no_info_log=no_info_log,
            cwd=cwd,
        )
        return process


if TYPE_CHECKING:
    NodesDict = UserDict[str, Node]
else:
    NodesDict = UserDict


class Nodes(NodesDict):
    def __init__(self) -> None:
        super().__init__()
        self._default: Optional[Node] = None
        self._list: List[Node] = list()

    @property
    def default(self) -> Node:
        if self._default is None:
            default = None
            for node in self._list:
                if node.is_default:
                    default = node
                    break
            if default is None:
                if len(self._list) == 0:
                    raise LisaException("No node found in current environment")
                else:
                    default = self._list[0]
            self._default = default
        return self._default

    def list(self) -> Iterable[Node]:
        for node in self._list:
            yield node

    def __getitem__(self, key: Union[int, str]) -> Node:
        found = None
        if not self._list:
            raise LisaException("no node found")

        if isinstance(key, int):
            if len(self._list) > key:
                found = self._list[key]
        else:
            for node in self._list:
                if node.name == key:
                    found = node
                    break
        if not found:
            raise KeyError(f"cannot find node {key}")

        return found

    def __setitem__(self, key: Union[int, str], v: Node) -> None:
        raise NotImplementedError("don't set node directly, call create_by_*")

    def __len__(self) -> int:
        return len(self._list)

    def close(self) -> None:
        for node in self._list:
            node.close()

    def from_local(self, node_runbook: schema.LocalNode) -> Node:
        assert isinstance(
            node_runbook, schema.LocalNode
        ), f"actual: {type(node_runbook)}"
        node = Node.create(
            len(self._list),
            node_type=node_runbook.type,
            is_default=node_runbook.is_default,
        )
        self._list.append(node)

        return node

    def from_remote(self, node_runbook: schema.RemoteNode) -> Optional[Node]:
        assert isinstance(
            node_runbook, schema.RemoteNode
        ), f"actual: {type(node_runbook)}"

        node = Node.create(
            len(self._list),
            node_type=node_runbook.type,
            is_default=node_runbook.is_default,
        )
        self._list.append(node)

        fields = [
            constants.ENVIRONMENTS_NODES_REMOTE_ADDRESS,
            constants.ENVIRONMENTS_NODES_REMOTE_PORT,
            constants.ENVIRONMENTS_NODES_REMOTE_PUBLIC_ADDRESS,
            constants.ENVIRONMENTS_NODES_REMOTE_PUBLIC_PORT,
            constants.ENVIRONMENTS_NODES_REMOTE_USERNAME,
            constants.ENVIRONMENTS_NODES_REMOTE_PASSWORD,
            constants.ENVIRONMENTS_NODES_REMOTE_PRIVATE_KEY_FILE,
        ]
        parameters = fields_to_dict(node_runbook, fields)
        node.set_connection_info(**parameters)

        return node

    def from_requirement(self, node_requirement: schema.NodeSpace) -> List[Node]:
        min_requirement = cast(
            schema.NodeSpace, node_requirement.generate_min_capaiblity(node_requirement)
        )
        assert isinstance(min_requirement.node_count, int), (
            f"must be int after generate_min_capaiblity, "
            f"actual: {min_requirement.node_count}"
        )
        nodes: List[Node] = []
        for _ in range(min_requirement.node_count):
            node = Node.create(
                len(self._list),
                requirement=node_requirement,
                node_type=constants.ENVIRONMENTS_NODES_REMOTE,
                is_default=node_requirement.is_default,
            )
            nodes.append(node)
            self._list.append(node)
        return nodes
