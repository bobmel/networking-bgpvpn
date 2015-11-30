# Copyright (c) 2015 Orange.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import mock
import webob.exc

from neutron import context as n_context

from neutron.common.constants import DEVICE_OWNER_DHCP
from neutron.common.constants import PORT_STATUS_ACTIVE
from neutron.common.constants import PORT_STATUS_DOWN

from neutron import manager
from neutron.plugins.ml2 import config as ml2_config
from neutron.plugins.ml2 import rpc as ml2_rpc

from networking_bgpvpn.tests.unit.services import test_plugin


class TestBagpipeCommon(test_plugin.BgpvpnTestCaseMixin):

    def setUp(self, plugin=None):
        self.mocked_bagpipeAPI = mock.patch(
            'networking_bagpipe.agent.bgpvpn.rpc_client'
            '.BGPVPNAgentNotifyApi').start().return_value

        provider = ('networking_bgpvpn.neutron.services.service_drivers.'
                    'bagpipe.bagpipe.BaGPipeBGPVPNDriver')
        super(TestBagpipeCommon, self).setUp(service_provider=provider,
                                             core_plugin=plugin)


class TestBagpipeServiceDriver(TestBagpipeCommon):

    def test_bagpipe_associate_net(self):
        mocked_update = self.mocked_bagpipeAPI.update_bgpvpn
        with self.port() as port1:
            net_id = port1['port']['network_id']
            with self.bgpvpn() as bgpvpn:
                id = bgpvpn['bgpvpn']['id']
                rt = bgpvpn['bgpvpn']['route_targets']
                mocked_update.reset_mock()
                with self.assoc_net(id, net_id):
                    formatted_bgpvpn = {'id': id,
                                        'network_id': net_id,
                                        'l3vpn':
                                        {'import_rt': rt,
                                         'export_rt': rt}}
                    mocked_update.assert_called_once_with(mock.ANY,
                                                          formatted_bgpvpn)

    def test_bagpipe_disassociate_net(self):
        mocked_delete = self.mocked_bagpipeAPI.delete_bgpvpn
        with self.port() as port1:
            net_id = port1['port']['network_id']
            with self.bgpvpn() as bgpvpn:
                id = bgpvpn['bgpvpn']['id']
                rt = bgpvpn['bgpvpn']['route_targets']
                with self.assoc_net(id, net_id,
                                    do_disassociate=False) as assoc:
                    mocked_delete.reset_mock()
                    del_req = self.new_delete_request(
                        'bgpvpn/bgpvpns',
                        id,
                        fmt=self.fmt,
                        subresource='network_associations',
                        sub_id=assoc['network_association']['id'])
                    res = del_req.get_response(self.ext_api)
                    if res.status_int >= 400:
                        raise webob.exc.HTTPClientError(code=res.status_int)

                    formatted_bgpvpn = {'id': id,
                                        'network_id': net_id,
                                        'l3vpn':
                                        {'import_rt': rt,
                                         'export_rt': rt}}
                    mocked_delete.assert_called_once_with(mock.ANY,
                                                          formatted_bgpvpn)

    def test_bagpipe_update_bgpvpn_rt(self):
        mocked_update = self.mocked_bagpipeAPI.update_bgpvpn
        with self.port() as port1:
            net_id = port1['port']['network_id']
            with self.bgpvpn() as bgpvpn:
                id = bgpvpn['bgpvpn']['id']
                rt = ['6543:21']
                with self.assoc_net(id, net_id):
                    formatted_bgpvpn = {'id': id,
                                        'network_id': net_id,
                                        'l3vpn':
                                        {'import_rt': rt,
                                         'export_rt': rt}}
                    update_data = {'bgpvpn': {'route_targets': ['6543:21']}}
                    mocked_update.reset_mock()
                    self._update('bgpvpn/bgpvpns',
                                 bgpvpn['bgpvpn']['id'],
                                 update_data)
                    mocked_update.assert_called_once_with(mock.ANY,
                                                          formatted_bgpvpn)

    def test_bagpipe_delete_bgpvpn(self):
        mocked_delete = self.mocked_bagpipeAPI.delete_bgpvpn
        with self.port() as port1:
            net_id = port1['port']['network_id']
            with self.bgpvpn(do_delete=False) as bgpvpn:
                id = bgpvpn['bgpvpn']['id']
                rt = bgpvpn['bgpvpn']['route_targets']
                mocked_delete.reset_mock()
                with self.assoc_net(id, net_id, do_disassociate=False):
                    self._delete('bgpvpn/bgpvpns', id)
                    formatted_bgpvpn = {'id': id,
                                        'network_id': net_id,
                                        'l3vpn':
                                        {'import_rt': rt,
                                         'export_rt': rt}}
                    mocked_delete.assert_called_once_with(mock.ANY,
                                                          formatted_bgpvpn)


TESTHOST = 'testhost'


BGPVPN_INFO = {'mac_address': 'de:ad:00:00:be:ef',
               'ip_address': '10.0.0.2',
               'gateway_ip': '10.0.0.1',
               'l3vpn': {'import_rt': ['12345:1'],
                         'export_rt': ['12345:1']
                         }
               }


class TestBagpipeServiceDriverCallbacks(TestBagpipeCommon):
    '''Check that receiving callbacks results in RPC calls to the agent'''

    _plugin_name = 'neutron.plugins.ml2.plugin.Ml2Plugin'

    def setUp(self):
        ml2_config.cfg.CONF.set_override('mechanism_drivers',
                                         ['logger', 'test', 'fake_agent'],
                                         'ml2')

        super(TestBagpipeServiceDriverCallbacks, self).setUp(self._plugin_name)

        self.port_create_status = 'DOWN'
        self.plugin = manager.NeutronManager.get_plugin()
        self.plugin.start_rpc_listeners()

        self.bagpipe_driver = self.bgpvpn_plugin.driver

        mock.patch.object(self.bgpvpn_plugin.driver,
                          '_retrieve_bgpvpn_network_info_for_port',
                          return_value=BGPVPN_INFO).start()

        self.mock_attach_rpc = self.mocked_bagpipeAPI.attach_port_on_bgpvpn
        self.mock_detach_rpc = self.mocked_bagpipeAPI.detach_port_from_bgpvpn

        self.ctxt = n_context.Context('fake_user', 'fake_project')

    def _build_expected_return_active(self, port):
        bgpvpn_info_port = BGPVPN_INFO.copy()
        bgpvpn_info_port.update({'id': port['id'],
                                 'network_id': port['network_id']})
        return bgpvpn_info_port

    def _build_expected_return_down(self, port):
        return {'id': port['id'],
                'network_id': port['network_id']}

    def test_bagpipe_callback_to_rpc_update_active(self):
        # REVISIT(tmorin): could avoid mocking get_host_port
        #  by setting binding:host_id at port creation
        #  as in _test_create_port_binding_profile
        with self.port() as port, \
            mock.patch.object(self.bagpipe_driver, '_get_port_host',
                              return_value=TESTHOST):
            port['port']['status'] = PORT_STATUS_ACTIVE
            self.bagpipe_driver.registry_port_updated(
                None, None, None,
                context=self.ctxt,
                port=port['port']
            )
            self.mock_attach_rpc.assert_called_once_with(
                mock.ANY,
                self._build_expected_return_active(port['port']),
                TESTHOST)

    def test_bagpipe_callback_to_rpc_update_down(self):
        with self.port() as port, \
            mock.patch.object(self.bagpipe_driver, '_get_port_host',
                              return_value=TESTHOST):
            port['port']['status'] = PORT_STATUS_DOWN
            self.bagpipe_driver.registry_port_updated(
                None, None, None,
                context=self.ctxt,
                port=port['port']
            )
            self.mock_detach_rpc.assert_called_once_with(
                mock.ANY,
                self._build_expected_return_down(port['port']),
                TESTHOST)

    def test_bagpipe_callback_to_rpc_deleted(self):
        with self.port() as port, \
            mock.patch.object(self.bagpipe_driver, '_get_port_host',
                              return_value=TESTHOST):
            port['port']['status'] = PORT_STATUS_DOWN
            self.bagpipe_driver.registry_port_deleted(
                None, None, None,
                context=self.ctxt,
                port_id=port['port']['id']
            )
            self.mock_detach_rpc.assert_called_once_with(
                mock.ANY,
                self._build_expected_return_down(port['port']),
                TESTHOST)

    def test_bagpipe_callback_to_rpc_update_active_ignore_DHCP(self):
        with self.port(device_owner=DEVICE_OWNER_DHCP) as port, \
            mock.patch.object(self.bagpipe_driver, '_get_port_host',
                              return_value=TESTHOST):
            port['port']['status'] = PORT_STATUS_ACTIVE
            self.bagpipe_driver.registry_port_updated(
                None, None, None,
                context=self.ctxt,
                port=port['port']
            )
            self.assertFalse(self.mock_attach_rpc.called)

    def test_bagpipe_callback_to_rpc_update_down_ignore_DHCP(self):
        with self.port(device_owner=DEVICE_OWNER_DHCP) as port, \
            mock.patch.object(self.bagpipe_driver, '_get_port_host',
                              return_value=TESTHOST):
            port['port']['status'] = PORT_STATUS_DOWN
            self.bagpipe_driver.registry_port_updated(
                None, None, None,
                context=self.ctxt,
                port=port['port']
            )
            self.assertFalse(self.mock_detach_rpc.called)

    def test_bagpipe_callback_to_rpc_deleted_ignore_DHCP(self):
        with self.port(device_owner=DEVICE_OWNER_DHCP) as port, \
            mock.patch.object(self.bagpipe_driver, '_get_port_host',
                              return_value=TESTHOST):
            port['port']['status'] = PORT_STATUS_DOWN
            self.bagpipe_driver.registry_port_deleted(
                None, None, None,
                context=self.ctxt,
                port_id=port['port']['id']
            )
            self.assertFalse(self.mock_detach_rpc.called)

    def test_delete_port_to_bgpvpn_rpc(self):

        ctxt = n_context.Context('fake_user', 'fake_project')

        with self.network() as net, \
            self.subnet(network=net) as subnet, \
            self.port(subnet=subnet) as port, \
            mock.patch.object(self.plugin, 'get_port',
                              return_value=port['port']), \
            mock.patch.object(self.plugin, 'get_network',
                              return_value=net['network']):

            port['port'].update({'binding:host_id': TESTHOST})

            self.plugin.delete_port(ctxt, port['port']['id'])

            self.mock_detach_rpc.assert_called_once_with(
                mock.ANY,
                self._build_expected_return_down(port['port']),
                TESTHOST)

    def test_l2agent_rpc_to_bgpvpn_rpc(self):
        #
        # Test that really simulate the ML2 codepath that
        # generate the registry events.

        ml2_rpc_callbacks = ml2_rpc.RpcCallbacks(mock.Mock(), mock.Mock())

        n_dict = {"name": "netfoo",
                  "tenant_id": "fake_project",
                  "admin_state_up": True,
                  "shared": False}

        net = self.plugin.create_network(self.ctxt, {'network': n_dict})

        subnet_dict = {'name': 'test_subnet',
                       'tenant_id': 'fake_project',
                       'ip_version': 4,
                       'cidr': '10.0.0.0/24',
                       'allocation_pools': [{'start': '10.0.0.2',
                                             'end': '10.0.0.254'}],
                       'enable_dhcp': False,
                       'dns_nameservers': [],
                       'host_routes': [],
                       'network_id': net['id']}

        self.plugin.create_subnet(self.ctxt, {'subnet': subnet_dict})

        p_dict = {'network_id': net['id'],
                  'name': 'fooport',
                  "admin_state_up": True,
                  "device_id": "tapfoo",
                  "device_owner": "not_me",
                  "mac_address": "de:ad:00:00:be:ef",
                  "fixed_ips": [],
                  "binding:host_id": TESTHOST,
                  }

        port = self.plugin.create_port(self.ctxt, {'port': p_dict})

        self.plugin.update_dvr_port_binding(self.ctxt,
                                            port['id'], {'port': p_dict})

        ml2_rpc_callbacks.update_device_up(self.ctxt,
                                           host=TESTHOST,
                                           agent_id='fooagent',
                                           device="de:ad:00:00:be:ef")

        self.mock_attach_rpc.assert_called_once_with(
            mock.ANY,
            self._build_expected_return_active(port),
            TESTHOST)

        # The test below currently fails, because there is
        # no registry event for Port down (in Neutron stable/liberty)
#             ml2_rpc_callbacks.update_device_down(self.ctxt,
#                                                  host=TESTHOST,
#                                                  agent_id='fooagent',
#                                                  device="de:ad:00:00:be:ef")
#
#             self.mock_detach_rpc.assert_called_once_with(
#                 mock.ANY,
#                 self._build_expected_return_down(port),
#                 TESTHOST)

        self.plugin.delete_port(self.ctxt, port['id'])

        self.mock_detach_rpc.assert_called_once_with(
            mock.ANY,
            self._build_expected_return_down(port),
            TESTHOST)