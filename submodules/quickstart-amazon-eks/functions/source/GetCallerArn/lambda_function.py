import logging
import json
from datetime import timedelta
from time import sleep
import boto3
from crhelper import CfnResource

logger = logging.getLogger(__name__)
helper = CfnResource(json_logging=True, log_level='DEBUG')

try:
    cfn_client = boto3.client('cloudformation')
    ct_client = boto3.client('cloudtrail')
except Exception as init_exception:
    helper.init_failure(init_exception)


def get_caller_arn(stack_id):
    stack_properties = cfn_client.describe_stacks(StackName=stack_id)['Stacks'][0]
    try:
        parent_id = [t for t in stack_properties['Tags'] if t['Key'] == 'ParentStackId'][0]['Value']
    except ValueError:
        return "NotFound"
    except IndexError:
        return "NotFound"
    root_id = parent_id
    try:
        root_id = cfn_client.describe_stacks(StackName=parent_id)['Stacks'][0]['RootId']
    except ValueError:
        pass
    create_time = cfn_client.describe_stacks(StackName=root_id)['Stacks'][0]['CreationTime']
    retries = 50
    while True:
        retries -= 1
        try:
            response = ct_client.lookup_events(
                LookupAttributes=[
                    {'AttributeKey': 'ResourceName', 'AttributeValue': root_id},
                    {'AttributeKey': 'EventName', 'AttributeValue': 'CreateStack'}
                ],
                StartTime=create_time - timedelta(minutes=15),
                EndTime=create_time + timedelta(minutes=15)
            )
            if len(response['Events']) > 0:
                return sts_to_role(json.loads(response['Events'][0]['CloudTrailEvent'])['userIdentity']['arn'])
            logger.info('Event not in cloudtrail yet, %s retries left' % str(retries))
        except Exception as e:
            logger.error(str(e), exc_info=True)
        if retries == 0:
            return "NotFound"
        sleep(15)


def sts_to_role(sts_arn):
    logger.debug(f"arn from cloudtrail: {sts_arn}")
    if not sts_arn.startswith('arn:aws:sts::') or not sts_arn.split('/')[0].endswith('assumed-role'):
        return sts_arn
    acct_id = sts_arn.split(":")[4]
    if len(sts_arn.split('/')) < 2:
        logger.error(f"failed to parse calling arn {sts_arn}")
        return "NotFound"
    role_name = sts_arn.split('/')[1]
    return f"arn:aws:iam::{acct_id}:role/{role_name}"


@helper.create
def create(event, _):
    try:
        arn = get_caller_arn(event['StackId'])
        helper.Data['Arn'] = arn
        if len(arn.split('/')) < 2:
            return arn
        return arn.split('/')[1]
    except Exception:
        logger.error("unexpected error", exc_info=True)
        helper.Data['Arn'] = "NotFound"
        return "NotFound"


def lambda_handler(event, context):
    helper(event, context)
