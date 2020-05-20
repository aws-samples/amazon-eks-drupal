import json
import logging
import boto3
import subprocess
import shlex
import os
import re
from ruamel import yaml
from datetime import date, datetime
from crhelper import CfnResource
from time import sleep

logger = logging.getLogger(__name__)
helper = CfnResource(json_logging=True, log_level='DEBUG')

try:
    s3_client = boto3.client('s3')
    kms_client = boto3.client('kms')
    ec2_client = boto3.client('ec2')
except Exception as init_exception:
    helper.init_failure(init_exception)


def run_command(command):
    retries = 0
    while True:
        try:
            try:
                logger.debug("executing command: %s" % command)
                output = subprocess.check_output(shlex.split(command), stderr=subprocess.STDOUT).decode("utf-8")
                logger.debug(output)
            except subprocess.CalledProcessError as exc:
                logger.error("Command failed with exit code %s, stderr: %s" % (exc.returncode,
                                                                               exc.output.decode("utf-8")))
                raise Exception(exc.output.decode("utf-8"))
            return output
        except Exception as e:
            if 'Unable to connect to the server' not in str(e) or retries >= 5:
                raise
            logger.debug("{}, retrying in 5 seconds".format(e))
            sleep(5)
            retries += 1


def create_kubeconfig(bucket, key, kms_context):
    try:
        os.mkdir("/tmp/.kube/")
    except FileExistsError:
        pass
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


def json_serial(o):
    if isinstance(o, (datetime, date)):
        return o.strftime('%Y-%m-%dT%H:%M:%SZ')
    raise TypeError("Object of type '%s' is not JSON serializable" % type(o))


def write_manifest(manifest, path):
    f = open(path, "w")
    f.write(json.dumps(manifest, default=json_serial))
    f.close()


def generate_name(event, physical_resource_id):
    manifest = event['ResourceProperties']['Manifest']
    if type(manifest) == str:
        manifest = yaml.safe_load(manifest)
    stack_name = event['StackId'].split('/')[1]
    if "metadata" in manifest.keys():
        if 'name' not in manifest["metadata"].keys() and 'generateName' not in manifest["metadata"].keys():
            if physical_resource_id:
                manifest["metadata"]["name"] = physical_resource_id.split('/')[-1]
            else:
                manifest["metadata"]["generateName"] = "cfn-%s-" % stack_name.lower()
    return manifest


def build_output(kube_response):
    outp = {}
    for key in ["uid", "selfLink", "resourceVersion", "namespace", "name"]:
        if key in kube_response["metadata"].keys():
            outp[key] = kube_response["metadata"][key]
    return outp


def get_config_details(event):
    s3_uri_parts = event['ResourceProperties']['KubeConfigPath'].split('/')
    if len(s3_uri_parts) < 4 or s3_uri_parts[0:2] != ['s3:', '']:
        raise Exception("Invalid KubeConfigPath, must be in the format s3://bucket-name/path/to/config")
    bucket = s3_uri_parts[2]
    key = "/".join(s3_uri_parts[3:])
    kms_context = {"QSContext": event['ResourceProperties']['KubeConfigKmsContext']}
    return bucket, key, kms_context


def traverse(obj, path=None, callback=None):
    if path is None:
        path = []

    if isinstance(obj, dict):
        value = {k: traverse(v, path + [k], callback)
                 for k, v in obj.items()}
    elif isinstance(obj, list):
        value = [traverse(obj[idx], path + [[idx]], callback)
                 for idx in range(len(obj))]
    else:
        value = obj

    if callback is None:
        return value
    else:
        return callback(path, value)


def traverse_modify(obj, target_path, action):
    target_path = to_path(target_path)

    def transformer(path, value):
        if path == target_path:
            return action(value)
        else:
            return value
    return traverse(obj, callback=transformer)


def traverse_modify_all(obj, action):

    def transformer(_, value):
        return action(value)
    return traverse(obj, callback=transformer)


def to_path(path):
    if isinstance(path, list):
        return path  # already in list format

    def _iter_path(inner_path):
        indexes = [[int(i[1:-1])] for i in re.findall(r'\[[0-9]+\]', inner_path)]
        lists = re.split(r'\[[0-9]+\]', inner_path)
        for parts in range(len(lists)):
            for part in lists[parts].strip('.').split('.'):
                yield part
            if parts < len(indexes):
                yield indexes[parts]
            else:
                yield []

    return list(_iter_path(path))[:-1]


def set_type(input_str):
    if type(input_str) == str:
        if input_str.lower() == 'false':
            return False
        if input_str.lower() == 'true':
            return True
        if input_str.isdigit():
            return int(input_str)
    return input_str


def fix_types(manifest):
    return traverse_modify_all(manifest, set_type)


def aws_auth_configmap(arns, groups, username=None, delete=False):
    new = False
    outp = ''
    try:
        outp = run_command("kubectl get configmap/aws-auth -n kube-system -o yaml")
    except Exception as e:
        if 'configmaps "aws-auth" not found' not in str(e):
            raise
        new = True
    if new:
        aws_auth = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "aws-auth", "namespace": "kube-system"},
            "data": {}
        }
    else:
        aws_auth = yaml.safe_load(outp)
    maps = {"role": [], "user": []}
    if 'mapRoles' in aws_auth['data'].keys():
        maps['role'] = yaml.safe_load(aws_auth['data']['mapRoles'])
    if 'mapUsers' in aws_auth['data'].keys():
        maps['user'] = yaml.safe_load(aws_auth['data']['mapUsers'])
    for arn in arns:
        if arn != 'NotFound':
            iam_type = arn.split(':')[5].split("/")[0]
            if iam_type == 'root':
                iam_type = 'user'
            entry = {
                "%sarn" % iam_type: arn,
                "username": username if username else arn,
                "groups": groups
            }
            if not delete:
                maps[iam_type].append(entry)
            else:
                maps[iam_type] = [value for value in maps[iam_type] if value != entry]
    if maps['role']:
        aws_auth['data']['mapRoles'] = yaml.dump(maps['role'], default_flow_style=False)
    if maps['user']:
        aws_auth['data']['mapUsers'] = yaml.dump(maps['user'], default_flow_style=False)
    logger.debug(yaml.dump(aws_auth, default_flow_style=False))
    write_manifest(aws_auth, '/tmp/aws-auth.json')
    kw = 'create' if new else 'replace'
    outp = run_command("kubectl %s -f /tmp/aws-auth.json --save-config" % kw)
    logger.debug(outp)


def enable_proxy(proxy_host, vpc_id):
    configmap = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": "proxy-environment-variables",
                "namespace": "kube-system"
            },
            "data": {
                "HTTP_PROXY": proxy_host,
                "HTTPS_PROXY": proxy_host,
                "NO_PROXY": "localhost,127.0.0.1,169.254.169.254,.internal"
            }
        }
    cluster_ip = run_command(
        "kubectl get service/kubernetes -o jsonpath='{.spec.clusterIP}'"
    )
    cluster_cidr = ".".join(cluster_ip.split(".")[:3]) + ".0/16"
    vpc_cidr = ec2_client.describe_vpcs(VpcIds=[vpc_id])['Vpcs'][0]['CidrBlock']
    configmap["data"]["NO_PROXY"] += f"{vpc_cidr},{cluster_cidr}"
    write_manifest(configmap, '/tmp/proxy.json')
    run_command("kubectl apply -f /tmp/proxy.json")
    patch_cmd = (
        """kubectl patch -n kube-system -p '{ "spec": {"template": { "spec": { """
        """"containers": [ { "name": "%s", "envFrom": [ { "configMapRef": {"name": """
        """"proxy-environment-variables"} } ] } ] } } } }' daemonset %s"""
    )
    setenv_cmd = (
        """kubectl set env daemonset/%s --namespace=kube-system """
        """--from=configmap/proxy-environment-variables --containers='*'"""
    )
    for pod in ["aws-node", "kube-proxy"]:
        logger.debug(run_command(patch_cmd % (pod, pod)))
        logger.debug(run_command(setenv_cmd % pod))


def handler_init(event):
    logger.debug('Received event: %s' % json.dumps(event, default=json_serial))

    physical_resource_id = None
    manifest_file = None
    if not event['ResourceProperties']['KubeConfigPath'].startswith("s3://"):
        raise Exception("KubeConfigPath must be a valid s3 URI (eg.: s3://my-bucket/my-key.txt")
    bucket, key, kms_context = get_config_details(event)
    create_kubeconfig(bucket, key, kms_context)
    if 'HttpProxy' in event['ResourceProperties'].keys() and event['RequestType'] != 'Delete':
        enable_proxy(event['ResourceProperties']['HttpProxy'], event['ResourceProperties']['VpcId'])
    if 'Users' in event['ResourceProperties'].keys():
        username = None
        if 'Username' in event['ResourceProperties']['Users'].keys():
            username = event['ResourceProperties']['Users']['Username']
        if event['RequestType'] == 'Delete':
            aws_auth_configmap(
                event['ResourceProperties']['Users']['Arns'],
                event['ResourceProperties']['Users']['Groups'],
                username,
                delete=True
            )
        else:
            aws_auth_configmap(
                event['ResourceProperties']['Users']['Arns'],
                event['ResourceProperties']['Users']['Groups'],
                username
            )
    if 'Manifest' in event['ResourceProperties'].keys():
        manifest_file = '/tmp/manifest.json'
        if "PhysicalResourceId" in event.keys():
            physical_resource_id = event["PhysicalResourceId"]
        if type(event['ResourceProperties']['Manifest']) == str:
            manifest = generate_name(event, physical_resource_id)
        else:
            manifest = fix_types(generate_name(event, physical_resource_id))
        write_manifest(manifest, manifest_file)
        logger.debug("Applying manifest: %s" % json.dumps(manifest, default=json_serial))
    return physical_resource_id, manifest_file


@helper.create
def create_handler(event, _):
    physical_resource_id,  manifest_file = handler_init(event)
    if not manifest_file:
        return physical_resource_id
    outp = run_command("kubectl create --save-config -o json -f %s" % manifest_file)
    helper.Data = build_output(json.loads(outp))
    return helper.Data["selfLink"]


@helper.update
def update_handler(event, _):
    physical_resource_id,  manifest_file = handler_init(event)
    if not manifest_file:
        return physical_resource_id
    outp = run_command("kubectl apply -o json -f %s" % manifest_file)
    helper.Data = build_output(json.loads(outp))
    return helper.Data["selfLink"]


@helper.delete
def delete_handler(event, _):
    physical_resource_id,  manifest_file = handler_init(event)
    if not manifest_file:
        return physical_resource_id
    run_command("kubectl delete -f %s" % manifest_file)


def lambda_handler(event, context):
    helper(event, context)
