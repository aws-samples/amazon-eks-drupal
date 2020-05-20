import json
import logging
import threading
from crhelper import CfnResource
import os
import boto3

KUBECONFIG = """apiVersion: v1
clusters:
- cluster:
    server: {endpoint}
    certificate-authority-data: {ca_data}
  name: kubernetes
contexts:
- context:
    cluster: kubernetes
    user: aws
  name: aws
current-context: aws
kind: Config
preferences: {{}}
users:
- name: aws
  user:
    exec:
      apiVersion: client.authentication.k8s.io/v1alpha1
      command: aws-iam-authenticator
      args:
        - "token"
        - "-i"
        - "{cluster_name}"
"""


helper = CfnResource(json_logging=True, log_level='DEBUG')

try:
    kms_client = boto3.client('kms')
    s3_client = boto3.client('s3')
except Exception as init_exception:
    helper.init_failure(init_exception)


def create_kubeconfig(endpoint, cluster_name, ca_data):
    return KUBECONFIG.format(endpoint=endpoint, ca_data=ca_data, cluster_name=cluster_name)


@helper.create
@helper.update
def create_update_handler(event, _):
    os.environ["PATH"] = "/var/task/bin:" + os.environ.get("PATH")
    endpoint = event['ResourceProperties']['EKSEndpoint']
    cluster_arn = event['ResourceProperties']['EKSArn']
    ca_data = event['ResourceProperties']['EKSCAData']
    kms_key_arn = event['ResourceProperties']['KmsKeyArn']
    s3_bucket_name = event['ResourceProperties']['S3BucketName']
    s3_key = event['ResourceProperties']['S3Key']
    enc_context = {"QSContext": event['ResourceProperties']['EncryptionContext']}
    kube_config = create_kubeconfig(endpoint, cluster_arn.split('/')[1], ca_data)
    enc_config = kms_client.encrypt(
        Plaintext=kube_config,
        KeyId=kms_key_arn,
        EncryptionContext=enc_context
    )['CiphertextBlob']
    s3_client.put_object(Body=enc_config, Bucket=s3_bucket_name, Key=s3_key)


@helper.delete
def delete_helper(event, _):
    s3_client.delete_object(Bucket=event['ResourceProperties']['S3BucketName'],
                            Key=event['ResourceProperties']['S3Key'])


def lambda_handler(event, context):
    helper(event, context)
