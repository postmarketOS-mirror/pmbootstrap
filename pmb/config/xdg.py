import os

def get_xdg_config_home():
    home = os.path.expanduser('~')
    xdg_config_home = os.environ.get('XDG_CONFIG_HOME') \
            or os.path.join(home, '.config')

    return os.path.join(xdg_config_home, 'pmbootstrap')
