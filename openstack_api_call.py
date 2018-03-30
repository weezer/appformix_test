from novaclient import client as nova_client
from keystoneclient.v3 import client as keystone_client
from keystoneauth1.identity import v3
from keystoneauth1 import session
from cinderclient import client as cinder_client
from neutronclient.v2_0 import client as neutron_client
import rpc_appformix_testing as rat
import os

def generate_session():
    auth = v3.Password(auth_url=os.environ["OS_AUTH_URL"], username=os.environ["OS_USERNAME"],
                       password=os.environ["OS_PASSWORD"], project_name=os.environ["OS_PROJECT_NAME"],
                       user_domain_id="default", project_domain_id="default")
    sess = session.Session(auth=auth, verify=False)
    return sess

def get_access_token(s):
    return s.get_token()

def generate_neutron_session(s):
    neutron = neutron_client.Client(session=s)
    return neutron

def generate_network(neutron):
    network = {'name': 'appformix_test_network', 'admin_state_up': True}
    network = neutron.create_network({'network': network})
    return network

def get_network_id(n):
    network_id = n['network']['id']
    return network_id

def generate_subnet(neutron, n_id):
    body = {
        "subnet": {
            "network_id": n_id,
            "name": "subnetwork",
            "ip_version": 4,
            "cidr": "10.10.10.0/24"
        }
    }
    sub_network = neutron.create_subnet(body)
    return sub_network

def get_subnet_id(sn):
    sub_network_id = sn['subnet']['id']
    return sub_network_id

def create_instance(s, n_id):
    nova = nova_client.Client(2, session=s)
    fl = nova.flavors.find(ram=8192)
    appformix_server = nova.servers.create("appformix-test-server", image="1176b73f-9a59-450e-86b9-e8aed11fb093",
                                           flavor=fl, nics=[{'net-id': n_id}])
    return appformix_server

def create_volume(s):
    cinder = cinder_client.Client(3, session=s)
    v = cinder.volumes.create(1, name="appformix-volume-test")
    return v

def delete_instance(i):
    i.delete()

def delete_network(neutron, network_id):
    neutron.delete_network(network_id)

def delete_subnet(neutron, sn_id):
    neutron.delete_subnet(sn_id)

def delete_volume(v):
    v.delete()

def read_infra_conf(f):
    pass

appformix_Url = "http://172.29.236.10:9000/appformix/controller/v2.0/"
rat.get_appformix_controller_status(appformix_Url)
session = generate_session()

token = get_access_token(session)
resp = rat.get_host_status(appformix_Url, token)
print token
print resp.json()
host_name = [x["Server"]["Name"] for x in resp.json()["ServerProfile"]]
print rat.compare_host_names(host_name, host_name)

ns = generate_neutron_session(session)
network = generate_network(ns)
network_id = get_network_id(network)
subnet = generate_subnet(ns, network_id)
subnet_id = get_subnet_id(subnet)

ins = create_instance(session, network_id)
ins_status = rat.get_instances_status(appformix_Url, token)
if "appformix-test-server" in str(ins_status.json()):
    print "appformix works for instance"

vol = create_volume(session)
vol_status = rat.get_volumes_status(appformix_Url, token)
if "appformix-volume-test" in str(vol_status.json()):
    print "appformix works for volume"

delete_subnet(ns, subnet_id)
delete_network(ns, network_id)
delete_volume(vol)
delete_instance(ins)