from __future__ import division
import argparse
import datetime
import logging
import os
from openstack import connection
import signal
import sys
import time
import tempfile
import requests
import json

from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

logger = logging.getLogger(__name__)


class ServiceTest(object):
    def pre_test(self, *args, **kwargs):
        """Any actions that need to be taken before starting the timer
        These actions will run inside the test loop, but before marking a
        start time.
        This might include creating a local resource, such as a file to upload
        to Glance, Cinder, or Swift.
        """
        raise NotImplementedError

    def run(self):
        """Run the main test, within the timing window.
        This test run should actually create and query a resource.
        """
        raise NotImplementedError

    def post_test(self):
        """Any post-test clean up work that needs to be done and not timed."""
        raise NotImplementedError

    def __init__(self):
        self.get_connection()

    def configure_logger(self, logger, console_logging=False):
        """Configure a stream and file log for a given service
        :param: service - name of service for log file.
                generates `/var/log/{service_name}_query.log`
        :param: logger - logger to be configure for the test.
                Filename will be based on the test's `service_name`
                property
        :param: console_logging - flag controlling whether or not a console
                logger is used
        """
        logger.setLevel(logging.INFO)
        filename = '/var/log/{}_appformix.log'.format(self.service_name)
        logfile = logging.FileHandler(filename, 'a')

        logfile.setLevel(logging.INFO)

        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s')
        # Make sure we're using UTC for everything.
        formatter.converter = time.gmtime

        logfile.setFormatter(formatter)

        logger.addHandler(logfile)

        if console_logging:
            console = logging.StreamHandler()
            console.setLevel(logging.INFO)
            console.setFormatter(formatter)
            logger.addHandler(console)

    def get_connection(self):
        """Get an OpenStackSDK connection"""

        conn = connection.from_config(cloud_name='default')
        self.conn = conn

        return conn

    def get_objects(self, service, name):
        """Retrieve some sort of object from OpenStack APIs
        This applies to high level concepts like 'flavors', 'networks',
        'subnets', etc.
        :params: service - an openstack service corresponding to the OpenStack
            SDK module used, such as 'compute', 'network', etc.
        :param: name - name of a type of object, such as a 'network',
            'server', 'volume', etc owned by an OpenStack service
        """

        objs = [obj for obj in getattr(getattr(self.conn, service), name)()]
        return objs

    def get_appformix_url(self):
        """Retrieve the session internal vip address and convert it into appformix
        endpoint"""
        app_url =  self.conn.session._identity_endpoint_cache.keys()[0].split(":5000")[0]
        app_url += ":9000/appformix/controller/v2.0/"
        return app_url

    def get_token(self):
        """Retrieve the session token"""
        return self.conn.session.get_token()


class AppformixTest(ServiceTest):
    service_name = 'appformix'
    description = 'Obtain the appformix controller status'

    def run(self):
        token = self.get_token()
        appformix_url = self.get_appformix_url()
        msg = "appformix controller is working"
        if 200 != requests.get(appformix_url + "/status", verify=False):
            msg = "Can't find the appformix controller, please verify"
        return msg


class PhysicalHostTest(ServiceTest):
    service_name = 'physical host'
    description = 'Obtain the physical host status'

    def pre_test(self):
        with open("infra_list", "r") as f:
            content = f.readlines()
        self.content = [x.strip() for x in content].sort()

    def run(self):
        token = self.get_token()
        appformix_url = self.get_appformix_url()
        headers = {'content-type': 'application/json', "X-Auth-Type": "openstack", "X-Auth-Token": token,
                   "details": "true"}
        msg = "Appformix is working on all phsical host"
        resp = requests.get(appformix_url + "/status", headers=headers, verify=False)
        host_name = [x["Server"]["Name"] for x in resp.json()["ServerProfile"]]
        if self.content != host_name:
            msg = "Appformix is not working on all physical host"
        return msg

class KeystoneTest(ServiceTest):
    service_name = 'keystone'
    description = 'Obtain a token then a project list to validate it worked'

    def run(self):

        projects = self.get_objects('identity', 'projects')
        msg = "API reached, no projects found."
        if projects:
            msg = "Project list retrieved"
        return msg


class GlanceTest(ServiceTest):
    service_name = 'glance'
    description = 'Upload and delete a 1MB file'

    def pre_test(self):
        # make a bogus file to give to glance.
        self.temp_file = tempfile.TemporaryFile()
        self.temp_file.write(os.urandom(1024 * 1024))
        self.temp_file.seek(0)

    def run(self):
        self.get_connection()

        image_attrs = {
            'name': 'Rolling test',
            'disk_format': 'raw',
            'container_format': 'bare',
            'data': self.temp_file,
            'visibility': 'public',
        }

        self.conn.image.upload_image(**image_attrs)

        image = self.conn.image.find_image('Rolling test')
        self.conn.image.delete_image(image, ignore_missing=False)

        self.temp_file.close()

        msg = "Image created and deleted."
        return msg


class NovaTest(ServiceTest):
    service_name = 'nova'
    description = 'Create a network, spawn a instance on it, check appformix finds it, delete the instance,' \
                  'delete the network'

    def generate_network(self):
        print("Create Network:")

        self.appformix_network = self.conn.network.create_network(name='appformix_test_network')

        self.appformix_subnet = self.conn.network.create_subnet(name='openstacksdk-example-project-subnet',
                                                                network_id=self.appformix_network.id, ip_version='4',
                                                                cidr='10.0.2.0/24', gateway_ip='10.0.2.1')

    def delete_network(self):
        print("Delete Network:")

        found_network = self.conn.network.find_network('appformix_test_network')

        for _subnet in found_network.subnet_ids:
            self.conn.network.delete_subnet(_subnet, ignore_missing=False)
        self.conn.network.delete_network(found_network, ignore_missing=False)

    def pre_test(self):
        self.generate_network()

    def run(self):
        # Have to iterate over the generator returned to actually
        # see the flavors
        flavors = [flavor for flavor in self.conn.compute.flavors()]
        images = [image for image in self.conn.compute.images()]
        self.server = self.conn.compute.create_server(name="appformix_test", image_id=image.id, flavor_id=flavor.id,
            networks=[{"uuid": self.appformix_network.id}])

        token = self.get_token()
        appformix_url = self.get_appformix_url()

        headers = {"content-type": "application/json", "X-Auth-Type": "openstack", "X-Auth-Token": token,
                   "details": "true"}

        resp = requests.get(appformix_url + "/instances", headers=headers, verify=False)

        msg = "Appformix works on nova"
        if "appformix-volume-test" not in str(resp.json()):
            msg = "Appformix not work on Nova"
        return msg

    def post_test(self):
        self.conn.compute.delete_server(self.server.id, force=True)
        self.delete_network()


class NeutronTest(ServiceTest):
    service_name = 'neutron'
    description = 'Query for a list of networks'

    def run(self):
        networks = self.get_objects('network', 'networks')

        msg = 'API reached, no networks found'
        if networks:
            msg = 'Network list received'

        return msg


class CinderTest(ServiceTest):
    service_name = 'cinder'
    description = 'Create a volume, check the appformix data then delete it'

    def get_volumes_status(self, url, token):
        headers = {'content-type': 'application/json', "X-Auth-Type": "openstack", "X-Auth-Token": token,
                   "details": "true"}
        r = requests.get(url + "/volumes", headers=headers, verify=False)
        return r

    def pre_test(self):
        self.appformic_volume = self.conn.block_store.create_volume(display_name="app_formix_test", size=1)
        #conn.block_store.delete_volume(volume.id)

    def run(self):
        appformix_url = self.get_appformix_url()
        token = self.get_token()
        vol_status = self.get_volumes_status(appformix_url, token)

        msg = 'API reached, no volumes found'
        if "appformix-volume-test" in str(vol_status.json()):
            msg = 'Volume list received'
        return msg


class SwiftTest(ServiceTest):
    service_name = 'swift'
    description = 'Query for a list of containers'

    def run(self):
        containers = self.get_objects('object_store', 'containers')

        msg = 'API reached, no containers found'
        if containers:
            msg = 'Container list received'

        return msg


class TestRunner(object):
    """Run a test in a loop, with the option to gracefully exit"""
    stop_now = False

    def __init__(self):
        signal.signal(signal.SIGINT, self.prep_exit)
        signal.signal(signal.SIGTERM, self.prep_exit)
        self.failures = 0
        self.attempts = 0

    def prep_exit(self, signum, frame):
        self.stop_now = True
        logger.info("Received signal, stopping")

    def write_summary(self):
        percentage = (self.failures / self.attempts) * 100
        # Display minimum of 2 digits, but don't use decimals.
        percent_str = "%2.0f" % percentage

        logger.info("%s%% failure rate", percent_str)

        # Output to stdout for use by other programs
        print(percent_str)

    def test_loop(self, test):
        """Main loop to execute tests
        Executes and times interactions with OpenStack services to gather
        timing data.
        Execution can be ended by sending SIGINT or SIGTERM and the running
        test will finish.
        :param: test - on object that performs some action
                against an OpenStack service API.
        """
        disconnected = None

        try:
            # Pause for a bit so we're not generating more data than we
            # can handle
            time.sleep(1)

            try:
                test.pre_test()
            except NotImplementedError:
                pass

            start_time = datetime.datetime.now()

            # Let the test function report it's own errors
            msg = test.run()

            end_time = datetime.datetime.now()

            if disconnected:
                dis_delta = end_time - disconnected
                disconnected = None
                logger.info("Reconnect {}s".format(
                            dis_delta.total_seconds()))

            delta = end_time - start_time

            logger.info("{} {}".format(msg, delta.total_seconds()))

            try:
                test.post_test()
            except NotImplementedError:
                pass

        # Catch all exceptions not handled by the tests themselves,
        # since we want to keep the loop running until explicitly stopped
        except Exception as e:
            self.failures += 1
            if not disconnected:
                disconnected = datetime.datetime.now()
            # OpenStack API exceptions put their info in the 'details'
            # attribute; 'message' is the standard one.
            error_msg = getattr(e, 'details', e.message)
            logger.error("%s", error_msg)

        if self.stop_now:
            self.write_summary()
            sys.exit()


available_tests = {
    'keystone': KeystoneTest,
    'glance': GlanceTest,
    'nova': NovaTest,
    'neutron': NeutronTest,
    'cinder': CinderTest,
    'swift': SwiftTest,
}


def args(arg_list):

    parser = argparse.ArgumentParser(
        usage='%(prog)s',
        description=('OpenStack activity simulators. Returns percentage of '
                     'failed attempts at creating/deleting resources.'),
    )

    parser.add_argument(
        'test',
        help=("Name of test to execute, 'list' for a list of available"
              " tests")
    )

    parser.add_argument(
        '-c',
        '--console',
        help=("Log output to the console for interactive viewing"),
        action='store_true',
    )

    return parser.parse_args(arg_list)


def find_test(test_name):
    if test_name in available_tests:
        return available_tests[test_name]
    elif test_name == "list":
        for key, test_class in available_tests.items():
            print("{} -> {}".format(key, test_class.description))
        sys.exit()
    else:
        print("Test named {} not found.".format(test_name))
        sys.exit()

def get_appformix_url():


if __name__ == "__main__":
    all_args = args(sys.argv[1:])

    target_test_class = find_test(all_args.test)

    target_test = target_test_class()
    target_test.configure_logger(logger, console_logging=all_args.console)

    runner = TestRunner()

    runner.test_loop(target_test)