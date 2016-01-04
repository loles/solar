#!/bin/bash
set -xe

# for now we assume that master ip is 10.0.0.2 and slaves ips are 10.0.0.{3,4,5,...}
ADMIN_IP=10.0.0.2
ADMIN_PASSWORD=vagrant
ADMIN_USER=vagrant
INSTALL_DIR=/vagrant

ENV_NAME=${ENV_NAME:-solar-test}
SLAVES_COUNT=${SLAVES_COUNT:-0}
CONF_PATH=${CONF_PATH:-utils/jenkins/default.yaml}

IMAGE_PATH=${IMAGE_PATH:-bootstrap/output-qemu/ubuntu1404}
TEST_SCRIPT=${TEST_SCRIPT:-/vagrant/examples/hosts_file/hosts.py}

dos.py erase ${ENV_NAME} | true
ENV_NAME=${ENV_NAME} SLAVES_COUNT=${SLAVES_COUNT} IMAGE_PATH=${IMAGE_PATH} CONF_PATH=${CONF_PATH} python utils/jenkins/env.py

# Wait for master to boot
sleep 30

sshpass -p ${ADMIN_PASSWORD} ssh -t ${ADMIN_USER}@${ADMIN_IP} bash -s <<EOF
set -x
export PYTHONWARNINGS="ignore"

#sudo git clone https://github.com/openstack/solar.git ${INSTALL_DIR}

#################
sudo git clone https://github.com/loles/solar.git ${INSTALL_DIR}
pushd ${INSTALL_DIR}
sudo git checkout tests
popd
##############3

sudo chown -R ${ADMIN_USER} ${INSTALL_DIR}
sudo ansible-playbook -v -i \"localhost,\" -c local ${INSTALL_DIR}/bootstrap/playbooks/solar.yaml

set -e

# wait for riak
sleep 30

export SOLAR_CONFIG_OVERRIDE="/.solar_config_override"

solar repo update templates ${INSTALL_DIR}/utils/jenkins/repository

bash -c "${TEST_SCRIPT}"

solar changes stage
solar changes process
solar orch run-once

while true
do
  error=\$(solar o report | grep -e ERROR)
  if [ -n "\${error}" ]; then
    solar orch report
    echo FAILURE
    exit 0
    exit 1
  fi

  running=\$(solar o report | grep -e PENDING -e INPROGRESS)
  if [ -z "\${running}" ]; then
    solar orch report
    echo SUCCESS
    exit 0
  fi

  sleep 5
done
EOF
