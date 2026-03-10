#!/usr/bin/env bash
set -euo pipefail

python3 -m pip install --upgrade virtualenv

python3 -m virtualenv -p python3.10.12 /workspace/.envqd

/workspace/.envqd/bin/python -m pip install --upgrade pip setuptools wheel

/workspace/.envqd/bin/python -m pip install -r /workspace/requirements.txt