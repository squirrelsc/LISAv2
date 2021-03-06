from pathlib import PurePath
from typing import cast

from lisa.executable import Tool
from lisa.operating_system import Linux
from lisa.tools import Gcc
from lisa.util import LisaException


class Make(Tool):
    repo = "https://github.com/microsoft/ntttcp-for-linux"

    @property
    def command(self) -> str:
        return "make"

    @property
    def can_install(self) -> bool:
        return True

    def _install(self) -> bool:
        linux_os: Linux = cast(Linux, self.node.os)
        linux_os.install_packages([self, Gcc])
        return self._check_exists()

    def make_and_install(self, cwd: PurePath) -> None:
        make_result = self.run(shell=True, cwd=cwd)
        if make_result.exit_code == 0:
            # install with sudo
            self.node.execute("make install", shell=True, sudo=True, cwd=cwd)
        else:
            raise LisaException(
                f"make commadn got non-zero exit code: {make_result.exit_code}"
            )
