import configparser
import subprocess


class Config:
    def __init__(self, config):
        self.user = ConfigUser(config['user'])
        self.imap = ConfigImap(config['imap'])


class ConfigUser:
    def __init__(self, config_user):
        self.name = config_user['name']
        self.email = config_user['email']


class ConfigImap:
    def __init__(self, config_imap):
        self.user = config_imap['user']
        if 'password' in config_imap:
            self.password = config_imap['password']
        elif 'password_cmd' in config_imap:
            self.password = _config_cmd(config_imap['password_cmd'])
        else:
            raise KeyError('password')
        self.host = config_imap['host']
        self.port = int(config_imap['port'])
        self.ssl = _config_boolean(config_imap['ssl'])


def parse_config(f):
    config = configparser.ConfigParser()
    config.read_file(f)
    return Config(config)


def _config_cmd(value):
    return subprocess.check_output(value, shell=True).decode('utf-8').strip()


def _config_boolean(value):
    if value in ['yes', 'on', 'true', '1']:
        return True
    elif value in ['no', 'off', 'false', '0']:
        return False
    else:
        raise ValueError('invalid boolean')
