#!/bin/bash 
source /etc/bashrc
##################################### Functions Definitions
function retry_command() {
    local -r __tries="$1"; shift
    local -r __run="$@"
    local -i __backoff_delay=2

    until $__run
        do
                if (( __current_try == __tries ))
                then
                        echo "Tried $__current_try times and failed!"
                        return 1
                else
                        echo "Retrying ...."
                        sleep $((((__backoff_delay++)) + ((__current_try++))))
                fi
        done

}
function setup_environment_variables() {
    REGION=$(curl -sq http://169.254.169.254/latest/meta-data/placement/availability-zone/)
      #ex: us-east-1a => us-east-1
    REGION=${REGION: :-1}
    
    ETH0_MAC=$(/sbin/ip link show dev eth0 | /bin/egrep -o -i 'link/ether\ ([0-9a-z]{2}:){5}[0-9a-z]{2}' | /bin/sed -e 's,link/ether\ ,,g')

    _userdata_file="/var/lib/cloud/instance/user-data.txt"

    INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
    EIP_LIST=$(grep EIP_LIST ${_userdata_file} | sed -e 's/EIP_LIST=//g' -e 's/\"//g')

    LOCAL_IP_ADDRESS=$(curl -sq 169.254.169.254/latest/meta-data/network/interfaces/macs/${ETH0_MAC}/local-ipv4s/)

    CWG=$(grep CLOUDWATCHGROUP ${_userdata_file} | sed 's/CLOUDWATCHGROUP=//g')

    # LOGGING CONFIGURATION
    BASTION_MNT="/var/log/bastion"
    BASTION_LOG="bastion.log"
    echo "Setting up bastion session log in ${BASTION_MNT}/${BASTION_LOG}"
    mkdir -p ${BASTION_MNT}
    BASTION_LOGFILE="${BASTION_MNT}/${BASTION_LOG}"
    BASTION_LOGFILE_SHADOW="${BASTION_MNT}/.${BASTION_LOG}"
    touch ${BASTION_LOGFILE}
    if ! [ -L "$BASTION_LOGFILE_SHADOW" ]; then
      ln ${BASTION_LOGFILE} ${BASTION_LOGFILE_SHADOW}
    fi
    mkdir -p /usr/bin/bastion
    touch /tmp/messages
    chmod 770 /tmp/messages

    export REGION ETH0_MAC EIP_LIST CWG BASTION_MNT BASTION_LOG BASTION_LOGFILE BASTION_LOGFILE_SHADOW \
          LOCAL_IP_ADDRESS INSTANCE_ID
}
function verify_dependencies(){
    if [[ "a$(which aws)" == "a" ]]; then
      pip install awscli
    fi
    echo "${FUNCNAME[0]} Ended"
}
function install_kubernetes_client_tools() {
    mkdir -p /usr/local/bin/
    retry_command 20 curl --retry 5 -o aws-iam-authenticator https://amazon-eks.s3-us-west-2.amazonaws.com/1.11.5/2018-12-06/bin/linux/amd64/aws-iam-authenticator
    chmod +x ./aws-iam-authenticator
    mv ./aws-iam-authenticator /usr/local/bin/
    retry_command 20 curl --retry 5 -o kubectl https://amazon-eks.s3-us-west-2.amazonaws.com/1.11.5/2018-12-06/bin/linux/amd64/kubectl
    chmod +x ./kubectl
    mv ./kubectl /usr/local/bin/
    cp -r /usr/local/bin/aws-iam-authenticator /bin
    echo "source <(kubectl completion bash)" >> ~/.bashrc

cat <<EOF > /etc/yum.repos.d/kubernetes.repo
[kubernetes]
name=Kubernetes
baseurl=https://packages.cloud.google.com/yum/repos/kubernetes-el7-x86_64
enabled=1
gpgcheck=1
repo_gpgcheck=1
gpgkey=https://packages.cloud.google.com/yum/doc/yum-key.gpg https://packages.cloud.google.com/yum/doc/rpm-package-key.gpg
EOF
sudo yum install -y kubectl
}
##################################### End Function Definitions


verify_dependencies
setup_environment_variables
install_kubernetes_client_tools
curl --silent --location "https://github.com/weaveworks/eksctl/releases/latest/download/eksctl_$(uname -s)_amd64.tar.gz" | tar xz -C /tmp
sudo mv -v /tmp/eksctl /usr/local/bin

echo "Preq Bootstrap complete."