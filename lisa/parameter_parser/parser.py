from lisa.parameter_parser.config import Config
import os
import yaml
from lisa import log


def parse(args):
    path = args.config
    path = os.path.realpath(path)
    log.info("load config from: %s", path)
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    with open(path, "r") as file:
        data = yaml.safe_load(file)

    log.debug("final config data: %s", data)
    config = Config(data)
    return config