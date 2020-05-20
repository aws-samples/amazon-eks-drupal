import boto3
import random
import string
import logging
from botocore.credentials import (
    AssumeRoleCredentialFetcher,
    CredentialResolver,
    DeferredRefreshableCredentials
)
from botocore.session import Session
from botocore.exceptions import ClientError
from crhelper import CfnResource

logger = logging.getLogger(__name__)
helper = CfnResource(json_logging=True, log_level='DEBUG')

try:
    lambda_client = boto3.client("lambda")
    events_client = boto3.client("events")
except Exception as init_exception:
    helper.init_failure(init_exception)


cfn_states = {
    "failed": ["CREATE_FAILED", "ROLLBACK_IN_PROGRESS", "ROLLBACK_FAILED", "ROLLBACK_COMPLETE", "DELETE_FAILED",
               "UPDATE_ROLLBACK_IN_PROGRESS", "UPDATE_ROLLBACK_FAILED", "UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS",
               "UPDATE_ROLLBACK_COMPLETE"],
    "in_progress": ["CREATE_IN_PROGRESS", "DELETE_IN_PROGRESS", "UPDATE_IN_PROGRESS",
                    "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS"],
    "success": ["CREATE_COMPLETE", "DELETE_COMPLETE", "UPDATE_COMPLETE"]
}


class AssumeRoleProvider(object):
    METHOD = 'assume-role'

    def __init__(self, fetcher):
        self._fetcher = fetcher

    def load(self):
        return DeferredRefreshableCredentials(
            self._fetcher.fetch_credentials,
            self.METHOD
        )


def assume_role(session: Session,
                role_arn: str,
                duration: int = 3600,
                session_name: str = None) -> Session:
    # noinspection PyTypeChecker
    fetcher = AssumeRoleCredentialFetcher(
        session.create_client,
        session.get_credentials(),
        role_arn,
        extra_args={
            'DurationSeconds': duration,
            'RoleSessionName': session_name
        }
    )
    role_session = Session()
    role_session.register_component(
        'credential_provider',
        CredentialResolver([AssumeRoleProvider(fetcher)])
    )
    return role_session


def rand_string(l):
    return ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(l))


def get_cfn_parameters(event):
    params = []
    for p in event['ResourceProperties']['CfnParameters'].keys():
        params.append({"ParameterKey": p, "ParameterValue": event['ResourceProperties']['CfnParameters'][p]})
    return params


@helper.create
def create(event, context):
    """
    Create a cfn stack using an assumed role
    """

    cfn_client = get_client("cloudformation", event, context)
    params = get_cfn_parameters(event)
    prefix = event['ResourceProperties']['ParentStackId'].split("/")[1]
    suffix = "-" + event["LogicalResourceId"] + "-" + rand_string(13)
    parent_properties = cfn_client.describe_stacks(StackName=prefix)['Stacks'][0]
    parent_tags = list(filter(lambda item: 'aws:' not in item['Key'], parent_properties['Tags']))
    prefix_length = len(prefix)
    suffix_length = len(suffix)
    if prefix_length + suffix_length > 128:
        prefix = prefix[:128-suffix_length]
    stack_name = prefix + suffix
    response = cfn_client.create_stack(
        StackName=stack_name,
        TemplateURL=event['ResourceProperties']['TemplateURL'],
        Parameters=params,
        Capabilities=parent_properties['Capabilities'],
        DisableRollback=parent_properties['DisableRollback'],
        NotificationARNs=parent_properties['NotificationARNs'],
        RollbackConfiguration=parent_properties['RollbackConfiguration'],
        Tags=[{
            'Key': 'ParentStackId',
            'Value': event['ResourceProperties']['ParentStackId']
        }] + parent_tags
    )
    return response['StackId']


@helper.update
def update(event, context):
    """
    Update a cfn stack using an assumed role
    """
    stack_id = event["PhysicalResourceId"]
    cfn_capabilities = []
    if 'capabilities' in event['ResourceProperties'].keys():
        cfn_capabilities = event['ResourceProperties']['capabilities']
    cfn_client = get_client("cloudformation", event, context)
    physical_resource_id = stack_id
    try:
        cfn_client.update_stack(
            StackName=stack_id,
            TemplateURL=event['ResourceProperties']['TemplateURL'],
            Parameters=get_cfn_parameters(event),
            Capabilities=cfn_capabilities,
            Tags=[{
                'Key': 'ParentStackId',
                'Value': event['ResourceProperties']['ParentStackId']
            }]
        )
    except ClientError as e:
        if "No updates are to be performed" not in str(e):
            raise
    return physical_resource_id


@helper.delete
def delete(event, context):
    """
    Delete a cfn stack using an assumed role
    """
    stack_id = event["PhysicalResourceId"]
    if '[$LATEST]' in stack_id:
        # No stack was created, so exiting
        return stack_id, {}
    cfn_client = get_client("cloudformation", event, context)
    cfn_client.delete_stack(StackName=stack_id)
    return stack_id


@helper.poll_create
@helper.poll_update
@helper.poll_delete
def poll(event, context):
    stack_id = event["CrHelperData"]["PhysicalResourceId"]
    cfn_client = get_client("cloudformation", event, context)
    stack = cfn_client.describe_stacks(StackName=stack_id)['Stacks'][0]
    response_data = {}
    if stack['StackStatus'] in cfn_states['in_progress']:
        return None
    elif stack['StackStatus'] in cfn_states['failed']:
        error = "Stack launch failed, status is %s" % stack['StackStatus']
        if 'StackStatusReason' in stack.keys():
            error = "Stack Failed: %s" % stack['StackStatusReason']
        raise Exception(error)
    # Stack operation was successful
    if 'Outputs' in stack.keys():
        for o in stack['Outputs']:
            response_data[o['OutputKey']] = o['OutputValue']
    helper.Data.update(response_data)
    return stack_id


def get_client(service, event, context):
    role_arn = None
    if 'RoleArn' in event['ResourceProperties']:
        role_arn = event['ResourceProperties']['RoleArn']
    region = context.invoked_function_arn.split(":")[3]
    if "Region" in event["ResourceProperties"].keys():
        region = event["ResourceProperties"]["Region"]
    if event['RequestType'] == 'Update':
        old_role = None
        if 'RoleArn' in event['OldResourceProperties'].keys():
            old_role = event['OldResourceProperties']['RoleArn']
        if role_arn != old_role:
            raise Exception("Changing the role ARN for stack updates is not supported")
        old_region = context.invoked_function_arn.split(":")[3]
        if "Region" in event['OldResourceProperties'].keys():
            old_region = event['OldResourceProperties']['Region']
        if region != old_region:
            raise Exception("Changing the region for stack updates is not supported")
    if role_arn:
        sess = assume_role(Session(), role_arn, session_name="QuickStartCfnStack")
        client = sess.create_client(service, region_name=region)
    else:
        client = boto3.client(service, region_name=region)
    return client


def lambda_handler(event, context):
    return helper(event, context)
