#!/bin/bash
yum update -y
yum install docker -y
service docker start
usermod -aG docker ec2-user
chkconfig docker on
