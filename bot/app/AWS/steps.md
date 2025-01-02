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
# Pull the image
docker pull 237733826785.dkr.ecr.eu-west-1.amazonaws.com/ghostfunds-ata-service:latest
## List images
aws ecr list-images --repository-name ghostfunds-ata-service --region eu-west-1
# Run the docker container
docker run -d -p 443:8000 237733826785.dkr.ecr.eu-west-1.amazonaws.com/ghostfunds-ata-service:latest
