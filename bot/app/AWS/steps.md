# AWS
# cli login
aws ecr get-login-password --region eu-west-1 | docker login --username AWS --password-stdin 237733826785.dkr.ecr.eu-west-1.amazonaws.com
# Docker build image
## Note: must provide --provenance=false to create lambda function from latest image. If not it'll fail.
docker build --platform linux/arm64/v8 --provenance=false -t ghostfunds-ata-service .
# Run and test locally
docker run -p 8000:8000 ghostfunds-ata-service
# Docker tag and push image into AWS ECR
docker tag ghostfunds-ata-service:latest 237733826785.dkr.ecr.eu-west-1.amazonaws.com/ghostfunds-ata-service:latest
docker push 237733826785.dkr.ecr.eu-west-1.amazonaws.com/ghostfunds-ata-service:latest

# EC2 and docker
## Install libraries
sudo yum update -y
sudo yum install docker -y
sudo service docker start

## Configure the client and include the keys for your AWS user
aws configure

## cli login
aws ecr get-login-password --region eu-west-1 | docker login --username AWS --password-stdin 237733826785.dkr.ecr.eu-west-1.amazonaws.com
## Add Your User to the Docker Group:
sudo usermod -aG docker $(whoami)
newgrp docker
### Verify Group Membership
groups
### Check docker's permission. Should be something like this: srw-rw---- 1 root docker 0 Dec  9 13:11 /var/run/docker.sock
ls -l /var/run/docker.sock
## restart 
sudo systemctl restart docker

# #####################################################
# Copy and paste in EC2 terminal
# login and Pull the image ###########################
aws ecr get-login-password --region eu-west-1 | docker login --username AWS --password-stdin 237733826785.dkr.ecr.eu-west-1.amazonaws.com
docker pull 237733826785.dkr.ecr.eu-west-1.amazonaws.com/ghostfunds-ata-service:latest
## List images
#### aws ecr list-images --repository-name ghostfunds-ata-service --region eu-west-1
### Stop current docker conatiner
CONTAINER_ID=$(docker ps | awk 'NR==2 {print $1}')
docker stop $CONTAINER_ID
### Remove previous images
docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | grep -v ':latest' | awk '{print $2}' | xargs docker rmi -f
# Run the docker container
docker run --memory=512m --memory-swap=512m -d -p 443:8000 237733826785.dkr.ecr.eu-west-1.amazonaws.com/ghostfunds-ata-service:latest
### ##################################################

# Start Docker when EC2 instance starts
## Create start-docker-container.sh and add the code 
### - look into /app/AWS/start-docker-container.sh
### - Adjust if dockerimage id changes
sudo vim /etc/init.d/start-docker-container.sh

## Make executable script
sudo chmod +x /etc/init.d/start-docker-container.sh
## Add script to chkconfig
sudo chkconfig --add start-docker-container.sh
## Enable the script at startup
sudo chkconfig start-docker-container.sh on
## Test the script
sudo service start-docker-container.sh start
docker ps


