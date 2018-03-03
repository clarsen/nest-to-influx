#!/bin/sh
cd `dirname $0`
pipenv run python poll.deploy.py
