#!/bin/bash
set -xe

export ENV_NAME="solar-example"
export SLAVES_COUNT=3
export TEST_SCRIPT="/vagrant/examples/riak/riaks.py create_all"

./utils/jenkins/run.sh 
