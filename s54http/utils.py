# -*- coding: utf-8 -*-


import argparse
import atexit
import collections
import logging
import os
import pathlib
import sys

from OpenSSL import SSL


__all__ = [
    'Cache',
    'SSLCtxFactory',
    'NullProxy',
    'daemonize',
    'init_logger',
    'parse_args',
]


class NullProxy:

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(
                cls,
                *args,
                **kwargs
            )
        return cls._instance

    def __getattr__(self, name):
        return self

    def __call__(self, *args, **kwargs):
        return self


class SSLCtxFactory:

    method = SSL.TLSv1_2_METHOD

    def __init__(self, client, ca, key, cert, *,
                 dhparam=None,
                 callback=None):
        self.isClient = client
        self._ca = ca
        self._key = key
        self._cert = cert
        self._dhparam = dhparam
        self._ctx = None
        if callback is None:

            def verify(conn, x509, errno, errdepth, ok):
                return ok

            callback = verify
        self._callback = callback
        self.cacheContext()

    def cacheContext(self):
        if self._ctx is not None:
            return
        ctx = SSL.Context(SSL.TLSv1_2_METHOD)
        ctx.set_options(SSL.OP_NO_SSLv2)
        ctx.set_options(SSL.OP_NO_SSLv3)
        ctx.set_options(SSL.OP_NO_TLSv1)
        ctx.set_options(SSL.OP_NO_TLSv1_1)
        ctx.use_certificate_file(self._cert)
        ctx.use_privatekey_file(self._key)
        ctx.check_privatekey()
        ctx.load_verify_locations(self._ca)
        if self._dhparam:
            ctx.load_tmp_dh(self._dhparam)
        ctx.set_cipher_list('ECDHE-RSA-AES128-GCM-SHA256')
        ctx.set_verify(
            SSL.VERIFY_PEER |
            SSL.VERIFY_FAIL_IF_NO_PEER_CERT |
            SSL.VERIFY_CLIENT_ONCE,
            self._callback
        )
        self._ctx = ctx

    def __getstate__(self):
        state = self.__dict__.copy()
        del state['_ctx']
        return state

    def __setstate__(self, state):
        self.__dict__ = state

    def getContext(self):
        return self._ctx


class Cache(collections.OrderedDict):

    def __init__(self, limit=1024):
        super().__init__()
        self.limit = limit

    def __setitem__(self, key, value):
        while len(self) >= self.limit:
            self.popitem(last=False)
        super().__setitem__(key, value)


def daemonize(pidfile, *,
              stdin='/dev/null',
              stdout='/dev/null',
              stderr='/dev/null'):
    if os.path.exists(pidfile):
        logging.getLogger(__name__).info('already running')
        raise SystemExit(1)

    try:
        if os.fork() > 0:
            raise SystemExit(0)
    except OSError as e:
        raise RuntimeError(f'fork #1 failed: {e}')
    os.chdir('/')
    os.umask(0)
    os.setsid()

    try:
        if os.fork() > 0:
            raise SystemExit(0)
    except OSError as e:
        raise RuntimeError(f'fork #2 failed: {e}')

    sys.stdin.flush()
    sys.stdout.flush()

    with open(stdin, 'rb', 0) as fp:
        os.dup2(fp.fileno(), sys.stdin.fileno())
    with open(stdout, 'ab', 0) as fp:
        os.dup2(fp.fileno(), sys.stdout.fileno())
    with open(stderr, 'ab', 0) as fp:
        os.dup2(fp.fileno(), sys.stderr.fileno())

    with open(pidfile, 'w') as fp:
        print(os.getpid(), file=fp)

    atexit.register(lambda: os.remove(pidfile))


def init_logger(config, logger):
    level = config['loglevel']
    formatter = logging.Formatter(
        '%(asctime)s-%(levelname)s : %(message)s',
        '%Y-%m-%d %H:%M:%S'
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger.setLevel(level)
    logger.addHandler(handler)


def parse_args(config):
    PATH_ARGUMENT = [
        'ca',
        'key',
        'cert',
        'dhparam',
        'pidfile',
        'logfile'
    ]
    FILE_ARGUMENT = [
        'ca',
        'arg',
        'cert'
    ]
    usage = f"{sys.argv[0].split('/')[-1]}"
    parser = argparse.ArgumentParser(usage)
    parser.add_argument(
        "-d",
        "--daemon",
        dest="daemon",
        action="store_true",
        help="run as daemon"
    )
    parser.add_argument(
        "-l",
        "--host",
        dest="host",
        help="listen address"
    )
    parser.add_argument(
        "-p",
        "--port",
        dest="port",
        type=int,
        help="listen port"
    )
    parser.add_argument(
        "--key",
        dest="key",
        help="key file path"
    )
    parser.add_argument(
        "--ca",
        dest="ca",
        help="ca file path"
    )
    parser.add_argument(
        "--cert",
        dest="cert",
        help="cert file path"
    )
    parser.add_argument(
        "--dhparam",
        dest="dhparam",
        help="dhparam file path"
    )
    parser.add_argument(
        "-S",
        dest="saddr",
        help="server address"
    )
    parser.add_argument(
        "-P",
        dest="sport",
        type=int,
        help="server port"
    )
    parser.add_argument(
        "--pidfile",
        dest="pidfile",
        help="pid file"
    )
    parser.add_argument(
        "--logfile",
        dest="logfile",
        help="log file"
    )
    parser.add_argument(
        "--loglevel",
        dest="loglevel",
        help="DEBUG, INFO, WARN, ERROR"
    )
    parser.add_argument(
        "--dns",
        dest="dns",
        help="dns server[addr:port|addr]"
    )
    args = parser.parse_args()
    for arg in config.keys():
        value = getattr(args, arg, None)
        if not value:
            continue
        config[arg] = value
    for arg in PATH_ARGUMENT:
        value = config[arg]
        fp = pathlib.Path(value)
        config[arg] = str(fp.absolute())
        if fp.exists():
            continue
        if arg == 'dhparam':
            config[arg] = None
        elif arg in FILE_ARGUMENT:
            raise RuntimeError(f'{arg} file not existed')
