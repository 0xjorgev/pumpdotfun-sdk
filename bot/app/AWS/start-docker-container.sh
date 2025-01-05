#!/bin/bash
# chkconfig: 2345 20 80
# description: Start Docker container for Ghostfunds service
# processname: start-docker-container

### BEGIN INIT INFO
# Provides: start-docker-container
# Required-Start: $network $docker
# Required-Stop: $network $docker
# Default-Start: 2 3 4 5
# Default-Stop: 0 1 6
# Short-Description: Start Ghostfunds Docker container
# Description: Runs a Docker container for the Ghostfunds service on startup
### END INIT INFO

docker run --memory=512m --memory-swap=512m -d -p 443:8000 237733826785.dkr.ecr.eu-west-1.amazonaws.com/ghostfunds-ata-service:latest
