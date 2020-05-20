import json
import logging
import boto3
import subprocess
import shlex
import os
import time
from hashlib import md5
from crhelper import CfnResource
from time import sleep

logger = logging.getLogger(__name__)
helper = CfnResource(json_logging=True, log_level='DEBUG')

try:
    s3_client = boto3.client('s3')
    kms_client = boto3.client('kms')
except Exception as init_exception:
    helper.init_failure(init_exception)


def run_command(command):
    try:
        print("executing command: %s" % command)
        output = subprocess.check_output(shlex.split(command), stderr=subprocess.STDOUT).decode("utf-8")
        print(output)
    except subprocess.CalledProcessError as exc:
        print("Command failed with exit code %s, stderr: %s" % (exc.returncode, exc.output.decode("utf-8")))
        raise Exception(exc.output.decode("utf-8"))
    return output


def create_kubeconfig(bucket, key, kms_context):
    try:
        os.mkdir("/tmp/.kube/")
    except FileExistsError:
        pass
    print("s3_client.get_object(Bucket='%s', Key='%s')" % (bucket, key))
    try:
        retries = 10
        while True:
            try:
                enc_config = s3_client.get_object(Bucket=bucket, Key=key)['Body'].read()
                break
            except Exception as e:
                logger.error(str(e), exc_info=True)
                if retries == 0:
                    raise
                sleep(10)
                retries -= 1
    except Exception as e:
        raise Exception("Failed to fetch KubeConfig from S3: %s" % str(e))
    kubeconf = kms_client.decrypt(
        CiphertextBlob=enc_config,
        EncryptionContext=kms_context
    )['Plaintext'].decode('utf8')
    f = open("/tmp/.kube/config", "w")
    f.write(kubeconf)
    f.close()
    os.environ["KUBECONFIG"] = "/tmp/.kube/config"


def get_config_details(event):
    s3_uri_parts = event['ResourceProperties']['KubeConfigPath'].split('/')
    if len(s3_uri_parts) < 4 or s3_uri_parts[0:2] != ['s3:', '']:
        raise Exception("Invalid KubeConfigPath, must be in the format s3://bucket-name/path/to/config")
    bucket = s3_uri_parts[2]
    key = "/".join(s3_uri_parts[3:])
    kms_context = {"QSContext": event['ResourceProperties']['KubeConfigKmsContext']}
    return bucket, key, kms_context


@helper.create
@helper.update
def create_handler(event, _):
    print('Received event: %s' % json.dumps(event))
    if not event['ResourceProperties']['KubeConfigPath'].startswith("s3://"):
        raise Exception("KubeConfigPath must be a valid s3 URI (eg.: s3://my-bucket/my-key.txt")
    bucket, key, kms_context = get_config_details(event)
    create_kubeconfig(bucket, key, kms_context)
    name = event['ResourceProperties']['Name']
    retry_timeout = 0
    if "Timeout" in event['ResourceProperties']:
        retry_timeout = int(event['ResourceProperties']["Timeout"])
    if retry_timeout > 600:
        retry_timeout = 600
    namespace = event['ResourceProperties']['Namespace']
    json_path = event['ResourceProperties']['JsonPath']
    while True:
        try:
            outp = run_command('kubectl get %s -o jsonpath="%s" --namespace %s' % (name, json_path, namespace))
            break
        except Exception as e:
            if retry_timeout < 1:
                raise
            else:
                logging.error('Exception: %s' % e, exc_info=True)
                print("retrying until timeout...")
                time.sleep(5)
                retry_timeout = retry_timeout - 5
    response_data = {}
    if "ResponseKey" in event['ResourceProperties']:
        response_data[event['ResourceProperties']["ResponseKey"]] = outp
    if len(outp.encode('utf-8')) > 1000:
        outp = 'MD5-' + str(md5(outp.encode('utf-8')).hexdigest())
    helper.Data.update(response_data)
    return outp


def lambda_handler(event, context):
    helper(event, context)
