#!/bin/bash
# This script updates the OS packages on an EC2 instance.

sudo dnf update -y
sudo dnf groupinstall "Development Tools" -y
sudo dnf install -y \
    gcc \
    openssl-devel \
    bzip2-devel \
    libffi-devel \
    zlib-devel \
    wget \
    make \
    tar \
    sqlite-devel \
    xz-devel

cd /usr/src
sudo wget https://www.python.org/ftp/python/3.10.14/Python-3.10.14.tgz

sudo tar xzf Python-3.10.14.tgz

cd Python-3.10.14
sudo ./configure --enable-optimizations
sudo make altinstall

# Testing installation
python3 --version

# Upgrading pip
python3 -m ensurepip --upgrade
pip3.10 install --upgrade pip

pip3 install python-telegram-bot==21.4
pip3 install openai==0.27.7

# Set Python 3.10.14 as the Default Version
sudo alternatives --install /usr/bin/python3 python3 /usr/local/bin/python3.10 1
sudo alternatives --config python3

# Housekeeping
cd ..
sudo rm Python-3.10.14.tgz

# sudo mkdir 
sudo mkdir /home/ec2-user/umotc

# repairing dnf error
sudo sed -i 's|#!/usr/bin/python3|#!/usr/bin/python3.9|g' /usr/bin/dnf
sudo head -1 /usr/bin/dnf

# installing crontab
sudo dnf install cronie -y
sudo systemctl enable crond.service
sudo systemctl start crond.service
# The status of the ‘cronie’ service should now reflect as ‘active’:
sudo systemctl status crond | grep Active
# */5 6-23 * * * /home/ec2-user/umotc/Telegram_bot/check_and_run.sh
