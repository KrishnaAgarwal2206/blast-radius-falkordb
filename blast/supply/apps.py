"""The demo applications: real OSS apps at a real tag, plus the dependency versions an unrefreshed lock would pin."""
from .. import config

APPS = {
    "httpie": dict(
        title="HTTPie 2.6.0", repo=str(config.ROOT / "data" / "apps" / "httpie"), pkg_dirs=["httpie"],
        pins=str(config.ROOT / "data" / "apps" / "httpie.pins.txt"),
        requires={"requests": ">=2.22.0", "pygments": ">=2.5.2", "requests-toolbelt": ">=0.9.1", "charset-normalizer": ">=2.0.0",
                  "defusedxml": ">=0.6.0", "setuptools": "", "pysocks": ">=1.5.6"},
        entries=["httpie.__main__.main", "httpie.core.main"]),
    "precommit": dict(
        title="pre-commit 2.9.0", repo=str(config.ROOT / "data" / "apps" / "precommit"), pkg_dirs=["pre_commit"],
        pins=str(config.ROOT / "data" / "apps" / "precommit.pins.txt"),
        requires={"cfgv": ">=2.0.0", "identify": ">=1.0.0", "nodeenv": ">=0.11.1", "pyyaml": ">=5.1", "toml": "", "virtualenv": ">=20.0.8"},
        entries=["pre_commit.main.main", "pre_commit.clientlib.validate_config_main", "pre_commit.clientlib.validate_manifest_main"]),
    "yamlfull": dict(
        title="yamlfull (positive control)", repo=str(config.ROOT / "data" / "apps" / "yamlfull"), pkg_dirs=["yamlfull"],
        pins=str(config.ROOT / "data" / "apps" / "yamlfull.pins.txt"), requires={"pyyaml": ">=5.1"},
        entries=["yamlfull.config.main"]),
}
ROUTE_DECOS = ("route", ".get", ".post", ".put", ".delete", ".patch", "websocket", "command", "task", "endpoint")
