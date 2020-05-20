#!/bin/bash
# author: nfairoza@amazon.com
#Assume you have configured aws profile

echo "Installing prerequisites..."
sudo yum update -y
sudo yum install jq -y

echo "installing docker....."
sudo yum install -y docker
sudo service docker start
docker version
source /etc/bashrc
echo "Setting up environment vairiables..."
ACCOUNT_ID="$(curl -s http://169.254.169.254/latest/dynamic/instance-identity/document | jq -r .accountId)"
REGION=$(curl -sq http://169.254.169.254/latest/meta-data/placement/availability-zone/)
REGION=${REGION: :-1}
export ACCOUNT_ID=$ACCOUNT_ID
export REGION=$REGION
echo "REGION=$REGION" >> /etc/bashrc
echo "ACCOUNT_ID=$ACCOUNT_ID" >> /etc/bashrc
IMAGE_NAME=$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPO_NAME
export IMAGE_NAME=$IMAGE_NAME
echo "IMAGE_NAME=$IMAGE_NAME" >> /etc/bashrc
TAG=latest
export TAG=latest
source /etc/bashrc
id=$(curl http://169.254.169.254/latest/meta-data/instance-id)
bastionsg=$(aws ec2 describe-instances --instance-ids $id --query "Reservations[].Instances[].SecurityGroups[].GroupId[]" --output text --region $REGION )

echo "adding inbound rule to the db security group for to allow website installation..."
aws ec2 authorize-security-group-ingress  --group-id $DB_SG --protocol tcp --port 3306 --source-group $bastionsg --region $REGION


echo "Logging in to Amazon ECR..."
$(aws ecr get-login --no-include-email --region $REGION)
#Awscli v2 update
#aws --region $REGION ecr get-login-password | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com

echo "Downloading the Dockerfile..."
sudo mkdir -p /tmp/docker
sudo aws s3 cp s3://${QSS3BucketName}/${QSS3KeyPrefix}scripts/Dockerfile /tmp/docker/
sudo chmod +x /tmp/docker/Dockerfile

echo "Setting Ulimit..."
ulimit -l unlimited
ulimit -n 10240
ulimit -c unlimited

echo "Building docker IMAGE "
echo IMAGE_NAME=$IMAGE_NAME >> /etc/bashrc
source /etc/bashrc
sudo docker build \
--build-arg DB_URL=$DB_URL \
--build-arg DB_NAME=$DB_NAME \
--build-arg DB_UNAME=$DB_UNAME \
--build-arg DB_PASSWORD=$DB_PASSWORD \
--build-arg ACCOUNT_UNAME=$ACCOUNT_UNAME \
--build-arg ACCOUNT_PASSWORD=$ACCOUNT_PASSWORD \
--build-arg SITE_NAME=$SITE_NAME \
--build-arg ACCOUNT_EMAIL=$ACCOUNT_EMAIL \
-t $IMAGE_NAME:$TAG /tmp/docker

echo "removing inbound rule to the db security group after the website installation..."
aws ec2 revoke-security-group-ingress --group-id $DB_SG --protocol tcp --port 3306 --source-group $bastionsg --region $REGION


echo "Pushing Docker image to ECR "
sudo docker push $IMAGE_NAME:$TAG


echo "ECR Bootstrap complete......"
