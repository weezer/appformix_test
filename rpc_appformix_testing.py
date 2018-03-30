import requests, json

from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


def get_auth(url, username, passwd):
    payload = {"AuthType": "openstack",
               "UserName": username,
               "Password": passwd}
    headers = {'content-type': 'application/json'}
    # print payload
    # print json.dumps(payload)
    r = requests.post(url + "auth_credentials", headers=headers, data=json.dumps(payload), verify=False)
    response = r.json()
    return response["Token"]["tokenId"]


def get_appformix_controller_status(url):
    return requests.get(url + "status", verify=False)


def get_host_status(url, token):
    headers = {'content-type': 'application/json', "X-Auth-Type": "openstack", "X-Auth-Token": token, "details": "true"}
    r = requests.get(url + "/hosts", headers=headers, verify=False)
    return r


def compare_host_names(lst_name1, lst_name2):
    return set(lst_name1) == set(lst_name2)


def get_instances_status(url, token):
    headers = {'content-type': 'application/json', "X-Auth-Type": "openstack", "X-Auth-Token": token, "details": "true"}
    r = requests.get(url + "/instances", headers=headers, verify=False)
    return r


def get_volumes_status(url, token):
    headers = {'content-type': 'application/json', "X-Auth-Type": "openstack", "X-Auth-Token": token, "details": "true"}
    r = requests.get(url + "/volumes", headers=headers, verify=False)
    return r


def post_volumes(url, token):
    headers = {'content-type': 'application/json', "X-Auth-Type": "openstack", "X-Auth-Token": token, "details": "true"}
    payload = {"DisplayName": "app-formix-test",
               "Size": 1,
               "Status": "available",
               "InstanceList": "None",
               "StorageHost": "727464-infra03@ceph"}
    r = requests.post(url + "/volumes", headers=headers, data=json.dumps(payload), verify=False)
    return r