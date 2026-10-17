"""A small config loader. Written as a positive control: it loads user-supplied YAML with the FullLoader."""
import yaml


def load_settings(path):
    with open(path) as f:
        return yaml.load(f, Loader=yaml.FullLoader)


def main(argv=None):
    import sys
    path = (argv or sys.argv)[1]
    return load_settings(path)
