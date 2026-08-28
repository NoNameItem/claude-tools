"""Throwaway probe: deliberately violates ruff format and ruff lint.

Created to verify that plugin CI posts reviewdog inline review comments.
Delete together with the probe PR.
"""

import os
import sys


def probe(  a,b ):
    x=a+b
    return x
