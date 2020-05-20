#!/bin/bash
# author: nfairoza@amazon.com

#Run eks bootstrap script
sudo yum update -y

export QSS3KeyPrefix=$QSS3KeyPrefix
export QSS3BucketName=$QSS3BucketName
export DB_URL=$DB_URL
export DB_NAME=$DB_NAME
export DB_UNAME=$DB_UNAME
export DB_SG=$DB_SG
export DB_PASSWORD=$DB_PASSWORD
export ACCOUNT_UNAME=$ACCOUNT_UNAME
export ACCOUNT_PASSWORD=$ACCOUNT_PASSWORD
export SITE_NAME=$SITE_NAME
export ACCOUNT_EMAIL=$ACCOUNT_EMAIL
export AWS_DEFAULT_REGION=$REGION
echo AWS_DEFAULT_REGION=$REGION  >>/etc/bashrc
echo QSS3KeyPrefix=$QSS3KeyPrefix >>/etc/bashrc
echo QSS3BucketName=$QSS3BucketName >>/etc/bashrc
echo DB_URL=$DB_URL >>/etc/bashrc
echo DB_NAME=$DB_NAME >>/etc/bashrc
echo DB_UNAME=$DB_UNAME >>/etc/bashrc
echo DB_PASSWORD=$DB_PASSWORD >>/etc/bashrc
echo DB_SG=$DB_SG >>/etc/bashrc
echo ACCOUNT_UNAME=$ACCOUNT_UNAME >>/etc/bashrc
echo ACCOUNT_PASSWORD=$ACCOUNT_PASSWORD >>/etc/bashrc
echo SITE_NAME=$SITE_NAME >>/etc/bashrc
echo ACCOUNT_EMAIL=$ACCOUNT_EMAIL >>/etc/bashrc
source /etc/bashrc

echo " ################################################ EKS bootstrap ################################################"
sudo aws s3 cp s3://${QSS3BucketName}/${QSS3KeyPrefix}scripts/inner_bastion_bootstrap.sh ./
sudo chmod +x inner_bastion_bootstrap.sh
sudo ./inner_bastion_bootstrap.sh

echo "Eks bootstrap is completed!"
echo " ################################################  Parameter Values ###########################################"

export K8S_ROLE_ARN=$K8S_ROLE_ARN
export K8S_CLUSTER_NAME=$K8S_CLUSTER_NAME
export K8S_CA_DATA=$K8S_CA_DATA
export K8S_ENDPOINT=$K8S_ENDPOINT
export REPO_NAME=$REPO_NAME

echo K8S_ROLE_ARN=$K8S_ROLE_ARN >>/etc/bashrc
echo K8S_CLUSTER_NAME=$K8S_CLUSTER_NAME >>/etc/bashrc
echo K8S_CA_DATA=$K8S_CA_DATA >>/etc/bashrc
echo K8S_ENDPOINT=$K8S_ENDPOINT >>/etc/bashrc
echo REPO_NAME=$REPO_NAME >>/etc/bashrc
echo K8S_ROLE_ARN=$K8S_ROLE_ARN
echo K8S_CLUSTER_NAME=$K8S_CLUSTER_NAME
echo K8S_CA_DATA=$K8S_CA_DATA
echo K8S_ENDPOINT=$K8S_ENDPOINT
echo REPO_NAME=$REPO_NAME
source /etc/bashrc

#Run ecr bootstrap script
echo " ################################################ ECR bootstrap ################################################"
sudo aws s3 cp s3://${QSS3BucketName}/${QSS3KeyPrefix}scripts/ecrbootstrap.sh ./
sudo chmod +x ecrbootstrap.sh
sudo ./ecrbootstrap.sh

echo "ECR bootstrap completed!"

echo " ################################################ Preq bootstrap ################################################"

sudo aws s3 cp s3://${QSS3BucketName}/${QSS3KeyPrefix}scripts/preq.sh ./
sudo chmod +x preq.sh
sudo ./preq.sh


which kubectl
echo "kubectl bootstrap completed!"

echo " ################################################ Setting up Kubeconfig  ################################################"
function setup_kubeconfig() {
    echo "running setup_kubeconfig function"
    sudo mkdir -p ~/.kube
    cat > ~/.kube/config <<EOF
apiVersion: v1
clusters:
- cluster:
    server: ${K8S_ENDPOINT}
    certificate-authority-data: ${K8S_CA_DATA}
  name: kubernetes
contexts:
- context:
    cluster: kubernetes
    user: aws
  name: aws
current-context: aws
kind: Config
preferences: {}
users:
- name: aws
  user:
    exec:
      apiVersion: client.authentication.k8s.io/v1alpha1
      command: aws-iam-authenticator
      args:
        - "token"
        - "-i"
        - "${K8S_CLUSTER_NAME}"
        # - "-r"
        # - "${K8S_ROLE_ARN}"
EOF
    cp ~/.kube /home/ec2-user/ -r
    chown -R ec2-user:ec2-user /home/ec2-user/.kube/
}
setup_kubeconfig
echo "Kubeconfig setup completed!"

echo " ################################################ END OF BOOTSTRAP ################################################"
