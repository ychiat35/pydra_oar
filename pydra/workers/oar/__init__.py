"""
Plugin OAR for Pydra.
This file exposes the OarWorker class to Pydra's plugin system.
"""

from .oar import OarWorker

# Alias so it can be referred to as oar.Worker
Worker = OarWorker

try:
    from ._version import __version__
except ImportError:
    raise RuntimeError(
        "Pydra package 'oar' has not been installed, please use "
        "`pip install -e <path-to-repo>` to install development version"
    )
